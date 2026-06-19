"""
模型載入 / 卸載 / 架構偵測，以及同步生成核心 (_generate_sync)。
全局 _pipe / _loaded_style 狀態的唯一所在。
"""
import asyncio
import io
import logging
import os
from typing import Callable, Literal

from PIL import Image

from services.illustration.settings import get_settings
from config import MODELS_DIR

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, str], None]

_BASE_DIR = str(MODELS_DIR)

# ─── 全局 pipe 狀態 ───────────────────────────────────────────────────────────

_pipe                     = None
_loaded_style: str | None = None
_pipe_lock                = asyncio.Lock()


def _find_model_entry(style: Literal["anime", "real"]) -> dict | None:
    try:
        from services.model_registry import get_registry
        for _mid, info in get_registry().get("image", {}).get("models", {}).items():
            if info.get("style") == style and info.get("type", "diffusers") == "diffusers":
                path = info.get("local_path", "")
                if path and os.path.isfile(path):
                    return info
    except Exception:
        pass
    return None


# ─── 架構偵測 ─────────────────────────────────────────────────────────────────

def _detect_architecture(model_path: str) -> str:
    try:
        from safetensors import safe_open
        with safe_open(model_path, framework="pt", device="cpu") as f:
            keys = " ".join(list(f.keys())[:12])
        if "cap_embedder" in keys or "context_refiner" in keys or "cap_pad_token" in keys:
            return "zimage"
        if "adaln_modulation_cross_attn" in keys or (
            "model.diffusion_model.blocks" in keys and "cross_attn" in keys
        ):
            return "wan"
    except Exception:
        pass
    return "sdxl"


def _active_model_arch(style: str) -> str:
    from diffusers import WanPipeline
    if _pipe is not None and _loaded_style == style:
        if getattr(_pipe, "_is_zimage", False):
            return "zimage"
        if isinstance(_pipe, WanPipeline):
            return "wan"
        return "sdxl"
    entry = _find_model_entry(style)
    if not entry or not entry.get("local_path"):
        return "sdxl"
    return _detect_architecture(entry["local_path"])


# ─── SDXL / SD1.5 ────────────────────────────────────────────────────────────

