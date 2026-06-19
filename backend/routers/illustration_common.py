"""
illustration 路由共用工具 / 狀態。
被 illustration.py（生圖任務）與 characters.py（角色管理）共同 import。
"""
import asyncio
import json
import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

from pydantic import BaseModel
from services.db import get_db_connection, DB_DIR
from config import DONE_TTL

# ─── 全局任務字典（單一實例，兩個 router 共享）───────────────────────────────────
_tasks:         dict[str, dict[str, Any]] = {}   # 生圖任務
_analysis_jobs: dict[str, dict[str, Any]] = {}   # 全書分析任務
_angle_jobs:    dict[str, dict[str, Any]] = {}   # 設定圖任務
_portrait_jobs: dict[str, dict[str, Any]] = {}   # 立繪任務

_queue_sem = asyncio.Semaphore(1)   # 生圖 / 設定圖 / 立繪序列化
_DONE_TTL  = DONE_TTL

# ─── 圖片目錄 ─────────────────────────────────────────────────────────────────
_IMAGES_DIR = DB_DIR / "images"


# ─── 工具函式 ─────────────────────────────────────────────────────────────────

def _evict_expired(d: dict, ttl: int) -> None:
    """惰性清除 dict 中 done_at 超過 ttl 秒的已完成/錯誤項目。"""
    now = time.time()
    expired = [k for k, v in d.items() if v.get("done_at") and now - v["done_at"] > ttl]
    for k in expired:
        d.pop(k, None)


def _ensure_columns(conn, table: str, col_defs: list[tuple[str, str]]) -> None:
    """只 ALTER TABLE 真正缺少的欄位，非預期錯誤會記錄而非靜默吞掉。"""
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for col_name, col_type in col_defs:
        if col_name not in existing:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
            except Exception as e:
                logger.warning("migration error — %s.%s: %s", table, col_name, e)


def _save_image_file(img_bytes: bytes, subdir: str = "illustrations") -> str:
    """將圖片位元組存到磁碟，回傳相對路徑（如 'illustrations/{uuid}.png'）。"""
    target = _IMAGES_DIR / subdir
    target.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4()}.png"
    (target / filename).write_bytes(img_bytes)
    return f"{subdir}/{filename}"


# 角色參考圖讀取已搬到 services/illustration/refs.py（service 層不應反向 import
# routers），此處保留同名轉出口，characters.py / illustration.py 不需改 import。
from services.illustration.refs import load_char_ref_image as _load_char_ref_image


def _delete_image_file(image_path: str | None) -> None:
    """刪除圖片檔案（路徑為 _save_image_file 回傳的相對路徑）。"""
    if not image_path:
        return
    try:
        full = _IMAGES_DIR / image_path
        if full.exists():
            full.unlink()
    except Exception:
        pass


def _persist_analysis_job(book_id: str, job: dict) -> None:
    """將分析任務狀態同步寫入 SQLite，供伺服器重啟後查詢。"""
    conn = get_db_connection()
    conn.execute("""
        INSERT INTO analysis_jobs (book_id, status, progress, label, result_json, error, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, strftime('%s','now'))
        ON CONFLICT(book_id) DO UPDATE SET
            status      = excluded.status,
            progress    = excluded.progress,
            label       = excluded.label,
            result_json = excluded.result_json,
            error       = excluded.error,
            updated_at  = excluded.updated_at
    """, (
        book_id,
        job.get("status", "pending"),
        job.get("progress", 0),
        job.get("label", ""),
        json.dumps(job["result"]) if job.get("result") is not None else None,
        job.get("error"),
    ))
    conn.commit()
    conn.close()


