"""
專案全域常數。所有 port / 時間 / 路徑 / 超參數集中於此管理。
"""
import os
import sys
from pathlib import Path

# ─── 網路 ────────────────────────────────────────────────────────────────────
BACKEND_PORT = 8765
LLM_PORT     = 18765

# ─── 插圖任務 ────────────────────────────────────────────────────────────────
DONE_TTL = 60       # 任務完成後前端仍可讀取的保留秒數

# ─── LLM 伺服器 ──────────────────────────────────────────────────────────────
BATCH_CHARS  = 35_000   # 每批最大輸入字元數
LLM_IDLE_TTL = 300      # 推理後伺服器閒置 TTL（秒），逾時自動關閉

# ─── 路徑 ────────────────────────────────────────────────────────────────────
# 生產（PyInstaller frozen）: models / llama_bin 在 ~/.epub-tts/
# 開發：backend/models/  backend/llama_bin/
_FROZEN = getattr(sys, "frozen", False)

if _FROZEN:
    _DATA_DIR     = Path(os.path.expanduser("~/.epub-tts"))
    _BUNDLE_DIR   = Path(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
    MODELS_DIR    = _DATA_DIR / "models"
    LLAMA_BIN_DIR = _BUNDLE_DIR / "llama_bin"
else:
    _BACKEND_DIR  = Path(__file__).parent
    MODELS_DIR    = _BACKEND_DIR / "models"
    LLAMA_BIN_DIR = _BACKEND_DIR / "llama_bin"
