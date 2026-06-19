"""
高階 LLM 非同步任務：prompt 擴寫、角色提取、全書分析、別名去重、欄位推斷。
依賴 server.py（生命週期）與 char_schema.py（schema/解析/補完）。
"""
import asyncio
import json as _json
import logging
import re

logger = logging.getLogger(__name__)

from services.llm.server import (
    find_gguf, find_analysis_gguf,
    _chat, _server_lock, _ensure_server, _arm_idle_stop,
)
from services.llm.char_schema import (
    _parse_character_json, _strip_inline_thinking,
    _CHAR_SCHEMA_PROMPT, _apply_defaults, _empty_character_fields,
    _trim_for_extraction, _is_valid_char_name, _merge_aliases,
    _BATCH_CHARS,
    _VALID_AGE_HINTS, _VALID_BODY_TYPES, _VALID_HAIR_STYLES,
    _SOFT_ERA_STYLES, _SOFT_SKIN_TONES, _SOFT_FACE_SHAPES, _SOFT_EYE_SHAPES,
)


# ─── 別名去重 ──────────────────────────────────────────────────────────────────

async def find_alias_groups(names: list[str]) -> list[list[str]]:
    if len(names) < 2:
        return []

    path = find_analysis_gguf()
    if not path:
        return []

    name_set  = set(names)
    name_list = "、".join(names)

    system = (
        "你是一個角色別名識別助手。\n"
        "以下是從小說中提取的角色名稱清單，請找出哪些名稱是同一個角色的不同稱呼"
        "（別名、字號、外號、年號、全名與縮寫等）。\n"
        "【規則】\n"
        "1. 只回傳確定相同的分組，不確定的不要包含\n"
        "2. 每組必須有 2 個以上名稱\n"
        "3. 只使用清單中出現的名稱，不要自行補充\n"
        "4. 只輸出合法 JSON 二維陣列，禁止任何解釋或 markdown\n"
        "5. 若找不到任何別名，回傳空陣列 []\n"
        '範例輸出：[["福臨","順治","愛新覺羅·福臨"],["孔明","諸葛亮","臥龍先生"]]'
    )

    async with _server_lock:
        await _ensure_server(path, 2048)
        try:
            raw = await _chat(
                system,
                f"角色名稱清單：{name_list}",
                max_tokens=500,
                temperature=0.1,
                prefill="[",
            )
        finally:
            _arm_idle_stop()

    logger.debug("find_alias_groups raw: %s", raw[:300])

    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", raw).strip()
    if cleaned.startswith("[["):
        cleaned = cleaned[1:]

    start = cleaned.find('[')
    if start == -1:
        return []
    try:
        data, _ = _json.JSONDecoder().raw_decode(cleaned, start)
    except _json.JSONDecodeError:
        return []

    if not isinstance(data, list):
        return []
    if data and isinstance(data[0], str):
        data = [data]

    result = []
    for group in data:
        if not isinstance(group, list):
            continue
        valid = [str(n).strip() for n in group if isinstance(n, str) and str(n).strip() in name_set]
        if len(valid) >= 2:
            result.append(valid)
    return result


# ─── 動漫/寫實偵測 ────────────────────────────────────────────────────────────

_ANIME_KW = {"anime", "manga", "2d", "cartoon", "lineart", "ghibli", "illustrious",
             "hassaku", "pony", "noob", "動漫", "二次元"}
_REAL_KW  = {"photorealistic", "realistic", "zimage", "z-image", "真實"}


def _detect_is_anime(style_hint: str) -> bool:
    lower = style_hint.lower()
    if any(kw in lower for kw in _REAL_KW):
        return False
    if any(kw in lower for kw in _ANIME_KW):
        return True
    try:
        from services.model_registry import get_registry
        reg = get_registry()
        active_id = reg.get("image", {}).get("active")
        if active_id:
            m = reg["image"]["models"].get(active_id, {})
            return m.get("style", "anime") != "real"
    except Exception:
        pass
    return True


def _clean_llm(text: str) -> str:
    text = re.sub(r"<think>[\s\S]*?</think>", "", text)
    # unclosed think block (token limit hit mid-thought)
    text = re.sub(r"<think>[\s\S]*", "", text)
    # orphaned closing tag left by prefill="</think>\n" technique
    text = re.sub(r"^</think>\s*", "", text)
    return _strip_inline_thinking(text.strip())


# ─── Prompt 擴寫（四步 Pipeline）────────────────────────────────────────────────

