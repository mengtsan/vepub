"""
TTS 角色配音（Phase 2）：把角色庫資料轉成「聲線」，並把對白歸屬到角色。

兩個職責：
  1. character_voice_instruct() — 角色 gender/age_hint → OmniVoice Voice Design instruct，
     同性別年齡者以名字 hash 配不同音高(pitch)以區分。
  2. attribute_speakers() — 啟發式判斷每句對白屬於哪個角色（引號＋鄰近角色名＋說話動詞）。
     刻意做成獨立函式，日後可替換為 LLM 版本而不動其餘管線。
"""
from __future__ import annotations

import hashlib
import re

# ─── 1. 角色 → 聲線 instruct ──────────────────────────────────────────────────

_GENDER_MAP = {"男": "male", "女": "female"}
_AGE_MAP = {
    "幼兒": "child", "兒童": "child", "孩童": "child",
    "少年": "teenager", "少女": "teenager", "青少年": "teenager",
    "青年": "young adult", "成年": "young adult",
    "中年": "middle-aged",
    "老年": "elderly", "老人": "elderly",
}
# 同性別年齡的不同角色，用名字 hash 落在不同音高，避免聽起來同一人。
_PITCHES = ["very low pitch", "low pitch", "moderate pitch", "high pitch", "very high pitch"]


def character_voice_instruct(
    gender: str | None,
    age_hint: str | None,
    name: str = "",
) -> str | None:
    """組出 OmniVoice Voice Design instruct，如 "female, young adult, high pitch"。

    無任何可用屬性時回傳 None（交由旁白/自動聲線處理）。
    """
    parts: list[str] = []

    g = _GENDER_MAP.get((gender or "").strip())
    if g:
        parts.append(g)

    a = _AGE_MAP.get((age_hint or "").strip())
    if a:
        parts.append(a)

    if not parts:
        return None

    # 以名字決定性地挑一個音高，讓同性別年齡的角色彼此有別。
    # 男聲偏低、女聲偏高，再以 hash 在其鄰近範圍微調。
    h = int(hashlib.md5((name or "").encode("utf-8")).hexdigest(), 16)
    if g == "male":
        pitch = _PITCHES[h % 3]          # very low ~ moderate
    elif g == "female":
        pitch = _PITCHES[2 + (h % 3)]    # moderate ~ very high
    else:
        pitch = _PITCHES[1 + (h % 3)]
    parts.append(pitch)

    return ", ".join(parts)


# ─── 2. 說話者歸屬（啟發式）────────────────────────────────────────────────────

# 中日全形引號；對白＝句中含這些。
_OPEN_QUOTES = "「『“"
_RE_HAS_QUOTE = re.compile(rf"[{_OPEN_QUOTES}]")

# 說話動詞：名字後（容許數字內的修飾字）接這些字視為「某某＋說」。
_SPEECH_VERBS = (
    "說道|說|道|問道|問|答道|答|回道|回答|回|喊道|喊|叫道|叫|笑道|笑|"
    "冷笑|嘆道|嘆|應道|應|罵道|罵|吼道|吼|嚷|低聲|輕聲|沉聲|續道|接道|開口"
)


def _build_speaker_regex(names: list[str]) -> re.Pattern | None:
    """組出 `(名字)(最多4字修飾)(說話動詞)` 的比對式；名字以長者優先避免短名先吃。"""
    valid = sorted({n for n in names if n and len(n) >= 1}, key=lambda s: -len(s))
    if not valid:
        return None
    alt = "|".join(re.escape(n) for n in valid)
    return re.compile(rf"({alt})[^，。！？,.!?「『“]{{0,4}}?(?:{_SPEECH_VERBS})")


def attribute_speakers(
    sentences: list[dict],
    names: list[str],
) -> list[str | None]:
    """為每句判定說話者：回傳與 sentences 等長的清單，元素為角色名或 None（旁白）。

    啟發式規則（保守，寧缺勿錯）：
      - 不含引號 → 旁白(None)。
      - 含引號 → 先在「本句」找 名字+說話動詞；找不到再看「前一句旁白」找同樣式。
      - 仍找不到 → 標記為對白但不指名（None，交 Phase 1 對白聲線）。
    """
    rx = _build_speaker_regex(names)
    result: list[str | None] = []

    for i, s in enumerate(sentences):
        text = s.get("text", "") if isinstance(s, dict) else str(s)
        if not _RE_HAS_QUOTE.search(text):
            result.append(None)
            continue
        if rx is None:
            result.append(None)
            continue

        # 本句內找 名字+說話動詞（含「『你好』秋月說」這種引號後具名）
        m = rx.search(text)

        # 退而求其次：前一句「旁白引言」（如「小巧笑著問：」）帶出本句對白。
        # 僅在前一句為旁白（不含引號）時採用——若前一句本身是對白，延續到本句
        # 容易把「你一句我一句」的交替對白全歸給同一人，故不採。
        if not m and i > 0:
            prev = sentences[i - 1]
            prev_text = prev.get("text", "") if isinstance(prev, dict) else str(prev)
            if not _RE_HAS_QUOTE.search(prev_text):
                m = rx.search(prev_text)

        result.append(m.group(1) if m else None)

    return result
