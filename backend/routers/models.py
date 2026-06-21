"""
模型管理路由器（統一管理 TTS / Image / LLM 三類模型）。

端點：
  GET  /v1/models/                         所有已安裝模型 + 狀態
  POST /v1/models/probe                    偵測 URL 類型
  POST /v1/models/download                 開始下載
  GET  /v1/models/download/{task_id}       SSE 下載進度
  DELETE /v1/models/download/{task_id}     取消下載
  POST /v1/models/{category}/activate     切換啟用模型（hot-swap）
  DELETE /v1/models/{category}/{model_id}  刪除模型
"""
import asyncio
import json
import os
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from services import model_registry, downloader

router = APIRouter()


# ─── Request / Response 模型 ──────────────────────────────────────────────────

class ProbeRequest(BaseModel):
    url: str

class DownloadRequest(BaseModel):
    url: str
    category: str           # "tts" | "image" | "llm"
    name: str               # 使用者填寫的顯示名稱
    role: str = "chat"      # 僅 LLM 使用："chat" | "analysis"

class ActivateRequest(BaseModel):
    model_id: str
    role: str = "default"   # 僅 LLM 使用

class PatchModelRequest(BaseModel):
    style: str | None = None   # "anime" | "real" | null = 清除

class TokenRequest(BaseModel):
    token: str


# ─── 列出所有模型 ─────────────────────────────────────────────────────────────

@router.get("/")
async def list_all_models(request: Request):
    """回傳三類模型的完整狀態，包含目前 active 及 loaded 狀態。"""
    reg = model_registry.get_registry()

    tts_backend  = getattr(request.app.state, "tts",   None)
    image_backend = getattr(request.app.state, "image", None)

    def _enrich(category: str, cat_data: dict) -> dict:
        active = cat_data.get("active") or cat_data.get("chat") or cat_data.get("analysis")
        models = cat_data.get("models", {})
        result = []
        for mid, info in models.items():
            # 孤兒條目（缺檔且無下載來源）不顯示；缺檔但可下載的「預設」保留
            if model_registry._is_orphan(info):
                continue
            m = dict(info)
            m["id"] = mid
            m["is_active"] = (
                mid == cat_data.get("active")
                or mid == cat_data.get("chat")
                or mid == cat_data.get("analysis")
            )
            # 是否已 loaded
            if category == "tts" and tts_backend and hasattr(tts_backend, "model_id"):
                m["is_loaded"] = (tts_backend.model_id == mid and tts_backend.is_loaded())
            elif category == "image" and image_backend and hasattr(image_backend, "model_id"):
                m["is_loaded"] = (image_backend.model_id == mid)
            else:
                m["is_loaded"] = False
            # 檔案是否實際存在於磁碟（登錄但未下載者為 False）
            m["available"] = model_registry.is_model_available(info)
            # 圖像模型：即時偵測實際架構（檔名可能誤導），供 UI 標籤顯示
            if category == "image":
                from services.illustration.pipelines import inspect_arch
                m["arch"] = inspect_arch(info.get("local_path", ""))
                m["is_turbo"] = "turbo" in (info.get("name", "") or mid).lower()
            result.append(m)
        return {"active": active, "models": result}

    return {
        "tts":   _enrich("tts",   reg.get("tts",   {})),
        "image": _enrich("image", reg.get("image", {})),
        "llm":   {
            "chat":     reg.get("llm", {}).get("chat"),
            "analysis": reg.get("llm", {}).get("analysis"),
            "models": [
                dict(info, id=mid, available=model_registry.is_model_available(info))
                for mid, info in reg.get("llm", {}).get("models", {}).items()
                if not model_registry._is_orphan(info)
            ],
        },
    }


# ─── Probe URL ────────────────────────────────────────────────────────────────

@router.post("/scan")
async def scan_models():
    """掃描本機 models/image/ 與 models/llm/ 目錄，自動登錄新發現的模型檔案。"""
    added = model_registry.scan_local_models()
    return {"added": added, "message": f"掃描完成，新增 {added} 個模型"}


