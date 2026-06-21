"""
角色描述 → Prompt 組合工具。
依賴 settings.py（取 negative_prompt），依賴 llm_engine（expand_prompt）。
"""
import hashlib
import logging

logger = logging.getLogger(__name__)


# ─── 中文角色描述 ─────────────────────────────────────────────────────────────

def build_character_fragment(char: dict) -> str:
    parts: list[str] = []
    g = char.get("gender") or ""

    if g:                             parts.append(g)
    if char.get("age_hint"):          parts.append(char["age_hint"])
    if char.get("skin_tone"):         parts.append(f'{char["skin_tone"]}膚')
    if char.get("face_shape"):        parts.append(char["face_shape"])

    hair = (char.get("hair_color") or "") + (char.get("hair_style") or "")
    if hair:                          parts.append(hair)

    eye_color = char.get("eye_color") or ""
    eye_shape = char.get("eye_shape") or ""
    if eye_color and eye_shape:       parts.append(f'{eye_color}{eye_shape}')
    elif eye_color:                   parts.append(f'{eye_color}瞳')
    elif eye_shape:                   parts.append(eye_shape)

    if char.get("body_type"):         parts.append(char["body_type"])
    if char.get("height_cm"):         parts.append(f'{char["height_cm"]}cm')
    if char.get("weight_kg"):         parts.append(f'{char["weight_kg"]}kg')
    if g == "女":
        if char.get("bwh"):           parts.append(f'三圍{char["bwh"]}')
        if char.get("cup_size"):      parts.append(f'{char["cup_size"]}罩杯')

    if char.get("era_style"):         parts.append(char["era_style"])
    if char.get("signature_outfit"):  parts.append(char["signature_outfit"])
    if char.get("color_palette"):     parts.append(f'主色調：{char["color_palette"]}')
    if char.get("accessories"):       parts.append(char["accessories"])
    if char.get("distinctive_marks"): parts.append(char["distinctive_marks"])
    if char.get("special_traits"):    parts.append(char["special_traits"])
    if char.get("other_features"):    parts.append(char["other_features"])

    if parts:
        return "，".join(parts)
    return char.get("description") or ""


# ─── Z-Image 自然語言角色描述 ─────────────────────────────────────────────────
# Z-Image 用 Qwen3 文字編碼器，偏好連貫的自然語言句子，而非 SDXL/CLIP 的逗號
# danbooru 標籤。這裡把與 build_character_fragment 相同的決定性外觀欄位組成一句
# 流暢中文描述（同角色每次一致，完全不經 LLM），是「架構分形態」中 zimage 的角色片段。

_AGE_PROSE_ZH: dict[str, str] = {
    "幼兒":      "年幼的",
    "少女/少年": "年輕的",
    "青年":      "年輕的",
    "壯年":      "成熟的",
    "中年":      "中年的",
    "老年":      "年長的",
}


