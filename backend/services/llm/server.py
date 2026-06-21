"""
LLM server 生命週期 + HTTP 推理。
管理 llama-server.exe subprocess、keep-alive 計時器、_chat() HTTP client。
"""
import asyncio
import json as _json
import logging
import os
import subprocess
import time

import httpx
from config import LLM_PORT, LLM_IDLE_TTL, MODELS_DIR, LLAMA_BIN_DIR

logger = logging.getLogger(__name__)

_BASE_DIR = str(MODELS_DIR)
_BIN_DIR  = str(LLAMA_BIN_DIR)

_LLM_PREFERRED = [
    "Gemma-4-12B-it-AEON-Abliterated-K4.gguf",
]

_SERVER_PORT      = LLM_PORT
_server_proc: subprocess.Popen | None = None
_server_lock      = asyncio.Lock()

_SERVER_IDLE_TTL  = LLM_IDLE_TTL
_server_ctx: int  = 0
_server_model: str = ""
_idle_stop_task: asyncio.Task | None = None


def _registry_gguf(role: str) -> str | None:
    try:
        from services.model_registry import get_llm_path
        return get_llm_path(role)
    except Exception:
        return None


def find_llama_server() -> str | None:
    path = os.path.join(_BIN_DIR, "llama-server.exe")
    return path if os.path.exists(path) else None


def find_gguf() -> str | None:
    """所有 LLM 推論統一使用最大的本地 GGUF。"""
    p = _registry_gguf("analysis")
    if p and os.path.exists(p):
        return p
    p = _registry_gguf("chat")
    if p and os.path.exists(p):
        return p
    all_ggufs = [
        f for f in os.listdir(_BASE_DIR)
        if f.endswith(".gguf") and os.path.isfile(os.path.join(_BASE_DIR, f))
    ]
    for name in _LLM_PREFERRED:
        if name in all_ggufs:
            return os.path.join(_BASE_DIR, name)
    for kw in ("72b", "32b", "27b", "14b"):
        for f in sorted(all_ggufs):
            if kw in f.lower():
                return os.path.join(_BASE_DIR, f)
    if all_ggufs:
        return os.path.join(
            _BASE_DIR,
            max(all_ggufs, key=lambda f: os.path.getsize(os.path.join(_BASE_DIR, f)))
        )
    return None


def find_analysis_gguf() -> str | None:
    return find_gguf()


def is_available() -> bool:
    return find_gguf() is not None and find_llama_server() is not None


def get_model_name() -> str | None:
    path = find_gguf()
    return os.path.basename(path) if path else None


def _kill_existing_server():
    import urllib.request
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{_SERVER_PORT}/health", timeout=1)
    except Exception:
        return
    try:
        import psutil
        for conn in psutil.net_connections(kind="inet"):
            if conn.laddr.port == _SERVER_PORT and conn.status == "LISTEN" and conn.pid:
                proc = psutil.Process(conn.pid)
                if proc.name().lower() in ("llama-server.exe", "llama-server"):
                    proc.kill()
                    time.sleep(1)
                else:
                    logger.warning("port %d 被非 llama-server 行程佔用（%s），略過 kill", _SERVER_PORT, proc.name())
                break
    except Exception:
        pass


