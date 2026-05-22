"""
模型下載與狀態管理服務。
負責管理專案目錄 models/ 底下官方 PyTorch 模型與 GGUF 量化版本模型之下載、刪除與狀態查詢。
同時追蹤各模型的引擎載入（in-memory）狀態。
"""
import os
import shutil
import threading
import requests
from huggingface_hub import snapshot_download
from services.db import get_db_connection

# 模型儲存根目錄：專案 backend/models/
MODELS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../models"))

# Hugging Face 模型配置資訊
GGUF_REPO = "Serveurperso/OmniVoice-GGUF"
MODEL_CONFIGS = {
    "official": {
        "name": "官方預設模型",
        "type": "PyTorch (FP32/FP16)",
        "size_str": "約 1.6 GB",
        "repo": "k2-fsa/OmniVoice",
        "local_dir": os.path.join(MODELS_DIR, "k2-fsa--OmniVoice")
    },
    "gguf_BF16": {
        "name": "BF16 高精度量化版",
        "type": "GGUF (BF16)",
        "size_str": "約 1.44 GB",
        "base": "omnivoice-base-BF16.gguf",
        "tokenizer": "omnivoice-tokenizer-BF16.gguf",
        "total_size": 1340000000 + 101000000
    },
    "gguf_Q8_0": {
        "name": "Q8_0 推薦量化版",
        "type": "GGUF (8-bit)",
        "size_str": "約 779 MB",
        "base": "omnivoice-base-Q8_0.gguf",
        "tokenizer": "omnivoice-tokenizer-Q8_0.gguf",
        "total_size": 722000000 + 57200000
    },
    "gguf_Q4_K_M": {
        "name": "Q4_K_M 輕量化版",
        "type": "GGUF (4-bit)",
        "size_str": "約 477 MB",
        "base": "omnivoice-base-Q4_K_M.gguf",
        "tokenizer": "omnivoice-tokenizer-Q4_K_M.gguf",
        "total_size": 438000000 + 39000000
    },
    "gguf_F32": {
        "name": "F32 除錯參考版",
        "type": "GGUF (FP32)",
        "size_str": "約 2.77 GB",
        "base": "omnivoice-base-F32.gguf",
        "tokenizer": "omnivoice-tokenizer-F32.gguf",
        "total_size": 2580000000 + 194000000
    }
}

# 全域下載進度字典：model_id -> {"progress": float, "status": str, "error": str | None}
DOWNLOAD_PROGRESS: dict[str, dict] = {}
# 下載取消旗標字典：model_id -> threading.Event（設定後代表取消）
CANCEL_FLAGS: dict[str, threading.Event] = {}
progress_lock = threading.Lock()

# 目前引擎中已載入的模型 ID（None 表示未載入任何模型或仍為啟動時自動載入）
_engine_loaded_model_id: str | None = None
_engine_loaded_lock = threading.Lock()


def get_engine_loaded_model_id() -> str | None:
    """
    取得目前已在 TTS 引擎中載入（in-memory）的模型 ID。
    若為 None，代表引擎已在啟動時依預設設定載入，尚未切換。
    """
    with _engine_loaded_lock:
        return _engine_loaded_model_id


def set_engine_loaded_model_id(model_id: str | None):
    """
    更新目前已在 TTS 引擎記憶體中載入的模型 ID。
    """
    global _engine_loaded_model_id
    with _engine_loaded_lock:
        _engine_loaded_model_id = model_id