def build_character_description_zimage(char: dict) -> str:
    """把角色固定外觀組成「一句」連貫中文描述，供 Z-Image（Qwen3 編碼器）使用。
    與 build_character_fragment 取用相同欄位，但輸出散文而非逗號標籤。"""
    g = char.get("gender") or ""
    noun = {"女": "女子", "男": "男子"}.get(g, "人物")
    age  = _AGE_PROSE_ZH.get(char.get("age_hint") or "", "")
    subject = f"一名{age}{noun}"

    looks: list[str] = []

    hair = (char.get("hair_color") or "") + (char.get("hair_style") or "")
    if hair:
        looks.append(hair)

    eye_color = char.get("eye_color") or ""
    eye_shape = char.get("eye_shape") or ""
    if eye_color and eye_shape:
        looks.append(f"{eye_color}的{eye_shape}")
    elif eye_color:
        looks.append(f"{eye_color}的眼眸")
    elif eye_shape:
        looks.append(eye_shape)

    if char.get("face_shape"):
        looks.append(char["face_shape"])
    if char.get("skin_tone"):
        looks.append(f"{char['skin_tone']}的肌膚")
    if char.get("body_type"):
        looks.append(f"{char['body_type']}的身形")
    if g == "女":
        if char.get("bwh"):
            looks.append(f"三圍{char['bwh']}")
        if char.get("cup_size"):
            looks.append(f"{char['cup_size']}罩杯")

    desc = subject
    if looks:
        desc += "，" + "、".join(looks)

    # 服裝（era_style 提供時代脈絡，signature_outfit 提供具體款式）
    era    = char.get("era_style") or ""
    outfit = char.get("signature_outfit") or ""
    attire = "，".join(p for p in (era, outfit) if p)
    if attire:
        desc += f"，身著{attire}"

    if char.get("color_palette"):
        desc += f"，整體色調以{char['color_palette']}為主"

    acc = (char.get("accessories") or "").strip()
    if acc and acc not in ("無", "無特色"):
        desc += f"，配有{acc}"

    marks = (char.get("distinctive_marks") or "").strip()
    if marks:
        desc += f"，{marks}"

    return desc + "。"


# ─── 英文 danbooru tags 常數 ──────────────────────────────────────────────────

_GENDER_EN = {"女": "1girl", "男": "1boy"}

_AGE_HINT_EN: dict[str, dict[str, str]] = {
    "幼兒":     {"女": "child, young girl",    "男": "young boy, child"},
    "少女/少年": {"女": "teenage girl, young",  "男": "teenage boy, young"},
    "青年":     {"女": "",                      "男": ""},
    "壯年":     {"女": "mature female, adult",  "男": "mature male, adult"},
    "中年":     {"女": "mature female, middle-aged", "男": "middle-aged man"},
    "老年":     {"女": "elderly woman",         "男": "elderly man"},
}

_PERSONALITY_EXPR_KW: list[tuple[str, str]] = [
    ("冷酷", "cold expression, sharp eyes, expressionless"),
    ("冷漠", "aloof expression, distant gaze"),
    ("活潑", "cheerful expression, bright eyes, smiling"),
    ("天真", "innocent expression, wide eyes, open mouth smile"),
    ("溫柔", "gentle expression, soft eyes, warm smile"),
    ("霸氣", "commanding expression, intense gaze, stern"),
    ("沉穩", "calm expression, steady gaze, composed"),
    ("傲慢", "haughty expression, condescending look, smug"),
    ("狡猾", "cunning expression, scheming look, sly smile"),
    ("憂鬱", "melancholic expression, sad eyes, downcast"),
    ("邪魅", "seductive expression, alluring eyes, slight smirk"),
    ("嚴肅", "serious expression, stern look, furrowed brows"),
    ("睿智", "wise expression, intelligent eyes, calm"),
    ("溫和", "gentle smile, kind eyes, friendly expression"),
    ("神秘", "mysterious expression, enigmatic smile, half-closed eyes"),
    ("堅定", "determined expression, resolute gaze, firm"),
]

_EXPRESSION_POOL = [
    "calm expression", "gentle expression", "serene expression", "cheerful expression",
    "serious expression", "confident expression", "focused expression",
    "warm smile", "determined expression",
    "elegant expression", "mysterious expression", "thoughtful expression",
    "gentle smile", "composed expression", "soft expression", "vibrant expression",
]

