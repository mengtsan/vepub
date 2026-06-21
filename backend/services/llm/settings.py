"""
LLM 取樣設定（LLMSettings）與持久化。

預設 override_enabled=False —— 此時完全沿用 tasks.py 內各呼叫「刻意分別調過」的
temperature/max_tokens（分析 0.15、場景 0.2、構圖 0.5/0.85…），不影響提示詞管線。
使用者主動開啟全域覆寫後，_chat() 才會以這裡的值取代各呼叫的取樣參數。

不依賴 server.py，可在 CI 中單獨測試。
"""
import json
import logging
import os

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class LLMSettings(BaseModel):
    # 全域覆寫總開關：關閉時下列值一律不套用，沿用各呼叫的調校值。
    override_enabled: bool = False
    temperature: float    = 0.4
    top_p: float          = 0.95
    top_k: int            = 40
    repeat_penalty: float = 1.1
    # null = 不覆寫輸出長度（沿用各呼叫值）。設值會截斷較長的輸出（如全書分析 3000），
    # 故預設留空，避免使用者一開啟覆寫就把分析/角色提取的 JSON 截斷。
    max_tokens: int | None = None


_settings = LLMSettings()
_SETTINGS_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "llm_settings.json")
)


def get_settings() -> LLMSettings:
    return _settings


def update_settings(patch: dict) -> LLMSettings:
    global _settings
    _settings = _settings.model_copy(update=patch)
    _persist_settings()
    return _settings


def _persist_settings():
    try:
        with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(_settings.model_dump(), f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning("LLM 設定儲存失敗: %s", e)


def _load_settings():
    global _settings
    if os.path.exists(_SETTINGS_PATH):
        try:
            with open(_SETTINGS_PATH, encoding="utf-8") as f:
                data = json.load(f)
            known = set(LLMSettings.model_fields)
            _settings = LLMSettings(**{k: v for k, v in data.items() if k in known})
            logger.info("LLM 設定已從 JSON 讀取: override=%s", _settings.override_enabled)
        except Exception as e:
            logger.warning("LLM 設定讀取失敗，使用預設值: %s", e)


_load_settings()
