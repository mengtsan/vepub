"""
通用模型下載器。
支援：HuggingFace repo、HF 單檔、Civitai、任意直連 URL。
提供 probe（偵測類型）與 download（帶進度）兩個主要功能。
"""
import asyncio
import json
import os
import re
import time
import uuid
from typing import Any
import httpx

_BASE_DIR    = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_MODELS_DIR  = os.path.join(_BASE_DIR, "models")
_TOKEN_FILE  = os.path.join(_BASE_DIR, "civitai_token.json")

# task_id → { status, progress, total, downloaded, speed, error, result }
_download_tasks: dict[str, dict[str, Any]] = {}


# ─── CivitAI Token ────────────────────────────────────────────────────────────

def get_civitai_token() -> str:
    """讀取已儲存的 CivitAI API token。"""
    try:
        with open(_TOKEN_FILE, encoding="utf-8") as f:
            return json.load(f).get("token", "")
    except Exception:
        return os.environ.get("CIVITAI_API_KEY", "")


def set_civitai_token(token: str) -> None:
    """儲存 CivitAI API token 到本地。"""
    with open(_TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump({"token": token.strip()}, f)


# ─── URL 偵測 ─────────────────────────────────────────────────────────────────

def _parse_hf_url(url: str) -> dict | None:
    """
    解析 HuggingFace URL，回傳 { repo, filename } 或 None。
    支援格式：
      https://huggingface.co/owner/repo
      https://huggingface.co/owner/repo/blob/main/file.gguf
      https://huggingface.co/owner/repo/resolve/main/file.gguf
      https://hf.co/owner/repo
    """
    m = re.match(
        r"https?://(?:huggingface\.co|hf\.co)/([^/]+/[^/]+)"
        r"(?:/(?:blob|resolve)/[^/]+/(.+))?",
        url,
    )
    if not m:
        return None
    repo = m.group(1).split("?")[0].rstrip("/")
    filename = m.group(2) if m.group(2) else None
    return {"repo": repo, "filename": filename}


def _guess_category(filename: str | None, repo: str | None) -> str | None:
    """從檔名或 repo 名稱猜測模型類別。"""
    targets = []
    if filename:
        targets.append(filename.lower())
    if repo:
        targets.append(repo.lower())
    combined = " ".join(targets)

    if any(k in combined for k in (".gguf", "gguf", "llama", "mistral", "qwen", "gemma",
                                    "llm", "chat", "instruct", "smollm")):
        return "llm"
    if any(k in combined for k in ("tts", "voice", "speech", "kokoro", "parler",
                                    "bark", "speecht5", "vits", "xtts")):
        return "tts"
    if any(k in combined for k in ("diffusion", "stable-diffusion", "flux", "sdxl",
                                    "image", "turbo", "dalle", "wan", "hidream",
                                    "illusion", "inpaint")):
        return "image"
    return None


async def _fetch_hf_metadata(repo: str) -> dict:
    """向 HF Hub API 查詢 repo 資訊。"""
    api_url = f"https://huggingface.co/api/models/{repo}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(api_url)
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return {}


async def _fetch_civitai_version(version_id: str, base: str) -> dict:
    """向 CivitAI API 查詢模型版本資訊（取得真實檔名）。"""
    api_url = f"{base}/api/v1/model-versions/{version_id}"
    try:
        async with httpx.AsyncClient(
            timeout=15, follow_redirects=True,
            headers={"User-Agent": "vepub-model-manager/1.0"},
        ) as client:
            r = await client.get(api_url)
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return {}


def _infer_image_style(name: str, download_url: str = "") -> str | None:
    """從模型名稱猜測 anime / real 風格，讓 registry 能自動分配。"""
    text = (name + " " + download_url).lower()
    anime_kw = {"anime", "wai", "manga", "2d", "cartoon", "illustrious", "pony",
                "meinamix", "anything", "counterfeit"}
    real_kw  = {"photo", "realistic", "turbo", "nsfw", "portrait", "cinematic",
                "epicrealism", "perfectworld", "zimage", "z-image"}
    if any(k in text for k in anime_kw):
        return "anime"
    if any(k in text for k in real_kw):
        return "real"
    return None


async def probe_url(url: str) -> dict:
    """
    偵測 URL 對應的模型類型與基本資訊。
    回傳：
    {
        "source": "hf_repo" | "hf_file" | "civitai" | "direct",
        "category": "tts" | "image" | "llm" | null,
        "name": str,
        "repo": str | null,
        "filename": str | null,
        "download_url": str,
    }
    """
    url = url.strip()
    result: dict = {
        "source": "direct",
        "category": None,
        "name": "",
        "repo": None,
        "filename": None,
        "download_url": url,
    }

    # ── HuggingFace ────────────────────────────────────────────────────────
    hf = _parse_hf_url(url)
    if hf:
        repo = hf["repo"]
        filename = hf["filename"]
        result["repo"] = repo
        result["filename"] = filename

        if filename:
            result["source"] = "hf_file"
            result["name"] = os.path.basename(filename)
            # 轉成 resolve URL 確保可直接下載
            result["download_url"] = (
                f"https://huggingface.co/{repo}/resolve/main/{filename}"
            )
            result["category"] = _guess_category(filename, repo)
        else:
            result["source"] = "hf_repo"
            result["name"] = repo.split("/")[-1]
            result["download_url"] = url
            # 查詢 API 取得更多資訊
            meta = await _fetch_hf_metadata(repo)
            tags = meta.get("tags", [])
            pipeline = meta.get("pipeline_tag", "")
            combined = " ".join(tags + [pipeline]).lower()
            if "text-to-speech" in combined or "tts" in combined:
                result["category"] = "tts"
            elif "text-to-image" in combined or "image" in combined:
                result["category"] = "image"
            else:
                result["category"] = _guess_category(None, repo)
        return result

    # ── Civitai (civitai.com 與 civitai.red 成人鏡像站) ──────────────────
    if "civitai.com" in url or "civitai.red" in url:
        result["source"] = "civitai"
        result["category"] = "image"
        base = "https://civitai.red" if "civitai.red" in url else "https://civitai.com"

        # 嘗試從 URL 取得版本 ID
        m_ver = re.search(r'modelVersionId=(\d+)', url)
        m_api = re.search(r'/api/download/models/(\d+)', url)
        version_id = (m_ver or m_api) and (m_ver or m_api).group(1)

        if version_id:
            result["download_url"] = f"{base}/api/download/models/{version_id}"
            # 向 CivitAI API 取得真實檔名與完整檔案清單
            meta = await _fetch_civitai_version(version_id, base)
            files = meta.get("files", [])

            # 主模型（primary=True 且 type=Model）
            primary = next(
                (f for f in files if f.get("primary") and f.get("type") in ("Model", "Pruned Model")),
                next((f for f in files if f.get("type") in ("Model", "Pruned Model")), files[0] if files else {}),
            )
            actual_name = primary.get("name") or f"civitai_{version_id}.safetensors"
            result["name"] = actual_name
            result["version_id"] = version_id

            # 附加檔案（VAE / Text Encoder）— 不包含非 primary 的同類型重複 Model
            _USEFUL = {"VAE", "Text Encoder"}
            extra = [
                {
                    "name":         f["name"],
                    "type":         f["type"],
                    "download_url": f["downloadUrl"],
                    "size_bytes":   int(f.get("sizeKB", 0) * 1024),
                }
                for f in files
                if f.get("type") in _USEFUL and f.get("downloadUrl")
            ]
            if extra:
                result["extra_files"] = extra
        else:
            result["name"] = url.split("/")[-1].split("?")[0] or "civitai_model"

        return result

    # ── 直連：猜檔名 ──────────────────────────────────────────────────────
    fname = url.split("?")[0].split("/")[-1]
    result["name"] = fname or "model"
    result["category"] = _guess_category(fname, None)
    return result


# ─── 下載 ─────────────────────────────────────────────────────────────────────

_CATEGORY_SUBDIR = {"tts": "tts", "llm": "llm", "image": "image"}


def _dest_path(probe: dict, category: str) -> str:
    """決定下載目的地路徑（category 子目錄）。"""
    name = re.sub(r"[^\w.\-]", "_", probe["name"])
    subdir = _CATEGORY_SUBDIR.get(category, "misc")

    if probe["source"] == "hf_repo":
        repo_slug = (probe["repo"] or name).replace("/", "--")
        return os.path.join(_MODELS_DIR, subdir, repo_slug)
    else:
        return os.path.join(_MODELS_DIR, subdir, name)


async def _download_hf_repo(
    repo: str, dest: str, task: dict, cancel: asyncio.Event
) -> None:
    """用 huggingface_hub 下載整個 repo 到本地目錄。"""
    from huggingface_hub import snapshot_download
    import concurrent.futures

    os.makedirs(dest, exist_ok=True)
    task["label"] = f"下載 HF repo {repo}…"

    loop = asyncio.get_running_loop()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = loop.run_in_executor(
            pool,
            lambda: snapshot_download(
                repo_id=repo,
                local_dir=dest,
                ignore_patterns=["*.msgpack", "flax_*", "tf_*", "rust_*"],
            ),
        )
        while not future.done():
            if cancel.is_set():
                future.cancel()
                raise asyncio.CancelledError("使用者取消下載")
            await asyncio.sleep(1)
        await future


async def _download_file(
    url: str, dest: str, task: dict, cancel: asyncio.Event
) -> None:
    """用 httpx 串流下載單一檔案。"""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".downloading"
    t0 = time.time()
    downloaded = 0

    headers = {"User-Agent": "vepub-model-manager/1.0"}
    if "civitai.com" in url or "civitai.red" in url:
        token = get_civitai_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(connect=30, read=300, write=300, pool=30),
        headers=headers,
    ) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            task["total"] = total

            with open(tmp, "wb") as f:
                async for chunk in resp.aiter_bytes(65536):
                    if cancel.is_set():
                        raise asyncio.CancelledError("使用者取消下載")
                    f.write(chunk)
                    downloaded += len(chunk)
                    elapsed = max(time.time() - t0, 0.001)
                    task["downloaded"] = downloaded
                    task["speed"] = downloaded / elapsed
                    if total:
                        task["progress"] = int(downloaded / total * 100)

    os.replace(tmp, dest)