_HAIR_COLOR_EN = {
    # ── 動畫深色變體（新增，精確匹配優先於單字 fallback）──────────────────
    "午夜藍":  "dark blue hair",
    "深紫黑":  "dark purple hair",
    "藏藍黑":  "navy blue hair",
    "墨綠黑":  "very dark green hair",
    "暗炭黑":  "dark charcoal hair",
    "深青黑":  "dark teal hair",
    "星夜黑":  "black hair, starry sheen",
    "深靛黑":  "dark indigo hair",
    "紅棕":    "auburn hair",
    "淺棕":    "light brown hair",
    "深棕":    "dark brown hair",
    # ── 單字 fallback（匹配所有含該字的顏色）──────────────────────────────
    "銀": "silver hair", "金": "blonde hair", "黑": "black hair",
    "棕": "brown hair",  "紅": "red hair",    "白": "white hair",
    "藍": "blue hair",   "紫": "purple hair", "粉": "pink hair",
    "橙": "orange hair", "灰": "grey hair",   "綠": "green hair",
}
_HAIR_STYLE_EN = {
    "雙馬尾": "twintails", "馬尾": "ponytail", "側馬尾": "side ponytail",
    "丸子頭": "hair bun", "辮子": "braid", "短髮": "short hair",
    "中髮": "medium hair", "長髮": "long hair", "捲髮": "curly hair",
    "卷髮": "curly hair", "波浪髮": "wavy hair", "直髮": "straight hair",
}
_EYE_COLOR_EN = {
    # ── 動畫深色變體（精確匹配優先）────────────────────────────────────────
    "午夜藍":  "dark blue eyes",
    "深紫":    "dark purple eyes",
    "藏藍":    "navy blue eyes",
    "暗青":    "dark teal eyes",
    "深灰":    "dark gray eyes",
    "深靛":    "dark indigo eyes",
    "深褐":    "dark brown eyes",
    # ── 單字 fallback ────────────────────────────────────────────────────
    "藍": "blue eyes",    "紅": "red eyes",    "金": "golden eyes",
    "黑": "black eyes",   "棕": "brown eyes",  "綠": "green eyes",
    "紫": "purple eyes",  "銀": "silver eyes", "橙": "orange eyes",
    "粉": "pink eyes",    "灰": "grey eyes",   "琥珀": "amber eyes",
}

# ── 動畫誇示化：自然黑/棕 → hash 分配各自的深色動畫變體 ──────────────────────
# 現實中東方人都是黑/棕，但動畫刻意給每個角色不同的色調讓他們可被辨識
_ANIME_HAIR_REMAP: dict[str, list[str]] = {
    "黑": [
        "black hair",          # 保留一部分真黑
        "dark blue hair",
        "dark purple hair",
        "navy blue hair",
        "very dark green hair",
        "dark charcoal hair",
        "dark teal hair",
        "black hair, dark blue sheen",
    ],
    "深棕": [
        "dark brown hair", "dark auburn hair",
        "very dark red hair", "dark chestnut hair",
    ],
    "棕色": [
        "brown hair", "chestnut hair", "auburn hair", "warm brown hair",
    ],
}
_ANIME_EYE_REMAP: dict[str, list[str]] = {
    "黑": [
        "black eyes",
        "dark blue eyes",
        "dark purple eyes",
        "navy blue eyes",
        "dark teal eyes",
        "dark gray eyes",
    ],
    "深褐": [
        "dark brown eyes", "amber eyes", "dark amber eyes", "dark hazel eyes",
    ],
    "棕": [
        "brown eyes", "amber eyes", "warm brown eyes", "hazel eyes",
    ],
}

# ── 罩杯視覺標籤（用 Danbooru 標準乳型標籤做誇示差異化）────────────────────────
_CUP_SIZE_EN: dict[str, str] = {
    "A": "flat chest",
    "B": "small breasts",
    "C": "medium breasts",
    "D": "large breasts",
    "E": "large breasts",
    "F": "very large breasts",
    "G": "huge breasts",
    "H": "gigantic breasts",
}

