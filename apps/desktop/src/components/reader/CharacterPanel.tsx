import { useEffect, useState, useCallback } from "react";
import { useReaderStore } from "@/stores/reader";
import { usePolling } from "@/hooks/usePolling";
import { useAnalysisJob } from "@/hooks/useAnalysisJob";
import { toast } from "sonner";
import {
  X, Users, UserRound, Plus, ScanSearch, GitMerge, Loader2,
  CheckSquare, Sparkles, Layers,
} from "lucide-react";
import {
  Character,
  getCharacters, deleteCharacter, upsertCharacter,
  deleteCharacterImage, setPrimaryCharacterImage,
  analyzeCharacters, getAnalysisCheckpoint,
  generateCharacterAngles, getAngleJobStatus, AngleJob,
  dedupCharacters, batchDeleteCharacters, fillCharacterDefaults,
} from "@/lib/api";
import { getAllModels } from "@/lib/model-api";
import { POLL_ANGLES_MS } from "@/lib/constants";
import CharacterEditModal from "./CharacterEditModal";
import { CharacterCard } from "./CharacterCard";
import { AnalysisProgress } from "./AnalysisProgress";
import { ImageLightbox } from "./ImageLightbox";

interface Props {
  isOpen: boolean;
  onClose: () => void;
  bookId: string;
  selectedCharName?: string;
  refreshKey?: number;
  onSelectCharacter: (char: Character | null) => void;
  pendingExtraction?: Partial<Character> | null;
  onExtractionConsumed?: () => void;
}

