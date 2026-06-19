import { useState } from "react";
import { X, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Character, upsertCharacter } from "@/lib/api";

// ── strict enum：值域固定 ──────────────────────────────────────────────────────
const GENDER_OPTIONS    = ["女", "男", "中性"];
const AGE_OPTIONS       = ["幼兒", "少女/少年", "青年", "壯年", "中年", "老年"];
const HAIR_STYLE_OPT    = ["長直", "長波浪", "長捲", "長辮", "盤髮", "古典髮髻",
                           "馬尾", "雙馬尾", "束髮", "中長", "短髮", "寸頭", "光頭"];
const BODY_TYPE_OPT     = ["嬌小", "消瘦", "苗條", "纖細", "適中", "窈窕", "健美", "高挑", "豐腴", "豐滿", "高挑豐滿", "魁梧"];
const CUP_OPTIONS       = ["A", "B", "C", "D", "E", "F", "G", "H"];

// ── soft enum：常見值 + 自由輸入都可 ──────────────────────────────────────────
const HAIR_COLOR_OPT    = [
  // 動畫深色系
  "午夜藍", "深紫黑", "藏藍黑", "墨綠黑", "暗炭黑", "深青黑", "星夜黑", "深靛黑",
  // 棕色系
  "深棕", "棕色", "淺棕", "紅棕",
  // 其他
  "黑色", "金色", "淡金", "銀白", "白色",
  "紅色", "橙色", "藍色", "紫色", "翠綠", "粉色", "多色漸變",
];
const EYE_COLOR_OPT     = [
  // 動畫深色系
  "午夜藍", "深紫", "藏藍", "暗青", "深灰", "深靛",
  // 其他
  "黑色", "深褐", "棕色", "琥珀", "藍色", "藍紫",
  "綠色", "金色", "紅色", "銀色", "紫色", "异色瞳",
];
const SKIN_TONE_OPT     = ["白皙", "米白", "小麥色", "棕褐", "深褐", "黑色", "蒼白（病態）", "金屬光澤"];
const FACE_SHAPE_OPT    = ["瓜子臉", "圓臉", "方臉", "長臉", "尖臉", "棱角分明"];
const EYE_SHAPE_OPT     = [
  // 基礎
  "杏眼", "水杏眼", "圓眼", "大眼",
  // 上挑銳利
  "鳳眼", "丹鳳眼", "貓眼", "凌厲眼", "細長眼", "吊梢眼",
  // 下垂溫柔
  "垂眼", "鹿眸",
  // 媚眼魅惑
  "桃花眼", "媚眼", "含情目",
  // 清澈深邃
  "明眸", "星眸", "秋水眼", "深邃眼",
];
const ERA_STYLE_OPT     = ["現代都市", "現代休閒", "商務正式", "學生制服",
                           "古代中式", "武俠江湖", "宮廷貴族", "民國",
                           "古代日式", "古代歐式", "中世紀奇幻",
                           "高魔幻", "末世廢土", "科幻機甲", "星際宇宙",
                           "賽博朋克", "蒸氣龐克"];

interface Props {
  bookId: string;
  initial?: Partial<Character>;
  onSave: (char: Character) => void;
  onClose: () => void;
}