# ── 服裝誇示化：素淡服裝加上角色專屬裝飾細節 ─────────────────────────────────
# 當 outfit 是通用素衣/日常服飾時，hash 選一個視覺差異化的裝飾標籤
_GENERIC_OUTFIT_KW = {"日常", "素衣", "白衣", "布衣", "尋常", "普通", "平常", "日常服飾"}
_OUTFIT_DETAIL_POOL = [
    "embroidered trim",
    "ornate collar",
    "flowing sleeves",
    "contrasting sash",
    "layered hemline",
    "decorative buttons",
    "embroidered cuffs",
    "asymmetric neckline",
    "gold-trimmed hem",
    "elaborate belt",
    "tasseled collar",
    "cloud pattern embroidery",
    "intricate stitching",
    "pleated skirt panel",
    "scholar ribbon",
]
_SKIN_EN: list[tuple[str, str]] = [
    ("蒼白", "very pale skin"), ("死白", "very pale skin"),
    # 白皙/白 在中文只是「自然白皙」，Danbooru 的 pale skin 是過白/蒼白；改用 fair skin
    ("白皙", "fair skin"), ("米白", "fair skin"), ("細膩白", "fair skin"),
    ("小麥", "lightly tanned skin"), ("古銅", "tanned skin"),
    ("棕褐", "tan skin"), ("深褐", "dark skin"), ("黑色", "dark skin"),
    ("金屬光澤", "metallic skin"),
    ("白", "fair skin"), ("黑", "dark skin"), ("棕", "tan skin"), ("黃", "light skin"),
]
_BODY_EN = {
    "嬌小": "petite, short stature",
    "消瘦": "skinny, thin",
    "纖細": "slender",
    "苗條": "slender",
    "適中": "",            # 不加標籤，讓模型自由發揮
    "健美": "athletic body, toned figure",
    "健壯": "athletic body, toned figure",
    "高挑": "tall, long legs",
    "豐滿": "voluptuous, full figure, wide hips",
    "豐腴": "plump, soft body",
    "高挑豐滿": "tall, voluptuous, full figure",
    "魁梧": "muscular, broad shoulders, large build",
    "窈窕": "graceful, shapely figure",
}
_EYE_SHAPE_EN = {
    # ── 基礎眼形 ────────────────────────────────────────────────────
    "杏眼":  "almond eyes",
    "水杏眼": "watery almond eyes",
    "圓眼":  "round eyes",
    "大眼":  "wide eyes",
    # ── 上挑系（銳利感）────────────────────────────────────────────
    "鳳眼":  "fox eyes, sharp eyes",
    "丹鳳眼": "upturned eyes",
    "細長眼": "tsurime eyes",
    "吊梢眼": "tsurime eyes",
    "貓眼":  "cat eyes",
    "凌厲眼": "fierce eyes, sharp gaze",
    # ── 下垂系（溫柔感）────────────────────────────────────────────
    "垂眼":  "tareme eyes",
    "下垂眼": "tareme eyes",
    "鹿眸":  "doe eyes",
    # ── 媚眼系（魅惑感）────────────────────────────────────────────
    "桃花眼": "seductive eyes, bedroom eyes",
    "媚眼":  "bedroom eyes",
    "含情目": "smoldering eyes",
    # ── 神韻系（清澈/深邃）──────────────────────────────────────────
    "明眸":  "bright eyes, clear eyes",
    "秋水眼": "limpid eyes",
    "星眸":  "sparkling eyes",
    "深邃眼": "deep-set eyes",
    # ── 特殊 ─────────────────────────────────────────────────────
    "鬥雞眼": "crossed eyes",
}
_FACE_SHAPE_EN = {
    "鵝蛋臉": "oval face", "圓臉": "round face", "瓜子臉": "v-shaped face",
    "方臉": "square face", "尖下巴": "sharp chin",
}
# ── era_style → Danbooru 時代/風格錨定標籤 ────────────────────────────────────
# 精確匹配優先（長詞在前），fallback 到子串匹配
_ERA_STYLE_EN: list[tuple[str, str]] = [
    # 中式古代
    ("宮廷貴族",    "hanfu, chinese imperial court clothing, elaborate hair ornaments"),
    ("武俠江湖",    "hanfu, ancient chinese clothes, wuxia"),
    ("古代中式",    "hanfu, ancient chinese clothes, chinese traditional costume"),
    ("古代日式",    "kimono, japanese traditional clothes"),
    ("古代歐式",    "medieval european clothes, corset, european costume"),
    ("中世紀奇幻",  "medieval fantasy clothes, fantasy costume"),
    ("民國",        "republic of china era clothes, cheongsam"),
    # 現代
    ("商務正式",    "business suit, formal wear"),
    ("學生制服",    "school uniform"),
    ("現代都市",    "modern clothes, casual wear"),
    ("現代休閒",    "casual clothes, modern"),
    # 幻想 / 科幻
    ("高魔幻",      "high fantasy outfit, magical robes, fantasy costume"),
    ("末世廢土",    "post-apocalyptic clothes, wasteland outfit, tattered clothes"),
    ("科幻機甲",    "futuristic suit, sci-fi outfit, mecha"),
    ("星際宇宙",    "spacesuit, futuristic, sci-fi uniform"),
    ("賽博朋克",    "cyberpunk outfit, neon accents, futuristic streetwear"),
    ("蒸氣龐克",    "steampunk outfit, victorian era, gears and goggles"),
]

