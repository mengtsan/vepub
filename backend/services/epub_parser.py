"""
EPUB 解析器。
輸入：EPUB 檔案路徑
輸出：
  - 書籍中繼資料（書名、作者、封面）
  - 章節清單（id, 標題, 順序）
  - 章節純文字（保留段落結構）
"""
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
from dataclasses import dataclass
from typing import Optional
import base64
import os


@dataclass
class BookMeta:
    title: str
    author: str
    language: str
    cover_base64: Optional[str]  # PNG Base64 字串，供前端顯示
    chapter_count: int

@dataclass
class Chapter:
    id: str
    title: str
    order: int
    paragraphs: list[str]  # 每個段落一個字串

def flatten_toc(toc_items) -> dict:
    """
    遞迴將 EPUB 的 TOC 樹平坦化為 href -> title 的 dictionary。
    """
    flat = {}
    for item in toc_items:
        if isinstance(item, tuple) and len(item) == 2:
            section, sub_items = item
            if section and hasattr(section, 'href') and section.href:
                href = section.href.split('#')[0]
                flat[href] = section.title
            elif section and hasattr(section, 'title') and section.title:
                pass
            flat.update(flatten_toc(sub_items))
        elif hasattr(item, 'href') and item.href:
            href = item.href.split('#')[0]
            flat[href] = item.title
    return flat

class EpubParser:
    def __init__(self, filepath: str):
        self.book = epub.read_epub(filepath)

    def get_meta(self) -> BookMeta:
        """
        取得書籍中繼資料與封面圖片。
        """
        title = self._get_meta_value("DC:title") or "未知書名"
        author = self._get_meta_value("DC:creator") or "未知作者"
        language = self._get_meta_value("DC:language") or "zh"

        cover_base64 = None
        try:
            cover_item = self.book.get_item_with_id("cover-image")
            if cover_item:
                cover_base64 = base64.b64encode(
                    cover_item.get_content()
                ).decode()
        except Exception:
            pass

        chapters = self._get_spine_items()
        return BookMeta(
            title=title,
            author=author,
            language=language,
            cover_base64=cover_base64,
            chapter_count=len(chapters),
        )

    def get_chapters(self) -> list[Chapter]:
        """
        解析並取得所有章節清單及其段落內容。
        """
        results = []
        spine_items = self._get_spine_items()
        flat_toc = flatten_toc(self.book.toc)

        # 定義塊級標籤與忽略標籤
        block_tags = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td", "blockquote", "pre"}
        ignore_tags = {"script", "style", "head", "title", "meta", "link"}

        for order, item in enumerate(spine_items):
            soup = BeautifulSoup(item.get_content(), "lxml")

            paragraphs = []
            current_para = []

            def walk(node):
                from bs4 import NavigableString
                
                if node.name in ignore_tags:
                    return
                    
                if isinstance(node, NavigableString):
                    txt = str(node).strip()
                    if txt:
                        current_para.append(txt)
                    return
                
                # 處理 br 標籤換行，避免文字黏黏在一起
                if node.name == "br":
                    if current_para and not current_para[-1].endswith(" "):
                        current_para.append(" ")
                    return

                is_block = node.name in block_tags
                
                if is_block:
                    # 進入 block 元素前，若當前有累積的文字，先存為段落
                    if current_para:
                        paragraphs.append("".join(current_para))
                        current_para.clear()
                        
                for child in node.children:
                    walk(child)
                    
                if is_block:
                    # 離開 block 元素時，若當前有累積的文字，存為段落
                    if current_para:
                        paragraphs.append("".join(current_para))
                        current_para.clear()

            body_tag = soup.find("body")
            if body_tag:
                walk(body_tag)
                
            # 最後保底處理
            if current_para:
                paragraphs.append("".join(current_para))
                
            # 清理段落中多餘的空白並過濾空段落
            paragraphs = [p.strip() for p in paragraphs if p.strip()]

            # 智慧取得章節標題
            title = None

            # 1. 優先從 Flat TOC 中匹配
            for href, toc_title in flat_toc.items():
                if (href.endswith(item.file_name) or 
                    item.file_name.endswith(href) or 
                    os.path.basename(href) == os.path.basename(item.file_name)):
                    title = toc_title
                    break

            # 2. 次優先：尋找 HTML 實體標題標籤
            if not title:
                title_tag = soup.find(["h1", "h2", "h3", "h4", "h5", "h6"])
                if title_tag:
                    title = title_tag.get_text(strip=True)

            # 3. 再次：尋找 <title> 標籤
            if not title:
                head_title = soup.find("title")
                if head_title:
                    t_text = head_title.get_text(strip=True)
                    # 避免無意義的預設 title
                    if t_text and t_text.lower() not in {"untitled", "無標題", "no title", "chapter", "section", "cover"}:
                        title = t_text

            # 4. 若仍無，嘗試拿第一個非空段落的前 20 個字
            if not title and paragraphs:
                first_p = paragraphs[0]
                if len(first_p) > 20:
                    title = first_p[:20] + "..."
                else:
                    title = first_p

            # 5. 保底標題（絕不用 "第 N 章"，避免打亂正式章節序號）
            if not title:
                title = f"過渡頁面 {order+1}"

            if paragraphs:
                results.append(Chapter(
                    id=item.id,
                    title=title,
                    order=order,
                    paragraphs=paragraphs,
                ))

        return results

    def _get_spine_items(self):
        """
        取得書籍的閱讀順序（Spine）中文檔項目。
        """
        spine_ids = [item_id for item_id, _ in self.book.spine]
        items = []
        for item_id in spine_ids:
            item = self.book.get_item_with_id(item_id)
            if item and item.get_type() == ebooklib.ITEM_DOCUMENT:
                items.append(item)
        return items

    def _get_meta_value(self, name: str) -> Optional[str]:
        """
        取得指定名稱的書籍中繼資料。
        """
        values = self.book.get_metadata(
            "http://purl.org/dc/elements/1.1/",
            name.replace("DC:", "").lower()
        )
        if values:
            return values[0][0]
        return None
