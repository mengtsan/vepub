"""
角色 JSON schema 常數、解析、欄位驗證與補完。
不依賴 server.py，可獨立在 CI 環境中測試。
"""
import hashlib as _hashlib
import json as _json
import logging
import re

from config import BATCH_CHARS

logger = logging.getLogger(__name__)

# ─── JSON 解析工具 ─────────────────────────────────────────────────────────────

_FIELD_ALIASES: dict[str, str] = {
    "age": "age_hint", "age_hints": "age_hint", "ageHint": "age_hint",
    "skinTone": "skin_tone", "skin": "skin_tone",
    "faceShape": "face_shape", "face": "face_shape",
    "hairColor": "hair_color", "hairStyle": "hair_style",
    "eyeColor": "eye_color", "eyeShape": "eye_shape",
    "bodyType": "body_type",
    "height": "height_cm", "height_km": "height_cm", "heightCm": "height_cm",
    "weight": "weight_kg", "weightKg": "weight_kg",
    "cupSize": "cup_size",
    "signatureOutfit": "signature_outfit", "outfit": "signature_outfit",
    "eraStyle": "era_style", "era": "era_style", "setting": "era_style",
    "colorPalette": "color_palette", "palette": "color_palette",
    "otherFeatures": "other_features",
    "distinctiveMarks": "distinctive_marks", "marks": "distinctive_marks",
    "specialTraits": "special_traits", "traits": "special_traits",
}


def _normalize_char(c: dict) -> dict:
    return {_FIELD_ALIASES.get(k, k): v for k, v in c.items()}


def _parse_character_json(raw: str) -> list[dict]:
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", raw).strip()

    if cleaned.startswith("[["):
        cleaned = cleaned[1:]

    start = cleaned.find('[')
    if start != -1:
        try:
            data, _ = _json.JSONDecoder().raw_decode(cleaned, start)
            if isinstance(data, list):
                if data and isinstance(data[0], list):
                    data = data[0]
                result = [_normalize_char(c) for c in data if isinstance(c, dict)]
                if result:
                    return result
        except _json.JSONDecodeError:
            pass

    objects = []
    decoder = _json.JSONDecoder()
    pos = 0
    while pos < len(cleaned):
        brace = cleaned.find('{', pos)
        if brace == -1:
            break
        try:
            obj, end = decoder.raw_decode(cleaned, brace)
            if isinstance(obj, dict):
                objects.append(_normalize_char(obj))
            pos = end
        except _json.JSONDecodeError:
            pos = brace + 1
    return objects


# ─── 思考內容清除 ─────────────────────────────────────────────────────────────

_THINKING_STARTS = (
    "here's a thinking", "let me think", "let me analyze",
    "thinking process", "i'll analyze", "i need to",
    "okay,", "ok,", "alright,", "sure,",
)


def _strip_inline_thinking(text: str) -> str:
    if not any(text.lower().startswith(p) for p in _THINKING_STARTS):
        return text

    lower = text.lower()
    for marker in (
        "\n\n---", "final output:", "final answer:", "output:", "result:",
        "image prompt:", "tags:", "prompt:", "here are the tags:",
        "here is the prompt:", "the image prompt:", "the tags:",
    ):
        idx = lower.rfind(marker)
        if idx != -1:
            extracted = text[idx + len(marker):].strip()
            if extracted:
                return extracted

    paras = [p.strip() for p in text.split('\n\n') if p.strip()]
    if len(paras) >= 2:
        return paras[-1]

    return text


# ─── 角色欄位 schema 常數 ──────────────────────────────────────────────────────

_VALID_GENDER     = ("女", "男", "中性")
_VALID_AGE_HINTS  = ("幼兒", "少女/少年", "青年", "壯年", "中年", "老年")
_VALID_BODY_TYPES = ("嬌小", "消瘦", "苗條", "纖細", "適中", "窈窕", "健美", "高挑", "豐腴", "豐滿", "高挑豐滿", "魁梧")
_VALID_HAIR_STYLES= ("長直", "長波浪", "長捲", "長辮", "盤髮", "古典髮髻",
                     "馬尾", "雙馬尾", "束髮", "中長", "短髮", "寸頭", "光頭")
_VALID_CUP_SIZES  = ("A", "B", "C", "D", "E", "F", "G", "H")