@router.post("/probe")
async def probe_url(req: ProbeRequest):
    """偵測連結的模型類型與基本資訊（不下載）。"""
    try:
        result = await downloader.probe_url(req.url)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── 下載 ─────────────────────────────────────────────────────────────────────

@router.post("/download")
async def start_download(req: DownloadRequest):
    """啟動下載任務，立即回傳 task_id。"""
    if req.category not in ("tts", "image", "llm"):
        raise HTTPException(status_code=400, detail="category 必須是 tts / image / llm")
    probe = await downloader.probe_url(req.url)
    task_id = await downloader.start_download(probe, req.category, req.name)
    return {"task_id": task_id}


@router.get("/download/{task_id}")
async def download_progress(task_id: str):
    """SSE 串流下載進度。前端用 EventSource 連接。"""
    async def _event_stream():
        while True:
            task = downloader.get_task(task_id)
            if task is None:
                yield f"data: {json.dumps({'error': 'task_not_found'})}\n\n"
                break
            yield f"data: {json.dumps(task)}\n\n"
            if task["status"] in ("done", "error", "cancelled"):
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/civitai-token")
async def get_civitai_token():
    """回傳目前儲存的 CivitAI token（遮蔽大部分字元）。"""
    token = downloader.get_civitai_token()
    if not token:
        return {"set": False, "preview": ""}
    preview = token[:4] + "…" + token[-4:] if len(token) > 8 else "****"
    return {"set": True, "preview": preview}


@router.post("/civitai-token")
async def set_civitai_token(req: TokenRequest):
    """儲存 CivitAI API token。"""
    downloader.set_civitai_token(req.token)
    return {"status": "ok"}


@router.delete("/download/{task_id}")
async def cancel_download(task_id: str):
    """取消進行中的下載。"""
    ok = downloader.cancel_task(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="下載任務不存在")
    return {"status": "cancelled"}


# ─── 切換啟用（Hot-swap）─────────────────────────────────────────────────────

@router.post("/{category}/activate")
async def activate_model(category: str, req: ActivateRequest, request: Request):
    """
    切換啟用的模型並進行 hot-swap（unload 舊的 → load 新的）。
    LLM 無需 load/unload（per-call subprocess），只更新 registry。
    """
    if category not in ("tts", "image", "llm"):
        raise HTTPException(status_code=400, detail="不支援的 category")

    info = model_registry.get_model(category, req.model_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"模型 {req.model_id!r} 不在登錄檔中")
    # 不允許切換到檔案不存在的模型（與 UI「移除的模型不可選」原則一致）
    if not model_registry.is_model_available(info):
        raise HTTPException(status_code=409, detail="模型檔案不存在，請先下載")

    # ── LLM：只更新 registry ──────────────────────────────────────────────
    if category == "llm":
        model_registry.activate_model("llm", req.model_id, role=req.role)
        return {"status": "ok", "model_id": req.model_id, "role": req.role}

    # ── TTS hot-swap ──────────────────────────────────────────────────────
    if category == "tts":
        new_backend = _build_tts_backend(req.model_id, info, request)
        old_backend = getattr(request.app.state, "tts", None)
        if old_backend and old_backend.is_loaded():
            await old_backend.unload()
        request.app.state.tts = new_backend
        model_registry.activate_model("tts", req.model_id)
        return {"status": "ok", "model_id": req.model_id}

    # ── Image hot-swap ────────────────────────────────────────────────────
    if category == "image":
        new_backend = _build_image_backend(req.model_id, info, request)
        old_backend = getattr(request.app.state, "image", None)
        if old_backend and await old_backend.is_ready():
            await old_backend.unload()
        request.app.state.image = new_backend
        model_registry.activate_model("image", req.model_id)
        return {"status": "ok", "model_id": req.model_id}


# ─── 更新模型屬性（style 等）─────────────────────────────────────────────────

