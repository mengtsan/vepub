from fastapi import APIRouter, Request

router = APIRouter()

@router.get("/")
async def get_health(request: Request):
    """
    回傳伺服器健康狀況與當前偵測到的硬體資訊。
    """
    return {
        "status": "healthy",
        "hardware": request.app.state.hardware
    }
