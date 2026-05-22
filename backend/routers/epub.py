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
from fastapi import APIRouter, UploadFile, File, HTTPException, Body
from services.epub_parser import EpubParser
from services.text_chunker import TextChunker
from services.db import get_db_connection, DB_DIR
import os
import uuid
import shutil
from pathlib import Path
from pydantic import BaseModel

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
    """
    book_id = str(uuid.uuid4())
    save_path = BOOKS_DIR / f"{book_id}.epub"

    # 儲存上傳的檔案
    try:
        with open(save_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"儲存電子書檔案失敗: {str(e)}")

    try:
        parser = EpubParser(str(save_path))
        meta = parser.get_meta()
        chapters = parser.get_chapters()

        # 將書籍元資料寫入資料庫
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO books (id, title, author, language, cover_base64, file_path, chapter_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                book_id,
                meta.title,
                meta.author,
                meta.language,
                meta.cover_base64,
                str(save_path),
                meta.chapter_count
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
            "_chapters_data": [
                {
                    "id": ch.id,
                    "paragraphs": ch.paragraphs
                }
                for ch in chapters
            ]
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

    # 刪除實體檔案
    if os.path.exists(file_path):
        try:
            os.unlink(file_path)
        except Exception as e:
            # 實體檔案刪除失敗僅作警告，不阻斷 API 回傳
            print(f"警告：刪除實體檔案失敗 ({file_path}): {str(e)}")

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
        parser = EpubParser(row["file_path"])
        chapters = parser.get_chapters()
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
        parser = EpubParser(row["file_path"])
        chapters = parser.get_chapters()
        
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
    chunker = TextChunker(language=language)
    sentences = chunker.chunk_paragraphs(paragraphs)
    return {
        "sentences": [
            {
                "index": s.index,
                "paragraph_index": s.paragraph_index,
                "text": s.text,
                "char_start": s.char_start,
                "char_end": s.char_end,
            }
            for s in sentences
        ]
    }

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
    return {"status": "success"}
