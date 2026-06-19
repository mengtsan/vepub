"""
角色管理路由
GET/POST/DELETE /illustration/characters/{book_id}
POST /illustration/characters/{book_id}/fill_defaults
POST /illustration/characters/{book_id}/dedup
POST /illustration/characters/{book_id}/batch_delete
POST/GET/DELETE /illustration/characters/{book_id}/images
GET/POST/DELETE /illustration/characters/{book_id}/image/{img_id}
POST /illustration/characters/{book_id}/set_primary/{img_id}
POST /illustration/analyze_characters/{book_id}
GET  /illustration/analyze_characters/{book_id}/checkpoint|status
POST /illustration/characters/{book_id}/generate_angles
GET  /illustration/angle_jobs/{job_id}
POST /illustration/characters/{book_id}/portrait
GET  /illustration/portrait_jobs/{job_id}
"""
import asyncio
import base64
import logging
import time
import uuid

logger = logging.getLogger(__name__)

from fastapi import APIRouter, BackgroundTasks
from services.illustration_engine import (
    build_character_fragment,
    get_settings,
)
from services import llm_engine
from services.db import get_db_connection
from routers.illustration_common import (
    _tasks, _queue_sem, _DONE_TTL,
    _analysis_jobs, _angle_jobs, _portrait_jobs,
    _evict_expired, _save_image_file, _delete_image_file,
    _load_char_ref_image, _persist_analysis_job,
    CharacterUpsert, CharacterImageAdd, ExtractCharacterRequest,
    BatchDeleteRequest, GenerateAnglesRequest, PortraitRequest,
    _ALL_TEXT_COLS,
)

router = APIRouter()


# ─── 角色 CRUD ────────────────────────────────────────────────────────────────

@router.get("/characters/{book_id}")
async def list_characters(book_id: str):
    def _query():
        conn = get_db_connection()
        try:
            chars = conn.execute(
                "SELECT * FROM characters WHERE book_id=? ORDER BY name",
                (book_id,)
            ).fetchall()
            result = []
            for c in chars:
                char = dict(c)
                imgs = conn.execute(
                    "SELECT id, angle, is_primary, created_at, prompt FROM character_images WHERE character_id=? ORDER BY is_primary DESC, created_at",
                    (char["id"],)
                ).fetchall()
                char["images"] = [dict(i) for i in imgs]
                primary = conn.execute(
                    "SELECT id FROM character_images WHERE character_id=? AND is_primary=1 LIMIT 1",
                    (char["id"],)
                ).fetchone()
                char["primary_image_url"] = f"/illustration/char-image/{primary['id']}" if primary else None
                result.append(char)
            return result
        finally:
            conn.close()

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _query)


@router.post("/characters/{book_id}")
async def upsert_character(book_id: str, char: CharacterUpsert):
    conn = get_db_connection()
    def _upsert_col(col: str) -> str:
        return (
            f"{col} = CASE WHEN excluded.{col}='__clear__' THEN NULL "
            f"WHEN excluded.{col} IS NOT NULL THEN excluded.{col} "
            f"ELSE {col} END"
        )

    text_cols = [
        "gender", "age_hint",
        "skin_tone", "face_shape", "hair_color", "hair_style", "eye_color", "eye_shape",
        "body_type", "bwh", "cup_size",
        "era_style", "signature_outfit", "color_palette", "accessories",
        "distinctive_marks", "special_traits", "other_features",
    ]
    conn.execute(
        f"""
        INSERT INTO characters (
            book_id, name, description, ref_image_base64,
            gender, age_hint,
            skin_tone, face_shape, hair_color, hair_style, eye_color, eye_shape,
            body_type, height_cm, weight_kg, bwh, cup_size,
            era_style, signature_outfit, color_palette, accessories,
            distinctive_marks, special_traits, other_features,
            character_seed, locked
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(book_id, name) DO UPDATE SET
            description       = excluded.description,
            ref_image_base64  = COALESCE(excluded.ref_image_base64, ref_image_base64),
            {", ".join(_upsert_col(c) for c in text_cols)},
            height_cm        = COALESCE(excluded.height_cm, height_cm),
            weight_kg        = COALESCE(excluded.weight_kg, weight_kg),
            character_seed   = CASE WHEN excluded.character_seed >= 0 THEN excluded.character_seed ELSE character_seed END,
            locked           = CASE WHEN excluded.locked IS NOT NULL THEN excluded.locked ELSE locked END
        """,
        (
            book_id, char.name, char.description, char.ref_image_base64,
            char.gender, char.age_hint,
            char.skin_tone, char.face_shape, char.hair_color, char.hair_style,
            char.eye_color, char.eye_shape,
            char.body_type, char.height_cm, char.weight_kg, char.bwh, char.cup_size,
            char.era_style, char.signature_outfit, char.color_palette, char.accessories,
            char.distinctive_marks, char.special_traits, char.other_features,
            char.character_seed, char.locked,
        )
    )
    conn.commit()
    conn.close()
    return {"status": "success"}


