"""
插圖生成路由（精簡版）
GET  /illustration/image/{id}           → 回傳插圖 PNG
GET  /illustration/char-image/{id}      → 回傳角色圖片 PNG
GET  /illustration/status               → 模型與 LLM 狀態
GET  /illustration/progress             → 所有任務進度
POST /illustration/load                 → 預先載入模型
POST /illustration/unload               → 卸載模型
GET  /illustration/settings             → 取得繪圖設定
PATCH /illustration/settings            → 更新繪圖設定
POST /illustration/extract_character    → 從段落提取角色特徵
POST /illustration/generate             → 非阻塞生圖（回傳 task_id）
GET  /illustration/list/{book_id}/{chapter_index}
DELETE /illustration/item/{id}

角色管理路由已移至 routers/characters.py
"""
import asyncio
import base64
import logging
import time
import uuid

logger = logging.getLogger(__name__)

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import FileResponse, Response
from services.illustration_engine import (
    get_settings,
    update_settings,
)
from services import llm_engine
from services.db import get_db_connection
from routers.illustration_common import (
    _tasks, _queue_sem, _DONE_TTL, _IMAGES_DIR,
    _evict_expired, _save_image_file, _delete_image_file,
    GenerateRequest, ExtractCharacterRequest,
)

router = APIRouter()


# ─── 背景生圖 worker ──────────────────────────────────────────────────────────

async def _run_task(task_id: str, req: GenerateRequest, image_backend=None):
    if task_id not in _tasks:
        return
    task = _tasks[task_id]
    task["status"] = "pending"

    async with _queue_sem:
        task["status"] = "running"

        def _cb(pct: int, label: str):
            task["progress"] = pct
            task["label"]    = label
            task["timings"].append({"pct": pct, "label": label, "ts": time.time()})

        # 取得所有角色資料，傳給 LLM 讓它自行判斷誰在場景中並生成提示詞。
        # 「誰在場」「FaceID 鎖誰的臉」「seed 用誰的」全部交給
        # generate_illustration 用同一份 LLM 判定結果解析（req.character_name
        # 為使用者手動選角時的顯式覆寫），避免本層獨立用 substring 猜測角色
        # 導致與 LLM 認定的在場角色不一致（見 plans/consistency-alignment-refactor.md）。
        char_descriptions: list[dict] = []
        if req.book_id:
            conn = get_db_connection()
            rows = conn.execute(
                "SELECT * FROM characters WHERE book_id=?",
                (req.book_id,)
            ).fetchall()
            conn.close()
            char_descriptions = [dict(r) for r in rows]

        logger.debug("角色資料庫=%d 筆，手動選角=%r", len(char_descriptions), req.character_name)

        try:
            backend = image_backend
            if backend is None:
                from services.illustration_engine import generate_illustration as _gen
                img_bytes, prompt, is_anime, meta = await _gen(
                    text=req.text,
                    character_descriptions=char_descriptions,
                    width=req.width, height=req.height, seed=req.seed,
                    prompt_prefix=req.prompt_prefix,
                    on_progress=_cb,
                    direct_prompt=req.direct_prompt,
                    book_id=req.book_id,
                    character_name=req.character_name,
                )
            else:
                result = await backend.generate(
                    text=req.text,
                    character_descriptions=char_descriptions,
                    width=req.width, height=req.height, seed=req.seed,
                    prompt_prefix=req.prompt_prefix,
                    on_progress=_cb,
                )
                img_bytes, prompt, is_anime = result[:3]
                meta = result[3] if len(result) > 3 else {}
        except Exception as e:
            task["status"]   = "error"
            task["error"]    = str(e)
            task["progress"] = 0
            task["done_at"]  = time.time()
            if image_backend is None:
                from services.illustration_engine import unload_model as _unload
                await _unload()
            else:
                await image_backend.unload()
            return

        illus_id   = None
        image_url  = None
        image_b64  = None
        if req.book_id and req.chapter_index >= 0:
            image_path = _save_image_file(img_bytes, "illustrations")
            conn = get_db_connection()
            cur  = conn.execute(
                "INSERT INTO illustrations "
                "(book_id, chapter_index, sentence_index, prompt, image_path, "
                " model_name, steps, guidance_scale, seed, width, height, is_anime, "
                " workflow, sampler, clip_skip, negative_prompt) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    req.book_id, req.chapter_index, req.sentence_index, prompt, image_path,
                    meta.get("model_name", ""), meta.get("steps"), meta.get("guidance_scale"),
                    meta.get("seed"), meta.get("width"), meta.get("height"),
                    1 if is_anime else 0,
                    meta.get("workflow", "txt2img"), meta.get("sampler", ""),
                    meta.get("clip_skip"), meta.get("negative_prompt", ""),
                ),
            )
            illus_id  = cur.lastrowid
            image_url = f"/illustration/image/{illus_id}"
            conn.commit()
            conn.close()
        else:
            image_b64 = base64.b64encode(img_bytes).decode()

        task["status"]   = "done"
        task["progress"] = 100
        task["done_at"]  = time.time()
        task["result"]   = {
            "id":              illus_id,
            "image_url":       image_url,
            "image_base64":    image_b64,
            "prompt":          prompt,
            "is_anime":        is_anime,
            "workflow":        meta.get("workflow", "txt2img"),
            "model_name":      meta.get("model_name", ""),
            "sampler":         meta.get("sampler", ""),
            "steps":           meta.get("steps"),
            "guidance_scale":  meta.get("guidance_scale"),
            "clip_skip":       meta.get("clip_skip"),
            "seed":            meta.get("seed"),
            "width":           meta.get("width"),
            "height":          meta.get("height"),
            "negative_prompt": meta.get("negative_prompt", ""),
        }


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/image/{illustration_id}")
async def serve_illustration_image(illustration_id: int):
    conn = get_db_connection()
    row = conn.execute(
        "SELECT image_path, image_base64 FROM illustrations WHERE id=?",
        (illustration_id,)
    ).fetchone()
    conn.close()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="找不到插圖")
    headers = {"Cache-Control": "public, max-age=31536000, immutable"}
    if row["image_path"]:
        path = _IMAGES_DIR / row["image_path"]
        if path.exists():
            return FileResponse(str(path), media_type="image/png", headers=headers)
    if row["image_base64"]:
        return Response(
            content=base64.b64decode(row["image_base64"]),
            media_type="image/png", headers=headers,
        )
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail="圖片資料不存在")