_SOFT_HAIR_COLORS = (
    # 動畫深色變體
    "午夜藍", "深紫黑", "藏藍黑", "墨綠黑", "暗炭黑", "深青黑", "星夜黑",
    # 原色
    "黑色", "深棕", "棕色", "淺棕", "紅棕", "金色", "淡金", "銀白", "白色",
    "紅色", "橙色", "藍色", "紫色", "翠綠", "粉色", "多色漸變",
)
_SOFT_EYE_COLORS  = (
    # 動畫深色變體
    "午夜藍", "深紫", "藏藍", "暗青", "深灰", "深靛",
    # 原色
    "黑色", "深褐", "棕色", "琥珀", "藍色", "藍紫", "綠色",
    "金色", "紅色", "銀色", "紫色", "异色瞳",
)
_SOFT_SKIN_TONES  = ("白皙", "米白", "小麥色", "棕褐", "深褐", "黑色", "蒼白（病態）", "金屬光澤")
_SOFT_FACE_SHAPES = ("瓜子臉", "圓臉", "方臉", "長臉", "尖臉", "棱角分明")
_SOFT_EYE_SHAPES  = (
    # 基礎
    "杏眼", "水杏眼", "圓眼", "大眼",
    # 上挑銳利
    "鳳眼", "丹鳳眼", "細長眼", "吊梢眼", "貓眼", "凌厲眼",
    # 下垂溫柔
    "垂眼", "鹿眸",
    # 媚眼魅惑
    "桃花眼", "媚眼", "含情目",
    # 清澈深邃
    "明眸", "秋水眼", "星眸", "深邃眼",
)
_SOFT_ERA_STYLES  = ("現代都市", "現代休閒", "商務正式", "學生制服",
                     "古代中式", "武俠江湖", "宮廷貴族", "民國",
                     "古代日式", "古代歐式", "中世紀奇幻",
                     "高魔幻", "末世廢土", "科幻機甲", "星際宇宙",
                     "賽博朋克", "蒸氣龐克")


def _fmt_soft(opts: tuple) -> str:
    return f"{'|'.join(opts)}|或自由描述"


def _fmt_strict(opts: tuple) -> str:
    return "|".join(opts)


_CHAR_SCHEMA_PROMPT = (
    "欄位鍵名固定如下，禁止新增或重命名欄位，未知填 null：\n"
    '{"name":"角色姓名（必填）",'
    '"description":"【必填，不可為 null】2-4句中文人設描述，依序涵蓋'
    '①外貌概覽（身形、髮色、眼神等最具識別度的特徵）'
    '②個性氣質（言行舉止、給人的整體感受）'
    '③身份背景（職業、出身、所處陣營）'
    '④與主要角色的關係（敵友情仇或牽絆）。'
    '供插圖生成 AI 快速掌握此角色的視覺形象與情境定位。'
    '範例：「高挑冷艷的黑髮女子，眼神銳利如刀，城府深沉、言少而精。'
    '皇朝第一影衛統領，效忠皇帝多年。'
    '與主角因任務相識，暗藏敵意卻又隱約依賴。」",'
    f'"gender":"{_fmt_strict(_VALID_GENDER)}|null",'
    f'"age_hint":"{_fmt_strict(_VALID_AGE_HINTS)}|null",'
    f'"skin_tone":"{_fmt_soft(_SOFT_SKIN_TONES)}|null",'
    f'"face_shape":"{_fmt_soft(_SOFT_FACE_SHAPES)}|null",'
    f'"hair_color":"{_fmt_soft(_SOFT_HAIR_COLORS)}|null",'
    f'"hair_style":"{_fmt_strict(_VALID_HAIR_STYLES)}|null",'
    f'"eye_color":"{_fmt_soft(_SOFT_EYE_COLORS)}|null",'
    f'"eye_shape":"{_fmt_soft(_SOFT_EYE_SHAPES)}|null",'
    f'"body_type":"{_fmt_strict(_VALID_BODY_TYPES)}|null",'
    '"height_cm":整數cm或null,'
    '"weight_kg":整數kg或null,'
    '"bwh":"B-W-H格式如85-60-86，或null（僅女性）",'
    f'"cup_size":"{_fmt_strict(_VALID_CUP_SIZES)}|null（僅女性）",'
    f'"era_style":"{_fmt_soft(_SOFT_ERA_STYLES)}|null",'
    '"signature_outfit":"標誌性服裝，含顏色/款式/材質/裝飾至少四項（如「藏藍武士長袍，銀線卷雲紋，革帶束腰，袖口束緊」），null若無描述",'
    '"color_palette":"角色整體主色調或null",'
    '"accessories":"武器/首飾/隨身物品等，或null",'
    '"distinctive_marks":"疤痕/紋身/胎記/異常印記，或null",'
    '"special_traits":"氣場/神格/超自然外觀（如發光眼睛），或null",'
    '"other_features":"其他重要外觀特徵，或null"}'
)


