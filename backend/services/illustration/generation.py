"""
高階生成介面：generate_character_sheet / generate_portrait / generate_illustration。
依賴 settings.py、prompt_builder.py、pipelines.py。
"""
import asyncio
import logging
import os
from typing import Callable

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, str], None]

from services.illustration.settings import get_settings
from services.illustration.prompt_builder import (
    build_character_fragment, build_character_fragment_en,
    build_character_description_zimage,
    _expand_prompt, _infer_is_anime, character_seed_for,
    _build_negative_prompt, _build_negative_prompt_sheet,
)
from services.illustration.pipelines import (
    _get_pipe, _active_model_arch,
    _generate_sync, _hires_fix_sync, _adetailer_sync, _pil_to_bytes,
    _resolve_effective_params, _find_model_entry,
    _unload_pipe_sync, _pipe, _pipe_lock,
)
from services.illustration.refs import load_char_ref_image


# ─── 構圖標籤集（LLM 生成後需提前至 prompt 最前）────────────────────────────────
# CLIP-L 有效窗口 75 tokens；style_hint + char_tags 往往佔 60-80 tokens，
# 若構圖 tag 落在 75 之後，模型遵從力幾乎為零，導致無論場景文字是什麼都生出大頭照。
_COMPOSITION_KW = frozenset({
    "upper body", "medium shot", "full body", "wide shot",
    "cowboy shot", "half body", "bust shot",
    "from above", "from below", "dutch angle",
})


def _pop_composition(tags: str) -> tuple[str, str]:
    """從 tag 串中取出第一個構圖 tag，回傳 (構圖tag, 剩餘tags)。找不到則 comp=''。"""
    parts = [p.strip() for p in tags.split(',')]
    comp = ""
    rest: list[str] = []
    for p in parts:
        if not comp and p.lower() in _COMPOSITION_KW:
            comp = p
        elif p:
            rest.append(p)
    return comp, ", ".join(rest)


# ─── 角色設定圖專用標籤（插圖生成時過濾掉）─────────────────────────────────────
_SHEET_TAG_SET = {
    # 構圖 / 視角
    "solo", "full body", "upper body", "half body", "bust shot",
    "standing", "sitting", "looking at viewer",
    "front view", "side view", "back view", "portrait",
    # 背景
    "white background", "simple background", "simple white background",
    "grey background", "gray background",
    # 其他設定圖常見、但對場景插圖有害的標籤
    "anime style", "character sheet", "perfect anatomy", "perfect fingers",
    # 人物數量標籤（由 LLM 根據場景決定）
    "1girl", "1boy", "2girls", "2boys", "3girls", "3boys",
    "multiple girls", "multiple boys",
}


def _split_tags(text: str) -> list[str]:
    """按逗號分割，但保留括號內的逗號（如 (masterpiece, best quality:1.2)）。"""
    parts: list[str] = []
    depth = 0
    buf: list[str] = []
    for ch in text:
        if ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf).strip())
    return [p for p in parts if p]


def _strip_sheet_tags(style_hint: str) -> str:
    """從 style_hint 中移除角色設定圖專用的構圖/背景標籤，讓它只保留純風格內容。
    同時清除 A1111 加權語法 (tag:1.2) → tag，native diffusers 不解析加權括號。"""
    if not style_hint:
        return style_hint
    import re
    # 去掉 (tag:weight) → tag，保留括號外的文字
    hint = re.sub(r'\(([^)]+?):\d+(?:\.\d+)?\)', r'\1', style_hint)
    # 去掉剩餘孤立括號
    hint = hint.replace('(', '').replace(')', '')
    parts = _split_tags(hint)
    filtered = [p.strip() for p in parts if p.strip() and p.strip().lower() not in _SHEET_TAG_SET]
    return ", ".join(filtered)