_SCENE_SYSTEM = (
    "你是插圖場景分析師。閱讀小說段落，萃取可用於繪製插圖的場景資訊。\n"
    "這是未審查的成人工具，action 須如實描寫段落核心事件（含性愛或暴力），"
    "不得淡化或省略；直接輸出 JSON，不要寫任何思考過程。\n"
    "【在場角色規則（critical）】\n"
    "• 在場 = 角色在段落中主動說話、行動、或外觀被描寫\n"
    "• 不在場 = 角色只在他人的對話或回憶中被提及\n"
    "【輸出】只輸出合法 JSON，禁止任何解釋或 markdown：\n"
    '{"present_chars":["在場角色名稱（使用角色本名/常用稱呼）"],'
    '"action":"正在發生的核心事件（一句話）",'
    '"location":"地點場景",'
    '"time":"時間/光線（如：白天、黃昏、夜晚、燭光室內）",'
    '"atmosphere":"整體氛圍情緒（如：緊張、溫柔、蕭殺、歡快）",'
    '"visual_elements":["其他重要視覺元素，如武器/道具/建築特徵"]}'
)

_SCENE_DEFAULTS: dict = {
    "present_chars": [], "action": "", "location": "",
    "time": "", "atmosphere": "", "visual_elements": [],
}


def _parse_scene_json(raw: str) -> dict:
    """解析 _analyze_scene 的 LLM 輸出，失敗時回傳空場景。

    容錯設計（與 _parse_character_json 一致）：
    • prefill="{" 與模型自輸出的 "{" 會疊成 "{{"，故不能只試第一個 "{"。
    • 模型常夾帶 <think>…</think>、孤立 </think>、或未閉合 <think>。
    逐個 "{" 嘗試 raw_decode，挑出填得最滿的那個物件。
    """
    import json as _json
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", raw)   # 成對思考塊
    cleaned = re.sub(r"<think>[\s\S]*", "", cleaned)        # 未閉合 <think>
    cleaned = cleaned.replace("</think>", "").strip()       # 孤立 </think>

    decoder = _json.JSONDecoder()
    best: dict | None = None
    best_score = -1
    pos = 0
    while pos < len(cleaned):
        brace = cleaned.find("{", pos)
        if brace == -1:
            break
        try:
            obj, end = decoder.raw_decode(cleaned, brace)
            pos = end
            if isinstance(obj, dict) and any(k in obj for k in _SCENE_DEFAULTS):
                score = sum(1 for k in _SCENE_DEFAULTS if obj.get(k))
                if score > best_score:
                    best, best_score = obj, score
        except _json.JSONDecodeError:
            pos = brace + 1

    if best is None:
        logger.warning("_parse_scene_json 無法解析: raw=%r", raw[:120])
        return dict(_SCENE_DEFAULTS)

    result = dict(_SCENE_DEFAULTS)
    result.update({k: v for k, v in best.items() if k in _SCENE_DEFAULTS})
    if not isinstance(result["present_chars"], list):
        result["present_chars"] = []
    if not isinstance(result["visual_elements"], list):
        result["visual_elements"] = []
    return result


def _subject_count_tag(scene: dict, char_contexts: list[dict]) -> str:
    """依在場角色性別推 1girl / 1boy / 1girl 1boy …，無性別資訊則退回人數。"""
    nf = nm = 0
    for c in char_contexts:
        g = str(c.get("gender") or "").lower()
        if g in ("female", "女", "f"):
            nf += 1
        elif g in ("male", "男", "m"):
            nm += 1
    parts = []
    if nf == 1: parts.append("1girl")
    elif nf >= 2: parts.append(f"{nf}girls")
    if nm == 1: parts.append("1boy")
    elif nm >= 2: parts.append(f"{nm}boys")
    if parts:
        return ", ".join(parts)
    n = max(1, len(scene.get("present_chars") or char_contexts or [1]))
    return "1girl" if n == 1 else f"{n}girls"


def _scene_fallback_tags(scene: dict, char_contexts: list[dict]) -> str:
    """構圖重試多次仍失敗時的最後保底。
    只用「在場人數」這個與文體完全無關、可靠的線索（性別→1girl/1boy）。
    刻意不從中文 location 猜室內外——那種關鍵字表換個文體（現代/科幻/西幻）就失效，
    正是會讓不同段落又塌縮成同一張圖的根源。場景的差異化交給上游可重試的 LLM。"""
    return f"{_subject_count_tag(scene, char_contexts)}, medium shot"


def _composition_usable(tags: str, count_tag: str) -> bool:
    """判定構圖輸出是否「有實質內容」：扣掉人數標籤後，至少還要有幾個內容標籤。
    這是健全性下限（模型只回人數、塌縮、或沒照格式時為 False），與文體無關，
    不是針對某篇文章調出來的魔術數字。"""
    if not tags:
        return False
    count_set = {t.strip().lower() for t in count_tag.split(",")}
    content = [t for t in tags.split(",") if t.strip() and t.strip().lower() not in count_set]
    return len(content) >= 4