def _empty_character_fields() -> dict:
    return {
        "name": "", "description": None, "gender": None, "age_hint": None,
        "skin_tone": None, "face_shape": None,
        "hair_color": None, "hair_style": None,
        "eye_color": None, "eye_shape": None,
        "body_type": None, "height_cm": None, "weight_kg": None,
        "bwh": None, "cup_size": None,
        "era_style": None, "signature_outfit": None,
        "color_palette": None, "accessories": None,
        "distinctive_marks": None, "special_traits": None,
        "other_features": None,
    }


_MAX_EXTRACT_CHARS = 2000


def _trim_for_extraction(text: str) -> str:
    if len(text) <= _MAX_EXTRACT_CHARS:
        return text
    half = _MAX_EXTRACT_CHARS // 2
    return text[:half] + "\n…（省略中間部分）…\n" + text[-half:]


# ─── 角色名稱過濾 ─────────────────────────────────────────────────────────────

_PRONOUN_CHARS = frozenset("他她它你我咱俺彼此誰")

_NON_NAME_TERMS = frozenset({
    "那人", "此人", "那小子", "那傢伙", "那家夥", "這人", "這小子",
    "逆賊", "奸賊", "賊人", "賊子", "叛賊", "惡賊", "奸細", "刺客",
    "偷牛賊", "偷馬賊", "小人", "惡人", "歹人", "壞人",
    "皇上", "公公", "奴才", "老爺", "大人", "主子", "奴婢",
})


def _is_valid_char_name(name: str) -> bool:
    if not name:
        return False
    if len(name) == 1 and name in _PRONOUN_CHARS:
        return False
    if name in _NON_NAME_TERMS:
        return False
    if len(name) <= 4 and (name.startswith("那") or name.startswith("這")):
        return False
    return True


_NAME_PREFIXES = {"小", "老", "大"}


def _merge_aliases(accumulated: dict[str, dict]) -> dict[str, dict]:
    if not accumulated:
        return accumulated

    canonical: dict[str, str] = {}
    names = sorted(accumulated.keys(), key=len, reverse=True)

    for name in names:
        target = None
        for sep in ("·", "．", "•"):
            if sep in name:
                short = name.split(sep)[-1].strip()
                if short and short in accumulated and short != name:
                    target = short
                    break
        if target is None:
            for prefix in _NAME_PREFIXES:
                if name.startswith(prefix):
                    short = name[len(prefix):]
                    if len(short) >= 2 and short in accumulated:
                        target = short
                        break
        if target is not None:
            canonical[name] = target

    if not canonical:
        return accumulated

    result: dict[str, dict] = {}
    for name, char in accumulated.items():
        dest = canonical.get(name, name)
        if dest not in result:
            if dest in accumulated:
                result[dest] = {k: v for k, v in accumulated[dest].items()}
            else:
                result[dest] = {k: v for k, v in char.items()}
                result[dest]["name"] = dest
        if dest != name:
            for k, v in char.items():
                if k == "name":
                    continue
                if v is not None and k not in result[dest]:
                    result[dest][k] = v
            logger.debug("別名合併: %r → %r", name, dest)

    for name, char in accumulated.items():
        if name not in canonical and name not in result:
            result[name] = char

    return result


_BATCH_CHARS = BATCH_CHARS


# ─── 視覺差異化預設值（名字 hash 決定外觀）────────────────────────────────────

# 動畫風格：黑色頭髮拆成 8 種深色變體，讓不同角色的「黑髮」各具識別度
_DARK_HAIR_ANIME_POOL = [
    "午夜藍", "深紫黑", "藏藍黑", "墨綠黑",
    "暗炭黑", "深青黑", "星夜黑", "深靛黑",
]
# 動畫風格：黑色眼睛拆成 6 種深色變體
_DARK_EYE_ANIME_POOL = [
    "午夜藍", "深紫", "藏藍", "暗青",
    "深灰", "深靛",
]
# 被視為「自然黑」的 hair_color 值（從小說提取或舊預設）
_PLAIN_DARK_HAIR = {"黑色", "黑", "黑髮", "烏黑", "漆黑", "深黑", "墨黑"}
_PLAIN_DARK_EYE  = {"黑色", "黑", "黑眸", "烏黑", "深黑"}