@router.patch("/{category}/{model_id}")
async def patch_model(category: str, model_id: str, req: PatchModelRequest):
    """更新 registry 中模型的可設定欄位（目前僅 style）。"""
    if category not in ("tts", "image", "llm"):
        raise HTTPException(status_code=400, detail="不支援的 category")
    try:
        patch = {k: v for k, v in req.model_dump().items() if k in req.model_fields_set}
        updated = model_registry.patch_model_info(category, model_id, patch)
        return updated
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ─── 刪除 ─────────────────────────────────────────────────────────────────────

@router.delete("/{category}/{model_id}")
async def delete_model(category: str, model_id: str, request: Request):
    """刪除模型（先 unload，再刪檔，再從 registry 移除）。"""
    info = model_registry.get_model(category, model_id)
    if not info:
        raise HTTPException(status_code=404, detail="模型不在登錄檔中")

    # 若正在使用中，先 unload
    if category == "tts":
        backend = getattr(request.app.state, "tts", None)
        if backend and backend.is_loaded() and getattr(backend, "model_id", None) == model_id:
            await backend.unload()
    elif category == "image":
        backend = getattr(request.app.state, "image", None)
        if backend and await backend.is_ready() and getattr(backend, "model_id", None) == model_id:
            await backend.unload()

    model_registry.delete_model_entry(category, model_id, remove_files=True)
    return {"status": "deleted", "model_id": model_id}


# ─── 後端工廠 ─────────────────────────────────────────────────────────────────

def _build_tts_backend(model_id: str, info: dict, request: Request):
    model_type = info.get("type", "omnivoice")
    local_path = info.get("local_path", "")

    if model_type == "omnivoice":
        from services.backends.tts_omnivoice import OmniVoiceBackend
        from services.tts_engine import TTSEngine
        hw = getattr(request.app.state, "hardware", {})
        device = hw.get("recommended_device", "cpu")
        engine = TTSEngine(device=device, local_path=local_path)
        b = OmniVoiceBackend(engine)
        b.model_id = model_id
        return b

    from services.backends.tts_pipeline import TransformersTTSBackend
    hw = getattr(request.app.state, "hardware", {})
    device = hw.get("recommended_device", "cpu")
    b = TransformersTTSBackend(model_id=model_id, local_path=local_path, device=device)
    return b


def _build_image_backend(model_id: str, info: dict, request: Request):
    # Image pipeline is managed directly by illustration_engine.py (dual-model auto-switch)
    return None


def build_active_tts(request_or_app) -> object | None:
    """從 registry 建立目前啟用的 TTS 後端（啟動時呼叫）。"""
    info = model_registry.get_active_model("tts")
    if not info:
        return None
    mid = info.get("_id", "unknown")
    return _build_tts_backend_raw(mid, info, request_or_app)


def build_active_image(request_or_app) -> object | None:
    """從 registry 建立目前啟用的 Image 後端（啟動時呼叫）。"""
    info = model_registry.get_active_model("image")
    if not info:
        return None
    mid = info.get("_id", "unknown")
    return _build_image_backend_raw(mid, info, request_or_app)


def _build_tts_backend_raw(model_id: str, info: dict, app_or_state):
    """不依賴 Request 物件的工廠函式（lifespan 使用）。"""
    model_type = info.get("type", "omnivoice")
    local_path  = info.get("local_path", "")
    hw = getattr(app_or_state, "hardware", {}) if hasattr(app_or_state, "hardware") else {}
    device = hw.get("recommended_device", "cpu")

    if model_type == "omnivoice":
        from services.backends.tts_omnivoice import OmniVoiceBackend
        from services.tts_engine import TTSEngine
        engine = TTSEngine(device=device, local_path=local_path)
        b = OmniVoiceBackend(engine)
        b.model_id = model_id
        return b

    from services.backends.tts_pipeline import TransformersTTSBackend
    return TransformersTTSBackend(model_id=model_id, local_path=local_path, device=device)


def _build_image_backend_raw(model_id: str, info: dict, app_or_state):
    # Image pipeline is managed directly by illustration_engine.py (dual-model auto-switch)
    return None