def _load_sdxl_pipe_sync(entry: dict, model_path: str):
    import torch
    from diffusers import StableDiffusionXLPipeline, DPMSolverMultistepScheduler

    kwargs: dict = {"torch_dtype": torch.float16, "use_safetensors": True}

    vae_path = entry.get("vae_path", "")
    if vae_path and os.path.isfile(vae_path):
        from diffusers import AutoencoderKL
        logger.info("載入 VAE: %s", os.path.basename(vae_path))
        try:
            kwargs["vae"] = AutoencoderKL.from_single_file(
                vae_path, torch_dtype=torch.float16
            ).to("cuda")
        except Exception as e:
            logger.warning("VAE 失敗，使用內建: %s", e)

    pipe = StableDiffusionXLPipeline.from_single_file(model_path, **kwargs)
    pipe.scheduler = DPMSolverMultistepScheduler.from_config(
        pipe.scheduler.config,
        use_karras_sigmas=True,
        algorithm_type="dpmsolver++",
    )
    pipe.to("cuda")

    _pred_type = getattr(pipe.scheduler.config, "prediction_type", "epsilon")
    pipe._is_vpred = (_pred_type == "v_prediction")
    pipe.vae.enable_slicing()

    print(f"[illustration] SDXL 模型就緒  prediction_type={_pred_type}  sampler=DPM++2M-Karras")

    # ── Textual Inversion embeddings（lazypos / lazyneg / lazyhand）──
    # 在 IP-Adapter 前載入，避免 tokenizer 詞表 ID 衝突
    _emb_dir = os.path.join(_BASE_DIR, "embeddings")
    _emb_tokens: list[str] = []
    for _token in ("lazypos", "lazyneg", "lazyhand"):
        _emb_path = os.path.join(_emb_dir, f"{_token}.safetensors")
        if not os.path.isfile(_emb_path):
            continue
        try:
            from safetensors.torch import load_file as _load_st
            _state = _load_st(_emb_path)
            if "clip_l" in _state and "clip_g" in _state:
                pipe.load_textual_inversion(
                    _state["clip_l"], token=_token,
                    text_encoder=pipe.text_encoder,
                    tokenizer=pipe.tokenizer,
                )
                pipe.load_textual_inversion(
                    _state["clip_g"], token=_token,
                    text_encoder=pipe.text_encoder_2,
                    tokenizer=pipe.tokenizer_2,
                )
            else:
                pipe.load_textual_inversion(_emb_path, token=_token)
            _emb_tokens.append(_token)
            logger.info("Embedding 已載入: %s (SDXL dual)", _token)
        except Exception as _e:
            logger.warning("Embedding 載入失敗 %s: %s", _token, _e)
    pipe._loaded_embeddings = set(_emb_tokens)

    # ── IP-Adapter FaceID (non-Plus) ─────────────────────────────────────
    pipe._ip_adapter_loaded = False
    pipe._ip_adapter_mode = "none"
    # ip-adapter-faceid_sdxl.bin (非 Plus)：只使用 ArcFace 512-dim embedding，
    # 不需要 CLIP ViT-H image_encoder_folder，與我們的 extract_face 輸出格式完全相符。
    # Plus v2 需要額外的 image encoder 才能載入，但我們僅傳 ArcFace embedding，
    # 使用 Plus v2 反而會因 image_encoder_folder=None 觸發 TypeError。
    _IPA_WEIGHT = "ip-adapter-faceid_sdxl.bin"
    _IPA_LOCAL  = os.path.join(_BASE_DIR, "ip_adapters", _IPA_WEIGHT)
    try:
        if os.path.isfile(_IPA_LOCAL):
            pipe.load_ip_adapter(
                os.path.dirname(_IPA_LOCAL), subfolder="", weight_name=_IPA_WEIGHT,
                image_encoder_folder=None,   # FaceID 不需要 CLIP image encoder
            )
        else:
            pipe.load_ip_adapter(
                "h94/IP-Adapter-FaceID", subfolder="", weight_name=_IPA_WEIGHT,
                image_encoder_folder=None,
            )
        pipe.set_ip_adapter_scale(0.0)
        pipe._ip_adapter_loaded = True
        pipe._ip_adapter_mode = "faceid"
        print(f"[illustration] IP-Adapter FaceID SDXL 已載入 ({_IPA_WEIGHT})")
    except Exception as e:
        print(f"[illustration] FaceID IP-Adapter 未載入: {e}")

    # ── LoRA 載入 ─────────────────────────────────────────────────────────
    # FaceID 專屬 LoRA（與 FaceID adapter 配套，提升身分一致性）
    _FACEID_LORA = os.path.join(_BASE_DIR, "ip_adapters", "ip-adapter-faceid_sdxl_lora.safetensors")
    _lora_names: list[str]  = []
    _lora_weights: list[float] = []
    if os.path.isfile(_FACEID_LORA) and pipe._ip_adapter_loaded:
        try:
            pipe.load_lora_weights(_FACEID_LORA, adapter_name="faceid_lora")
            _lora_names.append("faceid_lora")
            _lora_weights.append(1.0)
            logger.info("FaceID LoRA 已載入")
        except Exception as _e:
            logger.warning("FaceID LoRA 載入失敗: %s", _e)

    # 使用者選擇的 LoRA
    try:
        _s = get_settings()
        _loras_dir = os.path.join(_BASE_DIR, "loras")
        for _entry in _s.active_loras:
            if not _entry.enabled:
                continue
            _lp = os.path.join(_loras_dir, _entry.filename)
            if not os.path.isfile(_lp):
                logger.warning("LoRA 不存在，跳過: %s", _entry.filename)
                continue
            _aname = os.path.splitext(_entry.filename)[0][:40]
            try:
                pipe.load_lora_weights(_lp, adapter_name=_aname)
                _lora_names.append(_aname)
                _lora_weights.append(float(_entry.weight))
                logger.info("LoRA 已載入: %s (weight=%.2f)", _entry.filename, _entry.weight)
            except Exception as _e:
                logger.warning("LoRA 載入失敗 %s: %s", _entry.filename, _e)
    except Exception as _e:
        logger.warning("LoRA 設定讀取失敗: %s", _e)

    if _lora_names:
        try:
            pipe.set_adapters(_lora_names, adapter_weights=_lora_weights)
        except Exception as _e:
            logger.warning("set_adapters 失敗，改用 fuse_lora: %s", _e)
            try:
                pipe.fuse_lora()
            except Exception:
                pass
    pipe._loaded_lora_names = _lora_names

    # IP-Adapter FaceID 的 .bin（image projection encoder_hid_proj + to_k_ip/to_v_ip）
    # 及部分 LoRA 權重以 fp32 載入，與 fp16 UNet 不相容，forward 會丟
    # "mat1 and mat2 must have the same dtype (Half vs Float)"。統一 cast 回 fp16。
    try:
        pipe.unet.to(dtype=torch.float16)
    except Exception as _e:
        logger.warning("UNet fp16 re-cast 失敗: %s", _e)

    return pipe