def _extract_prompt_line(text: str, lead: str = "") -> str:
    """從構圖輸出萃取最終標籤行：取最後一個 'PROMPT:' 之後、第一個換行之前的內容，
    再去重（防止退化重複迴圈）並截到 28 個標籤。找不到 PROMPT: 時退回原文首行去重。

    lead：權威人數標籤（依角色性別算出）。置於最前面，確保畫面人數以我們的判定為準，
    不被模型偶爾重發 'PROMPT: 1boy…' 之類截斷的人數覆蓋。"""
    if not text and not lead:
        return ""
    low = text.lower()
    idx = low.rfind("prompt:")
    body = text[idx + len("prompt:"):] if idx != -1 else text
    body = body.splitlines()[0] if body.splitlines() else body  # 只取一行
    if lead:
        body = f"{lead}, {body}"

    seen: set[str] = set()
    out: list[str] = []
    for tag in body.split(","):
        t = tag.strip()
        if not t:
            continue
        # 去掉模型常黏在描述標籤前的多餘人數前綴（"1girl big breasts" → "big breasts"），
        # 但保留單獨的人數標籤本身（"1girl" 不動）。
        m = _COUNT_PREFIX_RE.match(t)
        if m and t[m.end():].strip():
            t = t[m.end():].strip()
        key = t.lower()
        if key in seen:
            continue          # 去重：擋退化迴圈
        seen.add(key)
        out.append(t)
        if len(out) >= 28:
            break
    return ", ".join(out)


_COUNT_PREFIX_RE = re.compile(
    r'^(?:\d+\s*girls?|\d+\s*boys?|multiple\s+(?:girls|boys))\b\s*', re.IGNORECASE
)


def _build_char_block_for_composition(char: dict, is_anime: bool) -> str:
    """Step 2：單一角色 → 給構圖 LLM 的雙層描述（人設敘述 + 視覺 tags）。"""
    name = (char.get("name") or "").strip()
    description = (char.get("description") or "").strip()

    if is_anime:
        from services.illustration.prompt_builder import build_character_fragment_en
        en_tags = build_character_fragment_en(char)
        if description and en_tags:
            return f"{name}｜人設：{description}｜視覺：{en_tags}"
        elif description:
            return f"{name}｜人設：{description}"
        elif en_tags:
            return f"{name}｜視覺：{en_tags}"
    else:
        from services.illustration.prompt_builder import build_character_fragment
        zh_tags = build_character_fragment(char)
        if description and zh_tags:
            return f"{name}｜人設：{description}｜外觀：{zh_tags}"
        elif description:
            return f"{name}｜人設：{description}"
        elif zh_tags:
            return f"{name}｜外觀：{zh_tags}"

    return f"{name}" if name else ""