@router.get("/char-image/{img_id}")
async def serve_char_image(img_id: int):
    conn = get_db_connection()
    row = conn.execute(
        "SELECT image_path, image_base64 FROM character_images WHERE id=?",
        (img_id,)
    ).fetchone()
    conn.close()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="找不到角色圖片")
    headers = {"Cache-Control": "public, max-age=31536000, immutable"}
    if row["image_path"]:
        path = _IMAGES_DIR / row["image_path"]
        if path.exists():
            return FileResponse(str(path), media_type="image/png", headers=headers)
    if row["image_base64"]:
        return Response(
            content=base64.b64decode(row["image_base64"]),
            media_type="image/png", headers=headers,
        )
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail="圖片資料不存在")


def _scan_asset_dir(subdir: str, suffixes=(".safetensors", ".bin", ".pt")) -> list[dict]:
    """掃描 models/<subdir>/ 下的權重檔，回傳 [{filename, size_mb}]。目錄不存在則空清單。"""
    from config import MODELS_DIR
    d = MODELS_DIR / subdir
    out = []
    if d.exists():
        for f in sorted(d.iterdir()):
            if f.suffix in suffixes and f.is_file():
                out.append({
                    "filename": f.name,
                    "size_mb":  round(f.stat().st_size / 1024 / 1024, 1),
                })
    return out


@router.get("/loras")
async def list_loras():
    return {"loras": _scan_asset_dir("loras")}


@router.get("/embeddings")
async def list_embeddings():
    return {"embeddings": _scan_asset_dir("embeddings")}