# ─── Z-Image Turbo ───────────────────────────────────────────────────────────

_ZIMAGE_HF_REPO = "Tongyi-MAI/Z-Image-Turbo"
_ZIMAGE_CACHE   = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", ".zimage_cache")
)


def _ensure_zimage_components() -> None:
    te_config = os.path.join(_ZIMAGE_CACHE, "text_encoder", "config.json")
    if os.path.exists(te_config):
        return

    logger.info("Downloading Z-Image components from %s …", _ZIMAGE_HF_REPO)
    from huggingface_hub import snapshot_download
    snapshot_download(
        repo_id=_ZIMAGE_HF_REPO,
        local_dir=_ZIMAGE_CACHE,
        local_dir_use_symlinks=False,
        ignore_patterns=["transformer/*", "*.md", "assets/*"],
    )
    logger.info("Z-Image components downloaded.")


def _load_zimage_pipe_sync(entry: dict, model_path: str):
    import torch
    from diffusers import ZImagePipeline, AutoencoderKL
    from transformers import Qwen3Model, Qwen2Tokenizer

    name_lower = entry.get("name", "").lower()
    is_turbo = "turbo" in name_lower

    _ensure_zimage_components()

    te_path  = os.path.join(_ZIMAGE_CACHE, "text_encoder")
    tok_path = os.path.join(_ZIMAGE_CACHE, "tokenizer")
    vae_path = os.path.join(_ZIMAGE_CACHE, "vae")

    logger.info("Loading Qwen3 text encoder from cache …")
    text_encoder = Qwen3Model.from_pretrained(te_path, torch_dtype=torch.bfloat16)
    tokenizer    = Qwen2Tokenizer.from_pretrained(tok_path)

    vae = AutoencoderKL.from_pretrained(vae_path, torch_dtype=torch.float16)

    from diffusers.models import ZImageTransformer2DModel
    transformer = ZImageTransformer2DModel.from_single_file(
        model_path, torch_dtype=torch.bfloat16
    )

    from diffusers import FlowMatchEulerDiscreteScheduler
    scheduler = FlowMatchEulerDiscreteScheduler()

    pipe = ZImagePipeline(
        text_encoder=text_encoder,
        tokenizer=tokenizer,
        vae=vae,
        transformer=transformer,
        scheduler=scheduler,
    )
    pipe.to("cuda")
    pipe.vae.enable_slicing()
    pipe._is_zimage = True
    pipe._is_vpred  = False
    pipe._ip_adapter_loaded = False
    pipe._ip_adapter_mode   = "none"
    pipe._loaded_embeddings = set()
    turbo_label = " (Turbo)" if is_turbo else ""
    print(f"[illustration] Z-Image{turbo_label} 模型就緒")
    return pipe


# ─── Wan2.1 ──────────────────────────────────────────────────────────────────

def _load_wan_pipe_sync(entry: dict, model_path: str):
    import torch
    from diffusers import WanPipeline, AutoencoderKLWan, UniPCMultistepScheduler
    from transformers import UMT5EncoderModel, AutoTokenizer
    from diffusers.models import WanTransformer3DModel

    logger.info("偵測到 Wan 架構，切換載入模式")

    model_dir = os.path.dirname(model_path)

    te_path = entry.get("te_path") or os.path.join(model_dir, "text_encoder")
    tokenizer    = AutoTokenizer.from_pretrained(te_path)
    text_encoder = UMT5EncoderModel.from_pretrained(te_path, torch_dtype=torch.bfloat16)

    vae_path = entry.get("vae_path") or os.path.join(model_dir, "vae")
    vae = AutoencoderKLWan.from_pretrained(vae_path, torch_dtype=torch.float32)

    transformer = WanTransformer3DModel.from_single_file(
        model_path, torch_dtype=torch.bfloat16
    )

    pipe = WanPipeline(
        tokenizer=tokenizer,
        text_encoder=text_encoder,
        vae=vae,
        transformer=transformer,
        scheduler=UniPCMultistepScheduler(),
    )
    pipe.to("cuda")
    pipe._ip_adapter_loaded = False
    pipe._ip_adapter_mode   = "none"
    print("[illustration] Wan2.1 模型就緒")
    return pipe