@router.post("/characters/{book_id}/fill_defaults")
async def fill_character_defaults(book_id: str):
    """對本書所有角色套用 fallback 補完邏輯。"""
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM characters WHERE book_id=?", (book_id,)
    ).fetchall()

    chars = [dict(r) for r in rows]
    originals = [dict(r) for r in rows]

    from services.llm_engine import infer_missing_fields, _apply_defaults
    chars = await infer_missing_fields(chars)

    for char in chars:
        _apply_defaults(char)

    fields = [
        "gender", "age_hint",
        "skin_tone", "face_shape", "hair_color", "hair_style", "eye_color", "eye_shape",
        "body_type", "height_cm", "weight_kg", "bwh", "cup_size",
        "era_style", "signature_outfit", "color_palette", "accessories",
        "distinctive_marks", "special_traits", "other_features",
    ]
    updated = 0
    orig_map = {r["id"]: r for r in originals}
    for char in chars:
        original = orig_map.get(char.get("id"), {})
        changes = {f: char.get(f) for f in fields if char.get(f) != original.get(f)}
        if changes:
            set_clause = ", ".join(f"{f}=?" for f in changes)
            conn.execute(
                f"UPDATE characters SET {set_clause} WHERE id=?",
                (*changes.values(), char["id"]),
            )
            updated += 1

    conn.commit()
    conn.close()
    return {"updated": updated, "total": len(rows)}


@router.delete("/characters/{book_id}")
async def delete_character(book_id: str, name: str):
    """name 以 query parameter 傳入，避免 URL 路徑中的 / 被正規化問題。"""
    conn = get_db_connection()
    conn.execute("DELETE FROM characters WHERE book_id=? AND name=?", (book_id, name))
    conn.commit()
    conn.close()
    return {"status": "success"}


@router.post("/characters/{book_id}/batch_delete")
async def batch_delete_characters(book_id: str, req: BatchDeleteRequest):
    conn = get_db_connection()
    for name in req.names:
        conn.execute("DELETE FROM characters WHERE book_id=? AND name=?", (book_id, name))
    conn.commit()
    conn.close()
    return {"deleted": len(req.names)}