_OUTFIT_KW: list[tuple[str, str]] = [
    ("女僕裝", "maid uniform"), ("女僕", "maid"),
    ("學生服", "school uniform"), ("校服", "school uniform"),
    ("旗袍", "qipao"), ("和服", "kimono"),
    ("鎧甲", "armor"), ("盔甲", "armor"),
    ("比基尼", "bikini"), ("泳衣", "swimsuit"),
    ("漢服", "hanfu"), ("古裝", "hanfu, ancient chinese clothes"),
    ("仙俠", "xianxia outfit"), ("修仙", "xianxia outfit"),
    ("制服", "uniform"),
    ("長袍", "long robe"), ("袍", "robe"),
    ("長裙", "long skirt"), ("短裙", "short skirt"), ("裙", "skirt"),
    ("長衣", "long dress"), ("衣", "dress"),
    ("褲", "pants"),
]
_OUTFIT_COLOR_KW: list[tuple[str, str]] = [
    ("白", "white"), ("黑", "black"), ("紅", "red"), ("藍", "blue"),
    ("綠", "green"), ("黃", "yellow"), ("紫", "purple"), ("粉", "pink"),
    ("橙", "orange"), ("銀", "silver"), ("金", "gold"), ("灰", "grey"),
]
_ACCESSORY_KW: list[tuple[str, str]] = [
    ("教鞭", "holding whip, whip"), ("鞭子", "holding whip, whip"), ("鞭", "whip"),
    ("太刀", "holding sword, tachi"), ("長劍", "holding sword, longsword"),
    ("劍", "holding sword, sword"), ("刀", "holding sword"),
    ("法杖", "holding staff, magic staff"), ("魔杖", "holding wand"),
    ("弓箭", "holding bow, bow and arrow"), ("弓", "holding bow"),
    ("折扇", "holding fan, folding fan"), ("扇子", "folding fan"), ("扇", "fan"),
    ("雨傘", "umbrella"), ("傘", "umbrella"),
    ("眼鏡", "glasses"), ("墨鏡", "sunglasses"),
    ("發簪", "hair ornament, hair pin"), ("髮釵", "hairpin, hair ornament"),
    ("項鍊", "necklace"), ("手鐲", "bracelet"), ("耳環", "earrings"),
    ("帽子", "hat"), ("頭盔", "helmet"),
]
_SPECIAL_TRAIT_KW: list[tuple[str, str]] = [
    ("貓耳", "cat ears, nekomimi"), ("獸耳", "animal ears"),
    ("狐耳", "fox ears"), ("兔耳", "rabbit ears, bunny ears"),
    ("翅膀", "wings"), ("天使翅膀", "angel wings"), ("惡魔翅膀", "demon wings"),
    ("尾巴", "tail"), ("狐狸尾巴", "fox tail"), ("狐狸尾", "fox tail"),
    ("角", "horns"), ("獸角", "horns"), ("惡魔角", "demon horns"),
    ("刀疤", "scar"), ("疤痕", "scar"), ("疤", "scar"),
    ("眼罩", "eyepatch"), ("眼帶", "eyepatch"),
    ("義手", "prosthetic arm"), ("義肢", "prosthetic limb"),
    ("紋身", "tattoo"), ("刺青", "tattoo"),
    ("發光眼", "glowing eyes"), ("異色瞳", "heterochromia"),
    ("透明", "transparent body"), ("半透明", "translucent"),
    ("骷髏", "skull"), ("骨骼", "skeleton"),
]