def init_illustration_tables():
    """由 main.py lifespan 呼叫一次，不在各 endpoint 重複執行。"""
    conn = get_db_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS characters (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id          TEXT NOT NULL,
            name             TEXT NOT NULL,
            description      TEXT DEFAULT '',
            ref_image_base64 TEXT,
            created_at       INTEGER DEFAULT (strftime('%s','now')),
            UNIQUE(book_id, name)
        )
    """)
    _ensure_columns(conn, "characters", [
        ("gender",            "TEXT"),
        ("age_hint",          "TEXT"),
        ("hair_color",        "TEXT"),
        ("hair_style",        "TEXT"),
        ("eye_color",         "TEXT"),
        ("body_type",         "TEXT"),
        ("height_cm",         "INTEGER"),
        ("weight_kg",         "INTEGER"),
        ("bwh",               "TEXT"),
        ("cup_size",          "TEXT"),
        ("signature_outfit",  "TEXT"),
        ("other_features",    "TEXT"),
        ("character_seed",    "INTEGER DEFAULT -1"),
        ("lora_path",         "TEXT"),
        ("lora_trained_at",   "INTEGER"),
        ("locked",            "INTEGER DEFAULT 0"),
        ("skin_tone",         "TEXT"),
        ("face_shape",        "TEXT"),
        ("eye_shape",         "TEXT"),
        ("era_style",         "TEXT"),
        ("color_palette",     "TEXT"),
        ("accessories",       "TEXT"),
        ("distinctive_marks", "TEXT"),
        ("special_traits",    "TEXT"),
    ])

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_characters_book_id
        ON characters(book_id)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS character_images (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            character_id  INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
            image_base64  TEXT DEFAULT '',
            angle         TEXT DEFAULT 'other',
            is_primary    INTEGER DEFAULT 0,
            created_at    INTEGER DEFAULT (strftime('%s','now'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_character_images_character_id
        ON character_images(character_id)
    """)
    _ensure_columns(conn, "character_images", [
        ("image_path", "TEXT"),
        ("prompt",     "TEXT"),
    ])
    # 遷移：若舊版資料庫的 image_base64 設為 NOT NULL，需重建表格
    ci_info = {row[1]: row for row in conn.execute("PRAGMA table_info(character_images)").fetchall()}
    if "image_base64" in ci_info and ci_info["image_base64"][3] == 1:  # notnull=1
        logger.info("遷移 character_images：移除 image_base64 的 NOT NULL 約束")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS character_images_new (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                character_id  INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
                image_base64  TEXT DEFAULT '',
                angle         TEXT DEFAULT 'other',
                is_primary    INTEGER DEFAULT 0,
                created_at    INTEGER DEFAULT (strftime('%s','now')),
                image_path    TEXT
            )
        """)
        conn.execute("""
            INSERT INTO character_images_new
                (id, character_id, image_base64, angle, is_primary, created_at, image_path)
            SELECT id, character_id,
                   COALESCE(image_base64, '') AS image_base64,
                   angle, is_primary, created_at, image_path
            FROM character_images
        """)
        conn.execute("DROP TABLE character_images")
        conn.execute("ALTER TABLE character_images_new RENAME TO character_images")
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_character_images_character_id
            ON character_images(character_id)
        """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS illustrations (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id        TEXT,
            chapter_index  INTEGER,
            sentence_index INTEGER,
            prompt         TEXT,
            image_base64   TEXT,
            created_at     INTEGER DEFAULT (strftime('%s','now'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_illustrations_book_chapter
        ON illustrations(book_id, chapter_index)
    """)
    _ensure_columns(conn, "illustrations", [
        ("model_name",      "TEXT"),
        ("steps",           "INTEGER"),
        ("guidance_scale",  "REAL"),
        ("seed",            "INTEGER"),
        ("width",           "INTEGER"),
        ("height",          "INTEGER"),
        ("is_anime",        "INTEGER"),
        ("image_path",      "TEXT"),
        ("workflow",        "TEXT"),
        ("sampler",         "TEXT"),
        ("clip_skip",       "INTEGER"),
        ("negative_prompt", "TEXT"),
    ])
    (_IMAGES_DIR / "illustrations").mkdir(parents=True, exist_ok=True)
    (_IMAGES_DIR / "characters").mkdir(parents=True, exist_ok=True)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS analysis_checkpoints (
            book_id       TEXT NOT NULL,
            chapter_index INTEGER NOT NULL,
            completed_at  INTEGER DEFAULT (strftime('%s','now')),
            PRIMARY KEY (book_id, chapter_index)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS analysis_jobs (
            book_id     TEXT PRIMARY KEY,
            status      TEXT NOT NULL DEFAULT 'pending',
            progress    INTEGER DEFAULT 0,
            label       TEXT DEFAULT '',
            result_json TEXT,
            error       TEXT,
            started_at  INTEGER DEFAULT (strftime('%s','now')),
            updated_at  INTEGER DEFAULT (strftime('%s','now'))
        )
    """)
    conn.execute(
        "UPDATE analysis_jobs SET status='interrupted', label='伺服器重啟，任務已中斷' "
        "WHERE status='running'"
    )

    # 書籍刪除時自動清除相關分析/角色資料（FK 替代方案：trigger）
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_book_delete_cascade
        AFTER DELETE ON books BEGIN
            DELETE FROM characters           WHERE book_id = OLD.id;
            DELETE FROM analysis_jobs        WHERE book_id = OLD.id;
            DELETE FROM analysis_checkpoints WHERE book_id = OLD.id;
        END
    """)

    conn.commit()
    conn.close()


# ─── Pydantic Models（兩個 router 共用）──────────────────────────────────────

class GenerateRequest(BaseModel):
    text: str            = ""
    direct_prompt: str   = ""
    character_name: str  = ""
    book_id: str         = ""
    chapter_index: int   = -1
    sentence_index: int  = -1
    width: int           = 1024
    height: int          = 1024
    seed: int            = -1
    prompt_prefix: str   = ""


class CharacterUpsert(BaseModel):
    name: str
    # ── 基本 ──
    gender: str | None           = None
    age_hint: str | None         = None
    # ── 面部特徵 ──
    skin_tone: str | None        = None
    face_shape: str | None       = None
    hair_color: str | None       = None
    hair_style: str | None       = None
    eye_color: str | None        = None
    eye_shape: str | None        = None
    # ── 體型 ──
    body_type: str | None        = None
    height_cm: int | None        = None
    weight_kg: int | None        = None
    bwh: str | None              = None
    cup_size: str | None         = None
    # ── 服飾配件 ──
    era_style: str | None        = None
    signature_outfit: str | None = None
    color_palette: str | None    = None
    accessories: str | None      = None
    # ── 特殊特徵 ──
    distinctive_marks: str | None = None
    special_traits: str | None    = None
    other_features: str | None    = None
    # ── 系統欄位 ──
    character_seed: int          = -1
    locked: int | None           = None
    # ── 相容舊版 ──
    description: str             = ""
    ref_image_base64: str | None = None


class ExtractCharacterRequest(BaseModel):
    text: str
    book_id: str = ""


class CharacterImageAdd(BaseModel):
    image_base64: str
    angle: str       = "other"
    is_primary: bool = False


class BatchDeleteRequest(BaseModel):
    names: list[str]


class GenerateAnglesRequest(BaseModel):
    name:          str       = ""
    width:         int | None = None
    height:        int | None = None
    seed:          int       = -1
    prompt_prefix: str | None = None


class PortraitRequest(BaseModel):
    name:          str       = ""
    width:         int | None = None
    height:        int | None = None
    seed:          int        = -1
    prompt_prefix: str | None = None


# ─── 角色分析輔助常數 ──────────────────────────────────────────────────────────
_ALL_TEXT_COLS = [
    "description",
    "gender", "age_hint",
    "skin_tone", "face_shape", "hair_color", "hair_style", "eye_color", "eye_shape",
    "body_type", "bwh", "cup_size",
    "era_style", "signature_outfit", "color_palette", "accessories",
    "distinctive_marks", "special_traits", "other_features",
]