@router.post("/characters/{book_id}/dedup")
async def dedup_characters(book_id: str):
    """讓 LLM 找出角色庫中的別名分組，合併重複角色。"""
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT id, name, locked FROM characters WHERE book_id=? ORDER BY name",
        (book_id,)
    ).fetchall()
    conn.close()

    names = [r["name"] for r in rows]
    if len(names) < 2:
        return {"merged": 0, "groups": []}

    groups = await llm_engine.find_alias_groups(names)
    if not groups:
        return {"merged": 0, "groups": []}

    locked_set = {r["name"] for r in rows if r["locked"]}

    merged_count = 0
    merge_log: list[dict] = []

    conn = get_db_connection()
    for group in groups:
        locked_in_group = [n for n in group if n in locked_set]
        if locked_in_group:
            canonical = min(locked_in_group, key=len)
        else:
            canonical = min(group, key=len)

        aliases = [n for n in group if n != canonical]
        deletable_aliases = [n for n in aliases if n not in locked_set]

        if not deletable_aliases:
            continue

        canonical_row = conn.execute(
            "SELECT * FROM characters WHERE book_id=? AND name=?",
            (book_id, canonical)
        ).fetchone()
        if not canonical_row:
            continue

        canonical_id   = canonical_row["id"]
        canonical_dict = dict(canonical_row)

        merge_fields = [
            "gender", "age_hint",
            "skin_tone", "face_shape", "hair_color", "hair_style",
            "eye_color", "eye_shape",
            "body_type", "height_cm", "weight_kg", "bwh", "cup_size",
            "era_style", "signature_outfit", "color_palette", "accessories",
            "distinctive_marks", "special_traits", "other_features",
        ]

        actually_merged = []
        for alias in deletable_aliases:
            alias_row = conn.execute(
                "SELECT * FROM characters WHERE book_id=? AND name=?",
                (book_id, alias)
            ).fetchone()
            if not alias_row:
                continue

            conn.execute(
                "UPDATE character_images SET character_id=? WHERE character_id=?",
                (canonical_id, alias_row["id"]),
            )

            alias_dict = dict(alias_row)
            for field in merge_fields:
                val = alias_dict.get(field)
                if val is not None and canonical_dict.get(field) is None:
                    conn.execute(
                        f"UPDATE characters SET {field}=? WHERE id=?",
                        (val, canonical_id),
                    )
                    canonical_dict[field] = val

            conn.execute(
                "DELETE FROM characters WHERE book_id=? AND name=?",
                (book_id, alias),
            )
            actually_merged.append(alias)
            merged_count += 1

        if actually_merged:
            merge_log.append({"canonical": canonical, "aliases": actually_merged})

    conn.commit()
    conn.close()

    return {"merged": merged_count, "groups": merge_log}


# ─── 角色圖片管理 ──────────────────────────────────────────────────────────────

@router.post("/characters/{book_id}/images")
async def add_character_image(book_id: str, name: str, body: CharacterImageAdd):
    """name 以 query parameter 傳入，避免 URL 路徑中的 / 被正規化問題。"""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT id FROM characters WHERE book_id=? AND name=?", (book_id, name)
    ).fetchone()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="角色不存在")
    char_id = row["id"]

    if body.is_primary:
        conn.execute("UPDATE character_images SET is_primary=0 WHERE character_id=?", (char_id,))

    img_bytes  = base64.b64decode(body.image_base64)
    image_path = _save_image_file(img_bytes, "characters")
    cur = conn.execute(
        "INSERT INTO character_images (character_id, image_path, angle, is_primary) VALUES (?,?,?,?)",
        (char_id, image_path, body.angle, 1 if body.is_primary else 0),
    )
    img_id = cur.lastrowid
    conn.commit()
    conn.close()
    return {"status": "success", "id": img_id, "image_url": f"/illustration/char-image/{img_id}"}


@router.get("/characters/{book_id}/image/{img_id}")
async def get_character_image(book_id: str, img_id: int):
    conn = get_db_connection()
    row = conn.execute(
        """SELECT ci.id, ci.angle, ci.is_primary, ci.created_at
           FROM character_images ci
           JOIN characters c ON c.id = ci.character_id
           WHERE c.book_id=? AND ci.id=?""",
        (book_id, img_id)
    ).fetchone()
    conn.close()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="圖片不存在")
    result = dict(row)
    result["image_url"] = f"/illustration/char-image/{img_id}"
    return result


@router.delete("/characters/{book_id}/image/{img_id}")
async def delete_character_image(book_id: str, img_id: int):
    conn = get_db_connection()
    row = conn.execute("SELECT image_path FROM character_images WHERE id=?", (img_id,)).fetchone()
    conn.execute(
        """DELETE FROM character_images WHERE id=?
           AND character_id IN (SELECT id FROM characters WHERE book_id=?)""",
        (img_id, book_id)
    )
    conn.commit()
    conn.close()
    _delete_image_file(row["image_path"] if row else None)
    return {"status": "success"}