# ─── 非同步 pipe 管理 ─────────────────────────────────────────────────────────

async def ensure_pipe(style: Literal["anime", "real"] = "anime"):
    global _pipe, _loaded_style
    async with _pipe_lock:
        if _pipe is not None and _loaded_style == style:
            return _pipe
        loop = asyncio.get_event_loop()
        entry = _find_model_entry(style)
        if not entry:
            raise RuntimeError(f"找不到 {style} 風格的本地模型，請先在 ModelManager 下載")
        model_path = entry["local_path"]
        arch = _detect_architecture(model_path)
        if arch == "zimage":
            _pipe = await loop.run_in_executor(None, _load_zimage_pipe_sync, entry, model_path)
        elif arch == "wan":
            _pipe = await loop.run_in_executor(None, _load_wan_pipe_sync, entry, model_path)
        else:
            _pipe = await loop.run_in_executor(None, _load_sdxl_pipe_sync, entry, model_path)
        _loaded_style = style
        return _pipe


async def unload_pipe():
    global _pipe, _loaded_style
    async with _pipe_lock:
        if _pipe is None:
            return
        import torch
        import gc
        _pipe = None
        _loaded_style = None
        gc.collect()
        torch.cuda.empty_cache()
        logger.info("模型已卸載，VRAM 已釋放")


# ─── 缺漏的公開符號（illustration_engine.py / generation.py 直接 import）────

_WAN_BASE  = os.path.join(_BASE_DIR, "wan")
_WAN_CACHE = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", ".wan_cache")
)


def _load_pipe_sync(entry: dict, model_path: str, arch: str):
    if arch == "zimage":
        return _load_zimage_pipe_sync(entry, model_path)
    if arch == "wan":
        return _load_wan_pipe_sync(entry, model_path)
    return _load_sdxl_pipe_sync(entry, model_path)


def _unload_pipe_sync():
    global _pipe, _loaded_style
    import torch
    import gc
    _pipe = None
    _loaded_style = None
    gc.collect()
    torch.cuda.empty_cache()
    logger.info("模型已卸載（sync）")


async def _get_pipe(style: Literal["anime", "real"] = "anime"):
    return await ensure_pipe(style)


def _resolve_effective_params(pipe, s):
    is_turbo  = getattr(pipe, "_is_turbo", False)
    is_zimage = getattr(pipe, "_is_zimage", False)
    if is_turbo or is_zimage:
        return 8, 1.5
    return s.steps, s.guidance_scale


# ─── BREAK 編碼（diffusers 不原生支援 A1111 的 BREAK 關鍵字）─────────────────

def _encode_with_break(pipe, text: str, device: str, clip_skip: int = 2, min_segments: int = 1) -> tuple:
    """
    將 prompt 按 BREAK 分段，每段在獨立的 77-token 窗口內編碼，
    然後沿 seq 維度串接 hidden states，等效於 A1111 的長 prompt 支援。
    回傳 (prompt_embeds (1, 77*n, 2048), pooled_prompt_embeds (1, 1280))。

    min_segments：用空段補齊到指定段數（A1111 同款空窗口 padding）。SDXL 要求
    正/負向 prompt_embeds 的 seq 維度一致，故正負向須編成相同段數，否則
    check_inputs 會丟 shape mismatch。
    """
    import torch

    segments = [s.strip() for s in text.split("BREAK") if s.strip()]
    if not segments:
        segments = [""]
    if len(segments) < min_segments:
        segments = segments + [""] * (min_segments - len(segments))

    all_e1: list = []
    all_e2: list = []
    pooled = None

    for seg in segments:
        # ── CLIP-L ────────────────────────────────────────────────────────
        ids1 = pipe.tokenizer(
            seg,
            max_length=pipe.tokenizer.model_max_length,
            padding="max_length",
            truncation=True,
            return_tensors="pt",
        ).input_ids.to(device)
        with torch.no_grad():
            out1 = pipe.text_encoder(ids1, output_hidden_states=True)
        hs1 = out1.hidden_states
        idx1 = -(clip_skip + 1) if len(hs1) > clip_skip + 1 else -2
        all_e1.append(hs1[idx1])   # (1, 77, 768)

        # ── CLIP-G ────────────────────────────────────────────────────────
        ids2 = pipe.tokenizer_2(
            seg,
            max_length=pipe.tokenizer_2.model_max_length,
            padding="max_length",
            truncation=True,
            return_tensors="pt",
        ).input_ids.to(device)
        with torch.no_grad():
            out2 = pipe.text_encoder_2(ids2, output_hidden_states=True)
        all_e2.append(out2.hidden_states[-2])   # (1, 77, 1280)
        if pooled is None:
            pooled = out2[0]   # (1, 1280) — 只取第一段的 pooled

    e1 = torch.cat(all_e1, dim=1)              # (1, 77*n, 768)
    e2 = torch.cat(all_e2, dim=1)              # (1, 77*n, 1280)
    prompt_embeds = torch.cat([e1, e2], dim=-1) # (1, 77*n, 2048)

    # text encoder 可能是 fp32，但 UNet 是 fp16；須 cast 到 UNet dtype，
    # 否則送進 UNet 會 "mat1 and mat2 must have the same dtype (Half vs Float)"。
    # diffusers 原生 encode_prompt 也會做這步。
    _dtype = pipe.unet.dtype
    prompt_embeds = prompt_embeds.to(dtype=_dtype)
    pooled = pooled.to(dtype=_dtype)

    return prompt_embeds, pooled


