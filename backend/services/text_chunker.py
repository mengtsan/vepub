"""
文字切句器。
支援語言：zh（中文）、en（英文）、ja（日文）、其他
策略：
  1. 依語言選擇斷句工具
  2. 切出 10–80 字的句子
  3. 保留句子在段落中的 index（供高亮同步）
"""
import re
from dataclasses import dataclass

@dataclass
class Sentence:
    index: int         # 全章節第幾句（0-based）
    paragraph_index: int
    text: str
    char_start: int    # 在段落中的起始字元位置（供高亮用）
    char_end: int

class TextChunker:
    MIN_CHARS = 10
    MAX_CHARS = 80

    def __init__(self, language: str = "zh", max_chars: int = None):
        self.language = language
        self._nlp = self._load_nlp(language)
        
        # 根據運算裝置智慧調整最大字數，避免 CPU 推理造成的巨大延遲
        if max_chars is not None:
            self.max_chars = max_chars
        else:
            try:
                from services.hardware_detector import detect_hardware
                hw = detect_hardware()
                if hw.get("recommended_device") == "cpu":
                    self.max_chars = 35  # CPU 模式下限制在 35 字，使單句推理縮減到 10 ~ 15 秒內
                else:
                    self.max_chars = 80  # GPU/MLX 模式下使用較長句子
            except Exception:
                self.max_chars = 35  # 發生異常時保險起見使用 35 字


    def _load_nlp(self, language: str):
        """
        依語言載入 spaCy 模型。
        """
        if language.startswith("zh"):
            import spacy
            try:
                return spacy.load("zh_core_web_sm")
            except Exception:
                return None
        elif language.startswith("ja"):
            import spacy
            try:
                return spacy.load("ja_core_news_sm")
            except Exception:
                return None
        elif language.startswith("en"):
            import spacy
            try:
                return spacy.load("en_core_web_sm")
            except Exception:
                return None
        return None

    def chunk_paragraphs(
        self, paragraphs: list[str]
    ) -> list[Sentence]:
        """
        將段落清單切成 Sentence 物件清單。
        """
        all_sentences = []
        global_index = 0

        for para_idx, paragraph in enumerate(paragraphs):
            sentences = self._split_paragraph(paragraph)

            char_pos = 0
            for sent_text in sentences:
                # 找到此句在段落中的起始位置
                start = paragraph.find(sent_text, char_pos)
                if start == -1:
                    start = char_pos
                end = start + len(sent_text)
                char_pos = end

                all_sentences.append(Sentence(
                    index=global_index,
                    paragraph_index=para_idx,
                    text=sent_text,
                    char_start=start,
                    char_end=end,
                ))
                global_index += 1

        return all_sentences

    def _split_paragraph(self, text: str) -> list[str]:
        """
        將單一段落切分成多個句子。
        """
        if self._nlp:
            doc = self._nlp(text)
            raw = [sent.text.strip() for sent in doc.sents if sent.text.strip()]
        else:
            # 備用方案：使用正則表達式
            raw = self._regex_split(text)

        # 合併過短句子，切分過長句子
        return self._normalize_lengths(raw)

    def _regex_split(self, text: str) -> list[str]:
        """
        使用中英日通用標點進行斷句的備用正則表達式。
        """
        pattern = r'(?<=[。！？.!?…])\s*'
        parts = re.split(pattern, text)
        return [p.strip() for p in parts if p.strip()]

    def _normalize_lengths(self, sentences: list[str]) -> list[str]:
        """
        調整句子的長度，使其落在指定的最小及最大字數區間內。
        """
        result = []
        buffer = ""

        for sent in sentences:
            if len(buffer) + len(sent) < self.MIN_CHARS:
                buffer += sent
            elif len(buffer) > 0 and len(buffer) + len(sent) <= self.max_chars:
                buffer += sent
            else:
                if buffer:
                    result.append(buffer)
                # 句子過長：強制在 max_chars 處切斷
                while len(sent) > self.max_chars:
                    result.append(sent[:self.max_chars])
                    sent = sent[self.max_chars:]
                buffer = sent

        if buffer:
            result.append(buffer)

        return result

