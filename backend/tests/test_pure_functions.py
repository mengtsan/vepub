"""
不需 GPU / LLM server 的純函數單元測試。
覆蓋範圍：
  - llm_engine: _parse_character_json, _is_valid_char_name, _merge_aliases, _apply_defaults
  - illustration_engine: build_character_fragment, build_character_fragment_en, character_seed_for
  - epub_parser: flatten_toc
  - text_chunker: TextChunker（regex fallback 路徑）
"""
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

# ─── 路徑設定 ─────────────────────────────────────────────────────────────────
BACKEND_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_DIR))


# ─── llm_engine 純函數 ────────────────────────────────────────────────────────

def _import_llm_engine():
    """延遲 import，只在第一次被呼叫時執行。"""
    import importlib
    return importlib.import_module("services.llm_engine")


class TestParseCharacterJson:
    def setup_method(self):
        self.mod = _import_llm_engine()

    def test_valid_array(self):
        raw = '[{"name": "林黛玉", "gender": "女"}]'
        result = self.mod._parse_character_json(raw)
        assert len(result) == 1
        assert result[0]["name"] == "林黛玉"

    def test_double_bracket_prefill(self):
        raw = '[[{"name": "賈寶玉", "gender": "男"}]]'
        result = self.mod._parse_character_json(raw)
        assert result[0]["name"] == "賈寶玉"

    def test_with_think_tags(self):
        raw = '<think>考慮一下</think>[{"name": "王熙鳳"}]'
        result = self.mod._parse_character_json(raw)
        assert result[0]["name"] == "王熙鳳"

    def test_truncated_json_partial_objects(self):
        # 策略 2：逐個擷取已完整的 {...}
        raw = '[{"name": "甲"}, {"name": "乙"}, {"name": "丙'  # 最後一個截斷
        result = self.mod._parse_character_json(raw)
        names = [r["name"] for r in result]
        assert "甲" in names
        assert "乙" in names

    def test_empty_string(self):
        assert self.mod._parse_character_json("") == []

    def test_invalid_json(self):
        assert self.mod._parse_character_json("not json at all") == []


class TestIsValidCharName:
    def setup_method(self):
        self.mod = _import_llm_engine()

    def test_valid_names(self):
        for name in ["林黛玉", "賈寶玉", "孫悟空", "約翰"]:
            assert self.mod._is_valid_char_name(name), f"{name} 應為合法名稱"

    def test_single_pronoun(self):
        for p in ["他", "她", "它", "我"]:
            assert not self.mod._is_valid_char_name(p), f"{p} 應被過濾"

    def test_empty(self):
        assert not self.mod._is_valid_char_name("")

    def test_pronoun_phrase(self):
        # 「那X」「這X」短語
        assert not self.mod._is_valid_char_name("那人")
        assert not self.mod._is_valid_char_name("這位")


class TestMergeAliases:
    def setup_method(self):
        self.mod = _import_llm_engine()

    def test_clan_name_merge(self):
        chars = {
            "愛新覺羅·福臨": {"name": "愛新覺羅·福臨", "gender": "男"},
            "福臨":          {"name": "福臨", "gender": "男"},
        }
        result = self.mod._merge_aliases(chars)
        assert "福臨" in result
        assert "愛新覺羅·福臨" not in result

    def test_prefix_merge(self):
        chars = {
            "小玉":  {"name": "小玉",  "gender": "女"},
            "玉":    {"name": "玉",    "gender": "女"},  # too short, won't be target
            "玉兒":  {"name": "玉兒",  "gender": "女"},
            "小玉兒": {"name": "小玉兒", "gender": "女"},
        }
        result = self.mod._merge_aliases(chars)
        # 「小玉兒」should merge into 「玉兒」
        assert "玉兒" in result
        assert "小玉兒" not in result

    def test_empty(self):
        assert self.mod._merge_aliases({}) == {}

    def test_no_aliases(self):
        chars = {"張三": {"name": "張三"}, "李四": {"name": "李四"}}
        result = self.mod._merge_aliases(chars)
        assert set(result.keys()) == {"張三", "李四"}


class TestApplyDefaults:
    def setup_method(self):
        self.mod = _import_llm_engine()

    def test_empty_char_gets_defaults(self):
        char = {"name": "春花"}
        result = self.mod._apply_defaults(char)
        assert result["gender"] in ("男", "女")
        assert result["age_hint"] == "青年"
        assert result["hair_color"]
        assert result["eye_color"]

    def test_female_suffix_detection(self):
        char = {"name": "林姑娘"}
        result = self.mod._apply_defaults(char)
        assert result["gender"] == "女"

    def test_existing_values_not_overwritten(self):
        char = {"name": "某人", "gender": "男", "hair_color": "銀白", "age_hint": "老年"}
        result = self.mod._apply_defaults(char)
        assert result["gender"] == "男"
        assert result["hair_color"] == "銀白"
        assert result["age_hint"] == "老年"

    def test_deterministic_for_same_name(self):
        char1 = {"name": "林小鳳"}
        char2 = {"name": "林小鳳"}
        r1 = self.mod._apply_defaults(char1)
        r2 = self.mod._apply_defaults(char2)
        assert r1["hair_color"] == r2["hair_color"]
        assert r1["eye_color"] == r2["eye_color"]


