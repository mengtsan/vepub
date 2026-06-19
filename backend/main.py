"""
FastAPI 入口檔案
啟動時：偵測硬體、載入 OmniVoice 模型、掛載所有路由
"""
import sys
# Windows 預設編碼為 cp950，強制設為 UTF-8 避免中文 print 失敗
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import tts, epub, health, models, illustration, characters
from config import BACKEND_PORT
from routers.illustration_common import init_illustration_tables
from services.hardware_detector import detect_hardware
from services.db import init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 初始化 SQLite 資料庫
    init_db()
    init_illustration_tables()

    # 初始化模型登錄檔（首次自動掃描現有模型）
    from services.model_registry import ensure_initialized
    ensure_initialized()

    # 偵測硬體
    hw = detect_hardware()
    app.state.hardware = hw

    # 從 registry 建立 active TTS 後端（不自動 load，等使用者手動）
    from routers.models import build_active_tts
    tts_backend = build_active_tts(app.state)
    if tts_backend is None:
        # fallback：沿用舊的 TTSEngine 方式
        from services.tts_engine import TTSEngine
        from services.backends.tts_omnivoice import OmniVoiceBackend
        engine = TTSEngine(device=hw["recommended_device"])
        tts_backend = OmniVoiceBackend(engine)
    app.state.tts = tts_backend

    # Image pipeline 由 illustration_engine.py 直接管理（動畫/寫實雙模型自動切換）
    app.state.image = None

    # 向 GPU 仲裁器註冊引擎（TTS 用 engine 物件，image 用 illustration_engine module）
    from services.gpu_manager import gpu_manager
    from services import illustration_engine
    _tts_engine = getattr(tts_backend, "_engine", tts_backend)
    gpu_manager.register_engines(_tts_engine, illustration_engine)

    yield
    # 關閉時可在這裡進行清理

app = FastAPI(title="EPUB TTS Backend", version="1.0.0", lifespan=lifespan)

# 設定跨來源資源共用 (CORS) 許可
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:1420", "http://localhost:5173", "http://127.0.0.1:5173", "tauri://localhost"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 掛載路由
app.include_router(health.router, prefix="/health")
app.include_router(tts.router, prefix="/v1/audio")
app.include_router(epub.router, prefix="/epub")
app.include_router(models.router, prefix="/v1/models")
app.include_router(illustration.router, prefix="/illustration")
app.include_router(characters.router, prefix="/illustration")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=BACKEND_PORT, log_level="info")
