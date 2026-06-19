import { Character, CharacterImage, AngleJob, charImageUrl } from "@/lib/api";
import { BACKEND_BASE_URL } from "@/lib/constants";
import {
  Pencil, Lock, LockOpen, ImagePlus, Trash2, Star, ZoomIn, Layers, Check, Square,
} from "lucide-react";

interface Props {
  char: Character;
  isSelected: boolean;
  isExpanded: boolean;
  selectMode: boolean;
  isChecked: boolean;
  angleJob?: { jobId: string; job: AngleJob };
  sheetStyle: "anime" | "real";
  availableStyles: Set<"anime" | "real">;
  onToggleSelect: () => void;
  onSelectAndClose: () => void;
  onEdit: () => void;
  onToggleLock: () => void;
  onToggleExpand: () => void;
  onDelete: () => void;
  onGenerateAngles: () => void;
  onSetPrimary: (imgId: number) => void;
  onDeleteImage: (imgId: number) => void;
  onPreview: (src: string, prompt?: string | null) => void;
  onStyleChange: (style: "anime" | "real") => void;
}

function fragmentOf(c: Character): string {
  return [
    c.gender, c.age_hint,
    c.skin_tone ? c.skin_tone + "膚" : "",
    c.face_shape,
    (c.hair_color || "") + (c.hair_style || ""),
    c.eye_color && c.eye_shape ? c.eye_color + c.eye_shape
      : c.eye_color ? c.eye_color + "瞳" : c.eye_shape,
    c.body_type,
    c.height_cm ? c.height_cm + "cm" : "",
    c.weight_kg ? c.weight_kg + "kg" : "",
    c.gender === "女" && c.bwh ? "三圍" + c.bwh : "",
    c.gender === "女" && c.cup_size ? c.cup_size + "罩杯" : "",
    c.era_style,
    c.signature_outfit,
    c.color_palette ? "主色調：" + c.color_palette : "",
    c.accessories,
    c.distinctive_marks,
    c.special_traits,
    c.other_features,
  ].filter(Boolean).join("，") || c.description || "";
}