def _match_kw(text: str, kw_list: list[tuple[str, str]]) -> list[str]:
    found: list[str] = []
    for kw, tag in kw_list:
        if kw in text:
            found.append(tag)
    return found


def _match_kw_dedup(text: str, kw_list: list[tuple[str, str]]) -> list[str]:
    """長關鍵字優先匹配，跳過已匹配關鍵字的子串（避免「短裙」和「裙」同時命中）。"""
    matched_kws: list[str] = []
    found: list[str] = []
    for kw, tag in sorted(kw_list, key=lambda x: -len(x[0])):
        if kw in text and not any(kw in mk for mk in matched_kws):
            matched_kws.append(kw)
            found.append(tag)
    return found


def build_character_fragment_en(char: dict, seed: int | None = None, include_expression: bool = False) -> str:
    """scene illustration 預設 include_expression=False，讓 LLM 從場景推斷表情。
    角色設定圖 / 立繪才傳 include_expression=True。"""
    parts: list[str] = []
    name = char.get("name", "") or ""
    g = char.get("gender") or ""
    gender_en = _GENDER_EN.get(g, "")
    if gender_en:
        parts.append(gender_en)

    age_hint = char.get("age_hint") or ""
    age_tags = _AGE_HINT_EN.get(age_hint, {}).get("女" if g == "女" else "男", "")
    if age_tags:
        parts.append(age_tags)

    # ── 眼睛優先（臉部最關鍵特徵，放早讓 CLIP 權重最高）──
    eye_color = char.get("eye_color") or ""
    _eye_tag  = ""
    for k, v in _EYE_COLOR_EN.items():
        if k in eye_color:
            _eye_tag = v
            break
    _PLAIN_DARK_EYE = {"黑色", "黑", "黑眸", "烏黑", "深黑"}
    if _eye_tag and name and eye_color in _PLAIN_DARK_EYE:
        for remap_kw, remap_pool in _ANIME_EYE_REMAP.items():
            if remap_kw in eye_color:
                h = int(hashlib.md5(f"{name}:eye".encode()).digest()[:4].hex(), 16)
                _eye_tag = remap_pool[h % len(remap_pool)]
                break
    if _eye_tag:
        parts.append(_eye_tag)
    eye_shape = char.get("eye_shape") or ""
    for k, v in _EYE_SHAPE_EN.items():
        if k in eye_shape:
            parts.append(v)
            break

    face_shape = char.get("face_shape") or ""
    for k, v in _FACE_SHAPE_EN.items():
        if k in face_shape:
            parts.append(v)
            break

    # ── 髮色/髮型（眼睛之後）──
    hair_color = char.get("hair_color") or ""
    hair_style = char.get("hair_style") or ""
    combined   = hair_color + hair_style
    _hair_tag  = ""
    for k, v in _HAIR_COLOR_EN.items():
        if k in combined:
            _hair_tag = v
            break
    _PLAIN_DARK = {"黑色", "黑", "黑髮", "烏黑", "漆黑", "深黑", "墨黑"}
    if _hair_tag and name and hair_color in _PLAIN_DARK:
        for remap_kw, remap_pool in _ANIME_HAIR_REMAP.items():
            if remap_kw in hair_color:
                h = int(hashlib.md5(f"{name}:hair".encode()).digest()[:4].hex(), 16)
                _hair_tag = remap_pool[h % len(remap_pool)]
                break
    if _hair_tag:
        parts.append(_hair_tag)
    for k, v in _HAIR_STYLE_EN.items():
        if k in combined:
            if v not in ", ".join(parts):
                parts.append(v)
            break

    skin = char.get("skin_tone") or ""
    for k, v in _SKIN_EN:
        if k in skin:
            parts.append(v)
            break

    # 身材：精確匹配優先，再 fallback substring（避免「高挑豐滿」被「高挑」搶先）
    body = char.get("body_type") or ""
    body_tag = _BODY_EN.get(body, None)
    if body_tag is None:
        for k, v in sorted(_BODY_EN.items(), key=lambda x: -len(x[0])):
            if k in body:
                body_tag = v
                break
    if body_tag:
        parts.append(body_tag)

    # 罩杯視覺誇示化（僅女性）：使用 Danbooru 乳型標籤做視覺差異化
    if g == "女":
        cup = (char.get("cup_size") or "").strip().upper()
        cup_tag = _CUP_SIZE_EN.get(cup, "")
        if cup_tag:
            parts.append(cup_tag)

    # 身高視覺標籤（性別感知，body_type 已含「高挑/嬌小」時跳過避免重複）
    _body_already_tall  = "高挑" in body
    _body_already_short = "嬌小" in body or "消瘦" in body
    try:
        hcm = int(char.get("height_cm") or 0)
        if hcm > 0:
            if g == "女":
                if hcm <= 150 and not _body_already_short: parts.append("very short")
                elif hcm <= 156 and not _body_already_short: parts.append("short")
                elif hcm >= 173 and not _body_already_tall: parts.append("tall")
            else:
                if hcm <= 162 and not _body_already_short: parts.append("short")
                elif hcm >= 183 and not _body_already_tall: parts.append("tall")
    except Exception:
        pass

    if include_expression:
        personality_src = (
            (char.get("special_traits") or "")
            + (char.get("other_features") or "")
            + (char.get("distinctive_marks") or "")
        )
        expr_tag = ""
        for kw, tag in _PERSONALITY_EXPR_KW:
            if kw in personality_src:
                expr_tag = tag
                break
        if not expr_tag and name:
            h = int(hashlib.md5(f"{name}:expr".encode()).digest()[:4].hex(), 16)
            expr_tag = _EXPRESSION_POOL[h % len(_EXPRESSION_POOL)]
        if expr_tag:
            parts.append(expr_tag)

    era    = char.get("era_style") or ""
    outfit = char.get("signature_outfit") or ""
    outfit_src = era + outfit

    # era_style → Danbooru 時代錨定（先注入，確保模型使用正確時代服裝）
    era_tag = ""
    for kw, tag in _ERA_STYLE_EN:
        if kw in era:
            era_tag = tag
            break
    if era_tag:
        parts.append(era_tag)

    if outfit_src:
        outfit_colors = [t for kw, t in _OUTFIT_COLOR_KW if kw in outfit_src]
        outfit_types  = _match_kw_dedup(outfit_src, _OUTFIT_KW)  # 長優先，避免「短裙」+「裙」重複

        # 素衣誇示化：普通服裝加裝飾細節
        # 使用 seed（每次生成可以換不同細節），沒有 seed 時 fallback 到 name hash
        _is_generic_outfit = any(kw in outfit_src for kw in _GENERIC_OUTFIT_KW)
        _outfit_accent = ""
        if _is_generic_outfit:
            if seed is not None:
                _outfit_accent = _OUTFIT_DETAIL_POOL[seed % len(_OUTFIT_DETAIL_POOL)]
            elif name:
                h = int(hashlib.md5(f"{name}:outfit".encode()).digest()[:4].hex(), 16)
                _outfit_accent = _OUTFIT_DETAIL_POOL[h % len(_OUTFIT_DETAIL_POOL)]

        if outfit_colors and outfit_types:
            for t in outfit_types:
                for c in outfit_colors:
                    parts.append(f"{c} {t}")
                    break
        elif outfit_types:
            parts.extend(outfit_types)
        elif outfit_colors:
            parts.append(outfit_colors[0] + " outfit")

        if _outfit_accent:
            parts.append(_outfit_accent)

    accessories = char.get("accessories") or ""
    if accessories:
        parts.extend(_match_kw(accessories, _ACCESSORY_KW))

    traits_src = (char.get("special_traits") or "") + (char.get("distinctive_marks") or "") + (char.get("other_features") or "")
    if traits_src:
        parts.extend(_match_kw(traits_src, _SPECIAL_TRAIT_KW))

    return ", ".join(parts) if parts else ""