def _inject_embeddings(pipe, prompt: str, neg: str) -> tuple[str, str]:
    """若 lazy embeddings 已載入，自動注入 lazypos / lazyneg token。"""
    loaded = getattr(pipe, "_loaded_embeddings", set())
    if "lazypos" in loaded and "lazypos" not in prompt:
        prompt = f"lazypos, {prompt}"
    if "lazyneg" in loaded and "lazyneg" not in neg:
        neg = f"lazyneg, {neg}"
    return prompt, neg


async def generate_character_sheet(
    character_desc: str,
    character_name: str = "",
    seed: int = -1,
    width: int = 0,
    height: int = 0,
    prompt_prefix: str = "",
    on_progress: ProgressCallback | None = None,
    char_data: dict | None = None,
    ip_adapter_image=None,
) -> tuple[bytes, str]:
    s = get_settings()
    if width  <= 0: width  = s.sheet_width
    if height <= 0: height = s.sheet_height

    def _cb(pct: int, label: str):
        if on_progress: on_progress(pct, label)

    if seed < 0:
        import random
        seed = random.randint(0, 2**32 - 1)

    is_anime   = _infer_is_anime(prompt_prefix)
    user_style = prompt_prefix.strip()
    _style_key = "anime" if is_anime else "real"
    _arch      = _active_model_arch(_style_key)

    # 先架構分形態：Z-Image 走自然語言散文；SDXL 走 danbooru 標籤 + BREAK 分窗。
    if _arch == "zimage":
        desc  = build_character_description_zimage(char_data) if char_data else (character_desc + "。")
        style = "動漫插畫風格，色彩鮮明、線條乾淨" if is_anime else "寫實攝影，自然光影、細節豐富"
        extra = (user_style + "。") if user_style else ""
        prompt = f"{style}。{desc}全身像，站姿，面向鏡頭，簡潔純色背景。{extra}"
    elif is_anime:
        # BREAK 分段：W1=角色外觀（身份），W2=構圖+風格/品質。各段在獨立的 77-token
        # 窗口編碼（見 _encode_with_break），避免長 prompt 把構圖/風格整段截斷丟掉。
        en_tags   = build_character_fragment_en(char_data, seed=seed, include_expression=True) if char_data else character_desc
        char_part = en_tags.strip()
        if user_style:
            composition = (
                "solo, full body, standing, looking at viewer, front view, "
                "white background, anime style, perfect anatomy"
            )
            tail = f"{composition}, {user_style}"
        else:
            quality = "masterpiece, best quality, absurdres, highres, newest, very aesthetic"
            tail = (
                f"{quality}, "
                f"solo, full body, standing, looking at viewer, front view, "
                f"simple white background, detailed face, beautiful detailed eyes, "
                f"symmetrical eyes, perfect eyes, detailed clothing, "
                f"beautiful, elegant, anime style, perfect anatomy, perfect fingers"
            )
        prompt = f"{char_part} BREAK {tail}" if char_part else tail
    else:
        zh_desc  = build_character_fragment(char_data) if char_data else character_desc
        name_str = character_name or "character"
        quality  = "超高清, 极致细节, 顶级画质, masterpiece, best quality, ultra detailed, 8k"
        identity = f"full body portrait of {name_str}, {zh_desc}"
        style_part = f"{user_style}, " if user_style else ""
        tail = (
            f"{style_part}"
            f"standing, white background, looking at viewer, front view, "
            f"detailed face, beautiful detailed eyes, symmetrical eyes, "
            f"detailed clothing, cinematic lighting, {quality}"
        )
        prompt = f"{identity} BREAK {tail}"

    logger.debug("character_sheet prompt (%dc): %s", len(prompt), prompt[:200])
    _cb(10, "組合角色設定圖 prompt")

    loop = asyncio.get_running_loop()
    from services.gpu_manager import gpu_manager
    _task = "illustration_sdxl" if _arch == "sdxl" else "illustration_zimage"
    await gpu_manager.acquire_gpu(_task)
    try:
        _cb(30, f"載入{'動畫' if is_anime else '寫實'}模型")
        pipe = await _get_pipe(_style_key)
        is_turbo = getattr(pipe, "_is_turbo", False)
        negative_prompt = _build_negative_prompt_sheet(is_anime, is_turbo, style_hint=prompt_prefix)
        prompt, negative_prompt = _inject_embeddings(pipe, prompt, negative_prompt)
        _cb(50, "擴散生成角色設定圖")
        img = await loop.run_in_executor(
            None, _generate_sync,
            pipe, prompt, negative_prompt,
            width, height, seed,
            s.guidance_scale, _cb,
            ip_adapter_image, s.ip_adapter_scale,
        )

        if (s.hires_fix_enabled
                and not getattr(pipe, "_is_turbo", False)
                and not getattr(pipe, "_is_zimage", False)):
            from diffusers import WanPipeline
            if not isinstance(pipe, WanPipeline):
                _cb(96, "高解析度精修")
                img = await loop.run_in_executor(
                    None, _hires_fix_sync,
                    pipe, img, prompt, negative_prompt, seed,
                    s.hires_upscale, s.hires_denoise,
                )

        if (s.adetailer_enabled
                and not getattr(pipe, "_is_turbo", False)
                and not getattr(pipe, "_is_zimage", False)):
            from diffusers import WanPipeline
            if not isinstance(pipe, WanPipeline):
                _cb(97, "ADetailer 臉部精修")
                img = await loop.run_in_executor(
                    None, _adetailer_sync,
                    pipe, img, prompt, negative_prompt, seed,
                    s.adetailer_denoise,
                )

    finally:
        gpu_manager.release_gpu()

    _cb(100, "角色設定圖完成")
    return _pil_to_bytes(img), prompt


