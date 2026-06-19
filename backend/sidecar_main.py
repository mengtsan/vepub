"""
生產模式 FastAPI 入口（供 PyInstaller 打包）。
差異與 main.py：
  - 不使用 --reload
  - 將 stdout/stderr 導向 ~/.epub-tts/backend.log
  - 直接呼叫 uvicorn.run（非 CLI）
"""
import logging
import os
import sys
from pathlib import Path

# 確保 bundle 內的模組路徑優先（PyInstaller onedir）
if getattr(sys, "frozen", False):
    _bundle = Path(sys._MEIPASS)
    if str(_bundle) not in sys.path:
        sys.path.insert(0, str(_bundle))

# ─── File logging ────────────────────────────────────────────────────────────
_LOG_DIR = Path(os.path.expanduser("~/.epub-tts"))
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOG_PATH = _LOG_DIR / "backend.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(_LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)
logger.info("vepub sidecar backend 啟動，log → %s", _LOG_PATH)

# ─── 啟動 ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    from config import BACKEND_PORT
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=BACKEND_PORT,
        log_level="info",
        # 不加 reload=True，生產模式不需要
    )
