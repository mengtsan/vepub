"""
FastAPI 入口檔案
啟動時：偵測硬體、載入 OmniVoice 模型、掛載所有路由
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import tts, epub, health, models
from services.tts_engine import TTSEngine
from services.hardware_detector import detect_hardware
from services.db import init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 初始化 SQLite 資料庫
    init_db()
    # 啟動時：偵測硬體、載入 OmniVoice 模型
    hw = detect_hardware()
    app.state.hardware = hw
    # 建立 TTS 引擎實例，但不自動載入模型（等使用者在設定頁手動載入）
    app.state.tts = TTSEngine(device=hw["recommended_device"])
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8765, log_level="info")