export function CharacterCard({
  char,
  isSelected,
  isExpanded,
  selectMode,
  isChecked,
  angleJob,
  sheetStyle,
  availableStyles,
  onToggleSelect,
  onSelectAndClose,
  onEdit,
  onToggleLock,
  onToggleExpand,
  onDelete,
  onGenerateAngles,
  onSetPrimary,
  onDeleteImage,
  onPreview,
  onStyleChange,
}: Props) {
  const fragment = fragmentOf(char);
  const thumb = char.primary_image_url
    ? `${BACKEND_BASE_URL}${char.primary_image_url}`
    : char.ref_image_base64
      ? `data:image/png;base64,${char.ref_image_base64}`
      : null;
  const busy = !!angleJob && (angleJob.job.status === "pending" || angleJob.job.status === "running");

  return (
    <div
      className={`rounded-xl border overflow-hidden transition-all ${
        selectMode && isChecked ? "border-sky-400/70" :
        !selectMode && isSelected ? "border-amber-500/60" : "border-white/10"
      }`}
      style={{
        backgroundColor: selectMode && isChecked
          ? "rgba(56,189,248,0.06)"
          : isSelected && !selectMode ? "rgba(245,158,11,0.06)" : "var(--bg-hover)",
        color: "var(--text-primary)",
      }}
    >
      {/* 角色主行 */}
      <div
        className="flex items-center gap-3 px-3 pt-3 pb-2 cursor-pointer"
        onClick={() => { selectMode ? onToggleSelect() : onSelectAndClose(); }}
      >
        {/* 縮圖 */}
        <div className="w-12 h-12 rounded-lg overflow-hidden shrink-0 border relative" style={{ borderColor: "var(--border)" }}>
          {thumb
            ? <img src={thumb} alt={char.name} className="w-full h-full object-cover" />
            : <div className="w-full h-full flex items-center justify-center bg-amber-500/20 text-amber-400 text-lg font-bold">{char.name.charAt(0)}</div>}
          {selectMode && (
            <div className={`absolute inset-0 flex items-center justify-center transition-all ${isChecked ? "bg-sky-500/70" : "bg-black/30"}`}>
              {isChecked
                ? <Check size={20} className="text-white" strokeWidth={3} />
                : <Square size={16} className="text-white/60" />}
            </div>
          )}
        </div>

        {/* 名稱 + fragment */}
        <div className="flex-1 min-w-0">
          <div className="text-xs font-semibold flex items-center gap-1.5 flex-wrap" style={{ color: "var(--text-primary)" }}>
            {char.name}
            {isSelected && <span className="text-[9px] px-1 py-0.5 rounded bg-amber-500 text-black font-bold">使用中</span>}
            {char.locked ? <span className="text-[9px] px-1 py-0.5 rounded border border-sky-400/60 text-sky-400 font-bold flex items-center gap-0.5"><Lock size={8} />鎖定</span> : null}
          </div>
          {fragment
            ? <div className="text-[10px] truncate mt-0.5" style={{ color: "var(--text-secondary)" }}>{fragment}</div>
            : <div className="text-[10px] italic mt-0.5 opacity-40">尚未填寫外觀</div>}
          <div className="text-[9px] mt-0.5 opacity-40">{char.images.length} 張參考圖</div>
        </div>
      </div>

      {/* 操作按鈕列 */}
      {!selectMode && (
        <div
          className="flex items-center border-t px-1"
          style={{ borderColor: "var(--border)", height: "36px" }}
          onClick={e => e.stopPropagation()}
        >
          <button onClick={onEdit}
            className="flex-1 flex items-center justify-center gap-1 py-1.5 rounded hover:bg-white/10 transition-all text-[10px]"
            style={{ color: "var(--text-secondary)" }}>
            <Pencil size={11} /><span>編輯</span>
          </button>
          <button onClick={onToggleLock}
            className="flex-1 flex items-center justify-center gap-1 py-1.5 rounded hover:bg-white/10 transition-all text-[10px]"
            style={{ color: char.locked ? "#38bdf8" : "var(--text-secondary)" }}>
            {char.locked ? <Lock size={11} /> : <LockOpen size={11} />}
            <span>{char.locked ? "解鎖" : "鎖定"}</span>
          </button>
          <button onClick={onToggleExpand}
            className="flex-1 flex items-center justify-center gap-1 py-1.5 rounded hover:bg-white/10 transition-all text-[10px]"
            style={{ color: isExpanded ? "#38bdf8" : "var(--text-secondary)" }}>
            <ImagePlus size={11} /><span>圖片</span>
          </button>
          <button onClick={onDelete}
            className="flex-1 flex items-center justify-center gap-1 py-1.5 rounded hover:bg-red-500/10 transition-all text-[10px] text-red-400">
            <Trash2 size={11} /><span>刪除</span>
          </button>
        </div>
      )}

      {/* 展開：圖片管理 */}
      {isExpanded && (
        <div className="border-t px-3 pb-3 pt-2" style={{ borderColor: "var(--border)" }}>
          {/* 多視角生成 */}
          <div className="mb-2 space-y-1.5">
            <div className="flex gap-1">
              {(["anime", "real"] as const).map(s => {
                const hasModel = availableStyles.has(s);
                return (
                  <button
                    key={s}
                    onClick={() => hasModel && onStyleChange(s)}
                    disabled={busy || !hasModel}
                    title={hasModel ? undefined : `需先在模型管理員安裝${s === "anime" ? "動畫" : "寫實"}模型`}
                    className={`flex-1 py-0.5 rounded text-[9px] font-medium border transition-colors ${
                      !hasModel
                        ? "border-white/5 text-white/15 cursor-not-allowed"
                        : busy
                        ? "opacity-40 cursor-not-allowed border-white/10 text-white/30"
                        : sheetStyle === s
                        ? s === "anime"
                          ? "bg-violet-500/20 border-violet-500/50 text-violet-400"
                          : "bg-amber-500/20 border-amber-500/50 text-amber-400"
                        : "border-white/10 text-white/30 hover:text-white/50"
                    }`}
                  >
                    {s === "anime" ? "動畫" : "寫實"}
                    {!hasModel && " ✕"}
                  </button>
                );
              })}
            </div>
            <button
              onClick={onGenerateAngles}
              disabled={busy}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[10px] border border-sky-500/40 text-sky-400 hover:bg-sky-500/10 disabled:opacity-40 transition-all w-full justify-center"
            >
              <Layers size={11} />
              {busy ? angleJob!.job.label : "生成角色設定圖"}
            </button>
            {busy && (
              <div className="mt-1 w-full h-0.5 rounded-full overflow-hidden" style={{ backgroundColor: "var(--border)" }}>
                <div
                  className="h-full rounded-full bg-sky-400 transition-all duration-500"
                  style={{ width: `${angleJob!.job.progress}%` }}
                />
              </div>
            )}
          </div>

          <p className="text-[10px] font-semibold mb-2" style={{ color: "var(--text-secondary)" }}>參考圖庫</p>
          {char.images.length === 0 && (
            <p className="text-[10px] italic" style={{ color: "var(--text-muted)" }}>
              無圖片。從插圖卡片「存為角色」時可附加圖片。
            </p>
          )}
          <div className="grid grid-cols-3 gap-1.5">
            {char.images.map(img => (
              <div
                key={img.id}
                className="relative aspect-square rounded overflow-hidden border"
                style={{ borderColor: img.is_primary ? "#f59e0b" : "var(--border)" }}
              >
                <CharImageThumb
                  img={img}
                  onSetPrimary={() => onSetPrimary(img.id)}
                  onDelete={() => onDeleteImage(img.id)}
                  onPreview={src => onPreview(src, img.prompt)}
                />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function CharImageThumb({
  img,
  onSetPrimary,
  onDelete,
  onPreview,
}: {
  img: CharacterImage;
  onSetPrimary?: () => void;
  onDelete?: () => void;
  onPreview?: (src: string, prompt?: string | null) => void;
}) {
  const src = charImageUrl(img.id);
  return (
    <div className="relative w-full h-full group">
      <img src={src} alt={img.angle} className="w-full h-full object-cover" />
      <div className="absolute inset-0 bg-black/0 group-hover:bg-black/60 transition-all flex items-center justify-center gap-1.5 opacity-0 group-hover:opacity-100">
        <button
          onClick={e => { e.stopPropagation(); onPreview?.(src, img.prompt); }}
          className="p-1 rounded bg-sky-500/80 text-white hover:bg-sky-400 transition-colors"
          title="放大檢視"
        >
          <ZoomIn size={10} />
        </button>
        {!img.is_primary && onSetPrimary && (
          <button
            onClick={e => { e.stopPropagation(); onSetPrimary(); }}
            className="p-1 rounded bg-amber-500/80 text-black hover:bg-amber-450 transition-colors"
            title="設為主要"
          >
            <Star size={10} />
          </button>
        )}
        {onDelete && (
          <button
            onClick={e => { e.stopPropagation(); onDelete(); }}
            className="p-1 rounded bg-red-500/80 text-white hover:bg-red-400 transition-colors"
            title="刪除"
          >
            <Trash2 size={10} />
          </button>
        )}
      </div>
      {img.is_primary && (
        <div className="absolute bottom-0 left-0 right-0 text-center text-[8px] bg-amber-500 text-black font-bold pointer-events-none">主</div>
      )}
      <div className="absolute top-0.5 right-0.5 text-[8px] px-1 rounded bg-black/60 text-white pointer-events-none">{img.angle}</div>
    </div>
  );
}
