"""
模型登錄檔管理 — 讀寫 model_registry.json。
首次啟動時自動掃描現有模型目錄並建立預設登錄檔。
"""
import json
import os
import shutil

_BASE_DIR      = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_MODELS_DIR    = os.path.join(_BASE_DIR, "models")
_REGISTRY_PATH = os.path.join(_BASE_DIR, "model_registry.json")


# ─── 讀寫 ─────────────────────────────────────────────────────────────────────

def _load() -> dict:
    if os.path.exists(_REGISTRY_PATH):
        try:
            with open(_REGISTRY_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return _build_default()


def _save(reg: dict) -> None:
    with open(_REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=2)


# ─── 首次初始化：掃描現有模型 ─────────────────────────────────────────────────

def _scan_gguf() -> dict:
    """掃描 models/ 目錄下的 GGUF 檔案，回傳 {model_id: info}。"""
    found = {}
    if not os.path.isdir(_MODELS_DIR):
        return found
    for fname in os.listdir(_MODELS_DIR):
        if not fname.endswith(".gguf"):
            continue
        path = os.path.join(_MODELS_DIR, fname)
        size = os.path.getsize(path)
        model_id = os.path.splitext(fname)[0]
        found[model_id] = {
            "name": fname,
            "type": "gguf",
            "local_path": path,
            "size_bytes": size,
            "source": "",
        }
    return found


def _build_default() -> dict:
    """掃描現有檔案，產生預設登錄檔。"""
    gguf_models = _scan_gguf()

    # chat 與 analysis 皆指向最大的 GGUF（27B）；
    # 4B GGUF 作為 Z-Image text encoder，不作為 llama-server 推論模型。
    llm_id = None
    for mid in gguf_models:
        ml = mid.lower()
        if any(k in ml for k in ("72b", "70b", "32b", "27b", "14b")):
            llm_id = mid
            break
    if not llm_id and gguf_models:
        # 無大模型：選最大的
        llm_id = max(gguf_models, key=lambda m: gguf_models[m]["size_bytes"])
    chat_id = llm_id
    analysis_id = llm_id

    # 偵測現有 TTS 本地目錄（統一在 models/tts/ 下，與 llm/、image/ 一致）
    tts_local = os.path.join(_MODELS_DIR, "tts", "k2-fsa--OmniVoice")
    tts_models: dict = {}
    if os.path.isdir(tts_local):
        sz = sum(
            os.path.getsize(os.path.join(dp, f))
            for dp, _, files in os.walk(tts_local)
            for f in files
        )
        tts_models["omnivoice"] = {
            "name": "OmniVoice",
            "type": "omnivoice",
            "local_path": tts_local,
            "size_bytes": sz,
            "source": "hf:k2-fsa/OmniVoice",
        }

    # 偵測現有 Z-Image（任意 .safetensors）
    image_models: dict = {}
    if os.path.isdir(_MODELS_DIR):
        for fname in os.listdir(_MODELS_DIR):
            if fname.endswith(".safetensors"):
                path = os.path.join(_MODELS_DIR, fname)
                size = os.path.getsize(path)
                mid = os.path.splitext(fname)[0]
                image_models[mid] = {
                    "name": fname,
                    "type": "diffusers",
                    "local_path": path,
                    "size_bytes": size,
                    "source": "",
                }

    reg = {
        "tts": {
            "active": "omnivoice" if tts_models else None,
            "models": tts_models,
        },
        "image": {
            "active": next(iter(image_models), None),
            "models": image_models,
        },
        "llm": {
            "chat": chat_id,
            "analysis": analysis_id,
            "models": gguf_models,
        },
    }
    _save(reg)
    print(f"[registry] 初始化登錄檔：{len(tts_models)} TTS / "
          f"{len(image_models)} Image / {len(gguf_models)} LLM")
    return reg


# ─── 公開 API ─────────────────────────────────────────────────────────────────

def get_registry() -> dict:
    return _load()


def get_model(category: str, model_id: str) -> dict | None:
    return _load().get(category, {}).get("models", {}).get(model_id)


def get_active_model(category: str, role: str = "default") -> dict | None:
    reg = _load()
    cat = reg.get(category, {})
    if category == "llm":
        mid = cat.get(role)   # role = "chat" | "analysis"
    else:
        mid = cat.get("active")
    if not mid:
        return None
    info = cat.get("models", {}).get(mid)
    if info:
        info = dict(info)
        info["_id"] = mid
    return info


def activate_model(category: str, model_id: str, role: str = "default") -> None:
    reg = _load()
    cat = reg.setdefault(category, {})
    if model_id not in cat.get("models", {}):
        raise KeyError(f"模型 {model_id!r} 不在 {category} 登錄檔中")
    if category == "llm":
        cat[role] = model_id
    else:
        cat["active"] = model_id
    _save(reg)


def register_model(category: str, model_id: str, info: dict) -> None:
    reg = _load()
    reg.setdefault(category, {}).setdefault("models", {})[model_id] = info
    _save(reg)
    print(f"[registry] 已登錄 {category}/{model_id}")


def delete_model_entry(category: str, model_id: str, remove_files: bool = True) -> dict:
    """從登錄檔移除模型，並選擇性刪除本地檔案。回傳被刪除的 info。"""
    reg = _load()
    models = reg.get(category, {}).get("models", {})
    info = models.pop(model_id, {})

    # 若刪除的是 active，改選第一個剩餘模型
    cat = reg.get(category, {})
    if category == "llm":
        for role in ("chat", "analysis"):
            if cat.get(role) == model_id:
                cat[role] = next(iter(models), None)
    else:
        if cat.get("active") == model_id:
            cat["active"] = next(iter(models), None)

    _save(reg)

    if remove_files and info.get("local_path"):
        lp = info["local_path"]
        if os.path.isdir(lp):
            shutil.rmtree(lp, ignore_errors=True)
            print(f"[registry] 已刪除目錄 {lp}")
        elif os.path.isfile(lp):
            try:
                os.remove(lp)
                print(f"[registry] 已刪除檔案 {lp}")
            except Exception as e:
                print(f"[registry] 刪除失敗 {lp}: {e}")

    return info


def get_llm_path(role: str) -> str | None:
    """回傳 LLM 模型的本地路徑（chat 或 analysis）。"""
    info = get_active_model("llm", role)
    return info.get("local_path") if info else None


def get_llm_ctx(role: str) -> int:
    """回傳 LLM ctx size，預設 chat=2048, analysis=65536。"""
    info = get_active_model("llm", role)
    if not info:
        return 65536 if role == "analysis" else 2048
    return info.get("ctx_size", 65536 if role == "analysis" else 2048)


def patch_model_info(category: str, model_id: str, patch: dict) -> dict:
    """更新 registry 中某個模型的欄位（只改傳入的 key）。回傳更新後的 info。"""
    reg = _load()
    models = reg.get(category, {}).get("models", {})
    if model_id not in models:
        raise KeyError(f"模型 {model_id!r} 不在 {category} 登錄檔中")
    for k, v in patch.items():
        if v is None:
            models[model_id].pop(k, None)
        else:
            models[model_id][k] = v
    _save(reg)
    return models[model_id]


def scan_local_models() -> int:
    """掃描 models/{tts,image,llm}/ 子目錄，自動登錄尚未在 registry 的模型檔案。
    回傳新增模型數量。"""
    reg = _load()
    added = 0

    # TTS：OmniVoice 為 snapshot 目錄（非單檔），偵測 config.json + model.safetensors
    tts_local = os.path.join(_MODELS_DIR, "tts", "k2-fsa--OmniVoice")
    if os.path.exists(os.path.join(tts_local, "config.json")) \
       and os.path.exists(os.path.join(tts_local, "model.safetensors")):
        tts_models = reg.setdefault("tts", {}).setdefault("models", {})
        if "omnivoice" not in tts_models:
            sz = sum(
                os.path.getsize(os.path.join(dp, f))
                for dp, _, files in os.walk(tts_local)
                for f in files
            )
            tts_models["omnivoice"] = {
                "name": "OmniVoice",
                "type": "omnivoice",
                "local_path": tts_local,
                "size_bytes": sz,
                "source": "hf:k2-fsa/OmniVoice",
            }
            # 首次登錄即設為 active
            if not reg["tts"].get("active"):
                reg["tts"]["active"] = "omnivoice"
            added += 1
            print("[registry] 自動登錄 TTS 模型: OmniVoice")

    image_dir = os.path.join(_MODELS_DIR, "image")
    if os.path.isdir(image_dir):
        for fname in os.listdir(image_dir):
            if not fname.endswith(".safetensors"):
                continue
            path = os.path.join(image_dir, fname)
            if not os.path.isfile(path):
                continue
            mid = fname.lower().replace(" ", "_")
            if mid not in reg.get("image", {}).get("models", {}):
                size = os.path.getsize(path)
                reg.setdefault("image", {}).setdefault("models", {})[mid] = {
                    "name": fname,
                    "type": "diffusers",
                    "local_path": path,
                    "size_bytes": size,
                    "source": "",
                }
                added += 1
                print(f"[registry] 自動登錄圖像模型: {fname}")

    llm_dir = os.path.join(_MODELS_DIR, "llm")
    if os.path.isdir(llm_dir):
        for fname in os.listdir(llm_dir):
            if not fname.endswith(".gguf"):
                continue
            path = os.path.join(llm_dir, fname)
            if not os.path.isfile(path):
                continue
            mid = os.path.splitext(fname)[0].lower().replace(" ", "_")
            if mid not in reg.get("llm", {}).get("models", {}):
                size = os.path.getsize(path)
                reg.setdefault("llm", {}).setdefault("models", {})[mid] = {
                    "name": fname,
                    "type": "gguf",
                    "local_path": path,
                    "size_bytes": size,
                    "source": "",
                }
                added += 1
                print(f"[registry] 自動登錄 LLM 模型: {fname}")

    if added > 0:
        _save(reg)
    return added


def is_model_available(info: dict) -> bool:
    """檢查模型檔案/目錄是否實際存在於磁碟。

    registry 可能登錄了「曾新增但未下載」的項目（例如只填了 source URL、
    size_bytes=0 的條目），這類在 UI 上不應顯示為可用、也不可被切換。
    """
    lp = info.get("local_path", "")
    return bool(lp) and os.path.exists(lp)


def verify_registry() -> dict:
    """回傳各類別中「有登錄、但檔案不存在」的模型 id 清單。"""
    reg = _load()
    missing: dict = {}
    for cat in ("tts", "image", "llm"):
        models = reg.get(cat, {}).get("models", {})
        miss = [mid for mid, info in models.items() if not is_model_available(info)]
        if miss:
            missing[cat] = miss
    return missing


def _is_orphan(info: dict) -> bool:
    """孤兒條目：檔案不存在「且」沒有下載來源（無法復原）。

    缺檔但帶 source（下載連結）的屬「預設/已知來源」，保留並在 UI 提供下載，不算孤兒。
    """
    return not is_model_available(info) and not info.get("source")


def normalize_active_pointers() -> bool:
    """將指向「孤兒條目」的 active 指標改指到該類別第一個可用模型（無則 None）。

    缺檔但有下載來源的「預設」保留不動（例如 llm.analysis = 未下載但可下載的 AEON），
    讓使用者仍能看到並下載它。回傳是否有變動。
    """
    reg = _load()
    changed = False

    for cat in ("image", "tts"):
        c = reg.get(cat, {})
        models = c.get("models", {})
        mid = c.get("active")
        if mid and _is_orphan(models.get(mid, {})):
            avail = next((k for k, v in models.items() if is_model_available(v)), None)
            print(f"[registry] {cat}.active {mid!r} 為孤兒條目 → 改為 {avail!r}")
            c["active"] = avail
            changed = True

    lc = reg.get("llm", {})
    lmodels = lc.get("models", {})
    for role in ("chat", "analysis"):
        mid = lc.get(role)
        if mid and _is_orphan(lmodels.get(mid, {})):
            avail = next((k for k, v in lmodels.items() if is_model_available(v)), None)
            print(f"[registry] llm.{role} {mid!r} 為孤兒條目 → 改為 {avail!r}")
            lc[role] = avail
            changed = True

    if changed:
        _save(reg)
    return changed


def ensure_initialized() -> None:
    """確保登錄檔存在，並掃描本機模型（main.py lifespan 呼叫）。"""
    _load()
    scan_local_models()

    # 啟動前檢查：登錄但檔案不存在的模型，並把指向它們的 active 指標導正到可用模型。
    missing = verify_registry()
    if missing:
        for cat, ids in missing.items():
            print(f"[registry] ⚠ {cat} 已登錄但檔案不存在（UI 將不顯示）: {ids}")
        normalize_active_pointers()
