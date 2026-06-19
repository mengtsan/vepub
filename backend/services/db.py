"""
SQLite 資料庫服務。
負責管理書庫、閱讀進度、書籤與使用者設定。
"""
import sqlite3
import os
from pathlib import Path

# 設定資料庫儲存路徑
DB_DIR = Path(os.path.expanduser("~/.epub-tts"))
DB_PATH = DB_DIR / "library.db"

def init_db():
    """
    初始化資料庫，建立所需的資料表與預設設定。
    """
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    # 1. 建立書庫資料表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS books (
      id            TEXT PRIMARY KEY,
      title         TEXT NOT NULL,
      author        TEXT,
      language      TEXT DEFAULT 'zh',
      cover_base64  TEXT,
      file_path     TEXT NOT NULL,
      chapter_count INTEGER DEFAULT 0,
      file_hash     TEXT,
      created_at    INTEGER DEFAULT (strftime('%s', 'now'))
    );
    """)
    # migration：為已存在的資料庫補 file_hash 欄位
    existing_cols = {row[1] for row in cursor.execute("PRAGMA table_info(books)").fetchall()}
    if "file_hash" not in existing_cols:
        cursor.execute("ALTER TABLE books ADD COLUMN file_hash TEXT")

    # 2. 建立閱讀進度資料表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reading_progress (
      book_id           TEXT PRIMARY KEY,
      chapter_index     INTEGER DEFAULT 0,
      sentence_index    INTEGER DEFAULT 0,
      scroll_position   REAL DEFAULT 0,
      updated_at        INTEGER DEFAULT (strftime('%s', 'now')),
      FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE
    );
    """)

    # 3. 建立書籤資料表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS bookmarks (
      id              INTEGER PRIMARY KEY AUTOINCREMENT,
      book_id         TEXT,
      chapter_index   INTEGER,
      sentence_index  INTEGER,
      note            TEXT,
      created_at      INTEGER DEFAULT (strftime('%s', 'now')),
      FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE CASCADE
    );
    """)

    # 4. 建立使用者設定資料表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
      key   TEXT PRIMARY KEY,
      value TEXT
    );
    """)

    # 寫入預設設定項目
    default_settings = [
      ('theme', 'dark'),
      ('font_size', '18'),
      ('font_family', 'sans'),
      ('line_height', '1.7'),
      ('speed', '1.0'),
      ('voice', 'default'),
      ('tts_model', 'official')
    ]
    cursor.executemany("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", default_settings)

    conn.commit()
    conn.close()

def get_db_connection():
    """
    獲取資料庫連線，並設定 row_factory 以回傳 dict 格式資料。
    """
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")   # 允許並發讀寫，避免 database is locked
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn
