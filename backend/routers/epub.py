"""
EPUB 與書庫路由。
POST /epub/parse             → 解析上傳的 EPUB，將其存入本地目錄並寫入資料庫，回傳書籍資訊
GET  /epub/books             → 取得書庫中所有的書籍列表
DELETE /epub/books/{book_id}  → 刪除指定書籍（包含實體檔案與資料庫記錄）
POST /epub/{book_id}/chapter/{chapter_id}/sentences → 將傳入的段落文字切割成句子列表
GET  /epub/{book_id}/progress → 取得該書的閱讀進度
POST /epub/{book_id}/progress → 儲存該書的閱讀進度
GET  /epub/settings          → 取得使用者設定
POST /epub/settings          → 儲存使用者設定
"""
import asyncio
import hashlib
import logging
import os
import uuid

logger = logging.getLogger(__name__)
import shutil
from pathlib import Path
from pydantic import BaseModel
from fastapi import APIRouter, UploadFile, File, HTTPException, Body
from services.epub_parser import EpubParser, get_chapters_cached, get_meta_cached, invalidate_cache
from services.text_chunker import TextChunker
from services.db import get_db_connection, DB_DIR

router = APIRouter()

# 設定書籍實體檔案儲存路徑
BOOKS_DIR = DB_DIR / "books"
BOOKS_DIR.mkdir(parents=True, exist_ok=True)

class ProgressUpdate(BaseModel):
    chapter_index: int
    sentence_index: int
    scroll_position: float = 0.0

@router.post("/parse")
async def parse_epub(file: UploadFile = File(...)):
    """
    解析上傳的 EPUB 檔案，並儲存至本地目錄與資料庫中。
    若同一檔案已匯入（依 sha256 去重），直接回傳既有書籍資料。
    """
    file_bytes = await file.read()
    file_hash = hashlib.sha256(file_bytes).hexdigest()[:32]

    # 去重查詢：同一檔案已匯入則直接回傳
    conn = get_db_connection()
    dup = conn.execute(
        "SELECT id, title, author, language, cover_base64, chapter_count, file_path FROM books WHERE file_hash=?",
        (file_hash,)
    ).fetchone()
    conn.close()

    if dup:
        loop = asyncio.get_running_loop()
        try:
            chapters = await loop.run_in_executor(None, get_chapters_cached, dup["file_path"])
        except Exception:
            chapters = []
        return {
            "book_id": dup["id"],
            "duplicate": True,
            "meta": {
                "title": dup["title"],
                "author": dup["author"],
                "language": dup["language"],
                "cover_base64": dup["cover_base64"],
                "chapter_count": dup["chapter_count"],
            },
            "chapters": [
                {"id": ch.id, "title": ch.title, "order": ch.order, "paragraph_count": len(ch.paragraphs)}
                for ch in chapters
            ],
        }

    book_id = str(uuid.uuid4())
    save_path = BOOKS_DIR / f"{book_id}.epub"

    # 儲存上傳的檔案（在 executor 執行，避免大檔寫入阻塞 event loop）
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, save_path.write_bytes, file_bytes)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"儲存電子書檔案失敗: {str(e)}")

    try:
        # 在 thread pool 執行同步的 EPUB 解析，避免阻塞 event loop
        loop = asyncio.get_running_loop()
        meta = await loop.run_in_executor(None, get_meta_cached, str(save_path))
        chapters = await loop.run_in_executor(None, get_chapters_cached, str(save_path))

        # 將書籍元資料寫入資料庫
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO books (id, title, author, language, cover_base64, file_path, chapter_count, file_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                book_id,
                meta.title,
                meta.author,
                meta.language,
                meta.cover_base64,
                str(save_path),
                meta.chapter_count,
                file_hash,
            )
        )
        # 初始化預設進度
        cursor.execute(
            "INSERT OR IGNORE INTO reading_progress (book_id, chapter_index, sentence_index) VALUES (?, 0, 0)",
            (book_id,)
        )
        conn.commit()
        conn.close()

        return {
            "book_id": book_id,
            "meta": {
                "title": meta.title,
                "author": meta.author,
                "language": meta.language,
                "cover_base64": meta.cover_base64,
                "chapter_count": meta.chapter_count,
            },
            "chapters": [
                {
                    "id": ch.id,
                    "title": ch.title,
                    "order": ch.order,
                    "paragraph_count": len(ch.paragraphs)
                }
                for ch in chapters
            ],
        }
    except Exception as e:
        # 發生錯誤時清理已儲存的檔案
        if save_path.exists():
            os.unlink(save_path)
        raise HTTPException(status_code=400, detail=f"解析 EPUB 檔案失敗: {str(e)}")

