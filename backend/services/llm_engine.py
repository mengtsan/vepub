"""
Facade — 重新匯出 services.llm.* 的所有公開與私有符號。
外部程式碼（routers、tests）繼續以 services.llm_engine.X 存取。
"""
# ── server ────────────────────────────────────────────────────────────────────
from services.llm.server import (
    _BASE_DIR, _BIN_DIR, _LLM_PREFERRED,
    _SERVER_PORT, _server_proc, _server_lock,
    _SERVER_IDLE_TTL, _server_ctx, _server_model, _idle_stop_task,
    _registry_gguf,
    find_llama_server, find_gguf, find_analysis_gguf,
    is_available, get_model_name,
    _kill_existing_server, _start_server_sync, _stop_server_sync,
    _ensure_server, _arm_idle_stop, stop_server_now,
    _chat,
)

# ── char_schema ───────────────────────────────────────────────────────────────
from services.llm.char_schema import (
    _FIELD_ALIASES, _normalize_char, _parse_character_json,
    _THINKING_STARTS, _strip_inline_thinking,
    _VALID_GENDER, _VALID_AGE_HINTS, _VALID_BODY_TYPES,
    _VALID_HAIR_STYLES, _VALID_CUP_SIZES,
    _SOFT_HAIR_COLORS, _SOFT_EYE_COLORS, _SOFT_SKIN_TONES,
    _SOFT_FACE_SHAPES, _SOFT_EYE_SHAPES, _SOFT_ERA_STYLES,
    _fmt_soft, _fmt_strict, _CHAR_SCHEMA_PROMPT,
    _empty_character_fields, _MAX_EXTRACT_CHARS, _trim_for_extraction,
    _PRONOUN_CHARS, _NON_NAME_TERMS, _is_valid_char_name,
    _NAME_PREFIXES, _merge_aliases,
    _BATCH_CHARS,
    _HAIR_COLOR_POOL_F, _HAIR_COLOR_POOL_M, _EYE_COLOR_POOL,
    _FACE_SHAPE_POOL, _EYE_SHAPE_POOL,
    _HAIR_STYLE_POOL_F, _HAIR_STYLE_POOL_M,
    _name_pick, _apply_defaults,
)

# ── tasks ─────────────────────────────────────────────────────────────────────
from services.llm.tasks import (
    find_alias_groups,
    _ANIME_KW, _REAL_KW, _detect_is_anime, _clean_llm,
    resolve_present_chars, expand_prompt,
    extract_character_features,
    _CONTEXTUAL_FIELDS, _KNOWN_CONTEXT_KEYS,
    _INFER_BATCH_SIZE, _INFER_TOKENS_EACH,
    _infer_contextual_fields, _infer_and_merge, infer_missing_fields,
    analyze_characters,
)