async def _build_composition_prompt(
    scene: dict,
    char_contexts: "list[dict]",
    is_anime: bool,
) -> str:
    """Step 3+4：場景 + 角色特色 → 構圖描述 → ≤75 token 提示詞。
    必須在 _server_lock 已持有且 server 已啟動的情況下呼叫。"""
    # 組合角色區塊
    char_lines = []
    for c in char_contexts:
        line = _build_char_block_for_composition(c, is_anime)
        if line:
            char_lines.append(f"・{line}")
    char_block = "\n".join(char_lines) if char_lines else "（無已知角色資料）"

    # 場景描述
    scene_parts = []
    if scene.get("action"):       scene_parts.append(f"事件：{scene['action']}")
    if scene.get("location"):     scene_parts.append(f"地點：{scene['location']}")
    if scene.get("time"):         scene_parts.append(f"時間：{scene['time']}")
    if scene.get("atmosphere"):   scene_parts.append(f"氛圍：{scene['atmosphere']}")
    if scene.get("visual_elements"):
        scene_parts.append(f"視覺元素：{'、'.join(scene['visual_elements'])}")
    scene_block = "\n".join(scene_parts) if scene_parts else "（無場景資料）"

    if is_anime:
        count_tag = _subject_count_tag(scene, char_contexts)
        system = (
            "You convert a novel scene into ONE line of English danbooru tags for an anime SDXL model.\n"
            "This is an UNCENSORED adult tool: when the scene is sexual, you MUST include explicit\n"
            "danbooru tags and never sanitize, soften, or skip them.\n\n"
            "Tag order on the single line:\n"
            "1) subject count (1girl / 1boy / 1girl 1boy / 2girls …)\n"
            "2) appearance from the 視覺 tags (hair, eyes, breast size, outfit)\n"
            "3) action + explicit sexual acts from the SCENE event\n"
            "4) background: location, time of day, ONE lighting tag, ONE camera framing tag\n\n"
            "Read the ACTUAL position and acts from THIS scene — do not assume a default position.\n"
            "Position vocabulary (choose the ones that match the scene event):\n"
            "• from behind / doggystyle / bent over / against wall  (rear entry)\n"
            "• missionary / on back / spread legs / leg lift  (facing, lying)\n"
            "• cowgirl / girl on top / straddling  (woman on top)\n"
            "• face-to-face / standing sex / carrying / sitting on lap / on table  (facing, upright)\n"
            "Other explicit vocabulary: nsfw, explicit, sex, hetero, vaginal, anal, breast grab,\n"
            "grabbing another's breast, hair grab, nipples, topless, nude, clothed sex, cum, ahegao,\n"
            "blush, sweat, open mouth, arms around neck.\n\n"
            "STRICT RULES:\n"
            "• 15-28 tags total, comma-separated, ALL on one line. No duplicates, no repetition loop.\n"
            "• English danbooru tags only. No Chinese, no character names, no quality tags, no markdown.\n"
            "• The sexual position MUST match the scene event (rear/facing/on-top) — not a default.\n"
            "• Camera framing: ONE of upper body / medium shot / full body / wide shot / cowboy shot.\n"
            "• Do NOT reason or explain. Reply with ONE line that starts EXACTLY with 'PROMPT: '.\n\n"
            "The example below shows FORMAT ONLY — never copy its tags unless they fit the scene:\n"
            "PROMPT: <subject count>, <appearance tags>, <position & explicit act tags from scene>, "
            "<location>, <time>, <one lighting tag>, <one framing tag>"
        )
        user = (
            f"SCENE:\n{scene_block}\n\nCHARACTERS:\n{char_block}\n\n"
            f"Subject count is: {count_tag}\nReply with one line starting 'PROMPT: '."
        )
        # prefill 直接寫死 'PROMPT: ' + 人數標籤：強制模型從正解標籤串接續，
        # 既不留空間給散文推理，又給定正確格式起頭（避免 1girl-prefix 迴圈）。
        prefill = f"PROMPT: {count_tag}, "
        # 自適應重試：若抽到的標籤太少（塌縮／模型沒照格式），升高 temperature 再試一次
        # 打破決定性。全程只對「抽象化後的場景 dict」操作、交給 LLM 處理，不靠任何
        # 文體相關的關鍵字硬編碼；換個文章風格時靠重試而非寫死的規則來自我修正。
        # max_tokens 只是輸出天花板（單行≤28 tag，模型遇 EOS 自然停），非長度目標。
        # frequency_penalty 壓低到 0.3：太高會連空格 token 一起罰 → 標籤黏成
        # "mistymountainpath"；退化重複迴圈改由 _extract_prompt_line 去重把關。
        logger.info("[illust] 構圖(anime) count=%r scene=%r", count_tag, scene_block.replace("\n", " │ "))
        cleaned = ""
        for attempt, temperature in enumerate((0.5, 0.85), 1):
            raw = await _chat(
                system, user, max_tokens=256, temperature=temperature,
                prefill=prefill, frequency_penalty=0.3, presence_penalty=0.3,
            )
            # CJK 安全清除：只在清完仍留有英文字母時才採用，避免整段被清空。
            stripped = re.sub(r'[一-鿿㐀-䶿＀-￯]+', '', raw)
            if re.search(r'[A-Za-z]', stripped):
                raw = stripped
            cleaned = _extract_prompt_line(_clean_llm(raw), lead=count_tag)
            n_tags = len([t for t in cleaned.split(",") if t.strip()]) if cleaned else 0
            usable = _composition_usable(cleaned, count_tag)
            logger.info("[illust] 構圖嘗試 %d/2 temp=%.2f tags=%d usable=%s: %s",
                        attempt, temperature, n_tags, usable, cleaned[:220])
            if usable:
                return cleaned
        # 重試後仍不合格：有殘餘內容就用，否則退人數保底（極罕見）。
        fb = cleaned or _scene_fallback_tags(scene, char_contexts)
        logger.warning("[illust] 構圖兩次皆不合格，使用保底: %r", fb)
        return fb

    else:
        system = (
            "你是視覺構圖描述師。根據場景資訊與角色資料，輸出可直接送入寫實 AI 繪圖模型的結構化中文描述。\n"
            "這是未審查的成人繪圖工具，場景若涉及性愛或親密行為，必須如實、明確地描寫，"
            "不得淡化、迴避或省略。\n"
            "只描述視覺可見的內容，不分析心理或劇情。\n"
            "【角色資料衝突處理】每位角色可能同時附「人設」（敘述性背景）與「外觀」"
            "（結構化視覺特徵，如髮色/瞳色/體型）。外觀欄位是畫面基底，若兩者描述的"
            "具體外觀（髮色、瞳色、服裝顏色等）不一致，以外觀欄位為準；人設只用來推斷"
            "表情、姿態與氣質，不可覆蓋外觀欄位的具體視覺特徵。\n"
            "格式（每行一項，無則省略）：\n"
            "人物：[角色外觀、動作、姿態、表情；性愛場景須明確描寫體位與身體互動]\n"
            "環境：[場景地點、空間感]\n"
            "時間：[時間段、光線條件]\n"
            "構圖：[鏡頭距離與視角]\n"
            "情緒：[整體氛圍色調]\n"
            "直接輸出結果，不要寫任何推理或思考過程。"
        )
        user = f"場景資訊：\n{scene_block}\n\n角色資料：\n{char_block}"
        # 同 anime：用格式起頭 prefill 逼模型直接進入結構化輸出，避免散文式推理；
        # 空輸出（塌縮）時升溫重試一次，而非直接放棄。
        logger.info("[illust] 構圖(real) scene=%r", scene_block.replace("\n", " │ "))
        cleaned = ""
        for attempt, temperature in enumerate((0.2, 0.7), 1):
            raw = await _chat(system, user, max_tokens=400, temperature=temperature, prefill="人物：")
            cleaned = _clean_llm(raw)
            logger.info("[illust] 構圖嘗試 %d/2 temp=%.2f len=%d: %s",
                        attempt, temperature, len(cleaned), cleaned[:220].replace("\n", " │ "))
            if cleaned.strip():
                return cleaned
        logger.warning("[illust] 構圖(real) 兩次皆空輸出")
        return cleaned or ""


