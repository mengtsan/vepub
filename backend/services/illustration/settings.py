"""
插圖設定（IllustrationSettings）與持久化。
不依賴 pipelines / generation，可在 CI 中測試。
"""
import json
import logging
import os

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class LoraEntry(BaseModel):
    filename: str
    weight: float = 1.0
    enabled: bool = True


class IllustrationSettings(BaseModel):
    steps: int            = 30
    guidance_scale: float = 6.0
    width: int            = 1024
    height: int           = 1024
    sheet_width: int      = 832
    sheet_height: int     = 1216
    prompt_prefix: str    = (
        "score_9, score_8_up, score_7_up, score_6_up, illustration, "
        "soft shading, detailed shading, colorful, "
        "absurdres, highres, masterpiece, best quality, highly detailed"
    )
    ip_adapter_scale: float = 0.7
    # ── Hires Fix ──────────────────────────────────────────────────────────────
    hires_fix_enabled: bool  = False
    hires_upscale: float     = 1.5
    hires_denoise: float     = 0.35
    # ── ADetailer ──────────────────────────────────────────────────────────────
    adetailer_enabled: bool  = True
    adetailer_denoise: float = 0.4   # 0.3 保守 / 0.45 明顯重繪
    active_loras: list[LoraEntry] = []
    negative_prompt: str  = (
        "score_5, score_4, score_3, score_2, score_1, "
        "worst quality, bad quality, lowres, jpeg artifacts, blurry, deformed, "
        "bad anatomy, bad hands, extra limbs, missing limbs, missing fingers, extra fingers, "
        "bad eyes, asymmetrical eyes, poorly drawn eyes, "
        "text, watermark, signature, "
        "flat color, flat shading, monochrome, greyscale, "
        "loli, minor, "
        "rough sketch, lineart, thick lines, thick outline, dirty lines, messy linework, "
        "cel shading, simple shading"
    )


_settings = IllustrationSettings()
_SETTINGS_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "illustration_settings.json")
)


def get_settings() -> IllustrationSettings:
    return _settings


def update_settings(patch: dict) -> IllustrationSettings:
    global _settings
    _settings = _settings.model_copy(update=patch)
    _persist_settings()
    return _settings


def _persist_settings():
    try:
        with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(_settings.model_dump(), f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning("設定儲存失敗: %s", e)
    try:
        from services.db import get_db_connection
        conn = get_db_connection()
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            ("illustration_prompt_prefix", _settings.prompt_prefix),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.debug("同步 prompt_prefix 到 SQLite 失敗: %s", e)


def _load_settings():
    global _settings
    if os.path.exists(_SETTINGS_PATH):
        try:
            with open(_SETTINGS_PATH, encoding="utf-8") as f:
                data = json.load(f)
            known = set(IllustrationSettings.model_fields)
            _settings = IllustrationSettings(**{k: v for k, v in data.items() if k in known})
            logger.info("設定已從 JSON 讀取: steps=%s", _settings.steps)
        except Exception as e:
            logger.warning("設定讀取失敗，使用預設值: %s", e)
    try:
        from services.db import get_db_connection
        conn = get_db_connection()
        row = conn.execute(
            "SELECT value FROM settings WHERE key='illustration_prompt_prefix'"
        ).fetchone()
        conn.close()
        if row and row["value"] is not None:
            _settings = _settings.model_copy(update={"prompt_prefix": row["value"]})
    except Exception:
        pass


_load_settings()
