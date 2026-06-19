import { UserRound, X } from "lucide-react";
import { Character } from "@/lib/api";

interface Props {
  candidates: Partial<Character>[];
  onSelect: (char: Partial<Character>) => void;
  onClose: () => void;
}

function briefDesc(c: Partial<Character>): string {
  return [
    c.gender,
    c.age_hint,
    c.hair_color && c.hair_style ? c.hair_color + c.hair_style : c.hair_color || c.hair_style,
    c.eye_color ? c.eye_color + "瞳" : undefined,
    c.body_type,
    c.signature_outfit,
  ].filter(Boolean).join("，") || "無外觀描述";
}

export default function CharacterPickerModal({ candidates, onSelect, onClose }: Props) {
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />

      <div
        className="relative z-10 w-full max-w-sm rounded-2xl shadow-2xl border flex flex-col overflow-hidden"
        style={{ backgroundColor: "var(--bg-surface)", borderColor: "var(--border)", color: "var(--text-primary)" }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b" style={{ borderColor: "var(--border)" }}>
          <div className="text-sm font-bold">選擇要提取的角色</div>
          <button onClick={onClose} className="p-1 rounded-full hover:bg-white/10 transition-all" style={{ color: "var(--text-secondary)" }}>
            <X size={16} />
          </button>
        </div>

        <p className="px-5 pt-3 pb-1 text-xs" style={{ color: "var(--text-secondary)" }}>
          偵測到 {candidates.length} 位角色，點選要新增到角色庫的對象
        </p>

        {/* 角色列表 */}
        <div className="overflow-y-auto max-h-[60vh] p-3 space-y-2">
          {candidates.map((c, i) => (
            <button
              key={i}
              onClick={() => onSelect(c)}
              className="w-full flex items-center gap-3 px-4 py-3 rounded-xl border text-left transition-all hover:border-amber-500/60 hover:bg-amber-500/5"
              style={{ borderColor: "var(--border)", backgroundColor: "var(--bg-hover)" }}
            >
              <div className="w-9 h-9 rounded-lg shrink-0 flex items-center justify-center text-base font-bold bg-amber-500/20 text-amber-400">
                {c.name ? c.name.charAt(0) : <UserRound size={16} />}
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-xs font-semibold">
                  {c.name || <span className="italic opacity-50">未知角色</span>}
                  {c.gender && (
                    <span className="ml-1.5 text-[9px] px-1 py-0.5 rounded bg-sky-500/20 text-sky-400">{c.gender}</span>
                  )}
                </div>
                <div className="text-[10px] mt-0.5 truncate" style={{ color: "var(--text-secondary)" }}>
                  {briefDesc(c)}
                </div>
              </div>
              <span className="text-[10px] text-amber-500 shrink-0">選取 →</span>
            </button>
          ))}
        </div>

        <div className="px-4 py-3 border-t" style={{ borderColor: "var(--border)" }}>
          <button
            onClick={onClose}
            className="w-full py-2 rounded-lg text-xs hover:bg-white/10 transition-all"
            style={{ color: "var(--text-secondary)" }}
          >
            取消
          </button>
        </div>
      </div>
    </div>
  );
}