export default function CharacterEditModal({ bookId, initial, onSave, onClose }: Props) {
  const isNew = !initial?.name;

  // ── 基本 ──────────────────────────────────────────────────────────────────
  const [name,     setName]    = useState(initial?.name ?? "");
  const [gender,   setGender]  = useState(initial?.gender ?? "");
  const [ageHint,  setAgeHint] = useState(initial?.age_hint ?? "");

  // ── 面部特徵 ──────────────────────────────────────────────────────────────
  const [skinTone,  setSkinTone]  = useState(initial?.skin_tone ?? "");
  const [faceShape, setFaceShape] = useState(initial?.face_shape ?? "");
  const [hairColor, setHairColor] = useState(initial?.hair_color ?? "");
  const [hairStyle, setHairStyle] = useState(initial?.hair_style ?? "");
  const [eyeColor,  setEyeColor]  = useState(initial?.eye_color ?? "");
  const [eyeShape,  setEyeShape]  = useState(initial?.eye_shape ?? "");

  // ── 體型 ──────────────────────────────────────────────────────────────────
  const [bodyType,  setBodyType]  = useState(initial?.body_type ?? "");
  const [heightCm,  setHeightCm]  = useState<string>(initial?.height_cm?.toString() ?? "");
  const [weightKg,  setWeightKg]  = useState<string>(initial?.weight_kg?.toString() ?? "");
  const [bwh,       setBwh]       = useState<string>(initial?.bwh ?? "");
  const [cupSize,   setCupSize]   = useState<string>(initial?.cup_size ?? "");

  // ── 服飾配件 ──────────────────────────────────────────────────────────────
  const [eraStyle,        setEraStyle]        = useState(initial?.era_style ?? "");
  const [signatureOutfit, setSignatureOutfit] = useState(initial?.signature_outfit ?? "");
  const [colorPalette,    setColorPalette]    = useState(initial?.color_palette ?? "");
  const [accessories,     setAccessories]     = useState(initial?.accessories ?? "");

  // ── 特殊特徵 ──────────────────────────────────────────────────────────────
  const [distinctiveMarks, setDistinctiveMarks] = useState(initial?.distinctive_marks ?? "");
  const [specialTraits,    setSpecialTraits]    = useState(initial?.special_traits ?? "");
  const [otherFeatures,    setOtherFeatures]    = useState(initial?.other_features ?? "");

  const [saving, setSaving] = useState(false);

  // ── Prompt 預覽（即時）────────────────────────────────────────────────────
  const real = (v: string) => (v && v !== "__clear__") ? v : "";
  const fragment = [
    real(gender), real(ageHint),
    real(skinTone) ? real(skinTone) + "膚" : "",
    real(faceShape),
    (real(hairColor) || real(hairStyle)) ? real(hairColor) + real(hairStyle) : "",
    real(eyeColor) && real(eyeShape) ? real(eyeColor) + real(eyeShape)
      : real(eyeColor) ? real(eyeColor) + "瞳" : real(eyeShape),
    real(bodyType),
    heightCm ? heightCm + "cm" : "",
    weightKg ? weightKg + "kg" : "",
    gender === "女" && bwh && bwh !== "__clear__" ? "三圍" + bwh : "",
    gender === "女" && real(cupSize) ? real(cupSize) + "罩杯" : "",
    real(eraStyle),
    real(signatureOutfit),
    real(colorPalette) ? "主色調：" + real(colorPalette) : "",
    real(accessories),
    real(distinctiveMarks),
    real(specialTraits),
    real(otherFeatures),
  ].filter(Boolean).join("，");

  // ── 儲存 ──────────────────────────────────────────────────────────────────
  const chipVal = (v: string) => v === "__clear__" ? "__clear__" : (v || null);
  const textVal = (v: string) => v.trim() === "" ? "__clear__" : v.trim();
  const displayV = (v: string) => (v === "__clear__" || v === "") ? null : v;

  const handleSave = async () => {
    if (!name.trim()) { toast.error("請填入角色名稱"); return; }
    setSaving(true);
    const isFemale = gender === "女";
    try {
      await upsertCharacter(bookId, {
        name: name.trim(),
        gender:            chipVal(gender),
        age_hint:          chipVal(ageHint),
        skin_tone:         chipVal(skinTone),
        face_shape:        chipVal(faceShape),
        hair_color:        chipVal(hairColor),
        hair_style:        chipVal(hairStyle),
        eye_color:         chipVal(eyeColor),
        eye_shape:         chipVal(eyeShape),
        body_type:         chipVal(bodyType),
        height_cm:         heightCm ? parseInt(heightCm) : null,
        weight_kg:         weightKg ? parseInt(weightKg) : null,
        bwh:               isFemale ? textVal(bwh) : "__clear__",
        cup_size:          isFemale ? chipVal(cupSize) : "__clear__",
        era_style:         chipVal(eraStyle),
        signature_outfit:  textVal(signatureOutfit),
        color_palette:     textVal(colorPalette),
        accessories:       textVal(accessories),
        distinctive_marks: textVal(distinctiveMarks),
        special_traits:    textVal(specialTraits),
        other_features:    textVal(otherFeatures),
      } as any);
      toast.success(`「${name.trim()}」已儲存`);
      onSave({
        ...initial,
        name: name.trim(),
        gender: displayV(gender), age_hint: displayV(ageHint),
        skin_tone: displayV(skinTone), face_shape: displayV(faceShape),
        hair_color: displayV(hairColor), hair_style: displayV(hairStyle),
        eye_color: displayV(eyeColor), eye_shape: displayV(eyeShape),
        body_type: displayV(bodyType),
        height_cm: heightCm ? parseInt(heightCm) : null,
        weight_kg: weightKg ? parseInt(weightKg) : null,
        bwh: isFemale ? (bwh.trim() || null) : null,
        cup_size: isFemale ? displayV(cupSize) : null,
        era_style: displayV(eraStyle),
        signature_outfit: signatureOutfit.trim() || null,
        color_palette: colorPalette.trim() || null,
        accessories: accessories.trim() || null,
        distinctive_marks: distinctiveMarks.trim() || null,
        special_traits: specialTraits.trim() || null,
        other_features: otherFeatures.trim() || null,
      } as Character);
    } catch { toast.error("儲存失敗"); }
    finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div
        className="relative w-full max-w-lg rounded-2xl shadow-2xl border overflow-hidden"
        style={{ backgroundColor: "var(--bg-surface)", borderColor: "var(--border)", color: "var(--text-primary)" }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b" style={{ borderColor: "var(--border)" }}>
          <h2 className="font-bold text-sm">{isNew ? "新增角色" : `編輯角色：${initial?.name}`}</h2>
          <button onClick={onClose} className="p-1 rounded-full hover:bg-white/10"><X size={16} /></button>
        </div>

        <div className="p-5 flex flex-col gap-5 max-h-[78vh] overflow-y-auto">

          {/* ── 基本 ── */}
          <Section label="基本">
            <div className="flex flex-col gap-1">
              <label className="text-xs font-semibold opacity-70">角色名稱 *</label>
              <input
                value={name} onChange={e => setName(e.target.value)}
                placeholder="例：秋月、林小明"
                disabled={!isNew}
                className="px-3 py-2 rounded-lg border text-sm outline-none disabled:opacity-50"
                style={{ backgroundColor: "var(--bg-primary)", borderColor: "var(--border)" }}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <ChipGroup label="性別" options={GENDER_OPTIONS} value={gender} onChange={setGender} />
              <ChipGroup label="年齡感" options={AGE_OPTIONS} value={ageHint} onChange={setAgeHint} cols={3} />
            </div>
          </Section>

          {/* ── 面部特徵 ── */}
          <Section label="面部特徵">
            <div className="grid grid-cols-2 gap-3">
              <SoftChipGroup label="膚色" options={SKIN_TONE_OPT} value={skinTone} onChange={setSkinTone} cols={2} />
              <SoftChipGroup label="臉型" options={FACE_SHAPE_OPT} value={faceShape} onChange={setFaceShape} cols={2} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <SoftChipGroup label="髮色" options={HAIR_COLOR_OPT} value={hairColor} onChange={setHairColor} cols={3} />
              <ChipGroup     label="髮型" options={HAIR_STYLE_OPT} value={hairStyle} onChange={setHairStyle} cols={3} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <SoftChipGroup label="瞳色" options={EYE_COLOR_OPT} value={eyeColor} onChange={setEyeColor} cols={3} />
              <SoftChipGroup label="眼型" options={EYE_SHAPE_OPT} value={eyeShape} onChange={setEyeShape} cols={3} />
            </div>
          </Section>

          {/* ── 體型 ── */}
          <Section label="體型">
            <div className="flex gap-3 items-end">
              <div className="flex-1">
                <ChipGroup label="體型" options={BODY_TYPE_OPT} value={bodyType} onChange={setBodyType} cols={4} />
              </div>
              <NumInput label="身高（cm）" value={heightCm} onChange={setHeightCm} min={100} max={250} />
              <NumInput label="體重（kg）" value={weightKg} onChange={setWeightKg} min={30} max={250} />
            </div>
            {gender === "女" && (
              <div className="flex gap-3 items-end">
                <div className="flex flex-col gap-1 flex-1">
                  <label className="text-xs opacity-70">三圍（B-W-H）</label>
                  <input
                    value={bwh} onChange={e => setBwh(e.target.value)}
                    placeholder="如 85-60-86"
                    className="px-3 py-1.5 rounded border text-xs outline-none font-mono"
                    style={{ backgroundColor: "var(--bg-primary)", borderColor: "var(--border)" }}
                  />
                </div>
                <div className="flex flex-col gap-1 w-36 shrink-0">
                  <ChipGroup label="罩杯" options={CUP_OPTIONS} value={cupSize} onChange={setCupSize} cols={4} />
                </div>
              </div>
            )}
          </Section>

          {/* ── 服飾配件 ── */}
          <Section label="服飾配件">
            <SoftChipGroup label="時代風格" options={ERA_STYLE_OPT} value={eraStyle} onChange={setEraStyle} cols={3} allowCustom />
            <TextInput label="標誌性服裝" value={signatureOutfit} onChange={setSignatureOutfit}
              placeholder="如：白色龍袍、黑色修士袍、紅色旗袍" />
            <div className="grid grid-cols-2 gap-3">
              <TextInput label="主色調" value={colorPalette} onChange={setColorPalette}
                placeholder="如：白藍色系、暗紅金邊" />
              <TextInput label="武器/配件" value={accessories} onChange={setAccessories}
                placeholder="如：長劍、玉佩、魔法杖" />
            </div>
          </Section>

          {/* ── 特殊特徵 ── */}
          <Section label="特殊特徵">
            <TextInput label="標誌性印記" value={distinctiveMarks} onChange={setDistinctiveMarks}
              placeholder="如：左臉刀疤、額間紅痣、手背龍紋" />
            <TextInput label="特殊氣質/神格/超自然特徵" value={specialTraits} onChange={setSpecialTraits}
              placeholder="如：眸光如星、周身靈氣流動、發光的蒼藍眼眸" />
            <TextInput label="其他特徵" value={otherFeatures} onChange={setOtherFeatures}
              placeholder="其他重要外觀細節" />
          </Section>

          {/* ── Prompt 預覽 ── */}
          {fragment && (
            <div className="rounded-lg p-3 text-[11px]" style={{ backgroundColor: "var(--bg-hover)", color: "var(--text-secondary)" }}>
              <div className="flex items-center gap-1.5 mb-1">
                <Sparkles size={11} className="text-amber-500" />
                <span className="font-semibold text-amber-500">注入 Prompt 預覽</span>
              </div>
              <span className="font-mono leading-relaxed">{fragment}</span>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex gap-2 px-5 py-4 border-t" style={{ borderColor: "var(--border)" }}>
          <button onClick={onClose} className="flex-1 py-2 rounded-lg text-xs hover:bg-white/5 transition-all" style={{ color: "var(--text-secondary)" }}>
            取消
          </button>
          <button onClick={handleSave} disabled={saving || !name.trim()}
            className="flex-1 py-2 rounded-lg text-xs font-bold bg-amber-500 text-black hover:bg-amber-400 disabled:opacity-40 transition-all">
            {saving ? "儲存中..." : "儲存角色"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── 小元件 ───────────────────────────────────────────────────────────────────

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <span className="text-[10px] font-bold tracking-widest uppercase opacity-40">{label}</span>
        <div className="flex-1 h-px" style={{ backgroundColor: "var(--border)" }} />
      </div>
      {children}
    </div>
  );
}

function NumInput({ label, value, onChange, min, max }: {
  label: string; value: string; onChange: (v: string) => void; min: number; max: number;
}) {
  return (
    <div className="flex flex-col gap-1 w-20 shrink-0">
      <label className="text-xs opacity-70">{label}</label>
      <input
        type="number" min={min} max={max} value={value}
        onChange={e => onChange(e.target.value)}
        placeholder="選填"
        className="px-2.5 py-1.5 rounded border text-xs outline-none text-center font-mono"
        style={{ backgroundColor: "var(--bg-primary)", borderColor: "var(--border)" }}
      />
    </div>
  );
}

function TextInput({ label, value, onChange, placeholder }: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-semibold opacity-70">{label}</label>
      <input value={value} onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        className="px-3 py-2 rounded-lg border text-xs outline-none"
        style={{ backgroundColor: "var(--bg-primary)", borderColor: "var(--border)" }}
      />
    </div>
  );
}

/** strict enum chip 選擇器：點同一個取消選取，不允許自由輸入 */
function ChipGroup({ label, options, value, onChange, cols = 3 }: {
  label: string; options: string[]; value: string; onChange: (v: string) => void; cols?: number;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-xs font-semibold opacity-70">{label}</label>
      <div className="grid gap-1" style={{ gridTemplateColumns: `repeat(${cols}, 1fr)` }}>
        {options.map(o => {
          const selected = value === o;
          return (
            <button key={o} onClick={() => onChange(selected ? "__clear__" : o)}
              className="py-1 rounded text-[10px] border transition-all truncate"
              style={{
                borderColor:     selected ? "var(--accent,#f59e0b)" : "var(--border)",
                backgroundColor: selected ? "rgba(245,158,11,0.12)" : "var(--bg-hover)",
                color:           selected ? "#f59e0b" : "var(--text-secondary)",
                fontWeight:      selected ? 700 : 400,
              }}
            >{o}</button>
          );
        })}
      </div>
    </div>
  );
}

/** soft enum chip 選擇器：可選常見值，也可在輸入框自由填寫 */
function SoftChipGroup({ label, options, value, onChange, cols = 3, allowCustom = false }: {
  label: string; options: string[]; value: string; onChange: (v: string) => void;
  cols?: number; allowCustom?: boolean;
}) {
  const isCustom = value !== "" && value !== "__clear__" && !options.includes(value);

  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-xs font-semibold opacity-70">{label}</label>
      <div className="grid gap-1" style={{ gridTemplateColumns: `repeat(${cols}, 1fr)` }}>
        {options.map(o => {
          const selected = value === o;
          return (
            <button key={o} onClick={() => onChange(selected ? "__clear__" : o)}
              className="py-1 rounded text-[10px] border transition-all truncate"
              style={{
                borderColor:     selected ? "#38bdf8" : "var(--border)",
                backgroundColor: selected ? "rgba(56,189,248,0.10)" : "var(--bg-hover)",
                color:           selected ? "#38bdf8" : "var(--text-secondary)",
                fontWeight:      selected ? 700 : 400,
              }}
            >{o}</button>
          );
        })}
      </div>
      {/* 自由輸入框（軟 enum 可自訂） */}
      <input
        value={isCustom ? value : ""}
        onChange={e => onChange(e.target.value || "__clear__")}
        placeholder={allowCustom ? "或自由輸入…" : "其他（自由輸入）"}
        className="px-2.5 py-1 rounded border text-[10px] outline-none"
        style={{
          backgroundColor: "var(--bg-primary)",
          borderColor: isCustom ? "#38bdf8" : "var(--border)",
          color: "var(--text-secondary)",
        } as React.CSSProperties}
      />
    </div>
  );
}
