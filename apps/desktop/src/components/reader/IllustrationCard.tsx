import { useState, useEffect } from "react";
import { toast } from "sonner";
import { ZoomIn, X, Download, UserRound, Trash2, Info, Copy, ChevronDown, ChevronUp } from "lucide-react";
import { Character, getCharacters, upsertCharacter, addCharacterImage, IllustrationMeta } from "@/lib/api";
import { BACKEND_BASE_URL } from "@/lib/constants";

const ANGLE_OPTIONS = ["正面", "側面", "半身", "全身", "其他"];

interface IllustrationCardProps {
  imageBase64?: string;
  imageUrl?: string;
  prompt: string;
  bookId: string;
  meta?: IllustrationMeta;
  chapterIndex?: number;
  sentenceIndex?: number;
  onDismiss: () => void;
  onImageSavedToCharacter?: (charName: string) => void;
}

export default function IllustrationCard({
  imageBase64, imageUrl, prompt, bookId, meta,
  onDismiss, onImageSavedToCharacter,
}: IllustrationCardProps) {
  const [lightbox, setLightbox] = useState(false);
  const [showSaveChar, setShowSaveChar] = useState(false);
  const [showInfo, setShowInfo] = useState(false);
  const [charName, setCharName] = useState("");
  const [angle, setAngle] = useState("正面");
  const [saving, setSaving] = useState(false);

  const [existingChars, setExistingChars] = useState<Character[]>([]);
  const [showDropdown, setShowDropdown] = useState(false);

  useEffect(() => {
    if (showSaveChar && bookId) {
      getCharacters(bookId)
        .then(setExistingChars)
        .catch(() => {});
    }
  }, [showSaveChar, bookId]);

  const filteredChars = existingChars.filter(c =>
    c.name.toLowerCase().includes(charName.toLowerCase())
  );

  const src = imageUrl
    ? `${BACKEND_BASE_URL}${imageUrl}`
    : `data:image/png;base64,${imageBase64}`;

  const handleSaveCharacter = async () => {
    if (!charName.trim() || !imageBase64) return;
    setSaving(true);
    try {
      await upsertCharacter(bookId, { name: charName.trim() });
      await addCharacterImage(bookId, charName.trim(), {
        image_base64: imageBase64,
        angle,
        is_primary: false,
      });
      toast.success(`已加入「${charName}」的角色圖庫（${angle}）`);
      setShowSaveChar(false);
      setCharName("");
      setAngle("正面");
      onImageSavedToCharacter?.(charName.trim());
    } catch {
      toast.error("儲存角色失敗");
    } finally {
      setSaving(false);
    }
  };

  const handleToggleInfo = () => {
    setShowInfo(v => !v);
    if (showSaveChar) setShowSaveChar(false);
  };
  const handleToggleSaveChar = () => {
    setShowSaveChar(v => !v);
    if (showInfo) setShowInfo(false);
  };

  const modelLabel = meta?.model_name
    ? meta.model_name.replace(/\.safetensors$/i, "")
    : null;

  return (
    <>
      <div className="my-5 rounded-xl overflow-hidden border shadow-lg" style={{ borderColor: "var(--border)", backgroundColor: "var(--bg-surface)" }}>
        {/* 圖片 */}
        <div className="relative group cursor-pointer" onClick={() => setLightbox(true)}>
          <img src={src} alt="AI 插圖" className="w-full max-h-[480px] object-contain bg-black/10" />
          <div className="absolute inset-0 bg-black/0 group-hover:bg-black/20 transition-all flex items-center justify-center opacity-0 group-hover:opacity-100">
            <ZoomIn size={28} className="text-white drop-shadow" />
          </div>
        </div>

        {/* 操作列 */}
        <div className="flex items-center justify-between px-4 py-2.5 border-t text-xs" style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}>
          <span className="truncate flex-1 mr-3 italic opacity-60">{prompt.slice(0, 70)}{prompt.length > 70 ? "…" : ""}</span>
          <div className="flex items-center gap-1.5 shrink-0">
            <button
              onClick={handleToggleInfo}
              className={`flex items-center gap-1 px-2 py-1 rounded transition-all ${showInfo ? "bg-sky-500/20 text-sky-400" : "hover:bg-white/10"}`}
              title="查看提示詞與參數"
            >
              <Info size={12} />
              {showInfo ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
            </button>
            <button onClick={handleToggleSaveChar} className="flex items-center gap-1 px-2 py-1 rounded hover:bg-white/10 text-amber-400 transition-all" title="設為角色樣板">
              <UserRound size={12} /><span>存為角色</span>
            </button>
            <button onClick={() => { const a = document.createElement("a"); a.href = src; a.download = `illus_${Date.now()}.png`; a.click(); }} className="p-1.5 rounded hover:bg-white/10 transition-all" title="下載">
              <Download size={13} />
            </button>
            <button onClick={onDismiss} className="p-1.5 rounded hover:bg-red-500/20 text-red-400 transition-all" title="移除">
              <Trash2 size={13} />
            </button>
          </div>
        </div>

        {/* 詳情面板 */}
        {showInfo && (
          <div className="px-4 pb-4 pt-3 border-t space-y-3 text-xs" style={{ borderColor: "var(--border)" }}>
            {/* 完整提示詞 */}
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <span className="font-semibold opacity-60 tracking-wide">完整提示詞</span>
                <button
                  onClick={() => { navigator.clipboard.writeText(prompt); toast.success("已複製"); }}
                  className="flex items-center gap-1 px-2 py-0.5 rounded text-[11px] hover:bg-white/10 text-sky-400 transition-all"
                >
                  <Copy size={11} /> 複製
                </button>
              </div>
              <div
                className="p-2.5 rounded leading-relaxed break-all max-h-36 overflow-y-auto font-mono text-[11px]"
                style={{ backgroundColor: "var(--bg-primary)", color: "var(--text-secondary)", whiteSpace: "pre-wrap" }}
              >
                {prompt}
              </div>
            </div>

            {/* 參數格 */}
            <div className="grid grid-cols-2 gap-x-6 gap-y-1.5" style={{ color: "var(--text-secondary)" }}>
              {modelLabel && (
                <div className="col-span-2 flex gap-2">
                  <span className="opacity-50 shrink-0">模型</span>
                  <span className="font-mono text-[11px] truncate" title={meta?.model_name}>{modelLabel}</span>
                </div>
              )}
              <div className="flex gap-2">
                <span className="opacity-50 shrink-0">風格</span>
                <span className={meta?.is_anime ? "text-pink-400" : "text-blue-400"}>
                  {meta?.is_anime ? "動畫" : "寫實"}
                </span>
              </div>
              {meta?.steps != null && (
                <div className="flex gap-2">
                  <span className="opacity-50 shrink-0">步數</span>
                  <span>{meta.steps}</span>
                </div>
              )}
              {meta?.guidance_scale != null && (
                <div className="flex gap-2">
                  <span className="opacity-50 shrink-0">CFG</span>
                  <span>{meta.guidance_scale}</span>
                </div>
              )}
              {meta?.seed != null && (
                <div className="flex gap-2">
                  <span className="opacity-50 shrink-0">Seed</span>
                  <span className="font-mono text-[11px]">{meta.seed}</span>
                </div>
              )}
              {meta?.width != null && meta?.height != null && (
                <div className="flex gap-2">
                  <span className="opacity-50 shrink-0">解析度</span>
                  <span>{meta.width} × {meta.height}</span>
                </div>
              )}
            </div>
          </div>
        )}

        {/* 存角色表單 */}
        {showSaveChar && (
          <div className="px-4 pb-4 pt-2 border-t flex flex-col gap-2" style={{ borderColor: "var(--border)" }}>
            <p className="text-xs font-semibold" style={{ color: "var(--text-primary)" }}>將此圖加入角色圖庫</p>
            <div className="relative">
              <input autoFocus type="text" placeholder="角色名稱（如：秋月，或點選下拉列表）" value={charName}
                onChange={e => { setCharName(e.target.value); setShowDropdown(true); }}
                onFocus={() => setShowDropdown(true)}
                onBlur={() => setTimeout(() => setShowDropdown(false), 200)}
                className="w-full px-2.5 py-1.5 rounded border text-xs outline-none"
                style={{ backgroundColor: "var(--bg-primary)", borderColor: "var(--border)", color: "var(--text-primary)" }} />
              {showDropdown && filteredChars.length > 0 && (
                <div className="absolute left-0 right-0 mt-1 max-h-40 overflow-y-auto rounded border shadow-lg z-50 text-xs"
                  style={{ backgroundColor: "var(--bg-surface)", borderColor: "var(--border)", color: "var(--text-primary)" }}>
                  {filteredChars.map(c => (
                    <div key={c.id}
                      onMouseDown={() => { setCharName(c.name); setShowDropdown(false); }}
                      className="px-2.5 py-1.5 cursor-pointer hover:bg-amber-500/20 text-left transition-colors">
                      {c.name}
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-[10px] opacity-60">圖片角度</span>
              <div className="flex gap-1.5 flex-wrap">
                {ANGLE_OPTIONS.map(a => (
                  <button key={a} onClick={() => setAngle(a)}
                    className="px-2 py-0.5 rounded text-[10px] border transition-all"
                    style={{
                      borderColor:     angle === a ? "#f59e0b" : "var(--border)",
                      backgroundColor: angle === a ? "rgba(245,158,11,0.12)" : "var(--bg-hover)",
                      color:           angle === a ? "#f59e0b" : "var(--text-secondary)",
                      fontWeight:      angle === a ? 700 : 400,
                    }}>{a}</button>
                ))}
              </div>
            </div>
            <p className="text-[10px]" style={{ color: "var(--text-secondary)" }}>
              儲存後請至角色庫填寫詳細外觀描述
            </p>
            <div className="flex gap-2">
              <button onClick={handleSaveCharacter} disabled={!charName.trim() || saving}
                className="flex-1 py-1.5 rounded text-xs font-semibold bg-amber-500 text-black hover:bg-amber-400 disabled:opacity-50 transition-all">
                {saving ? "儲存中..." : "存入角色庫"}
              </button>
              <button onClick={() => setShowSaveChar(false)}
                className="px-3 py-1.5 rounded text-xs hover:bg-white/10 transition-all" style={{ color: "var(--text-secondary)" }}>
                取消
              </button>
            </div>
          </div>
        )}
      </div>

      {/* 燈箱 */}
      {lightbox && (
        <div className="fixed inset-0 z-[100] bg-black/90 flex items-center justify-center p-4" onClick={() => setLightbox(false)}>
          <button className="absolute top-4 right-4 p-2 rounded-full bg-white/10 hover:bg-white/20" onClick={() => setLightbox(false)}>
            <X size={20} className="text-white" />
          </button>
          <img src={src} alt="插圖放大" className="max-w-full max-h-full object-contain rounded-lg shadow-2xl" onClick={e => e.stopPropagation()} />
        </div>
      )}
    </>
  );
}