def _start_server_sync(model_path: str, n_ctx: int) -> subprocess.Popen:
    global _server_proc

    server_exe = find_llama_server()
    if not server_exe:
        raise RuntimeError("找不到 llama-server.exe，請確認 backend/llama_bin/ 目錄")

    _kill_existing_server()

    cmd = [
        server_exe,
        "-m",          model_path,
        "--ctx-size",  str(n_ctx),
        "-ngl",        "99",
        "--port",      str(_SERVER_PORT),
        "--host",      "127.0.0.1",
        "--log-disable",
    ]
    logger.info("啟動 llama-server: %s  ctx=%d", os.path.basename(model_path), n_ctx)
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    import urllib.request
    url      = f"http://127.0.0.1:{_SERVER_PORT}/health"
    deadline = time.time() + 180
    while time.time() < deadline:
        time.sleep(2)
        if proc.poll() is not None:
            raise RuntimeError(f"llama-server 提前退出 exit={proc.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if _json.loads(r.read()).get("status") == "ok":
                    logger.info("llama-server 就緒")
                    return proc
        except Exception:
            pass

    proc.terminate()
    raise RuntimeError("llama-server 啟動逾時（>180s）")


def _stop_server_sync():
    global _server_proc, _server_ctx, _server_model
    if _server_proc is not None:
        _server_proc.terminate()
        try:
            _server_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _server_proc.kill()
        _server_proc = None
        _server_ctx   = 0
        _server_model = ""
        logger.info("llama-server 已關閉，VRAM 已釋放")


async def _ensure_server(path: str, n_ctx: int) -> None:
    global _server_proc, _server_ctx, _server_model, _idle_stop_task

    if _idle_stop_task and not _idle_stop_task.done():
        _idle_stop_task.cancel()
        try:
            await _idle_stop_task
        except asyncio.CancelledError:
            pass
        _idle_stop_task = None

    if (
        _server_proc is not None
        and _server_proc.poll() is None
        and _server_model == path
        and _server_ctx >= n_ctx
    ):
        logger.info("複用已就緒的 server（ctx=%d >= %d）", _server_ctx, n_ctx)
        return

    loop = asyncio.get_running_loop()
    if _server_proc is not None:
        await loop.run_in_executor(None, _stop_server_sync)
    _server_proc = await loop.run_in_executor(None, _start_server_sync, path, n_ctx)
    _server_ctx   = n_ctx
    _server_model = path


def _arm_idle_stop() -> None:
    global _idle_stop_task

    async def _delayed_stop():
        await asyncio.sleep(_SERVER_IDLE_TTL)
        async with _server_lock:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _stop_server_sync)
        logger.info("server 閒置 %ds，已自動關閉", _SERVER_IDLE_TTL)

    _idle_stop_task = asyncio.ensure_future(_delayed_stop())


async def stop_server_now() -> None:
    global _idle_stop_task, _server_ctx, _server_model
    if _idle_stop_task and not _idle_stop_task.done():
        _idle_stop_task.cancel()
        try:
            await _idle_stop_task
        except asyncio.CancelledError:
            pass
        _idle_stop_task = None
    if _server_proc is None:
        return
    async with _server_lock:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _stop_server_sync)


async def _chat(
    system: str,
    user: str,
    max_tokens: int = 400,
    temperature: float = 0.4,
    prefill: str = "",
    frequency_penalty: float = 0.0,
    presence_penalty: float = 0.0,
) -> str:
    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": user},
    ]
    if prefill:
        messages.append({"role": "assistant", "content": prefill})

    payload = {
        "messages":    messages,
        "max_tokens":  max_tokens,
        "temperature": temperature,
    }
    if frequency_penalty:
        payload["frequency_penalty"] = frequency_penalty
    if presence_penalty:
        payload["presence_penalty"] = presence_penalty

    # 全域取樣覆寫（預設關閉）。開啟後以使用者在「模型管理」設定的值取代各呼叫的
    # 調校參數；max_tokens 留空(None)時不覆寫，避免截斷較長輸出（全書分析等）。
    try:
        from services.llm.settings import get_settings as _get_llm_settings
        _s = _get_llm_settings()
        if _s.override_enabled:
            payload["temperature"]    = _s.temperature
            payload["top_p"]          = _s.top_p
            payload["top_k"]          = _s.top_k
            payload["repeat_penalty"] = _s.repeat_penalty
            if _s.max_tokens is not None:
                payload["max_tokens"] = _s.max_tokens
    except Exception:
        pass
    url = f"http://127.0.0.1:{_SERVER_PORT}/v1/chat/completions"
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=payload, timeout=600.0)

        if resp.status_code >= 500:
            body_preview = resp.text[:400]
            logger.warning("server %d (prefill=%s): %s", resp.status_code, bool(prefill), body_preview)
            if prefill and payload["messages"][-1]["role"] == "assistant":
                logger.info("移除 prefill 後重試…")
                payload["messages"] = payload["messages"][:-1]
                resp = await client.post(url, json=payload, timeout=600.0)
                if resp.status_code >= 500:
                    logger.warning("重試仍失敗 %d: %s", resp.status_code, resp.text[:200])
                    resp.raise_for_status()
                prefill = ""
            else:
                resp.raise_for_status()

    msg = resp.json()["choices"][0]["message"]
    content = msg.get("content", "") or msg.get("reasoning_content", "")
    return (prefill + content).strip()