# ─── 核心同步生成 _generate_sync ─────────────────────────────────────────────

IP_END_FRAC = 0.75  # IP-Adapter 在前 75% steps 後停止，讓後段自由收斂


def _generate_sync(
    pipe,
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    seed: int,
    guidance_scale: float,
    progress_cb: ProgressCallback | None = None,
    ip_adapter_image=None,
    ip_adapter_scale: float = 0.5,
    prompt_2: "str | None" = None,
) -> Image.Image:
    import torch

    s = get_settings()

    is_zimage = getattr(pipe, "_is_zimage", False)
    try:
        from diffusers import WanPipeline
        is_wan = isinstance(pipe, WanPipeline)
    except Exception:
        is_wan = False

    generator = torch.Generator("cuda").manual_seed(seed)

    ip_adapter_ready = getattr(pipe, "_ip_adapter_loaded", False) and not is_wan and not is_zimage
    use_ip = ip_adapter_image is not None and ip_adapter_ready

    ip_embeds = None
    if use_ip:
        import numpy as np
        face_emb = ip_adapter_image
        if isinstance(face_emb, np.ndarray):
            # diffusers 在 CFG（guidance_scale>1）下會對傳入的 image_embeds 做
            # chunk(2) 拆成 (negative, positive)，故 batch 維度必須為 2，否則丟
            # 「not enough values to unpack (expected 2, got 1)」。負向用零向量。
            pos = torch.from_numpy(face_emb).float().reshape(1, 1, 512)
            neg = torch.zeros_like(pos)
            ip_embeds = torch.cat([neg, pos], dim=0).to("cuda", dtype=torch.float16)  # (2,1,512)
    elif ip_adapter_ready:
        # 一旦 load_ip_adapter() 載入過，UNet 的 encoder_hid_dim_type 就固定為
        # 'ip_image_proj'，往後每次 forward 都「結構性」要求 added_cond_kwargs
        # 帶 image_embeds——即使這次生成不想用 FaceID（如角色設定圖無參考圖）也
        # 必須給，否則 diffusers 直接丟例外。scale 維持 0 即可讓它不產生實際影響。
        # batch=2 同樣是為了滿足 CFG 下的 chunk(2)。
        ip_embeds = torch.zeros((2, 1, 512), device="cuda", dtype=torch.float16)

    # 單一來源覆寫實際使用的步數／CFG（turbo/zimage 用 8步+1.5，其餘沿用 settings）；
    # 之前只在 meta 算過一次、從未套用到實際生成，Z-Image 因此一直跑 30 步 + CFG 6.0
    num_steps, guidance_scale = _resolve_effective_params(pipe, s)
    clip_skip  = 2  # NoobAI / Illustrious XL 建議值，不放進 settings

    total_steps = [0]

    def _step_cb(p, i, t, kwargs):
        total_steps[0] = i + 1
        frac = (i + 1) / num_steps
        if use_ip and frac >= IP_END_FRAC:
            pipe.set_ip_adapter_scale(0.0)
        if progress_cb:
            pct = 10 + int(frac * 82)
            progress_cb(min(pct, 92), f"擴散 step {i+1}/{num_steps}")
        return kwargs

    if ip_adapter_ready:
        pipe.set_ip_adapter_scale(ip_adapter_scale if use_ip else 0.0)

    kwargs: dict = {
        "width":               width,
        "height":              height,
        "num_inference_steps": num_steps,
        "guidance_scale":      guidance_scale,
        "generator":           generator,
        "callback_on_step_end": _step_cb,
    }

    # BREAK 分段編碼：各段各自在 77-token 視窗內編碼，不截斷
    _use_break = "BREAK" in prompt and not is_wan and not is_zimage
    if _use_break:
        try:
            _dev = str(next(pipe.text_encoder.parameters()).device)
            # 正/負向須編成相同段數（SDXL 要求 pos/neg embeds seq 維度一致）
            _pos_n = len([s for s in prompt.split("BREAK") if s.strip()]) or 1
            _neg_n = len([s for s in negative_prompt.split("BREAK") if s.strip()]) or 1
            _tgt = max(_pos_n, _neg_n)
            _p_emb, _p_pool = _encode_with_break(pipe, prompt, _dev, clip_skip=clip_skip, min_segments=_tgt)
            _n_emb, _n_pool = _encode_with_break(pipe, negative_prompt, _dev, clip_skip=clip_skip, min_segments=_tgt)
            kwargs["prompt_embeds"]                 = _p_emb
            kwargs["negative_prompt_embeds"]        = _n_emb
            kwargs["pooled_prompt_embeds"]          = _p_pool
            kwargs["negative_pooled_prompt_embeds"] = _n_pool
            logger.debug(
                "BREAK 編碼完成：%d 段，embeds shape=%s",
                prompt.count("BREAK") + 1, tuple(_p_emb.shape),
            )
        except Exception as _e:
            logger.warning("BREAK encoding 失敗，回退普通 prompt: %s", _e)
            _use_break = False

    if not _use_break:
        # 非 SDXL（zimage/wan）不走分段編碼；把分段標記還原成逗號，
        # 否則 "BREAK" 會被當成字面 token 編進 prompt。
        if "BREAK" in prompt:
            prompt = ", ".join(s.strip() for s in prompt.split("BREAK") if s.strip())
        kwargs["prompt"] = prompt
        if prompt_2 is not None and not is_wan and not is_zimage:
            kwargs["prompt_2"] = prompt_2
        if not is_zimage:
            kwargs["negative_prompt"] = negative_prompt
        if not is_wan and not is_zimage:
            kwargs["clip_skip"] = clip_skip

    if ip_embeds is not None:
        kwargs["ip_adapter_image_embeds"] = [ip_embeds]

    if is_wan:
        kwargs.pop("guidance_scale", None)
        kwargs.pop("clip_skip", None)
        kwargs["num_frames"] = 1

    if ip_adapter_ready:
        # 前一次 hires/adetailer 的 from_pipe() 可能已把共用 unet 的 proj 升回 fp32
        _ensure_ip_proj_dtype(pipe)

    if progress_cb:
        progress_cb(10, "開始擴散")

    out = pipe(**kwargs)

    if use_ip:
        pipe.set_ip_adapter_scale(0.0)

    if is_wan:
        frames = out.frames
        if hasattr(frames, "__len__") and len(frames) > 0:
            frame = frames[0]
            if hasattr(frame, "__len__") and len(frame) > 0:
                return frame[0]
            return frame
        return out.images[0] if hasattr(out, "images") else frames

    return out.images[0]