async def start_download(
    probe: dict, category: str, name: str
) -> str:
    """
    啟動背景下載任務，立即回傳 task_id。
    """
    task_id = str(uuid.uuid4())
    cancel_event = asyncio.Event()
    task: dict = {
        "task_id": task_id,
        "status": "running",
        "progress": 0,
        "total": 0,
        "downloaded": 0,
        "speed": 0,
        "label": "準備下載…",
        "error": None,
        "result": None,
        "_cancel": cancel_event,
        "name": name,
        "category": category,
    }
    _download_tasks[task_id] = task

    async def _run():
        try:
            from services.model_registry import register_model

            # ── 1. 下載主模型 ──────────────────────────────────────────────
            dest = _dest_path(probe, category)
            task["dest"] = dest
            extra_files = probe.get("extra_files", [])
            total_steps = 1 + len(extra_files)

            task["label"] = f"下載主模型 (1/{total_steps}): {probe['name']}"
            if probe["source"] == "hf_repo":
                await _download_hf_repo(probe["repo"], dest, task, cancel_event)
            else:
                await _download_file(probe["download_url"], dest, task, cancel_event)

            size = os.path.getsize(dest) if os.path.isfile(dest) else sum(
                os.path.getsize(os.path.join(dp, f))
                for dp, _, fls in os.walk(dest) for f in fls
            )
            model_id = re.sub(r"[^\w.\-]", "_", name.lower())
            style = _infer_image_style(name, probe.get("download_url", "")) if category == "image" else None
            entry: dict = {
                "name": name,
                "type": _infer_type(probe, category),
                "local_path": dest,
                "size_bytes": size,
                "source": f"hf:{probe['repo']}" if probe.get("repo") else probe["download_url"],
            }
            if style:
                entry["style"] = style

            # ── 2. 下載附加檔案（VAE / Text Encoder），路徑嵌入主 entry ──
            # 不建立獨立 registry entry，避免 style 碰撞造成配對錯誤。
            _PATH_KEY = {"VAE": "vae_path", "Text Encoder": "text_encoder_path"}
            subdir = _CATEGORY_SUBDIR.get(category, "misc")
            for i, ef in enumerate(extra_files, start=2):
                ef_name = ef["name"]
                ef_dest = os.path.join(_MODELS_DIR, subdir, re.sub(r"[^\w.\-]", "_", ef_name))
                task["label"] = f"下載 {ef['type']} ({i}/{total_steps}): {ef_name}"
                task["progress"] = 0
                task["downloaded"] = 0
                await _download_file(ef["download_url"], ef_dest, task, cancel_event)
                path_key = _PATH_KEY.get(ef["type"])
                if path_key:
                    entry[path_key] = ef_dest
                    entry["size_bytes"] = entry["size_bytes"] + os.path.getsize(ef_dest)
                print(f"[downloader] {ef['type']} {ef_name} 完成 → {ef_dest}")

            register_model(category, model_id, entry)
            print(f"[downloader] {name} 全部檔案已登錄 → {dest}")

            task["status"] = "done"
            task["progress"] = 100
            task["result"] = {"model_id": model_id, "local_path": dest, "size_bytes": size}
            print(f"[downloader] {name} 全部檔案下載完成")

        except asyncio.CancelledError:
            task["status"] = "cancelled"
            task["error"] = "已取消"
        except Exception as e:
            task["status"] = "error"
            task["error"] = str(e)
            print(f"[downloader] 下載失敗 {name}: {e}")

    asyncio.create_task(_run())
    return task_id


def _infer_type(probe: dict, category: str) -> str:
    if category == "llm":
        return "gguf"
    if category == "tts":
        if probe["source"] == "hf_repo":
            return "transformers_tts"
        return "transformers_tts"
    if category == "image":
        if probe["source"] == "hf_repo":
            return "diffusers"
        return "diffusers"
    return "unknown"


def get_task(task_id: str) -> dict | None:
    t = _download_tasks.get(task_id)
    if not t:
        return None
    # 回傳給前端（去除內部欄位）
    return {k: v for k, v in t.items() if not k.startswith("_")}


def cancel_task(task_id: str) -> bool:
    t = _download_tasks.get(task_id)
    if not t:
        return False
    t["_cancel"].set()
    return True


def list_tasks() -> list[dict]:
    return [get_task(tid) for tid in _download_tasks]
