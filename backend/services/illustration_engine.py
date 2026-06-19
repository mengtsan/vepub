"""
Facade — 重新匯出 services.illustration.* 的所有公開與私有符號。
外部程式碼（routers、tests）繼續以 services.illustration_engine.X 存取。
"""
# ── settings ──────────────────────────────────────────────────────────────────
from services.illustration.settings import (
    IllustrationSettings,
    _settings, _SETTINGS_PATH,
    get_settings, update_settings,
    _persist_settings, _load_settings,
)

# ── prompt_builder ────────────────────────────────────────────────────────────
from services.illustration.prompt_builder import (
    build_character_fragment,
    _GENDER_EN, _AGE_HINT_EN, _PERSONALITY_EXPR_KW, _EXPRESSION_POOL,
    _HAIR_COLOR_EN, _HAIR_STYLE_EN, _EYE_COLOR_EN, _SKIN_EN,
    _BODY_EN, _EYE_SHAPE_EN, _FACE_SHAPE_EN,
    _OUTFIT_KW, _OUTFIT_COLOR_KW, _ACCESSORY_KW, _SPECIAL_TRAIT_KW,
    _match_kw,
    build_character_fragment_en,
    character_seed_for,
    _expand_prompt, _infer_is_anime,
    _STYLE_NEG_REMOVES, _build_negative_prompt, _build_negative_prompt_sheet,
)

# ── pipelines ─────────────────────────────────────────────────────────────────
from services.illustration.pipelines import (
    _BASE_DIR,
    _pipe, _loaded_style, _pipe_lock,
    _find_model_entry,
    _detect_architecture, _active_model_arch,
    _load_pipe_sync, _load_sdxl_pipe_sync,
    _ZIMAGE_HF_REPO, _ZIMAGE_CACHE,
    _ensure_zimage_components, _load_zimage_pipe_sync,
    _WAN_BASE, _WAN_CACHE, _load_wan_pipe_sync,
    _unload_pipe_sync, _get_pipe,
    _resolve_effective_params, _generate_sync,
    _pil_to_bytes,
)

# ── generation ────────────────────────────────────────────────────────────────
from services.illustration.generation import (
    generate_character_sheet,
    generate_portrait,
    generate_illustration,
    is_model_ready,
    load_model,
    unload_model,
    unload,
)