def _ensure_ip_proj_dtype(pipe) -> None:
    """StableDiffusionXLImg2Img/Inpaint.from_pipe()（hires-fix / ADetailer）會把
    「共用的同一顆 unet」整顆升回 fp32——連帶污染原 pipe（同一物件）。之後 forward
    時 fp16 的 IP-Adapter image_embeds × fp32 權重會丟
    'mat1 and mat2 must have the same dtype (Half vs Float)'。
    每次用到 IP-Adapter 前把 unet 強制 cast 回 fp16（用顯式 float16，不可用
    pipe.unet.dtype——from_pipe 後它已是 fp32，cast 會變 no-op）。"""
    import torch
    try:
        pipe.unet.to(dtype=torch.float16)
        # ModelMixin.to 可能略過 keep_in_fp32 模組；image projection 直接顯式再補一次
        ehp = getattr(pipe.unet, "encoder_hid_proj", None)
        if ehp is not None:
            ehp.to(dtype=torch.float16)
    except Exception as _e:
        logger.warning("unet/encoder_hid_proj dtype re-cast 失敗: %s", _e)


def _ip_adapter_passthrough_kwargs(pipe) -> dict:
    """hires-fix / ADetailer 透過 from_pipe() 共用同一個 UNet 物件；一旦該 UNet
    載入過 IP-Adapter，encoder_hid_dim_type 就固定為 'ip_image_proj'，往後任何
    用這顆 UNet 的 pipeline（包括 img2img / inpaint）forward 都結構性要求
    image_embeds，否則 diffusers 直接丟例外。這兩段精修不使用 FaceID，給零向量
    + scale 0 即可滿足簽名又不影響輸出。"""
    import torch
    if not getattr(pipe, "_ip_adapter_loaded", False):
        return {}
    pipe.set_ip_adapter_scale(0.0)
    _ensure_ip_proj_dtype(pipe)   # from_pipe() 會把 proj 升回 fp32，補回 fp16
    # batch=2：CFG 下 diffusers 會 chunk(2) 成 (negative, positive)，見 _generate_sync 註解。
    zeros = torch.zeros((2, 1, 512), device="cuda", dtype=torch.float16)
    return {"ip_adapter_image_embeds": [zeros]}