@router.get("/books")
async def get_books():
    """
    取得書庫內所有書籍列表（包含最新進度）。
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT b.id, b.title, b.author, b.language, b.cover_base64, b.chapter_count, b.created_at,
               p.chapter_index, p.sentence_index, p.scroll_position
        FROM books b
        LEFT JOIN reading_progress p ON b.id = p.book_id
        ORDER BY b.created_at DESC
    """)
    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]

@router.delete("/books/{book_id}")
async def delete_book(book_id: str):
    """
    自書庫中刪除書籍（含實體檔案與資料庫記錄）。
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 查詢檔案路徑以利刪除
    cursor.execute("SELECT file_path FROM books WHERE id = ?", (book_id,))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="找不到該書籍")

    file_path = row["file_path"]

    try:
        # 刪除資料庫記錄（藉由外鍵級聯刪除進度與書籤）
        cursor.execute("DELETE FROM books WHERE id = ?", (book_id,))
        conn.commit()
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"自資料庫刪除書籍失敗: {str(e)}")
    finally:
        conn.close()

    # 刪除實體檔案並清除快取
    if os.path.exists(file_path):
        try:
            invalidate_cache(file_path)
            os.unlink(file_path)
        except Exception as e:
            logger.warning("刪除實體檔案失敗 (%s): %s", file_path, e)

    return {"status": "success", "message": "書籍已成功刪除"}

@router.get("/{book_id}/chapters")
async def get_book_chapters(book_id: str):
    """
    依書籍 ID 獲取該書所有章節的元資料清單。
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT file_path FROM books WHERE id = ?", (book_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="找不到該書籍")

    try:
        loop = asyncio.get_running_loop()
        chapters = await loop.run_in_executor(None, get_chapters_cached, row["file_path"])
        return [
            {
                "id": ch.id,
                "title": ch.title,
                "order": ch.order,
                "paragraph_count": len(ch.paragraphs)
            }
            for ch in chapters
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"讀取書籍章節失敗: {str(e)}")

@router.get("/{book_id}/chapter/{chapter_id}/paragraphs")
async def get_chapter_paragraphs(book_id: str, chapter_id: str):
    """
    獲取指定章節的所有段落純文字內容。
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT file_path FROM books WHERE id = ?", (book_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="找不到該書籍")

    try:
        loop = asyncio.get_running_loop()
        chapters = await loop.run_in_executor(None, get_chapters_cached, row["file_path"])

        # 優先以 ID 進行匹配
        for ch in chapters:
            if ch.id == chapter_id:
                return {"paragraphs": ch.paragraphs}
        
        # 備用方案：若 ID 無法匹配且為數字，則以章節 index 匹配
        try:
            idx = int(chapter_id)
            if 0 <= idx < len(chapters):
                return {"paragraphs": chapters[idx].paragraphs}
        except ValueError:
            pass
            
        raise HTTPException(status_code=404, detail="找不到指定章節")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"讀取章節段落失敗: {str(e)}")

@router.post("/{book_id}/chapter/{chapter_id}/sentences")
async def get_sentences(
    book_id: str,
    chapter_id: str,
    paragraphs: list[str],
    language: str = "zh"
):
    """
    將段落列表切割為句子列表。
    """
    loop = asyncio.get_running_loop()
    def _chunk():
        chunker = TextChunker(language=language)
        return chunker.chunk_paragraphs(paragraphs)
    sentences = await loop.run_in_executor(None, _chunk)
    out = [
        {
            "index": s.index,
            "paragraph_index": s.paragraph_index,
            "text": s.text,
            "char_start": s.char_start,
            "char_end": s.char_end,
        }
        for s in sentences
    ]
    # Phase 2 角色配音：歸屬每句說話者並附上聲線 instruct（在執行緒池跑，含 DB 查詢）。
    await loop.run_in_executor(None, _attach_character_voices, book_id, out)
    return {"sentences": out}


def _attach_character_voices(book_id: str, sentences: list[dict]) -> None:
    """就地為每句加上 speaker（角色名|None）與 instruct（該角色聲線|None）。

    受 tts_settings.character_voices 開關控制；關閉或無角色時不附加（前端退回旁白/對白）。
    """
    try:
        from services.tts_settings import get_settings as _tts_get
        if not _tts_get().character_voices:
            return
        from services.tts_voice import attribute_speakers, character_voice_instruct

        conn = get_db_connection()
        try:
            rows = conn.execute(
                "SELECT name, gender, age_hint FROM characters WHERE book_id=?",
                (book_id,),
            ).fetchall()
        finally:
            conn.close()
        chars = {r["name"]: dict(r) for r in rows if r["name"]}
        if not chars:
            return

        speakers = attribute_speakers(sentences, list(chars.keys()))
        for sent, who in zip(sentences, speakers):
            if not who:
                continue
            c = chars.get(who, {})
            sent["speaker"] = who
            sent["instruct"] = character_voice_instruct(
                c.get("gender"), c.get("age_hint"), who
            )
    except Exception as e:
        logger.warning("角色配音歸屬失敗（略過，退回旁白/對白）: %s", e)

@router.get("/{book_id}/progress")
async def get_progress(book_id: str):
    """
    取得指定書籍的閱讀進度。
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT chapter_index, sentence_index, scroll_position, updated_at FROM reading_progress WHERE book_id = ?",
        (book_id,)
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        return {"chapter_index": 0, "sentence_index": 0, "scroll_position": 0.0}
    return dict(row)