@router.post("/characters/{book_id}/set_primary/{img_id}")
async def set_primary_image(book_id: str, img_id: int):
    conn = get_db_connection()
    row = conn.execute(
        """SELECT c.id FROM characters c
           JOIN character_images ci ON ci.character_id = c.id
           WHERE c.book_id=? AND ci.id=?""",
        (book_id, img_id)
    ).fetchone()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="圖片不存在")
    char_id = row["id"]
    conn.execute("UPDATE character_images SET is_primary=0 WHERE character_id=?", (char_id,))
    conn.execute("UPDATE character_images SET is_primary=1 WHERE id=? AND character_id=?", (img_id, char_id))
    conn.commit()
    conn.close()
    return {"status": "success"}


# ─── 全書角色分析 ─────────────────────────────────────────────────────────────

def _upsert_col_expr(col: str) -> str:
    """全書分析 upsert：現有值優先，只在欄位為 NULL 時才寫入。
    防止 LLM 跨角色汙染——錯誤屬性再長也不會蓋掉已存在的正確值。
    description 例外：較長的新描述可覆蓋舊描述（後面章節可能提供更完整的人設）。
    """
    if col == "description":
        return (
            f"{col} = CASE "
            f"WHEN excluded.{col} IS NOT NULL "
            f"AND length(excluded.{col}) > length(COALESCE({col}, '')) "
            f"THEN excluded.{col} "
            f"ELSE COALESCE({col}, excluded.{col}) END"
        )
    return f"{col} = COALESCE({col}, excluded.{col})"


def _upsert_characters_to_db(book_id: str, chars: dict[str, dict]) -> int:
    """將 accumulated dict 中的角色 upsert 到 DB，回傳新增數（跳過已鎖定）。"""
    conn = get_db_connection()
    added = 0
    for name, c in chars.items():
        name = (c.get("name") or name).strip()
        if not name:
            continue
        locked_row = conn.execute(
            "SELECT locked FROM characters WHERE book_id=? AND name=?",
            (book_id, name)
        ).fetchone()
        if locked_row and locked_row["locked"]:
            continue
        try:
            conn.execute(
                f"""INSERT INTO characters
                   (book_id, name, {", ".join(_ALL_TEXT_COLS)}, height_cm, weight_kg)
                   VALUES (?,?,{",".join("?" * len(_ALL_TEXT_COLS))},?,?)
                   ON CONFLICT(book_id, name) DO UPDATE SET
                    {", ".join(_upsert_col_expr(col) for col in _ALL_TEXT_COLS)},
                    height_cm = COALESCE(excluded.height_cm, height_cm),
                    weight_kg = COALESCE(excluded.weight_kg, weight_kg)""",
                (
                    book_id, name,
                    *[c.get(col) for col in _ALL_TEXT_COLS],
                    c.get("height_cm") if isinstance(c.get("height_cm"), int) else None,
                    c.get("weight_kg") if isinstance(c.get("weight_kg"), int) else None,
                )
            )
            if conn.execute("SELECT changes()").fetchone()[0]:
                added += 1
        except Exception as e:
            logger.warning("角色插入失敗 %r: %s", name, e)
    conn.commit()
    conn.close()
    return added