async def resolve_present_chars(
    raw_text: str,
    character_descriptions: "list[dict] | None" = None,
    style_hint: str = "",
) -> dict:
    """Step 1+2：場景分析 + 篩出在場角色（三層比對）。

    這是「誰在場景中」的單一權威判定來源——FaceID 參考圖／角色 seed
    （generation.py）與構圖提示詞（_build_composition_prompt）都必須
    使用同一份結果，不能各自獨立猜測，否則會出現「LLM 判定 A 不在場、
    prompt 描述 B，但 FaceID 卻把 A 的臉貼上去」的不一致。
    見 plans/consistency-alignment-refactor.md。
    """
    is_anime = _detect_is_anime(style_hint)
    all_chars = character_descriptions or []

    path = find_gguf()
    if not path:
        return {"scene": dict(_SCENE_DEFAULTS), "char_contexts": [], "is_anime": is_anime}

    try:
        from services.model_registry import get_llm_ctx
        n_ctx = get_llm_ctx("analysis")
    except Exception:
        n_ctx = 4096

    async with _server_lock:
        await _ensure_server(path, n_ctx)
        try:
            # ── Step 1：場景分析 ───────────────────────────────────────────────
            raw_scene = await _chat(
                _SCENE_SYSTEM,
                f"段落：\n{raw_text}",
                max_tokens=400, temperature=0.2, prefill="{",
            )
            scene = _parse_scene_json(raw_scene)
            logger.info("[illust] 場景解析 chars=%s action=%r loc=%r time=%r atmo=%r",
                        scene["present_chars"], scene.get("action"), scene.get("location"),
                        scene.get("time"), scene.get("atmosphere"))
        finally:
            _arm_idle_stop()

    # ── Step 2：篩出在場角色（三層比對，確保外觀錨點不流失）──────────────
    present_names = [str(n).strip() for n in scene["present_chars"] if str(n).strip()]

    # 第一層：精確比對
    char_contexts = [c for c in all_chars if c.get("name") in present_names]

    # 第二層：LLM 回傳變體稱呼（如「李大人」vs DB「李明」）→ 寬鬆 substring 互含
    if not char_contexts and present_names:
        for c in all_chars:
            nm = c.get("name", "")
            if nm and any(nm in pn or pn in nm for pn in present_names):
                char_contexts.append(c)

    # 第三層保底：直接掃原文找最長匹配名，保證至少有一個外觀錨點
    if not char_contexts and all_chars:
        for c in sorted(all_chars, key=lambda x: -len(x.get("name", ""))):
            nm = c.get("name", "")
            if nm and nm in raw_text:
                char_contexts.append(c)
                break

    logger.info("[illust] 在場角色 present=%s → char_contexts=%s",
                present_names, [c.get("name") for c in char_contexts])

    return {"scene": scene, "char_contexts": char_contexts, "is_anime": is_anime}