@router.post("/{book_id}/progress")
async def save_progress(book_id: str, progress: ProgressUpdate):
    """
    儲存指定書籍的閱讀進度。
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO reading_progress (book_id, chapter_index, sentence_index, scroll_position, updated_at)
        VALUES (?, ?, ?, ?, strftime('%s', 'now'))
        ON CONFLICT(book_id) DO UPDATE SET
          chapter_index = excluded.chapter_index,
          sentence_index = excluded.sentence_index,
          scroll_position = excluded.scroll_position,
          updated_at = excluded.updated_at
        """,
        (book_id, progress.chapter_index, progress.sentence_index, progress.scroll_position)
    )
    conn.commit()
    conn.close()
    return {"status": "success"}

class BookmarkCreate(BaseModel):
    chapter_index: int
    sentence_index: int
    note: str = ""

@router.get("/{book_id}/bookmarks")
async def get_bookmarks(book_id: str):
    """取得指定書籍的所有書籤。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, chapter_index, sentence_index, note, created_at FROM bookmarks WHERE book_id = ? ORDER BY created_at DESC",
        (book_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

@router.post("/{book_id}/bookmarks")
async def create_bookmark(book_id: str, bm: BookmarkCreate):
    """新增書籤。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO bookmarks (book_id, chapter_index, sentence_index, note) VALUES (?, ?, ?, ?)",
        (book_id, bm.chapter_index, bm.sentence_index, bm.note)
    )
    bm_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {"id": bm_id, "status": "success"}

@router.delete("/{book_id}/bookmarks/{bookmark_id}")
async def delete_bookmark(book_id: str, bookmark_id: int):
    """刪除書籤。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM bookmarks WHERE id = ? AND book_id = ?", (bookmark_id, book_id))
    conn.commit()
    conn.close()
    return {"status": "success"}

@router.get("/settings")
async def get_settings():
    """
    取得全域使用者設定。
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM settings")
    rows = cursor.fetchall()
    conn.close()
    return {row["key"]: row["value"] for row in rows}

@router.post("/settings")
async def update_settings(settings: dict = Body(...)):
    """
    儲存或更新全域使用者設定。
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    for key, value in settings.items():
        cursor.execute(
            """
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, str(value))
        )
    conn.commit()
    conn.close()

    # 同步更新插圖引擎的 in-memory 設定
    illus_patch: dict = {}
    if "illustration_prompt_prefix" in settings:
        illus_patch["prompt_prefix"] = str(settings["illustration_prompt_prefix"])
    if "illustration_negative_prompt" in settings:
        illus_patch["negative_prompt"] = str(settings["illustration_negative_prompt"])
    if illus_patch:
        try:
            from services.illustration.settings import update_settings as _update_illus
            _update_illus(illus_patch)
        except Exception:
            pass

    return {"status": "success"}