# ─── Hires Fix ────────────────────────────────────────────────────────────────

def _hires_fix_sync(
    pipe,
    image: Image.Image,
    prompt: str,
    negative_prompt: str,
    seed: int,
    scale: float = 1.5,
    denoise: float = 0.4,
) -> Image.Image:
    """Lanczos 上採樣 + img2img 細化（SDXL only）。"""
    import torch
    from diffusers import StableDiffusionXLImg2ImgPipeline

    w, h   = image.size
    new_w  = int(w * scale)
    new_h  = int(h * scale)
    up     = image.resize((new_w, new_h), Image.LANCZOS)

    # hires fix 為 img2img，構圖已定；只用第一 BREAK 段（品質+外觀）即可
    _prompt_hires = prompt.split("BREAK")[0].strip() if "BREAK" in prompt else prompt

    i2i = StableDiffusionXLImg2ImgPipeline.from_pipe(pipe)
    i2i.to(torch.float16)   # from_pipe 會把共用 pipe 升回 fp32，cast 回 fp16
    gen = torch.Generator("cuda").manual_seed(seed)
    out = i2i(
        prompt=_prompt_hires,
        negative_prompt=negative_prompt,
        image=up,
        strength=denoise,
        guidance_scale=7.0,
        num_inference_steps=20,
        generator=gen,
        clip_skip=2,
        **_ip_adapter_passthrough_kwargs(pipe),
    ).images[0]
    return out


# ─── ADetailer（inpainting 精修）─────────────────────────────────────────────