async def expand_prompt(
    raw_text: str,
    character_descriptions: "list[dict] | None" = None,
    style_hint: str = "",
) -> tuple[str, bool, list[dict]]:
    """Step 1~4 全流程：場景分析 → 篩在場角色 → 構圖融合 → 轉提示詞。
    回傳 (prompt, is_anime, char_contexts)——char_contexts 是 resolve_present_chars
    判定的在場角色，呼叫端（generate_illustration）拿它來解析 FaceID 參考圖與 seed，
    確保「畫面描述的是誰」與「FaceID 鎖的是誰臉」永遠一致。
    """
    resolved = await resolve_present_chars(raw_text, character_descriptions, style_hint)
    scene, char_contexts, is_anime = resolved["scene"], resolved["char_contexts"], resolved["is_anime"]

    path = find_gguf()
    if not path:
        return "", is_anime, char_contexts

    try:
        from services.model_registry import get_llm_ctx
        n_ctx = get_llm_ctx("analysis")
    except Exception:
        n_ctx = 4096

    async with _server_lock:
        await _ensure_server(path, n_ctx)
        try:
            # ── Step 3+4：構圖融合 + 轉提示詞 ────────────────────────────────
            prompt = await _build_composition_prompt(scene, char_contexts, is_anime)
        finally:
            _arm_idle_stop()

    logger.info("[illust] 最終 prompt (%s): %s", "anime" if is_anime else "real", prompt[:300])
    return prompt or ("1girl, medium shot, indoors" if is_anime else ""), is_anime, char_contexts


# ─── 角色特徵提取 ─────────────────────────────────────────────────────────────

async def extract_character_features(text: str) -> list[dict]:
    path = find_analysis_gguf()
    if not path:
        return [_empty_character_fields()]

    trimmed = _trim_for_extraction(text)

    system = (
        "你是一位角色外觀提取助手。\n"
        "根據以下小說段落，提取所有有外觀描寫的角色。\n"
        "【規則】\n"
        "1. 提取段落中所有出現的角色，每個角色一個 JSON 物件\n"
        "2. name 填角色的稱呼或名字，包含「老師」「師父」「小姐」「大人」等稱謂（如「秋月老師」）\n"
        "3. 只填段落中明確描述或可直接推論的特徵；無法確定的欄位填 null\n"
        "4. 寧可填 null 也不要捏造無根據的特徵\n"
        "5. gender：從稱謂或代詞（她/他/女/男）推論；無任何線索填 null\n"
        "6. 只輸出合法 JSON 陣列，禁止任何解釋或 markdown\n"
        "格式：[" + _CHAR_SCHEMA_PROMPT + "]\n"
    )

    async with _server_lock:
        await _ensure_server(path, 8192)
        try:
            raw = await _chat(system, f"段落：\n{trimmed}", max_tokens=4096, temperature=0.2, prefill="[")
        finally:
            _arm_idle_stop()

    logger.debug("extract_char raw (%dc) head=%r tail=%r", len(raw), raw[:200], raw[-100:])

    chars = _parse_character_json(raw)
    logger.debug("extract_char parsed=%d chars, names=%s", len(chars), [c.get("name") for c in chars])
    if not chars:
        return [_empty_character_fields()]

    result = []
    for c in chars:
        _apply_defaults(c)
        result.append(c)
    return result


# ─── 情境欄位推斷 ─────────────────────────────────────────────────────────────

_CONTEXTUAL_FIELDS = [
    "age_hint", "body_type", "era_style", "signature_outfit",
    "skin_tone", "face_shape", "eye_shape",
    "color_palette", "accessories",
]

_KNOWN_CONTEXT_KEYS = (
    "gender", "age_hint", "body_type",
    "hair_color", "hair_style", "eye_color", "skin_tone",
    "face_shape", "eye_shape", "era_style", "signature_outfit",
    # 身份/氣質欄位——對服裝推斷非常重要
    "special_traits", "other_features", "distinctive_marks",
)

_INFER_BATCH_SIZE  = 20
_INFER_TOKENS_EACH = 160