_HAIR_COLOR_POOL_F = [
    # 動畫深色變體（取代單調的「黑色」）
    *_DARK_HAIR_ANIME_POOL,
    # 棕色系
    "深棕", "棕色", "淺棕", "紅棕",
    # 鮮豔色系
    "金色", "淡金", "銀白", "白色",
    "紅色", "橙色", "藍色", "紫色", "翠綠", "粉色", "多色漸變",
]
_HAIR_COLOR_POOL_M = [
    # 男性：保留一點「正常黑」但也有其他深色
    "黑色", "午夜藍", "深紫黑", "藏藍黑",
    "深棕", "棕色", "淺棕", "金色", "銀白", "白色", "紅色",
]
_EYE_COLOR_POOL = [
    # 動畫深色變體（取代單調的「黑色」）
    *_DARK_EYE_ANIME_POOL,
    # 其他顏色
    "深褐", "棕色", "琥珀", "藍色", "藍紫", "綠色",
    "金色", "紅色", "銀色", "紫色",
]
_FACE_SHAPE_POOL = ["瓜子臉", "圓臉", "鵝蛋臉", "方臉", "長臉", "尖臉"]
_EYE_SHAPE_POOL  = [
    # 每一類各挑視覺最鮮明者，確保 hash 分配時出現頻率均等
    # 基礎
    "杏眼", "水杏眼", "圓眼", "大眼",
    # 上挑銳利
    "鳳眼", "丹鳳眼", "貓眼", "凌厲眼",
    # 下垂溫柔
    "垂眼", "鹿眸",
    # 媚眼
    "桃花眼", "含情目",
    # 清澈深邃
    "明眸", "星眸", "秋水眼", "深邃眼",
]
_SKIN_TONE_POOL  = [
    "白皙", "米白", "自然色", "健康色", "象牙白", "蜜桃色",
    "小麥色", "自然棕", "明亮",
]
# 女性身材預設——大幅差異化，避免全部「苗條」
_BODY_TYPE_POOL_F = [
    "苗條", "纖細", "嬌小", "高挑", "豐滿", "消瘦",
    "健美", "高挑豐滿", "適中", "窈窕", "豐腴",
]
# 男性身材預設
_BODY_TYPE_POOL_M = [
    "適中", "高挑", "健美", "魁梧", "纖細", "消瘦",
]
_HAIR_STYLE_POOL_F = ["長直", "長波浪", "長捲", "馬尾", "雙馬尾", "盤髮", "中長", "長辮", "古典髮髻"]
_HAIR_STYLE_POOL_M = ["短髮", "寸頭", "中長", "束髮", "長直"]
# 依身材分配罩杯范圍，hash 選擇讓同身材的不同角色有不同但合理的罩杯
_CUP_POOL_BY_BODY: dict[str, list[str]] = {
    "嬌小":   ["A", "A", "B"],
    "消瘦":   ["A", "A", "B"],
    "苗條":   ["A", "B", "B", "C"],
    "纖細":   ["A", "B", "B", "C"],
    "適中":   ["B", "C", "C", "D"],
    "健美":   ["B", "C", "C"],
    "高挑":   ["B", "C", "C", "D"],
    "豐腴":   ["C", "D", "D", "E"],
    "豐滿":   ["D", "D", "E", "F"],
    "高挑豐滿": ["D", "E", "E", "F", "G"],
    "窈窕":   ["B", "C", "C", "D"],
}


def _name_pick(name: str, salt: str, pool: list) -> str:
    h = int(_hashlib.md5(f"{name}:{salt}".encode()).hexdigest(), 16)
    return pool[h % len(pool)]