async def generate_portrait(
    character_desc: str,
    character_name: str = "",
    seed: int = -1,
    width: int = 0,
    height: int = 0,
    prompt_prefix: str = "",
    on_progress: ProgressCallback | None = None,
    char_data: dict | None = None,
    ip_adapter_image=None,
) -> tuple[bytes, str]:
    s = get_settings()
    if width  <= 0: width  = s.width
    if height <= 0: height = s.height

    def _cb(pct: int, label: str):
        if on_progress: on_progress(pct, label)

    if seed < 0:
        import random
        seed = random.randint(0, 2**32 - 1)

    is_anime   = _infer_is_anime(prompt_prefix)
    user_style = prompt_prefix.strip()
    _style_key = "anime" if is_anime else "real"
    _arch      = _active_model_arch(_style_key)

    # 先架構分形態：Z-Image 自然語言散文；SDXL danbooru 標籤 + BREAK 分窗。
    if _arch == "zimage":
        desc  = build_character_description_zimage(char_data) if char_data else (character_desc + "。")
        style = "動漫插畫風格，色彩鮮明、線條乾淨" if is_anime else "寫實攝影，自然光影、細節豐富"
        extra = (user_style + "。") if user_style else ""
        prompt = f"{style}。{desc}上半身像，面向鏡頭，簡潔純色背景。{extra}"
    elif is_anime:
        # BREAK 分段：W1=角色外觀，W2=構圖+風格/品質（同 generate_character_sheet）。
        en_tags   = build_character_fragment_en(char_data, seed=seed, include_expression=True) if char_data else character_desc
        char_part = en_tags.strip()
        if user_style:
            composition = (
                "solo, upper body, looking at viewer, "
                "white background, anime style, perfect anatomy"
            )
            tail = f"{composition}, {user_style}"
        else:
            quality = "masterpiece, best quality, absurdres, highres, newest, very aesthetic"
            tail = (
                f"{quality}, "
                f"solo, upper body, looking at viewer, "
                f"simple white background, detailed face, beautiful detailed eyes, "
                f"symmetrical eyes, perfect eyes, detailed clothing, "
                f"beautiful, elegant, anime style, perfect anatomy, perfect fingers"
            )
        prompt = f"{char_part} BREAK {tail}" if char_part else tail
    else:
        zh_desc  = build_character_fragment(char_data) if char_data else character_desc
        name_str = character_name or "character"
        quality  = "超高清, 极致细节, 顶级画质, masterpiece, best quality, ultra detailed, 8k"
        identity = f"portrait of {name_str}, {zh_desc}"
        style_part = f"{user_style}, " if user_style else ""
        tail = (
            f"{style_part}"
            f"upper body, white background, looking at viewer, "
            f"detailed face, beautiful detailed eyes, symmetrical eyes, "
            f"detailed clothing, cinematic lighting, {quality}"
        )
        prompt = f"{identity} BREAK {tail}"

    logger.debug("portrait prompt (%dc): %s", len(prompt), prompt[:200])
    _cb(10, "組合立繪 prompt")

    loop = asyncio.get_running_loop()
    from services.gpu_manager import gpu_manager
    _task = "illustration_sdxl" if _arch == "sdxl" else "illustration_zimage"
    await gpu_manager.acquire_gpu(_task)
    try:
        _cb(30, f"載入{'動畫' if is_anime else '寫實'}模型")
        pipe = await _get_pipe(_style_key)
        is_turbo = getattr(pipe, "_is_turbo", False)
        negative_prompt = _build_negative_prompt_sheet(is_anime, is_turbo, style_hint=prompt_prefix)
        prompt, negative_prompt = _inject_embeddings(pipe, prompt, negative_prompt)
        _cb(50, "擴散生成立繪")
        img = await loop.run_in_executor(
            None, _generate_sync,
            pipe, prompt, negative_prompt,
            width, height, seed,
            s.guidance_scale, _cb,
            ip_adapter_image, s.ip_adapter_scale,
        )

        if (s.hires_fix_enabled
                and not getattr(pipe, "_is_turbo", False)
                and not getattr(pipe, "_is_zimage", False)):
            from diffusers import WanPipeline
            if not isinstance(pipe, WanPipeline):
                _cb(96, "高解析度精修")
                img = await loop.run_in_executor(
                    None, _hires_fix_sync,
                    pipe, img, prompt, negative_prompt, seed,
                    s.hires_upscale, s.hires_denoise,
                )

        if (s.adetailer_enabled
                and not getattr(pipe, "_is_turbo", False)
                and not getattr(pipe, "_is_zimage", False)):
            from diffusers import WanPipeline
            if not isinstance(pipe, WanPipeline):
                _cb(97, "ADetailer 臉部精修")
                img = await loop.run_in_executor(
                    None, _adetailer_sync,
                    pipe, img, prompt, negative_prompt, seed,
                    s.adetailer_denoise,
                )

    finally:
        gpu_manager.release_gpu()

    _cb(100, "立繪生成完成")
    return _pil_to_bytes(img), prompt