export default function CharacterPanel({
  isOpen, onClose, bookId, selectedCharName, refreshKey,
  onSelectCharacter, pendingExtraction, onExtractionConsumed,
}: Props) {
  const [characters,  setCharacters]  = useState<Character[]>([]);
  const [loading,     setLoading]     = useState(false);
  const [editTarget,  setEditTarget]  = useState<Partial<Character> | null>(null);
  const [expandedId,  setExpandedId]  = useState<number | null>(null);
  const [previewSrc,  setPreviewSrc]  = useState<{ src: string; prompt?: string | null } | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [sortBy,      setSortBy]      = useState<"name" | "time">("time");

  // 多視角生圖：charId → { jobId, job }
  const [angleJobs,       setAngleJobs]       = useState<Record<number, { jobId: string; job: AngleJob }>>({});
  const [sheetStyle,      setSheetStyle]      = useState<"anime" | "real">("anime");
  const [availableStyles, setAvailableStyles] = useState<Set<"anime" | "real">>(new Set(["anime"]));

  const { illustrationPromptPrefix } = useReaderStore();

  const [deduping,       setDeduping]       = useState(false);
  const [filling,        setFilling]        = useState(false);
  const [resumeDialog,   setResumeDialog]   = useState<{ count: number } | null>(null);
  const [deleteConfirm,  setDeleteConfirm]  = useState<
    { type: "single"; name: string } | { type: "batch"; count: number; names: string[] } | null
  >(null);
  const [selectMode,    setSelectMode]    = useState(false);
  const [selectedNames, setSelectedNames] = useState<Set<string>>(new Set());

  const fetchChars = useCallback(async () => {
    if (!bookId) return;
    setLoading(true);
    try { setCharacters(await getCharacters(bookId)); }
    catch { /* silent */ }
    finally { setLoading(false); }
  }, [bookId]);

  const { analysis, setAnalysis } = useAnalysisJob(bookId, fetchChars);

  useEffect(() => {
    if (!isOpen) {
      setSelectMode(false);
      setSelectedNames(new Set());
      return;
    }
    fetchChars();
    // 確認哪些生圖風格有安裝對應模型
    getAllModels().then(all => {
      const styles = new Set<"anime" | "real">();
      for (const m of all.image.models) {
        if (m.style === "anime" || m.style === "real") styles.add(m.style);
      }
      if (styles.size === 0) styles.add("anime");
      setAvailableStyles(styles);
      setSheetStyle(prev => styles.has(prev) ? prev : (styles.has("anime") ? "anime" : "real"));
    }).catch(() => {});
  }, [isOpen, fetchChars, refreshKey, bookId]);

  // 接收外部提取的角色，自動開啟編輯 Modal
  useEffect(() => {
    if (pendingExtraction == null) return;
    setEditTarget(pendingExtraction);
    onExtractionConsumed?.();
  }, [pendingExtraction, onExtractionConsumed]);

  // 多視角任務 polling
  const angleActive = Object.values(angleJobs).some(
    e => e.job.status === "pending" || e.job.status === "running"
  );
  usePolling(async () => {
    const updates: Record<number, { jobId: string; job: AngleJob }> = {};
    let anyDone = false;
    for (const [charIdStr, entry] of Object.entries(angleJobs)) {
      if (entry.job.status !== "pending" && entry.job.status !== "running") continue;
      const s = await getAngleJobStatus(entry.jobId).catch(() => null);
      if (!s) continue;
      updates[+charIdStr] = { jobId: entry.jobId, job: s };
      if (s.status === "done") { anyDone = true; toast.success("角色設定圖已生成"); }
      if (s.status === "error") toast.error(`角色設定圖生成失敗：${s.error}`);
    }
    if (Object.keys(updates).length) setAngleJobs(prev => ({ ...prev, ...updates }));
    if (anyDone) fetchChars();
  }, POLL_ANGLES_MS, angleActive);

  // 啟動全書分析（含 resume 判斷）
  const handleAnalyze = async () => {
    try {
      const cp = await getAnalysisCheckpoint(bookId);
      if (cp.count > 0) { setResumeDialog({ count: cp.count }); return; }
      await analyzeCharacters(bookId);
      setAnalysis({ status: "running", progress: 0, label: "準備中…", result: null, error: null });
      toast.info("開始分析全書角色，請稍候…");
    } catch (e: any) { toast.error(e.message || "啟動分析失敗"); }
  };

  const handleResumeChoice = async (resume: boolean) => {
    setResumeDialog(null);
    try {
      await analyzeCharacters(bookId, { restart: !resume });
      setAnalysis({ status: "running", progress: 0, label: "準備中…", result: null, error: null });
      toast.info(resume ? "繼續上次分析進度…" : "重新開始分析全書角色…");
    } catch (e: any) { toast.error(e.message || "啟動分析失敗"); }
  };

  const handleDedup = async () => {
    if (characters.length < 2) { toast.info("角色數量不足，無需整理"); return; }
    setDeduping(true);
    try {
      const result = await dedupCharacters(bookId);
      if (result.merged === 0) {
        toast.success("未發現重複角色");
      } else {
        const detail = result.groups.map(g => `${g.canonical}（合併 ${g.aliases.join("、")}）`).join("\n");
        toast.success(`已合併 ${result.merged} 個重複角色`, { description: detail });
        fetchChars();
      }
    } catch (e: any) {
      toast.error(e.message || "整理失敗");
    } finally {
      setDeduping(false);
    }
  };

  const handleFillDefaults = async () => {
    setFilling(true);
    try {
      const r = await fillCharacterDefaults(bookId);
      if (r.updated === 0) {
        toast.success("所有角色欄位已完整，無需補完");
      } else {
        toast.success(`已補完 ${r.updated} 個角色的空欄位`);
        fetchChars();
      }
    } catch (e: any) {
      toast.error(e.message || "補完失敗");
    } finally {
      setFilling(false);
    }
  };

  const toggleSelect = (name: string) =>
    setSelectedNames(prev => {
      const next = new Set(prev);
      next.has(name) ? next.delete(name) : next.add(name);
      return next;
    });

  const handleBatchDelete = () => {
    if (selectedNames.size === 0) return;
    setDeleteConfirm({ type: "batch", count: selectedNames.size, names: [...selectedNames] });
  };

  const executeBatchDelete = async (names: string[]) => {
    setDeleteConfirm(null);
    try {
      await batchDeleteCharacters(bookId, names);
      if (selectedCharName && names.includes(selectedCharName)) onSelectCharacter(null);
      setCharacters(prev => prev.filter(c => !names.includes(c.name)));
      setSelectedNames(new Set());
      setSelectMode(false);
      toast.success(`已刪除 ${names.length} 個角色`);
    } catch (e: any) { toast.error(e.message || "刪除失敗"); }
  };

  const STYLE_PREFIX: Record<"anime" | "real", string> = {
    anime: "anime style, vibrant colors, clean lineart, highly detailed",
    real:  "photorealistic, cinematic lighting, ultra-detailed, realistic",
  };

  const handleGenerateAngles = async (char: Character) => {
    try {
      const prefix = illustrationPromptPrefix.trim() || STYLE_PREFIX[sheetStyle];
      const { job_id } = await generateCharacterAngles(bookId, char.name, undefined, undefined, prefix);
      setAngleJobs(prev => ({
        ...prev,
        [char.id]: { jobId: job_id, job: { status: "pending", progress: 0, label: "排隊中", done: 0, total: 1, error: null } },
      }));
      toast.info(`開始生成「${char.name}」的角色設定圖…`);
    } catch (e: any) { toast.error(e.message || "啟動生成失敗"); }
  };

  const handleBatchGenerateAngles = async () => {
    const targets = characters.filter(c => selectedNames.has(c.name));
    if (targets.length === 0) return;
    const prefix = illustrationPromptPrefix.trim() || STYLE_PREFIX[sheetStyle];
    let started = 0;
    for (const char of targets) {
      const existing = angleJobs[char.id];
      if (existing && (existing.job.status === "pending" || existing.job.status === "running")) continue;
      try {
        const { job_id } = await generateCharacterAngles(bookId, char.name, undefined, undefined, prefix);
        setAngleJobs(prev => ({
          ...prev,
          [char.id]: { jobId: job_id, job: { status: "pending", progress: 0, label: "排隊中", done: 0, total: 1, error: null } },
        }));
        started++;
      } catch { /* skip */ }
    }
    if (started > 0) {
      toast.info(`已排入 ${started} 個角色的人設圖生成…`);
      setSelectMode(false);
      setSelectedNames(new Set());
    }
  };

  const handleToggleLock = async (char: Character) => {
    const newLocked = char.locked ? 0 : 1;
    try {
      await upsertCharacter(bookId, { name: char.name, locked: newLocked } as any);
      setCharacters(prev => prev.map(c => c.id === char.id ? { ...c, locked: newLocked } : c));
      toast.success(newLocked ? `「${char.name}」已鎖定，自動分析不會覆蓋` : `「${char.name}」已解鎖`);
    } catch { toast.error("操作失敗"); }
  };

  const handleDelete = (name: string) => {
    setDeleteConfirm({ type: "single", name });
  };

  const executeDelete = async (name: string) => {
    setDeleteConfirm(null);
    try {
      await deleteCharacter(bookId, name);
      setCharacters(prev => prev.filter(c => c.name !== name));
      toast.success(`已刪除「${name}」`);
      if (selectedCharName === name) onSelectCharacter(null);
    } catch { toast.error("刪除失敗"); }
  };

  const handleSaved = (saved: Character) => {
    setCharacters(prev => {
      const idx = prev.findIndex(c => c.name === saved.name);
      if (idx >= 0) { const a = [...prev]; a[idx] = { ...a[idx], ...saved }; return a; }
      return [...prev, { ...saved, images: [], primary_image_url: null }];
    });
    setEditTarget(null);
  };

  const handleDeleteImage = async (char: Character, imgId: number) => {
    try {
      await deleteCharacterImage(bookId, char.name, imgId);
      setCharacters(prev => prev.map(c =>
        c.id === char.id ? { ...c, images: c.images.filter(i => i.id !== imgId) } : c
      ));
      toast.success("已刪除圖片");
    } catch { toast.error("刪除失敗"); }
  };

  const handleSetPrimary = async (char: Character, imgId: number) => {
    try {
      await setPrimaryCharacterImage(bookId, char.name, imgId);
      setCharacters(prev => prev.map(c =>
        c.id === char.id ? {
          ...c,
          primary_image_url: `/illustration/char-image/${imgId}`,
          images: c.images.map(i => ({ ...i, is_primary: i.id === imgId ? 1 : 0 })),
        } : c
      ));
      toast.success("已設為主要圖片");
    } catch { toast.error("設定失敗"); }
  };

  const filteredAndSortedChars = characters
    .filter(c => c.name.toLowerCase().includes(searchQuery.toLowerCase()))
    .sort((a, b) => sortBy === "name" ? a.name.localeCompare(b.name, "zh-Hant") : 0);

  const analysisRunning = analysis?.status === "running" || analysis?.status === "pending";

  return (
    <>
      {isOpen && <div onClick={onClose} onWheel={e => e.stopPropagation()} className="fixed inset-0 bg-black/40 backdrop-blur-xs z-40" />}

      {/* Resume / Restart 確認彈窗 */}
      {resumeDialog && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-zinc-900 border border-white/10 rounded-xl p-6 max-w-sm w-full mx-4 shadow-2xl">
            <h3 className="text-sm font-semibold text-white mb-2">發現未完成的分析</h3>
            <p className="text-xs text-white/60 mb-5 leading-relaxed">
              上次分析中斷時已完成 <span className="text-sky-400 font-bold">{resumeDialog.count}</span> 章，
              可以從中斷處繼續，或重新開始（將清除已分析的角色）。
            </p>
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setResumeDialog(null)}
                className="px-3 py-1.5 rounded text-xs text-white/50 hover:text-white/80 transition-colors"
              >取消</button>
              <button
                onClick={() => handleResumeChoice(false)}
                className="px-3 py-1.5 rounded text-xs bg-red-900/60 text-red-300 hover:bg-red-900 transition-colors"
              >重新開始</button>
              <button
                onClick={() => handleResumeChoice(true)}
                className="px-3 py-1.5 rounded text-xs bg-sky-600 text-white hover:bg-sky-500 transition-colors"
              >繼續分析</button>
            </div>
          </div>
        </div>
      )}

      {/* 刪除確認彈窗 */}
      {deleteConfirm && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-zinc-900 border border-white/10 rounded-xl p-6 max-w-sm w-full mx-4 shadow-2xl">
            <h3 className="text-sm font-semibold text-white mb-2">確認刪除</h3>
            <p className="text-xs text-white/60 mb-5 leading-relaxed">
              {deleteConfirm.type === "single"
                ? `確定要刪除角色「${deleteConfirm.name}」嗎？此操作無法復原。`
                : `確定要刪除選取的 ${deleteConfirm.count} 個角色嗎？此操作無法復原。`}
            </p>
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setDeleteConfirm(null)}
                className="px-3 py-1.5 rounded text-xs text-white/50 hover:text-white/80 transition-colors"
              >取消</button>
              <button
                onClick={() => {
                  if (deleteConfirm.type === "single") executeDelete(deleteConfirm.name);
                  else executeBatchDelete(deleteConfirm.names);
                }}
                className="px-3 py-1.5 rounded text-xs bg-red-600 text-white hover:bg-red-500 transition-colors"
              >確認刪除</button>
            </div>
          </div>
        </div>
      )}

      {editTarget !== null && (
        <CharacterEditModal
          key={editTarget?.name ?? "__new__"}
          bookId={bookId}
          initial={editTarget}
          onSave={handleSaved}
          onClose={() => setEditTarget(null)}
        />
      )}

      <div
        className="fixed top-0 right-0 h-full w-[320px] shadow-2xl z-50 flex flex-col border-l transition-transform duration-300 ease-out"
        style={{
          backgroundColor: "var(--bg-surface)",
          borderColor: "var(--border)",
          color: "var(--text-primary)",
          transform: isOpen ? "translateX(0)" : "translateX(100%)",
        }}
      >
        {/* Header */}
        <header className="flex items-center justify-between px-5 py-4 border-b" style={{ borderColor: "var(--border)" }}>
          <div className="flex items-center gap-2 text-sm font-bold tracking-wider">
            <Users size={15} className="text-amber-500" />
            <span>角色庫</span>
            {characters.length > 0 && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-500 text-black font-bold">{characters.length}</span>
            )}
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={handleAnalyze}
              disabled={analysisRunning}
              className="flex items-center gap-1 px-2 py-1 rounded hover:bg-white/10 text-sky-400 text-xs transition-all disabled:opacity-40"
              title="用 LLM 分析全書，自動建立角色資料"
            >
              <ScanSearch size={13} /><span>分析全書</span>
            </button>
            <button
              onClick={handleFillDefaults}
              disabled={filling || characters.length === 0}
              className="flex items-center gap-1 px-2 py-1 rounded hover:bg-white/10 text-emerald-400 text-xs transition-all disabled:opacity-40"
              title="補完所有角色的空欄位（套用預設值）"
            >
              {filling ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
              <span>補完</span>
            </button>
            <button
              onClick={handleDedup}
              disabled={deduping || characters.length < 2}
              className="flex items-center gap-1 px-2 py-1 rounded hover:bg-white/10 text-violet-400 text-xs transition-all disabled:opacity-40"
              title="讓 LLM 找出重複角色並合併"
            >
              {deduping ? <Loader2 size={13} className="animate-spin" /> : <GitMerge size={13} />}
              <span>整理重複</span>
            </button>
            <button
              onClick={() => { setSelectMode(v => !v); setSelectedNames(new Set()); }}
              className={`flex items-center gap-1 px-2 py-1 rounded text-xs transition-all ${selectMode ? "bg-white/10 text-white" : "hover:bg-white/10 text-zinc-400"}`}
              title="批次選取並刪除"
            >
              <CheckSquare size={13} /><span>{selectMode ? "取消" : "選取"}</span>
            </button>
            <button
              onClick={() => setEditTarget({})}
              className="flex items-center gap-1 px-2 py-1 rounded hover:bg-white/10 text-amber-400 text-xs transition-all"
              title="新增角色"
            >
              <Plus size={13} /><span>新增</span>
            </button>
            <button onClick={onClose} className="p-1 rounded-full hover:bg-white/10 transition-all" style={{ color: "var(--text-secondary)" }}>
              <X size={18} />
            </button>
          </div>
        </header>

        {/* 分析進度條 */}
        {analysis && (
          <AnalysisProgress analysis={analysis} onDismiss={() => setAnalysis(null)} />
        )}

        <div className="px-4 py-2.5 text-[10px] border-b" style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}>
          選取角色後，生圖時自動注入外觀描述，提升人物一致性
        </div>

        {/* 搜尋與排序 */}
        {characters.length > 0 && (
          <div className="px-4 py-2 border-b flex gap-2 items-center shrink-0" style={{ borderColor: "var(--border)" }}>
            <input
              type="text"
              placeholder="搜尋角色..."
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              className="flex-1 px-2.5 py-1 rounded border text-xs outline-none"
              style={{ backgroundColor: "var(--bg-primary)", borderColor: "var(--border)", color: "var(--text-primary)" }}
            />
            <select
              value={sortBy}
              onChange={e => setSortBy(e.target.value as "name" | "time")}
              className="px-2 py-1 rounded border text-xs outline-none cursor-pointer"
              style={{ backgroundColor: "var(--bg-primary)", borderColor: "var(--border)", color: "var(--text-secondary)" }}
            >
              <option value="time">建立時間</option>
              <option value="name">名稱排序</option>
            </select>
          </div>
        )}

        {/* 角色列表 */}
        <main className="flex-1 min-h-0 overflow-y-auto overscroll-contain p-3 space-y-2">
          {loading && (
            <div className="text-center py-8 text-xs animate-pulse" style={{ color: "var(--text-secondary)" }}>載入中...</div>
          )}

          {!loading && characters.length === 0 && (
            <div className="flex flex-col items-center justify-center py-12 gap-3 text-center" style={{ color: "var(--text-secondary)" }}>
              <UserRound size={32} className="opacity-30" />
              <span className="text-xs">尚無角色</span>
              <span className="text-[10px] px-4" style={{ color: "var(--text-muted)" }}>
                點上方「新增」建立角色，或生圖後從插圖卡片「存為角色」
              </span>
              <button
                onClick={() => setEditTarget({})}
                className="mt-1 flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border border-amber-500/40 text-amber-500 hover:bg-amber-500/10 transition-all"
              >
                <Plus size={12} /> 新增角色
              </button>
            </div>
          )}

          {!loading && characters.length > 0 && filteredAndSortedChars.length === 0 && (
            <div className="flex flex-col items-center justify-center py-12 gap-2 text-center" style={{ color: "var(--text-secondary)" }}>
              <UserRound size={32} className="opacity-10" />
              <span className="text-xs">找不到符合的角色</span>
              <span className="text-[10px] opacity-50">試著修改搜尋關鍵字</span>
            </div>
          )}

          {filteredAndSortedChars.map(char => (
            <CharacterCard
              key={char.id}
              char={char}
              isSelected={char.name === selectedCharName}
              isExpanded={expandedId === char.id}
              selectMode={selectMode}
              isChecked={selectedNames.has(char.name)}
              angleJob={angleJobs[char.id]}
              sheetStyle={sheetStyle}
              availableStyles={availableStyles}
              onToggleSelect={() => toggleSelect(char.name)}
              onSelectAndClose={() => { onSelectCharacter(char.name === selectedCharName ? null : char); onClose(); }}
              onEdit={() => setEditTarget(char)}
              onToggleLock={() => handleToggleLock(char)}
              onToggleExpand={() => setExpandedId(expandedId === char.id ? null : char.id)}
              onDelete={() => handleDelete(char.name)}
              onGenerateAngles={() => handleGenerateAngles(char)}
              onSetPrimary={imgId => handleSetPrimary(char, imgId)}
              onDeleteImage={imgId => handleDeleteImage(char, imgId)}
              onPreview={(src, prompt) => setPreviewSrc({ src, prompt })}
              onStyleChange={s => setSheetStyle(s)}
            />
          ))}
        </main>

        {/* Footer */}
        {selectMode ? (
          <div className="p-3 border-t flex flex-col gap-2 shrink-0" style={{ borderColor: "var(--border)" }}>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setSelectedNames(new Set(filteredAndSortedChars.map(c => c.name)))}
                className="text-[11px] px-2 py-1.5 rounded hover:bg-white/10 transition-all shrink-0"
                style={{ color: "var(--text-secondary)" }}
              >全選</button>
              <button
                onClick={() => setSelectedNames(new Set())}
                className="text-[11px] px-2 py-1.5 rounded hover:bg-white/10 transition-all shrink-0"
                style={{ color: "var(--text-secondary)" }}
              >清除</button>
              {selectedNames.size > 0 && (
                <span className="ml-auto text-[10px]" style={{ color: "var(--text-muted)" }}>
                  已選 {selectedNames.size} 個
                </span>
              )}
            </div>
            <div className="flex gap-2">
              <button
                onClick={handleBatchGenerateAngles}
                disabled={selectedNames.size === 0}
                className="flex-1 py-1.5 rounded text-[11px] font-semibold bg-sky-500/20 text-sky-400 hover:bg-sky-500/30 disabled:opacity-40 transition-all flex items-center justify-center gap-1.5"
              >
                <Layers size={11} />
                生成人設圖{selectedNames.size > 0 ? `（${selectedNames.size}）` : ""}
              </button>
              <button
                onClick={handleBatchDelete}
                disabled={selectedNames.size === 0}
                className="flex-1 py-1.5 rounded text-[11px] font-semibold bg-red-500/20 text-red-400 hover:bg-red-500/30 disabled:opacity-40 transition-all"
              >
                刪除{selectedNames.size > 0 ? `（${selectedNames.size}）` : ""}
              </button>
            </div>
          </div>
        ) : selectedCharName && (
          <div className="p-3 border-t shrink-0" style={{ borderColor: "var(--border)" }}>
            <button
              onClick={() => { onSelectCharacter(null); onClose(); }}
              className="w-full py-1.5 rounded text-xs hover:bg-white/10 transition-all"
              style={{ color: "var(--text-secondary)" }}
            >取消使用角色（回到無角色模式）</button>
          </div>
        )}
      </div>

      {/* 預覽大圖燈箱 */}
      {previewSrc && <ImageLightbox src={previewSrc.src} prompt={previewSrc.prompt} onClose={() => setPreviewSrc(null)} />}
    </>
  );
}