async def _run_analysis(book_id: str, file_path: str, max_chapters: int = 0):
    job = _analysis_jobs[book_id]
    job["status"] = "running"
    _persist_analysis_job(book_id, job)

    from services.gpu_manager import gpu_manager
    await gpu_manager.acquire_gpu('analysis')
    try:
        import asyncio as _aio
        from services.epub_parser import get_chapters_cached
        loop = _aio.get_running_loop()
        chapters = await loop.run_in_executor(None, get_chapters_cached, file_path)
        chapters_paragraphs = [ch.paragraphs for ch in chapters]
        if max_chapters > 0:
            chapters_paragraphs = chapters_paragraphs[:max_chapters]

        total_chapters = len(chapters_paragraphs)

        conn = get_db_connection()
        done_rows = conn.execute(
            "SELECT chapter_index FROM analysis_checkpoints WHERE book_id=?",
            (book_id,)
        ).fetchall()
        skip_chapters: set[int] = {r["chapter_index"] for r in done_rows}

        initial_accumulated: dict[str, dict] = {}
        if skip_chapters:
            char_rows = conn.execute(
                "SELECT * FROM characters WHERE book_id=?", (book_id,)
            ).fetchall()
            for row in char_rows:
                d = dict(row)
                name = d.get("name", "")
                if name:
                    initial_accumulated[name] = d
            logger.info("Resume：跳過 %d/%d 章，載入 %d 位現有角色",
                        len(skip_chapters), total_chapters, len(initial_accumulated))
        conn.close()

        def _cb(pct: int, label: str):
            job["progress"] = pct
            job["label"]    = label

        _chapter_added_total = [0]

        async def _on_chapter_done(chapter_index: int, snapshot: dict):
            n = _upsert_characters_to_db(book_id, snapshot)
            _chapter_added_total[0] += n
            conn2 = get_db_connection()
            conn2.execute(
                "INSERT OR IGNORE INTO analysis_checkpoints (book_id, chapter_index) VALUES (?,?)",
                (book_id, chapter_index)
            )
            conn2.commit()
            conn2.close()
            logger.debug("checkpoint ch%d 已儲存（+%d 角色）", chapter_index + 1, n)

        chars = await llm_engine.analyze_characters(
            chapters_paragraphs,
            on_progress=_cb,
            on_chapter_done=_on_chapter_done,
            skip_chapters=skip_chapters,
            initial_accumulated=initial_accumulated,
        )

        final_added = _upsert_characters_to_db(book_id, {c["name"]: c for c in chars if c.get("name")})

        conn = get_db_connection()
        conn.execute("DELETE FROM analysis_checkpoints WHERE book_id=?", (book_id,))
        conn.commit()
        conn.close()

        total_found = len(chars)
        job["status"]   = "done"
        job["progress"] = 100
        job["label"]    = f"完成，共找到 {total_found} 位角色"
        job["result"]   = {"added": final_added, "total": total_found}

    except Exception as e:
        job["status"]   = "error"
        job["error"]    = str(e)
        job["progress"] = 0
        job["label"]    = f"錯誤：{str(e)[:120]}"

    finally:
        gpu_manager.end_analysis()
        _persist_analysis_job(book_id, job)
        _analysis_jobs.pop(book_id, None)


@router.post("/analyze_characters/{book_id}")
async def start_analyze_characters(
    book_id: str,
    background_tasks: BackgroundTasks,
    max_chapters: int = 0,
    restart: bool = False,
):
    """啟動全書角色分析（非阻塞）。同一本書同時只允許一個分析任務。"""
    from fastapi import HTTPException
    existing = _analysis_jobs.get(book_id)
    if not existing:
        conn_chk = get_db_connection()
        row_chk = conn_chk.execute(
            "SELECT status FROM analysis_jobs WHERE book_id=?", (book_id,)
        ).fetchone()
        conn_chk.close()
        if row_chk:
            existing = dict(row_chk)
    if existing and existing.get("status") in ("pending", "running"):
        return {"status": "already_running", "job": existing}

    conn = get_db_connection()
    book = conn.execute("SELECT file_path FROM books WHERE id=?", (book_id,)).fetchone()
    if not book:
        conn.close()
        raise HTTPException(status_code=404, detail="書籍不存在")

    if restart:
        conn.execute("DELETE FROM analysis_checkpoints WHERE book_id=?", (book_id,))
        conn.execute("DELETE FROM characters WHERE book_id=? AND (locked IS NULL OR locked=0)", (book_id,))
        conn.commit()
        logger.info("restart：已清除 %s 的 checkpoints 與未鎖定角色", book_id)
    conn.close()

    _analysis_jobs[book_id] = {
        "status": "pending", "progress": 0,
        "label": "準備中…", "result": None, "error": None,
    }
    background_tasks.add_task(_run_analysis, book_id, book["file_path"], max_chapters)
    return {"status": "started"}


@router.get("/analyze_characters/{book_id}/checkpoint")
async def get_analyze_checkpoint(book_id: str):
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT chapter_index FROM analysis_checkpoints WHERE book_id=? ORDER BY chapter_index",
        (book_id,)
    ).fetchall()
    conn.close()
    completed = [r["chapter_index"] for r in rows]
    return {"completed_chapters": completed, "count": len(completed)}