def character_seed_for(book_id: str, name: str) -> int:
    h = hashlib.md5(f"{book_id}:{name}".encode()).digest()
    return int.from_bytes(h[:4], "big") & 0x7FFF_FFFF


# ─── Prompt 擴寫 ──────────────────────────────────────────────────────────────

async def _expand_prompt(
    raw_text: str,
    character_descriptions: "list[dict] | None" = None,
    style_hint: str = "",
    target_arch: str = "sdxl",
) -> tuple[str, bool]:
    from services import llm_engine
    return await llm_engine.expand_prompt(
        raw_text, character_descriptions, style_hint, target_arch=target_arch
    )


def _infer_is_anime(text: str) -> bool:
    from services.llm_engine import _detect_is_anime
    return _detect_is_anime(text)


# ─── Negative prompt ─────────────────────────────────────────────────────────

_STYLE_NEG_REMOVES: list[tuple[str, set[str]]] = [
    ("sketch",      {"monochrome", "greyscale"}),
    ("pencil",      {"monochrome", "greyscale"}),
    ("monochrome",  {"monochrome", "greyscale"}),
    ("ink",         {"monochrome", "greyscale"}),
    ("linework",    {"monochrome", "greyscale"}),
    ("watercolor",  {"flat color", "flat shading"}),
    ("ghibli",      {"flat color", "flat shading"}),
    ("flat color",  {"flat color", "flat shading"}),
    ("cel shading", {"flat color", "flat shading"}),
]