def _find_text_primary_char(text: str, character_descriptions: "list[dict]") -> dict | None:
    """簡單 substring 比對（最長名優先），只給 direct_prompt（無場景 LLM 判斷）情境用。
    場景插圖請走 resolve_present_chars（由 LLM 判定在場角色），見下方 generate_illustration。"""
    if not text or not character_descriptions:
        return None
    for c in sorted(character_descriptions, key=lambda x: -len(x.get("name", ""))):
        n = c.get("name", "")
        if n and n in text:
            return c
    return None


async def generate_illustration(
    text: str              = "",
    character_descriptions: "list[dict] | None" = None,
    width: int             = 0,
    height: int            = 0,
    seed: int              = -1,
    prompt_prefix: str     = "",
    on_progress: ProgressCallback | None = None,
    ip_adapter_image=None,
    direct_prompt: str     = "",
    book_id: str           = "",
    character_name: str    = "",
) -> tuple[bytes, str, bool, dict]:
    s = get_settings()
    if width  <= 0: width  = s.width
    if height <= 0: height = s.height

    def _cb(pct: int, label: str):
        if on_progress: on_progress(pct, label)

    style_hint = _strip_sheet_tags(prompt_prefix.strip())
    is_direct  = bool(direct_prompt.strip())

    _quality = "score_9, score_8_up, masterpiece, best quality, absurdres"

    char_contexts: list[dict] = []
    if is_direct:
        _cb(25, "直接使用提示詞")
        is_anime    = _infer_is_anime(style_hint) or _infer_is_anime(direct_prompt)
        target_arch = _active_model_arch("anime" if is_anime else "real")
        full_prompt = direct_prompt.strip()
        primary = _find_text_primary_char(text, character_descriptions or [])
        if primary:
            char_contexts = [primary]
    else:
        _cb(25, "LLM 生成插圖 prompt")
        # 先粗判風格以決定要載入哪個模型 → 得知架構形態（zimage 句子 / sdxl 標籤）。
        # 與 _expand_prompt 內部的 _detect_is_anime(style_hint) 同源，結果一致。
        _pre_is_anime = _infer_is_anime(style_hint)
        target_arch = _active_model_arch("anime" if _pre_is_anime else "real")
        scene_prompt, is_anime, char_contexts = await _expand_prompt(
            text,
            character_descriptions=character_descriptions,
            style_hint=style_hint,
            target_arch=target_arch,
        )
        if target_arch == "zimage":
            # Z-Image：scene_prompt 已是含風格錨的自然語言段落，不前置 danbooru 品質詞
            full_prompt = scene_prompt or (
                "動漫插畫風格，高品質，細節豐富。" if is_anime else "寫實攝影，高品質，細節豐富。"
            )
        else:
            # 品質詞前置 + LLM 輸出的場景標籤（兩個 CLIP encoder 吃同一份）
            full_prompt = f"{_quality}, {scene_prompt}" if scene_prompt else _quality

    # ── 在場角色解析：FaceID 參考圖／seed 與構圖 prompt 共用同一份判定 ──────────
    # 顯式 character_name（使用者手動選角）優先；否則用 char_contexts[0]
    # （LLM 已確認在場，is_direct 時為 substring fallback）。
    # 避免「prompt 描述 B、FaceID 卻鎖 A 的臉」這種架構性不一致
    # （見 plans/consistency-alignment-refactor.md）。
    primary_char: dict | None = None
    if character_name:
        primary_char = next(
            (c for c in (character_descriptions or []) if c.get("name") == character_name),
            {"name": character_name},
        )
    elif char_contexts:
        primary_char = char_contexts[0]

    if seed < 0:
        if primary_char and book_id:
            cs = primary_char.get("character_seed", -1)
            if cs is not None and cs >= 0:
                seed = cs
            else:
                seed = character_seed_for(book_id, primary_char["name"])
        else:
            # 無法定錨角色 seed 時，用文字內容 hash，至少同段落重生時畫面一致
            import hashlib as _hs
            seed = int.from_bytes(_hs.md5(text.encode()).digest()[:4], "big") & 0x7FFF_FFFF

    if ip_adapter_image is None and primary_char and book_id:
        ip_adapter_image = load_char_ref_image(book_id, primary_char["name"])

    logger.debug("prompt (%dc, %s): %s", len(full_prompt), "anime" if is_anime else "real", full_prompt[:160])

    loop = asyncio.get_running_loop()
    from services.gpu_manager import gpu_manager
    _style = "anime" if is_anime else "real"
    _arch = _active_model_arch(_style)
    _task = "illustration_sdxl" if _arch == "sdxl" else "illustration_zimage"
    await gpu_manager.acquire_gpu(_task)
    try:
        style = _style
        _cb(35, f"載入{'動畫' if is_anime else '寫實'}模型")
        pipe = await _get_pipe(style)

        is_turbo  = getattr(pipe, "_is_turbo", False)
        is_zimage = getattr(pipe, "_is_zimage", False)
        from diffusers import WanPipeline
        is_wan = isinstance(pipe, WanPipeline)

        effective_steps, effective_cfg = _resolve_effective_params(pipe, s)

        entry = _find_model_entry(style)
        model_name = ""
        if entry:
            model_name = entry.get("name") or os.path.basename(entry.get("local_path", ""))

        negative_prompt = _build_negative_prompt(is_anime, is_turbo, style_hint=style_hint)
        if is_direct:
            # direct_prompt 使用者已有正向品質詞，只補 lazyneg 到 negative
            loaded = getattr(pipe, "_loaded_embeddings", set())
            if "lazyneg" in loaded and "lazyneg" not in negative_prompt:
                negative_prompt = f"lazyneg, {negative_prompt}"
        else:
            full_prompt, negative_prompt = _inject_embeddings(pipe, full_prompt, negative_prompt)

        sampler_name = type(pipe.scheduler).__name__
        clip_skip = 2 if (not is_wan and not is_zimage) else 0

        # 將參考圖（PIL Image）轉成 IP-Adapter FaceID 所需的 ArcFace numpy embedding
        ip_face_emb = None
        if (ip_adapter_image is not None
                and getattr(pipe, "_ip_adapter_loaded", False)
                and not is_wan and not is_zimage):
            try:
                from services.illustration.face_extractor import extract_face as _ef
                emb, _ = await loop.run_in_executor(None, _ef, ip_adapter_image)
                if emb is not None:
                    ip_face_emb = emb[0].numpy()  # (512,) float32
                    logger.info("IP-Adapter: 人臉 embedding 提取成功")
                else:
                    logger.info("IP-Adapter: 參考圖未偵測到人臉，跳過")
            except Exception as _e:
                logger.warning("IP-Adapter 人臉提取失敗: %s", _e)

        _cb(50, "開始擴散")
        img = await loop.run_in_executor(
            None, _generate_sync,
            pipe, full_prompt, negative_prompt,
            width, height, seed,
            s.guidance_scale, _cb,
            ip_face_emb, s.ip_adapter_scale,
        )

        if (s.hires_fix_enabled
                and not is_turbo and not is_zimage and not is_wan):
            _cb(96, "高解析度精修")
            img = await loop.run_in_executor(
                None, _hires_fix_sync,
                pipe, img, full_prompt, negative_prompt, seed,
                s.hires_upscale, s.hires_denoise,
            )

        if (s.adetailer_enabled
                and not is_turbo and not is_zimage and not is_wan):
            _cb(97, "ADetailer 臉部精修")
            img = await loop.run_in_executor(
                None, _adetailer_sync,
                pipe, img, full_prompt, negative_prompt, seed,
                s.adetailer_denoise,
            )

    finally:
        gpu_manager.release_gpu()

    meta = {
        "workflow":         "txt2img",
        "model_name":       model_name,
        "sampler":          sampler_name,
        "steps":            effective_steps,
        "guidance_scale":   effective_cfg,
        "clip_skip":        clip_skip,
        "seed":             seed,
        "width":            width,
        "height":           height,
        "negative_prompt":  negative_prompt,
    }
    _cb(100, "完成")
    return _pil_to_bytes(img), full_prompt, is_anime, meta


# ─── 狀態 / 載入 / 卸載 ──────────────────────────────────────────────────────

async def is_model_ready() -> bool:
    from services.illustration.pipelines import _pipe as _p
    return _p is not None


async def load_model():
    await _get_pipe("anime")


async def unload_model():
    from services.illustration import pipelines as _pl
    async with _pl._pipe_lock:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _pl._unload_pipe_sync)


async def unload():
    await unload_model()
