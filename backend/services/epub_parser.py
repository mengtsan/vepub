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

    def _find_cover_item(self):
        """多路徑封面偵測：cover-image ID → OPF meta → properties → 檔名啟發式。"""
        # 1. 標準 EPUB id: cover-image
        item = self.book.get_item_with_id("cover-image")
        if item and item.get_content():
            return item

        # 2. EPUB2 <meta name="cover" content="..."> 指向的 item id
        for ns_dict in self.book.metadata.values():
            for values in ns_dict.values():
                for _val, attrs in values:
                    if isinstance(attrs, dict) and attrs.get("name", "").lower() == "cover":
                        cover_id = attrs.get("content", "")
                        if cover_id:
                            ci = self.book.get_item_with_id(cover_id)
                            if ci and ci.get_content():
                                return ci

        # 3. EPUB3 properties="cover-image"
        for img_item in self.book.get_items_of_type(ebooklib.ITEM_IMAGE):
            props = getattr(img_item, "properties", None) or []
            if isinstance(props, str):
                props = props.split()
            if "cover-image" in props and img_item.get_content():
                return img_item

        # 4. 檔名啟發式（cover.jpg / cover.png / ...）
        for img_item in self.book.get_items_of_type(ebooklib.ITEM_IMAGE):
            fname = os.path.basename(getattr(img_item, "file_name", "") or "").lower()
            if fname.startswith("cover") and img_item.get_content():
                return img_item

        return None

    def get_meta(self) -> BookMeta:
        """
        取得書籍中繼資料與封面圖片。
        """
        title = self._get_meta_value("DC:title") or "未知書名"
        author = self._get_meta_value("DC:creator") or "未知作者"
        language = self._get_meta_value("DC:language") or "zh"

        cover_base64 = None
        try:
            cover_item = self._find_cover_item()
            if cover_item:
                cover_base64 = base64.b64encode(cover_item.get_content()).decode()
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
            # 使用 html.parser（Python 內建，無 lxml XMLParsedAsHTMLWarning）
            soup = BeautifulSoup(item.get_content(), "html.parser")

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


# ─── 模組級快取（支援單鍵失效，替代 functools.lru_cache 的 cache_clear()） ───────

_MAX_CACHED_BOOKS = 16
_chapters_cache: dict[str, list[Chapter]] = {}
_meta_cache: dict[str, BookMeta] = {}


def _trim(cache: dict) -> None:
    """超過上限時踢除最舊的 entry（Python 3.7+ dict 插入有序）。"""
    while len(cache) >= _MAX_CACHED_BOOKS:
        cache.pop(next(iter(cache)))


def get_chapters_cached(filepath: str) -> list[Chapter]:
    """對外介面：取得快取的章節清單（快取同路徑結果，最多 16 本）。"""
    if filepath not in _chapters_cache:
        _trim(_chapters_cache)
        _chapters_cache[filepath] = EpubParser(filepath).get_chapters()
    return _chapters_cache[filepath]


def get_meta_cached(filepath: str) -> BookMeta:
    """對外介面：取得快取的書籍 metadata（快取同路徑結果，最多 16 本）。"""
    if filepath not in _meta_cache:
        _trim(_meta_cache)
        _meta_cache[filepath] = EpubParser(filepath).get_meta()
    return _meta_cache[filepath]


def invalidate_cache(filepath: str) -> None:
    """書籍被刪除時呼叫，只清除該書的快取（不影響其他書）。"""
    _chapters_cache.pop(filepath, None)
    _meta_cache.pop(filepath, None)