def _apply_defaults(char: dict) -> dict:
    _NULL = frozenset({None, "", "不明", "null", "NULL"})

    def _empty(v) -> bool:
        return v in _NULL

    name = char.get("name", "") or ""

    g = char.get("gender")
    if _empty(g) or g not in _VALID_GENDER:
        female_suffixes = ["姑", "姨", "女", "姐", "妹", "媽", "媼", "娘", "嫂", "婆"]
        char["gender"] = "女" if any(k in name for k in female_suffixes) else "男"

    gender = char["gender"]

    if _empty(char.get("age_hint")) or char["age_hint"] not in _VALID_AGE_HINTS:
        char["age_hint"] = "青年"

    if _empty(char.get("hair_color")):
        pool = _HAIR_COLOR_POOL_F if gender == "女" else _HAIR_COLOR_POOL_M
        char["hair_color"] = _name_pick(name, "hair", pool) if name else pool[0]
    # 小說中描述的自然黑髮 → 動畫深色變體（存進 DB 讓角色卡/編輯頁面也能看出差異）
    if char.get("hair_color") in _PLAIN_DARK_HAIR and name:
        char["hair_color"] = _name_pick(name, "hair_dark", _DARK_HAIR_ANIME_POOL)

    # 髮型屬於場景可變項目，LLM 未填寫時留 None，每次生成由模型或 seed 決定
    if char.get("hair_style") not in _VALID_HAIR_STYLES:
        pool = _HAIR_STYLE_POOL_F if gender == "女" else _HAIR_STYLE_POOL_M
        char["hair_style"] = _name_pick(name, "hairstyle", pool) if name else None

    if _empty(char.get("eye_color")):
        char["eye_color"] = _name_pick(name, "eye", _EYE_COLOR_POOL) if name else "午夜藍"
    # 小說中描述的自然黑眼 → 動畫深色變體
    if char.get("eye_color") in _PLAIN_DARK_EYE and name:
        char["eye_color"] = _name_pick(name, "eye_dark", _DARK_EYE_ANIME_POOL)

    if _empty(char.get("face_shape")):
        char["face_shape"] = _name_pick(name, "face", _FACE_SHAPE_POOL) if name else None

    if _empty(char.get("eye_shape")):
        char["eye_shape"] = _name_pick(name, "eyeshape", _EYE_SHAPE_POOL) if name else None

    if _empty(char.get("skin_tone")):
        char["skin_tone"] = _name_pick(name, "skin", _SKIN_TONE_POOL) if name else "自然色"

    if _empty(char.get("body_type")) or char["body_type"] not in _VALID_BODY_TYPES:
        pool = _BODY_TYPE_POOL_F if gender == "女" else _BODY_TYPE_POOL_M
        char["body_type"] = _name_pick(name, "body", pool) if name else ("苗條" if gender == "女" else "適中")

    h = char.get("height_cm")
    try:
        h = int(h) if h is not None else None
    except Exception:
        h = None
    char["height_cm"] = h if (h and h > 0) else (162 if gender == "女" else 175)

    w = char.get("weight_kg")
    try:
        w = int(w) if w is not None else None
    except Exception:
        w = None
    if not w or w <= 0:
        hc = char["height_cm"]
        char["weight_kg"] = (int(hc - 112) if hc > 112 else 48) if gender == "女" else (int(hc - 105) if hc > 105 else 70)
    else:
        char["weight_kg"] = w

    if gender == "女":
        if _empty(char.get("bwh")):
            bt = char.get("body_type", "適中")
            if bt in ("豐滿", "高挑豐滿"):        char["bwh"] = "92-62-92"
            elif bt == "嬌小":                     char["bwh"] = "80-56-82"
            elif bt in ("苗條", "消瘦", "健美"):   char["bwh"] = "82-58-84"
            else:                                  char["bwh"] = "85-60-86"
    else:
        char["bwh"] = None

    if gender == "女":
        if _empty(char.get("cup_size")) or char["cup_size"] not in _VALID_CUP_SIZES:
            bt = char.get("body_type") or "適中"
            pool = _CUP_POOL_BY_BODY.get(bt, ["B", "C", "C", "D"])
            char["cup_size"] = _name_pick(name, "cup", pool) if name else pool[len(pool) // 2]
    else:
        char["cup_size"] = None

    if _empty(char.get("signature_outfit")):
        era = char.get("era_style") or ""
        if any(k in era for k in ("古代中式", "武俠", "宮廷", "江湖")):
            char["signature_outfit"] = "素色棉布長袍，領口簡潔，腰繫細帶"
        elif any(k in era for k in ("古代日式",)):
            char["signature_outfit"] = "素色棉布和服，腰帶束緊，袖口寬鬆"
        elif any(k in era for k in ("現代都市", "現代休閒", "學生制服")):
            char["signature_outfit"] = "素色棉質上衣，配合身份的日常穿著"
        elif any(k in era for k in ("科幻", "星際", "賽博")):
            char["signature_outfit"] = "深色機能外套，金屬拉鍊，貼身剪裁"
        elif any(k in era for k in ("奇幻", "高魔", "中世紀")):
            char["signature_outfit"] = "粗布長袍，皮革護腕，腰間掛小袋"
        else:
            char["signature_outfit"] = "素色布衣，款式簡樸，合乎身份"

    return char