def get_current_model_id() -> str:
    """
    從資料庫中取得目前選取的模型 ID。若無則預設為 'official'。
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = 'tts_model'")
        row = cursor.fetchone()
        conn.close()
        if row:
            return row["value"]
    except Exception:
        pass
    return "official"


def set_current_model_id(model_id: str) -> bool:
    """
    將選取的模型 ID 寫入資料庫設定中。
    """
    if model_id not in MODEL_CONFIGS:
        return False
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('tts_model', ?)", (model_id,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[set_current_model_id] 寫入資料庫失敗: {e}")
        return False


def check_model_downloaded(model_id: str) -> bool:
    """
    檢查指定模型是否已完整下載至本地（僅檢查專案目錄或全域快取）。
    """
    config = MODEL_CONFIGS.get(model_id)
    if not config:
        return False

    if model_id == "official":
        # 1. 先確認專案本地目錄是否有完整模型
        local_path = config["local_dir"]
        if os.path.exists(os.path.join(local_path, "config.json")) and \
           os.path.exists(os.path.join(local_path, "model.safetensors")):
            return True
        # 2. 確認使用者全域 Hugging Face 快取目錄
        user_home = os.path.expanduser("~")
        hf_cache_path = os.path.join(user_home, ".cache", "huggingface", "hub", "models--k2-fsa--OmniVoice")
        snapshots_dir = os.path.join(hf_cache_path, "snapshots")
        if os.path.exists(snapshots_dir) and os.listdir(snapshots_dir):
            return True
        return False
    else:
        # GGUF 模型：確認 base 與 tokenizer 實體檔案是否皆存在（非暫存）
        gguf_dir = os.path.join(MODELS_DIR, "Serveurperso--OmniVoice-GGUF")
        base_path = os.path.join(gguf_dir, config["base"])
        tok_path = os.path.join(gguf_dir, config["tokenizer"])
        return os.path.exists(base_path) and os.path.exists(tok_path)


def get_models_status_list() -> list[dict]:
    """
    獲取所有模型在 UI 顯示所需的狀態清單，包含下載進度與引擎載入狀態。
    """
    active_model = get_current_model_id()
    loaded_model = get_engine_loaded_model_id()

    # None / "" = 引擎未載入任何模型
    # str       = 已明確載入的模型 ID
    effective_loaded = loaded_model if loaded_model else None

    results = []

    for mid, config in MODEL_CONFIGS.items():
        is_downloaded = check_model_downloaded(mid)

        status = "not_downloaded"
        progress = 0.0
        error_msg = None

        with progress_lock:
            if mid in DOWNLOAD_PROGRESS:
                status = DOWNLOAD_PROGRESS[mid]["status"]
                progress = DOWNLOAD_PROGRESS[mid]["progress"]
                error_msg = DOWNLOAD_PROGRESS[mid].get("error")

        # 若全域下載器沒有紀錄，但實體檔案已存在，則更新為已下載
        if is_downloaded and status not in ("downloaded", "downloading"):
            status = "downloaded"
            progress = 100.0

        results.append({
            "id": mid,
            "name": config["name"],
            "type": config["type"],
            "size_str": config["size_str"],
            "status": status,
            "progress": round(progress, 1),
            "active": (mid == active_model),
            "loaded": (mid == effective_loaded),
            "error": error_msg
        })

    return results


def delete_model_files(model_id: str) -> bool:
    """
    刪除已下載的本地模型實體檔案。
    若模型正在下載中，會先設置取消旗標並等待執行緒停止，
    再清除所有實體檔案（包含臨時 .download 暫存檔）。
    """
    config = MODEL_CONFIGS.get(model_id)
    if not config:
        return False

    # 1. 若有下載中的執行緒，設定取消旗標，強制它在下一個 chunk 停止
    with progress_lock:
        if model_id in CANCEL_FLAGS:
            CANCEL_FLAGS[model_id].set()

    try:
        if model_id == "official":
            # 1. 刪除專案內本地儲存目錄
            local_path = config["local_dir"]
            if os.path.exists(local_path):
                shutil.rmtree(local_path)
                print(f"[delete_model_files] 已刪除本地目錄: {local_path}")

            # 2. 刪除 Hugging Face 全域快取目錄（官方模型主要儲存位置）
            user_home = os.path.expanduser("~")
            hf_cache_path = os.path.join(
                user_home, ".cache", "huggingface", "hub", "models--k2-fsa--OmniVoice"
            )
            if os.path.exists(hf_cache_path):
                shutil.rmtree(hf_cache_path)
                print(f"[delete_model_files] 已刪除 HF 全域快取: {hf_cache_path}")
            else:
                print(f"[delete_model_files] HF 全域快取不存在，跳過: {hf_cache_path}")

        else:
            # 刪除 GGUF 實體檔案與可能存在的暫存檔
            gguf_dir = os.path.join(MODELS_DIR, "Serveurperso--OmniVoice-GGUF")
            for fname in [config["base"], config["tokenizer"]]:
                # 正式檔案
                fpath = os.path.join(gguf_dir, fname)
                if os.path.exists(fpath):
                    os.remove(fpath)
                # 暫存下載檔案
                temp_path = fpath + ".download"
                if os.path.exists(temp_path):
                    os.remove(temp_path)

        # 2. 清除全域下載進度紀錄與取消旗標
        with progress_lock:
            if model_id in DOWNLOAD_PROGRESS:
                del DOWNLOAD_PROGRESS[model_id]
            if model_id in CANCEL_FLAGS:
                del CANCEL_FLAGS[model_id]

        return True
    except Exception as e:
        print(f"[delete_model_files] 刪除模型 {model_id} 失敗: {e}")
        return False


def start_download_thread(model_id: str) -> bool:
    """
    啟動背景下載執行緒。若已在下載中則不重複發起。
    """
    if model_id not in MODEL_CONFIGS:
        return False

    with progress_lock:
        # 若已在下載中，不重複發起
        if model_id in DOWNLOAD_PROGRESS and DOWNLOAD_PROGRESS[model_id]["status"] == "downloading":
            return True
        # 建立新的取消旗標（清除舊的旗標以防殘留）
        cancel_event = threading.Event()
        CANCEL_FLAGS[model_id] = cancel_event
        DOWNLOAD_PROGRESS[model_id] = {
            "status": "downloading",
            "progress": 0.0,
            "error": None
        }

    thread = threading.Thread(target=_download_worker, args=(model_id, cancel_event), daemon=True)
    thread.start()
    return True


def _download_worker(model_id: str, cancel_event: threading.Event):
    """
    背景下載執行緒實體。
    支援取消旗標：一旦 cancel_event 被設定，立即停止並清除已下載的暫存檔。
    """
    config = MODEL_CONFIGS[model_id]
    os.makedirs(MODELS_DIR, exist_ok=True)

    temp_files: list[str] = []  # 追蹤本次建立的暫存檔，以便取消時清除

    def update_progress(progress: float):
        """安全地更新進度，若 key 已被刪除（外部取消）則忽略。"""
        with progress_lock:
            if model_id in DOWNLOAD_PROGRESS:
                DOWNLOAD_PROGRESS[model_id]["progress"] = progress

    def mark_error(msg: str):
        """安全地標記錯誤狀態。"""
        with progress_lock:
            if model_id in DOWNLOAD_PROGRESS:
                DOWNLOAD_PROGRESS[model_id]["status"] = "not_downloaded"
                DOWNLOAD_PROGRESS[model_id]["error"] = msg
                DOWNLOAD_PROGRESS[model_id]["progress"] = 0.0

    def mark_done():
        """安全地標記下載完成。"""
        with progress_lock:
            if model_id in DOWNLOAD_PROGRESS:
                DOWNLOAD_PROGRESS[model_id]["progress"] = 100.0
                DOWNLOAD_PROGRESS[model_id]["status"] = "downloaded"

    try:
        if model_id == "official":
            # 官方 PyTorch 模型：使用 snapshot_download 下載至專案目錄
            update_progress(10.0)
            snapshot_download(
                repo_id=config["repo"],
                local_dir=config["local_dir"],
                local_dir_use_symlinks=False
            )
            mark_done()
        else:
            # GGUF 模型：使用 requests 串流依序下載 base 與 tokenizer
            gguf_dir = os.path.join(MODELS_DIR, "Serveurperso--OmniVoice-GGUF")
            os.makedirs(gguf_dir, exist_ok=True)

            files_to_download = [
                {"name": config["base"], "url": f"https://huggingface.co/{GGUF_REPO}/resolve/main/{config['base']}"},
                {"name": config["tokenizer"], "url": f"https://huggingface.co/{GGUF_REPO}/resolve/main/{config['tokenizer']}"}
            ]

            # 取得各檔案大小以計算整體進度
            total_bytes = 0
            for item in files_to_download:
                try:
                    r = requests.head(item["url"], allow_redirects=True, timeout=10)
                    size = int(r.headers.get("content-length", 0))
                    total_bytes += size
                except Exception:
                    pass

            if total_bytes == 0:
                total_bytes = config["total_size"]

            bytes_downloaded = 0

            for item in files_to_download:
                # 若已被取消，停止並清理暫存
                if cancel_event.is_set():
                    print(f"[_download_worker] 模型 {model_id} 下載已被取消")
                    for tmp in temp_files:
                        if os.path.exists(tmp):
                            os.remove(tmp)
                    return

                dest_path = os.path.join(gguf_dir, item["name"])
                temp_dest = dest_path + ".download"
                temp_files.append(temp_dest)

                response = requests.get(item["url"], stream=True, timeout=60)
                response.raise_for_status()

                with open(temp_dest, "wb") as f:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        # 每個 chunk 前先確認是否已被取消
                        if cancel_event.is_set():
                            print(f"[_download_worker] 模型 {model_id} 下載在 chunk 迴圈中被取消")
                            f.flush()
                            break

                        if not chunk:
                            continue

                        f.write(chunk)
                        bytes_downloaded += len(chunk)
                        progress = min(99.0, (bytes_downloaded / total_bytes) * 100)
                        update_progress(progress)

                # 若中途被取消，清除所有暫存並返回
                if cancel_event.is_set():
                    for tmp in temp_files:
                        if os.path.exists(tmp):
                            os.remove(tmp)
                    return

                # 下載成功，重新命名為正式檔案
                if os.path.exists(dest_path):
                    os.remove(dest_path)
                os.rename(temp_dest, dest_path)

            mark_done()

    except Exception as e:
        print(f"[_download_worker] 下載模型 {model_id} 失敗: {e}")
        # 清除暫存檔
        for tmp in temp_files:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except Exception:
                    pass
        mark_error(str(e))