async def _infer_contextual_fields(chars: list[dict]) -> list[dict]:
    to_infer = []
    for c in chars:
        missing = [f for f in _CONTEXTUAL_FIELDS if not c.get(f)]
        if missing:
            to_infer.append({"char": c, "missing": missing})

    if not to_infer:
        return []

    system = (
        "你是角色外觀推斷助手。根據每個角色「自己」的已知欄位，為其缺少的欄位填入合適的值。\n"
        "【策略】只根據該角色本人的已知資訊推斷；禁止參考同批次其他角色的欄位；無法從該角色自身資訊推斷的欄位填 null。\n"
        "【欄位規則】\n"
        f"- age_hint 只能是：{'|'.join(_VALID_AGE_HINTS)}\n"
        f"- body_type 只能是：{'|'.join(_VALID_BODY_TYPES)}\n"
        f"- hair_style 只能是：{'|'.join(_VALID_HAIR_STYLES)}\n"
        f"- era_style 常見值：{'|'.join(_SOFT_ERA_STYLES)}（亦可填其他合理描述）\n"
        f"- skin_tone 常見值：{'|'.join(_SOFT_SKIN_TONES)}（亦可填其他）\n"
        f"- face_shape 常見值：{'|'.join(_SOFT_FACE_SHAPES)}（亦可填其他）\n"
        f"- eye_shape 常見值：{'|'.join(_SOFT_EYE_SHAPES)}（亦可填其他）\n"
        "- signature_outfit：根據角色身份與 era_style 推斷服裝，必須包含至少四項細節：\n"
        "  ①主色調  ②款式/剪裁（長袍/短衫/裙裝…）  ③材質（絲綢/麻布/皮革…）  ④裝飾（刺繡圖案/滾邊/扣件/腰帶…）\n"
        "  身份參考：武者→勁裝/護甲；貴族→錦袍/華服；修士→道袍/禪衣；宮廷→朝服/宮裝；江湖→俠客裝/風塵服；\n"
        "           商人→長衫；農民→粗布短衫；現代學生→校服/休閒；現代職場→西裝/套裝\n"
        "  範例：「藏藍色武士長袍，領口繡銀線卷雲紋，腰繫玄色革帶，袖口束緊利落」\n"
        "        「月白色廣袖仙衣，裙擺飄逸，胸前繡淡金蓮花紋，肩披薄紗」\n"
        "        「深灰色粗布短打，領口磨損，右肩縫有補丁，腰間紮麻繩」\n"
        "- color_palette：角色整體主色調（如「白色＋金色」「黑紅」）\n"
        "- accessories：武器/首飾/隨身物品（如「青銅長劍」「白玉髮簪」），無特色填「無」\n"
        "【輸出】只輸出合法 JSON 陣列，只含 name 與需推斷的欄位，禁止任何解釋或 markdown\n"
        '範例：[{"name":"X","era_style":"古代中式","skin_tone":"白皙","face_shape":"瓜子臉","accessories":"無"}]'
    )

    def _build_line(item: dict) -> str:
        c = item["char"]
        known_parts = [f"{k}={c[k]}" for k in _KNOWN_CONTEXT_KEYS if c.get(k)]
        known_str   = "，".join(known_parts) or "無"
        missing_str = "、".join(item["missing"])
        return f'- 名稱：{c.get("name","")}，已知[{known_str}]，需填[{missing_str}]'

    results: list[dict] = []
    total_batches = (len(to_infer) + _INFER_BATCH_SIZE - 1) // _INFER_BATCH_SIZE
    for batch_idx, batch_start in enumerate(range(0, len(to_infer), _INFER_BATCH_SIZE)):
        batch   = to_infer[batch_start : batch_start + _INFER_BATCH_SIZE]
        lines   = [_build_line(item) for item in batch]
        max_tok = len(batch) * _INFER_TOKENS_EACH + 100

        try:
            raw = await _chat(
                system,
                "請為以下角色填寫缺少的欄位：\n" + "\n".join(lines),
                max_tokens=max_tok,
                temperature=0.3,
                prefill="[",
            )
        except Exception as e:
            logger.warning("infer_contextual batch %d/%d 失敗: %s", batch_idx + 1, total_batches, e)
            continue

        parsed = _parse_character_json(raw)
        logger.debug("infer_contextual batch %d/%d（%d chars → %d 結果）: %s",
                     batch_idx + 1, total_batches, len(batch), len(parsed), raw[:120])
        results.extend(parsed)

    return results


async def _infer_and_merge(accumulated: dict[str, dict]):
    chars_list     = list(accumulated.values())
    inferred_list  = await _infer_contextual_fields(chars_list)
    for inferred in inferred_list:
        name = (inferred.get("name") or "").strip()
        if name not in accumulated:
            continue
        for k, v in inferred.items():
            if k == "name" or not v:
                continue
            if not accumulated[name].get(k):
                accumulated[name][k] = v


async def infer_missing_fields(chars: list[dict]) -> list[dict]:
    needs = any(not c.get(f) for c in chars for f in _CONTEXTUAL_FIELDS)
    if not needs:
        return chars

    path = find_gguf()
    if not path:
        return chars

    name_map = {c.get("name", ""): c for c in chars}

    async with _server_lock:
        await _ensure_server(path, 4096)
        try:
            inferred_list = await _infer_contextual_fields(chars)
        finally:
            _arm_idle_stop()

    for inferred in inferred_list:
        name = (inferred.get("name") or "").strip()
        if name not in name_map:
            continue
        for k, v in inferred.items():
            if k == "name" or not v:
                continue
            if not name_map[name].get(k):
                name_map[name][k] = v

    return list(name_map.values())


# ─── 全書角色分析 ─────────────────────────────────────────────────────────────

