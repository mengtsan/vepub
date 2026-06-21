"""
LLM 取樣設定路由。

GET   /v1/llm/settings    → 取得全域取樣設定
PATCH /v1/llm/settings    → 更新全域取樣設定（override_enabled / temperature / …）

注意：未掛在 /v1/models 之下，以避免與 models 路由的
`PATCH /{category}/{model_id}` 動態路徑（會把 "settings" 當成 model_id）衝突。
"""
from fastapi import APIRouter, HTTPException
from services.llm.settings import get_settings, update_settings

router = APIRouter()


@router.get("/settings")
async def get_llm_settings():
    return get_settings().model_dump()


@router.patch("/settings")
async def patch_llm_settings(patch: dict):
    try:
        updated = update_settings(patch)
        return updated.model_dump()
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