def _adetailer_sync(
    pipe,
    image: Image.Image,
    prompt: str,
    negative_prompt: str,
    seed: int,
    denoise: float = 0.4,
) -> Image.Image:
    """
    ADetailer 正確實作：偵測人臉 → 生成全尺寸 mask → inpainting 精修。
    與原版 ADetailer 相同流程：完整原圖 + mask 送進 inpaint pipeline，
    由 pipeline 自行處理邊界合成（padding_mask_crop），不需手動 crop/paste。
    """
    import numpy as np
    import torch
    from PIL import ImageFilter
    from diffusers import StableDiffusionXLInpaintPipeline

    try:
        from services.illustration.face_extractor import _get_app
        app = _get_app()
    except Exception as e:
        logger.warning("ADetailer: 無法載入 InsightFace，跳過: %s", e)
        return image

    img_rgb = image.convert("RGB")
    img_np  = np.array(img_rgb)

    faces = app.get(img_np)
    if not faces:
        try:
            app.det_model.det_thresh = 0.3
            faces = app.get(img_np)
        except Exception:
            pass

    if not faces:
        logger.debug("ADetailer: 未偵測到人臉，跳過")
        return image

    logger.info("ADetailer: 偵測到 %d 張人臉，開始 inpainting 精修", len(faces))

    w, h = image.size

    # adetailer 只精修人臉；取第一 BREAK 段（外觀 tags）加上臉部品質詞
    _prompt_base = prompt.split("BREAK")[0].strip() if "BREAK" in prompt else prompt
    face_prompt = (
        "score_9, score_8_up, detailed face, beautiful detailed eyes, "
        "symmetrical eyes, perfect eyes, clear pupils, shiny pupils, "
        "detailed iris, sparkling eyes, detailed skin, " + _prompt_base
    )
    face_neg = (
        "bad eyes, ugly eyes, asymmetrical eyes, unequal eyes, "
        "crossed eyes, lazy eye, blurry eyes, empty eyes, dead eyes, "
        "waterfall eyes, extra eyes, fused eyes, " + negative_prompt
    )

    inpaint = StableDiffusionXLInpaintPipeline.from_pipe(pipe)
    inpaint.to(torch.float16)   # from_pipe 會把共用 pipe 升回 fp32，cast 回 fp16
    result  = image.copy()

    for idx, face in enumerate(faces):
        bbox = face.bbox.astype(int)
        x1, y1, x2, y2 = bbox

        bw, bh = x2 - x1, y2 - y1
        pad_x, pad_y = int(bw * 0.30), int(bh * 0.30)
        cx1 = max(0, x1 - pad_x)
        cy1 = max(0, y1 - pad_y)
        cx2 = min(w, x2 + pad_x)
        cy2 = min(h, y2 + pad_y)

        mask = Image.new("L", (w, h), 0)
        mask.paste(255, [cx1, cy1, cx2, cy2])
        mask = mask.filter(ImageFilter.MaxFilter(size=15))
        mask = mask.filter(ImageFilter.GaussianBlur(radius=6))

        generator = torch.Generator("cuda").manual_seed(seed + idx)
        out = inpaint(
            prompt=face_prompt,
            negative_prompt=face_neg,
            image=result,
            mask_image=mask,
            strength=denoise,
            guidance_scale=7.0,
            num_inference_steps=28,
            generator=generator,
            clip_skip=2,
            padding_mask_crop=32,
            **_ip_adapter_passthrough_kwargs(pipe),
        ).images[0]
        result = out
        logger.debug("ADetailer: 第 %d 張臉精修完成", idx + 1)

    return result


# ─── 啟發式臉部精修（備用，無 InsightFace 時）────────────────────────────────

def _refine_face_sync(
    pipe,
    image: Image.Image,
    prompt: str,
    negative_prompt: str,
    seed: int,
    denoise: float = 0.45,
) -> Image.Image:
    """啟發式（上 1/3）臉部 crop → img2img → 羽化貼回（備用方案）。"""
    import torch
    import numpy as np
    from diffusers import StableDiffusionXLImg2ImgPipeline

    w, h = image.size
    face_h = int(h * 0.38)
    face_w = int(w * 0.65)
    x1 = (w - face_w) // 2
    y1 = 0
    x2 = x1 + face_w
    y2 = face_h

    face_crop = image.crop((x1, y1, x2, y2))
    target_w  = max(512, (face_w  // 64) * 64)
    target_h  = max(512, (face_h  // 64) * 64)
    face_resized = face_crop.resize((target_w, target_h), Image.LANCZOS)

    face_prompt = (
        "score_9, score_8_up, detailed face, beautiful detailed eyes, "
        "symmetrical eyes, " + prompt
    )
    face_neg = "bad eyes, ugly eyes, asymmetrical eyes, " + negative_prompt

    i2i = StableDiffusionXLImg2ImgPipeline.from_pipe(pipe)
    gen = torch.Generator("cuda").manual_seed(seed + 99)
    refined_resized = i2i(
        prompt=face_prompt,
        negative_prompt=face_neg,
        image=face_resized,
        strength=denoise,
        guidance_scale=7.5,
        num_inference_steps=20,
        generator=gen,
        clip_skip=2,
        **_ip_adapter_passthrough_kwargs(pipe),
    ).images[0]

    refined = refined_resized.resize((face_w, face_h), Image.LANCZOS)

    feather = min(30, face_w // 8, face_h // 8)
    mask_arr = np.ones((face_h, face_w), dtype=np.float32)
    for i in range(feather):
        a = i / feather
        mask_arr[i, :]           = np.minimum(mask_arr[i, :], a)
        mask_arr[face_h-1-i, :]  = np.minimum(mask_arr[face_h-1-i, :], a)
        mask_arr[:, i]           = np.minimum(mask_arr[:, i], a)
        mask_arr[:, face_w-1-i]  = np.minimum(mask_arr[:, face_w-1-i], a)
    mask = Image.fromarray((mask_arr * 255).astype(np.uint8))

    result = image.copy()
    result.paste(refined, (x1, y1), mask)
    return result


def _pil_to_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