async def analyze_characters(
    chapters_paragraphs: list[list[str]],
    on_progress=None,
    on_chapter_done=None,
    skip_chapters: set = frozenset(),
    initial_accumulated: dict = None,
) -> list[dict]:
    path = find_analysis_gguf()
    if not path:
        return []

    system = (
        "你是一個角色提取助手。\n"
        "以下是小說原文（可能跨多個章節），請找出所有具名角色（主角、配角均包含）。\n"
        "【規則】\n"
        "1. 提取所有有姓名的角色，包括主角及重要配角；路人、跑龍套、僅一句話提及的次要人物不列\n"
        "2. name 必須是該角色的真實姓名或常用稱呼（如「孔明」「多爾袞」「孝莊」）\n"
        "3. 嚴禁用代詞（他、她、此人、那人、那小子）或描述詞（逆賊、奸細、刺客）作為 name\n"
        "4. 同一角色統一使用最常出現的簡短稱呼（如「順治」而非「愛新覺羅·福臨」）\n"
        "5. 外觀欄位：只在原文對「該角色本人」有明確文字描寫時才填；禁止從其他角色的描述推斷、禁止憑空猜測；無描寫一律填 null\n"
        "6. 若整批文字都沒有任何具名角色出現，回傳空陣列 []\n"
        "7. 只輸出合法 JSON 陣列，禁止任何解釋或 markdown\n"
        "格式：[" + _CHAR_SCHEMA_PROMPT + "]\n"
    )

    accumulated: dict[str, dict] = dict(initial_accumulated) if initial_accumulated else {}
    total = len(chapters_paragraphs)

    try:
        from services.model_registry import get_llm_ctx
        n_ctx = get_llm_ctx("analysis")
    except Exception:
        n_ctx = 65536

    batches: list[list[tuple[int, str]]] = []
    current_batch: list[tuple[int, str]] = []
    current_chars = 0

    for i, paragraphs in enumerate(chapters_paragraphs):
        if i in skip_chapters:
            if on_progress:
                on_progress(int((i + 1) / total * 90), f"跳過第 {i + 1}/{total} 章（已完成）")
            continue
        chapter_text = "\n".join(paragraphs)
        chapter_len  = len(chapter_text)
        if current_batch and current_chars + chapter_len > _BATCH_CHARS:
            batches.append(current_batch)
            current_batch = [(i, chapter_text)]
            current_chars = chapter_len
        else:
            current_batch.append((i, chapter_text))
            current_chars += chapter_len

    if current_batch:
        batches.append(current_batch)

    if not batches:
        accumulated = _merge_aliases(accumulated)
        if on_progress:
            on_progress(100, "分析完成（全書已完成）")
        return list(accumulated.values())

    async with _server_lock:
        await _ensure_server(path, n_ctx)
        try:
            for b_idx, batch in enumerate(batches):
                chapter_indices = [ci for ci, _ in batch]
                first_ch = chapter_indices[0] + 1
                last_ch  = chapter_indices[-1] + 1
                if on_progress:
                    on_progress(
                        int(chapter_indices[-1] / total * 90),
                        f"分析第 {first_ch}–{last_ch}/{total} 章（批次 {b_idx + 1}/{len(batches)}）…",
                    )

                parts     = [f"【第 {ci + 1} 章】\n{text}" for ci, text in batch]
                full_text = "\n\n".join(parts)

                try:
                    raw = await _chat(
                        system,
                        full_text,
                        max_tokens=3000,
                        temperature=0.15,
                        prefill="[",
                    )
                except Exception as e:
                    logger.warning("批次 %d/%d 失敗，跳過: %s", b_idx + 1, len(batches), e)
                    continue

                parsed = _parse_character_json(raw)
                logger.debug("批次 %d/%d ch%d–%d: 解析到 %d 位 | %s",
                             b_idx + 1, len(batches), first_ch, last_ch, len(parsed), raw[:120])

                for c in parsed:
                    name = (c.get("name") or "").strip()
                    if not name or len(name) > 20 or not _is_valid_char_name(name):
                        if name:
                            logger.debug("過濾非名稱詞: %r", name)
                        continue
                    if name not in accumulated:
                        accumulated[name] = {
                            k: v for k, v in c.items()
                            if v is not None and v != "" and v != "不明"
                        }
                    else:
                        existing = accumulated[name]
                        for k, v in c.items():
                            if k == "name" or v is None or v == "" or v == "不明":
                                continue
                            current = existing.get(k)
                            if current is None:
                                existing[k] = v  # 空欄位直接填入
                            elif isinstance(v, str) and isinstance(current, str) and len(v) > len(current):
                                existing[k] = v  # 後面章節的描述更詳細則覆蓋

                if on_chapter_done:
                    for ci, _ in batch:
                        await on_chapter_done(ci, accumulated)

            if on_progress:
                on_progress(92, "推斷角色情境特徵…")
            await _infer_and_merge(accumulated)

        finally:
            _arm_idle_stop()

    for char in accumulated.values():
        char.pop("_inferred_set", None)
        char.pop("inferred_fields", None)
        _apply_defaults(char)

    accumulated = _merge_aliases(accumulated)

    if on_progress:
        on_progress(100, "分析完成")

    return list(accumulated.values())
