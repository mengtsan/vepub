"""
模型管理路由器。
提供下載、刪除、選擇啟用、載入至記憶體、卸載與狀態查詢的 API 端點。
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from services.models_manager import (
    get_models_status_list,
    start_download_thread,
    delete_model_files,
    set_current_model_id,
    check_model_downloaded,
    get_engine_loaded_model_id,
)

router = APIRouter()

class ModelActionRequest(BaseModel):
    model_id: str

@router.get("/status")
async def get_status():
    """
    查詢所有模型的下載狀態、進度、啟用狀態與引擎載入狀態。
    """
    try:
        return {"models": get_models_status_list()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"獲取模型狀態失敗: {e}")

@router.post("/download")
async def download_model(req: ModelActionRequest):
    """
    發起模型下載請求，將在背景執行緒中進行下載。
    """
    success = start_download_thread(req.model_id)
    if not success:
        raise HTTPException(status_code=400, detail="發起下載失敗，請確認模型 ID 是否正確或已在下載中")
    return {"status": "success", "message": f"模型 {req.model_id} 已在背景啟動下載"}

@router.post("/delete")
async def delete_model(req: ModelActionRequest, request: Request):
    """
    刪除指定的本地模型實體檔案。
    若模型正在下載中，會先設置取消旗標使下載停止，再刪除所有相關檔案（包含暫存檔）。
    若模型目前已載入引擎（safetensors mmap 會在 Windows 上鎖定檔案），會先卸載再刪除。
    """
    from services.tts_engine import TTSEngine

    tts: TTSEngine = request.app.state.tts
    if tts.is_loaded():
        loaded_id = get_engine_loaded_model_id()
        if loaded_id == req.model_id:
            await tts.unload()

    success = delete_model_files(req.model_id)
    if not success:
        raise HTTPException(status_code=400, detail=f"刪除模型 {req.model_id} 失敗")
    return {"status": "success", "message": f"模型 {req.model_id} 已成功刪除"}

@router.post("/select")
async def select_model(req: ModelActionRequest):
    """
    設定目前啟用的模型 ID（儲存至資料庫）。
    注意：此操作只更新資料庫設定，不會立即切換已載入的引擎。
    若要讓新設定立刻生效，請呼叫 /load。
    """
    success = set_current_model_id(req.model_id)
    if not success:
        raise HTTPException(status_code=400, detail=f"啟用模型 {req.model_id} 失敗，可能是不支援的模型 ID")
    return {"status": "success", "message": f"已成功將 {req.model_id} 設定為當前啟用模型"}

@router.post("/load")
async def load_model(req: ModelActionRequest, request: Request):
    """
    動態載入指定模型至 TTS 引擎記憶體中。
    此操作會：
      1. 先將當前已載入的模型從記憶體中卸載（釋放資源）
      2. 更新資料庫設定
      3. 重新載入指定模型

    注意：此為長時間阻塞操作（需等待模型載入完成），前端應顯示載入中提示。
    """
    from services.tts_engine import TTSEngine

    # 確認模型已下載
    if not check_model_downloaded(req.model_id) and req.model_id != "official":
        raise HTTPException(
            status_code=400,
            detail=f"模型 {req.model_id} 尚未下載，請先下載後再載入"
        )

    tts: TTSEngine = request.app.state.tts
    try:
        await tts.load_specific(req.model_id)
        return {
            "status": "success",
            "message": f"模型 {req.model_id} 已成功載入至記憶體"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"載入模型失敗: {str(e)}")

@router.post("/unload")
async def unload_model(request: Request):
    """
    從 TTS 引擎記憶體中卸載目前載入的模型，釋放 GPU/CPU 記憶體。
    卸載後若需要繼續播放，請重新呼叫 /load。
    """
    from services.tts_engine import TTSEngine
    from services.models_manager import set_engine_loaded_model_id

    tts: TTSEngine = request.app.state.tts
    if not tts.is_loaded():
        return {"status": "success", "message": "模型目前已是卸載狀態，無需操作"}

    try:
        await tts.unload()
        return {"status": "success", "message": "模型已成功從記憶體中卸載"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"卸載模型失敗: {str(e)}")
