"""
TTS 全域設定（TTSSettings）與持久化。

目前僅含「優先手動語系」forced_language：
  - None 或 "auto" → 不強制，由文字內容自動偵測（detect_language）。
  - OmniVoice 語言 ID（如 "zh" 普通話 / "ja" 日文 / "en" 英文 / "yue" 粵語）→ 強制使用。

語言決議優先序（高→低）：單次請求的 language ＞ 此處 forced_language ＞ 自動偵測。

不依賴 tts_engine，可單獨測試（避免循環匯入）。
"""
import json
import logging
import os

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class TTSSettings(BaseModel):
    # 優先手動語系：覆寫自動偵測。None / "auto" = 不強制。
    forced_language: str | None = None


_settings = TTSSettings()
_SETTINGS_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "tts_settings.json")
)


def get_settings() -> TTSSettings:
    return _settings


def get_forced_language() -> str | None:
    """回傳已設定的強制語系；未設定或為 'auto' 時回傳 None。"""
    fl = _settings.forced_language
    if fl and fl.strip().lower() != "auto":
        return fl.strip()
    return None


def update_settings(patch: dict) -> TTSSettings:
    global _settings
    _settings = _settings.model_copy(update=patch)
    _persist_settings()
    return _settings


def _persist_settings():
    try:
        with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(_settings.model_dump(), f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning("TTS 設定儲存失敗: %s", e)


def _load_settings():
    global _settings
    if os.path.exists(_SETTINGS_PATH):
        try:
            with open(_SETTINGS_PATH, encoding="utf-8") as f:
                data = json.load(f)
            known = set(TTSSettings.model_fields)
            _settings = TTSSettings(**{k: v for k, v in data.items() if k in known})
            logger.info("TTS 設定已從 JSON 讀取: forced_language=%s", _settings.forced_language)
        except Exception as e:
            logger.warning("TTS 設定讀取失敗，使用預設值: %s", e)


_load_settings()