def _build_negative_prompt(is_anime: bool, is_turbo: bool = False, style_hint: str = "") -> str:
    from services.illustration.settings import get_settings
    if is_turbo:
        return "blurry, ugly, bad quality, deformed"
    base = get_settings().negative_prompt
    lower = style_hint.lower()

    removes: set[str] = set()
    for kw, neg_set in _STYLE_NEG_REMOVES:
        if kw in lower:
            removes.update(neg_set)
    if removes:
        parts = [p.strip() for p in base.split(",") if p.strip().lower() not in {r.lower() for r in removes}]
        base = ", ".join(parts)

    if is_anime:
        return (
            base
            + ", realistic, photorealistic, 3d render, photographic, photo"
            + ", chibi, q version, super deformed, 4koma, comic panel, comic strip,"
            " manga panel, multiple views, character sheet, reference sheet"
        )
    else:
        return base + ", anime, cartoon, illustration, drawing, 2d, flat color"


def _build_negative_prompt_sheet(is_anime: bool, is_turbo: bool = False, style_hint: str = "") -> str:
    if is_turbo:
        return "blurry, ugly, bad quality, deformed, multiple characters, chibi"
    base = _build_negative_prompt(is_anime, style_hint=style_hint)
    base_parts = [p.strip() for p in base.split(",") if p.strip().lower() != "simple background"]
    base = ", ".join(base_parts)
    return (
        base + ", chibi, multiple characters, multiple views, reference sheet, "
        "character sheet, crowd, group, q version, super deformed, bad proportions"
    )