# ─── illustration_engine 純函數 ───────────────────────────────────────────────

def _import_illus_engine():
    import importlib
    # 先確保 services.db 可被 import（建立 ~/.epub-tts 目錄）
    importlib.import_module("services.db")
    return importlib.import_module("services.illustration_engine")


class TestBuildCharacterFragment:
    def setup_method(self):
        self.mod = _import_illus_engine()

    def test_empty_char(self):
        result = self.mod.build_character_fragment({})
        assert isinstance(result, str)

    def test_basic_fields(self):
        char = {
            "gender": "女", "age_hint": "青年",
            "hair_color": "黑色", "hair_style": "長直",
            "eye_color": "棕色", "signature_outfit": "白色旗袍",
        }
        fragment = self.mod.build_character_fragment(char)
        assert "女" in fragment
        assert "黑色長直" in fragment
        assert "白色旗袍" in fragment

    def test_special_traits(self):
        char = {"other_features": "貓耳，尾巴"}
        fragment = self.mod.build_character_fragment(char)
        assert fragment  # 不應為空

    def test_english_fragment(self):
        char = {
            "gender": "女", "hair_color": "金色", "hair_style": "長波浪",
            "eye_color": "藍色", "signature_outfit": "魔法師長袍",
        }
        en = self.mod.build_character_fragment_en(char)
        assert "girl" in en or "female" in en or "1girl" in en
        assert "blonde" in en or "golden" in en


class TestCharacterSeedFor:
    def setup_method(self):
        self.mod = _import_illus_engine()

    def test_returns_non_negative_int(self):
        seed = self.mod.character_seed_for("book123", "林黛玉")
        assert isinstance(seed, int)
        assert seed >= 0

    def test_same_inputs_same_seed(self):
        s1 = self.mod.character_seed_for("book1", "角色A")
        s2 = self.mod.character_seed_for("book1", "角色A")
        assert s1 == s2

    def test_different_names_different_seeds(self):
        s1 = self.mod.character_seed_for("book1", "角色A")
        s2 = self.mod.character_seed_for("book1", "角色B")
        assert s1 != s2


# ─── epub_parser flatten_toc ──────────────────────────────────────────────────

class TestFlattenToc:
    def setup_method(self):
        import importlib
        self.mod = importlib.import_module("services.epub_parser")

    def _link(self, href, title):
        class Link:
            pass
        l = Link()
        l.href = href
        l.title = title
        return l

    def test_flat_list(self):
        items = [self._link("ch1.xhtml", "第一章"), self._link("ch2.xhtml", "第二章")]
        result = self.mod.flatten_toc(items)
        assert result["ch1.xhtml"] == "第一章"
        assert result["ch2.xhtml"] == "第二章"

    def test_nested_tuple(self):
        section = self._link("part1.xhtml", "第一部")
        sub = [self._link("ch1.xhtml", "第一章")]
        result = self.mod.flatten_toc([(section, sub)])
        assert result["part1.xhtml"] == "第一部"
        assert result["ch1.xhtml"] == "第一章"

    def test_fragment_stripped(self):
        items = [self._link("ch1.xhtml#section1", "Section 1")]
        result = self.mod.flatten_toc(items)
        assert "ch1.xhtml" in result
        assert "ch1.xhtml#section1" not in result

    def test_empty(self):
        assert self.mod.flatten_toc([]) == {}


# ─── TextChunker regex fallback ───────────────────────────────────────────────

class TestTextChunkerRegex:
    def setup_method(self):
        import importlib
        self.mod = importlib.import_module("services.text_chunker")

    def test_basic_chunking(self):
        chunker = self.mod.TextChunker(language="unknown")  # 無 spaCy → 用 regex
        sentences = chunker.chunk_paragraphs(["你好。今天天氣很好！明天呢？"])
        assert len(sentences) >= 1
        texts = [s.text for s in sentences]
        assert any("你好" in t for t in texts)

    def test_long_sentence_split(self):
        long_text = "甲" * 100
        chunker = self.mod.TextChunker(language="unknown", max_chars=20)
        sentences = chunker.chunk_paragraphs([long_text])
        for s in sentences:
            assert len(s.text) <= 20

    def test_multiple_paragraphs_continuous_index(self):
        chunker = self.mod.TextChunker(language="unknown")
        sentences = chunker.chunk_paragraphs([
            "段落一的文字。",
            "段落二的文字。",
        ])
        indices = [s.index for s in sentences]
        assert indices == list(range(len(sentences)))
        para_ids = [s.paragraph_index for s in sentences]
        assert 0 in para_ids
        assert 1 in para_ids