@router.get("/analyze_characters/{book_id}/status")
async def get_analyze_status(book_id: str):
    import json as _json
    from fastapi import HTTPException
    if book_id in _analysis_jobs:
        return _analysis_jobs[book_id]
    conn = get_db_connection()
    row = conn.execute(
        "SELECT status, progress, label, result_json, error FROM analysis_jobs WHERE book_id=?",
        (book_id,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="無分析任務")
    job = dict(row)
    result_json = job.pop("result_json", None)
    job["result"] = _json.loads(result_json) if result_json else None
    return job


# ─── 角色設定圖生成 ───────────────────────────────────────────────────────────

async def _run_angle_job(job_id: str, book_id: str, name: str, char: dict, prompt_prefix: str | None = None, seed: int = -1):
    job = _angle_jobs[job_id]

    async with _queue_sem:
        job["status"] = "running"
        job["label"]  = "組合角色描述…"

        char_desc = build_character_fragment(char)
        if seed < 0:
            seed = char.get("character_seed", -1)
        if prompt_prefix is None:
            prompt_prefix = get_settings().prompt_prefix

        def _cb(pct: int, label: str):
            job["progress"] = pct
            job["label"]    = label

        try:
            from services.illustration_engine import generate_character_sheet
            img_bytes, prompt = await generate_character_sheet(
                character_desc   = char_desc,
                character_name   = name,
                seed             = seed,
                width            = job["width"],
                height           = job["height"],
                prompt_prefix    = prompt_prefix,
                on_progress      = _cb,
                char_data        = char,
                ip_adapter_image = None,
            )
        except Exception as e:
            job["status"]  = "error"
            job["error"]   = str(e)
            job["done_at"] = time.time()
            return

        image_path = _save_image_file(img_bytes, "characters")
        try:
            conn = get_db_connection()
            char_row = conn.execute(
                "SELECT id FROM characters WHERE book_id=? AND name=?", (book_id, name)
            ).fetchone()
            if char_row:
                conn.execute(
                    "UPDATE character_images SET is_primary=0 WHERE character_id=?",
                    (char_row["id"],)
                )
                conn.execute(
                    "INSERT INTO character_images (character_id, image_path, angle, is_primary, prompt) VALUES (?,?,?,?,?)",
                    (char_row["id"], image_path, "設定圖", 1, prompt),
                )
                conn.commit()
            conn.close()
        except Exception as e:
            logger.error("設定圖存入 DB 失敗 %r: %s", name, e)
            job["status"]  = "error"
            job["error"]   = f"DB 儲存失敗：{e}"
            job["done_at"] = time.time()
            return

        job["done"] = 1

    job["status"]   = "done"
    job["progress"] = 100
    job["label"]    = "角色設定圖已生成"
    job["done_at"]  = time.time()


@router.post("/characters/{book_id}/generate_angles")
async def generate_angles(
    book_id: str,
    req: GenerateAnglesRequest,
    background_tasks: BackgroundTasks,
):
    from fastapi import HTTPException
    name = req.name
    if not name:
        raise HTTPException(status_code=422, detail="name 不可為空")
    conn = get_db_connection()
    row  = conn.execute(
        "SELECT * FROM characters WHERE book_id=? AND name=?", (book_id, name)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="角色不存在")

    s = get_settings()
    job_id = str(uuid.uuid4())
    _angle_jobs[job_id] = {
        "status": "pending", "progress": 0, "label": "排隊中",
        "book_id": book_id, "name": name,
        "done": 0, "total": 1,
        "width":  req.width  if req.width  is not None else s.sheet_width,
        "height": req.height if req.height is not None else s.sheet_height,
        "error": None,
    }
    background_tasks.add_task(_run_angle_job, job_id, book_id, name, dict(row), req.prompt_prefix, req.seed)
    return {"job_id": job_id}


@router.get("/angle_jobs/{job_id}")
async def get_angle_job(job_id: str):
    from fastapi import HTTPException
    _evict_expired(_angle_jobs, _DONE_TTL)
    if job_id not in _angle_jobs:
        raise HTTPException(status_code=404, detail="任務不存在")
    return _angle_jobs[job_id]


# ─── 角色立繪生成 ─────────────────────────────────────────────────────────────

async def _run_portrait_job(job_id: str, book_id: str, name: str, char: dict, prompt_prefix: str | None, seed: int):
    job = _portrait_jobs[job_id]

    async with _queue_sem:
        job["status"] = "running"
        job["label"]  = "組合角色描述…"

        char_desc = build_character_fragment(char)
        if seed < 0:
            seed = char.get("character_seed", -1)
        if prompt_prefix is None:
            prompt_prefix = get_settings().prompt_prefix

        def _cb(pct: int, label: str):
            job["progress"] = pct
            job["label"]    = label

        try:
            from services.illustration_engine import generate_portrait
            img_bytes, prompt = await generate_portrait(
                character_desc   = char_desc,
                character_name   = name,
                seed             = seed,
                width            = job["width"],
                height           = job["height"],
                prompt_prefix    = prompt_prefix,
                on_progress      = _cb,
                char_data        = char,
                ip_adapter_image = None,
            )
        except Exception as e:
            job["status"]  = "error"
            job["error"]   = str(e)
            job["done_at"] = time.time()
            return

        image_path = _save_image_file(img_bytes, "characters")
        try:
            conn = get_db_connection()
            char_row = conn.execute(
                "SELECT id FROM characters WHERE book_id=? AND name=?", (book_id, name)
            ).fetchone()
            if char_row:
                conn.execute(
                    "INSERT INTO character_images (character_id, image_path, angle, is_primary, prompt) VALUES (?,?,?,?,?)",
                    (char_row["id"], image_path, "立繪", 0, prompt),
                )
                conn.commit()
            conn.close()
        except Exception as e:
            logger.error("立繪存入 DB 失敗 %r: %s", name, e)
            job["status"]  = "error"
            job["error"]   = f"DB 儲存失敗：{e}"
            job["done_at"] = time.time()
            return

        job["status"]   = "done"
        job["progress"] = 100
        job["label"]    = "立繪已生成"
        job["image_path"] = image_path
        job["done_at"]  = time.time()


@router.post("/characters/{book_id}/portrait")
async def generate_portrait_endpoint(
    book_id: str,
    req: PortraitRequest,
    background_tasks: BackgroundTasks,
):
    from fastapi import HTTPException
    if not req.name:
        raise HTTPException(status_code=422, detail="name 不可為空")
    conn = get_db_connection()
    row = conn.execute(
        "SELECT * FROM characters WHERE book_id=? AND name=?", (book_id, req.name)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="角色不存在")

    s = get_settings()
    job_id = str(uuid.uuid4())
    _portrait_jobs[job_id] = {
        "status": "pending", "progress": 0, "label": "排隊中",
        "book_id": book_id, "name": req.name,
        "width":  req.width  if req.width  is not None else s.width,
        "height": req.height if req.height is not None else s.height,
        "error": None, "image_path": None,
    }
    background_tasks.add_task(
        _run_portrait_job, job_id, book_id, req.name, dict(row), req.prompt_prefix, req.seed
    )
    return {"job_id": job_id}


@router.get("/portrait_jobs/{job_id}")
async def get_portrait_job(job_id: str):
    from fastapi import HTTPException
    _evict_expired(_portrait_jobs, _DONE_TTL)
    if job_id not in _portrait_jobs:
        raise HTTPException(status_code=404, detail="任務不存在")
    job = dict(_portrait_jobs[job_id])
    if job.get("image_path"):
        img_id_row = None
        conn = get_db_connection()
        char_row = conn.execute(
            "SELECT id FROM characters WHERE book_id=? AND name=?",
            (job["book_id"], job["name"])
        ).fetchone()
        if char_row:
            img_id_row = conn.execute(
                "SELECT id FROM character_images WHERE character_id=? AND image_path=?",
                (char_row["id"], job["image_path"])
            ).fetchone()
        conn.close()
        job["image_id"] = img_id_row["id"] if img_id_row else None
    return job