@router.get("/vaes")
async def list_vaes():
    return {"vaes": _scan_asset_dir("vae", suffixes=(".safetensors", ".pt", ".ckpt"))}


@router.get("/status")
async def get_illustration_status(request: Request):
    backend = getattr(request.app.state, "image", None)
    if backend is not None:
        model_loaded = await backend.is_ready()
    else:
        from services.illustration_engine import is_model_ready
        model_loaded = await is_model_ready()
    return {
        "llm_available":  llm_engine.is_available(),
        "llm_model":      llm_engine.get_model_name(),
        "model_loaded":   model_loaded,
    }


@router.get("/progress")
async def get_illustration_progress():
    _evict_expired(_tasks, _DONE_TTL)
    result = []
    for tid, t in list(_tasks.items()):
        result.append({
            "task_id":        tid,
            "status":         t["status"],
            "progress":       t["progress"],
            "label":          t["label"],
            "sentence_index": t["sentence_index"],
            "chapter_index":  t["chapter_index"],
            "book_id":        t["book_id"],
            "timings":        t.get("timings", []),
            "result":         t.get("result"),
            "error":          t.get("error"),
        })
    return result


@router.post("/load")
async def preload_model(background_tasks: BackgroundTasks, request: Request):
    backend = getattr(request.app.state, "image", None)
    if backend is not None:
        if await backend.is_ready():
            return {"status": "already_loaded"}
        background_tasks.add_task(backend.load)
    else:
        from services.illustration_engine import is_model_ready, load_model
        if await is_model_ready():
            return {"status": "already_loaded"}
        background_tasks.add_task(load_model)
    return {"status": "loading"}


@router.post("/unload")
async def unload_model_endpoint(request: Request):
    backend = getattr(request.app.state, "image", None)
    if backend is not None:
        await backend.unload()
    else:
        from services.illustration_engine import unload_model
        await unload_model()
    return {"status": "unloaded"}


@router.get("/settings")
async def get_illustration_settings():
    return get_settings().model_dump()


@router.patch("/settings")
async def patch_illustration_settings(patch: dict):
    try:
        updated = update_settings(patch)
        return updated.model_dump()
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/extract_character")
async def extract_character_endpoint(req: ExtractCharacterRequest):
    return await llm_engine.extract_character_features(req.text)


@router.post("/generate")
async def generate(req: GenerateRequest, background_tasks: BackgroundTasks, request: Request):
    task_id = str(uuid.uuid4())
    _tasks[task_id] = {
        "status":         "pending",
        "progress":       0,
        "label":          "排隊中",
        "book_id":        req.book_id,
        "chapter_index":  req.chapter_index,
        "sentence_index": req.sentence_index,
        "timings":        [],
        "result":         None,
        "error":          None,
    }
    image_backend = getattr(request.app.state, "image", None)
    background_tasks.add_task(_run_task, task_id, req, image_backend)
    queue_position = sum(
        1 for t in _tasks.values() if t["status"] in ("pending", "running")
    )
    return {"task_id": task_id, "queue_position": queue_position}


@router.get("/list/{book_id}/{chapter_index}")
async def list_illustrations(book_id: str, chapter_index: int):
    def _query():
        conn = get_db_connection()
        try:
            rows = conn.execute(
                "SELECT id, sentence_index, prompt, "
                "model_name, steps, guidance_scale, seed, width, height, is_anime "
                "FROM illustrations WHERE book_id=? AND chapter_index=? ORDER BY created_at",
                (book_id, chapter_index),
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["image_url"] = f"/illustration/image/{d['id']}"
                result.append(d)
            return result
        finally:
            conn.close()

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _query)


@router.delete("/item/{illustration_id}")
async def delete_illustration(illustration_id: int):
    conn = get_db_connection()
    row = conn.execute("SELECT image_path FROM illustrations WHERE id=?", (illustration_id,)).fetchone()
    conn.execute("DELETE FROM illustrations WHERE id=?", (illustration_id,))
    conn.commit()
    conn.close()
    _delete_image_file(row["image_path"] if row else None)
    return {"status": "success"}
