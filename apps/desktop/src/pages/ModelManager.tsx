import { useEffect, useState, useRef } from "react";
import { toast } from "sonner";
import { useRouter } from "@tanstack/react-router";
import {
  Cpu, Mic, Image, ArrowLeft, Trash2, CheckCircle2, Circle,
  Plus, X, Loader2, Download, Key,
} from "lucide-react";
import {
  getAllModels, probeUrl, startDownload, subscribeDownloadProgress,
  cancelDownload, activateModel, deleteModel, patchModel,
  getCivitaiToken, setCivitaiToken, scanLocalModels,
  formatBytes, formatSpeed,
  AllModels, ModelInfo, ProbeResult, DownloadTask,
} from "@/lib/model-api";
import {
  getIllustrationStatus, preloadIllustrationModel, unloadIllustrationModel,
} from "@/lib/api";

type Category = "tts" | "image" | "llm";
type LLMRole = "chat" | "analysis";

const CATEGORY_META: Record<Category, { label: string; icon: React.ReactNode; color: string }> = {
  tts:   { label: "語音合成",  icon: <Mic  size={16} />, color: "text-sky-400"    },
  image: { label: "圖像生成",  icon: <Image size={16} />, color: "text-violet-400" },
  llm:   { label: "語言模型",  icon: <Cpu  size={16} />, color: "text-emerald-400" },
};

// ─── 下載區塊 ─────────────────────────────────────────────────────────────────

interface AddModelFormProps {
  defaultCategory?: Category;
  onSuccess: () => void;
}

function AddModelForm({ defaultCategory = "tts", onSuccess }: AddModelFormProps) {
  const [url,      setUrl]      = useState("");
  const [name,     setName]     = useState("");
  const [category, setCategory] = useState<Category>(defaultCategory);
  const [role,     setRole]     = useState<LLMRole>("chat");
  const [probe,    setProbe]    = useState<ProbeResult | null>(null);
  const [probing,  setProbing]  = useState(false);
  const [task,     setTask]     = useState<DownloadTask | null>(null);
  const [taskId,   setTaskId]   = useState<string | null>(null);
  const unsubRef = useRef<(() => void) | null>(null);

  const handleProbe = async () => {
    if (!url.trim()) return;
    setProbing(true);
    setProbe(null);
    try {
      const result = await probeUrl(url.trim());
      setProbe(result);
      if (result.name && !name) setName(result.name);
      if (result.category) setCategory(result.category as Category);
    } catch (e: any) {
      toast.error(e.message || "偵測失敗");
    } finally {
      setProbing(false);
    }
  };

  const handleDownload = async () => {
    if (!url.trim() || !name.trim()) {
      toast.error("請填寫連結和名稱");
      return;
    }
    try {
      const id = await startDownload(url.trim(), category, name.trim(), role);
      setTaskId(id);
      unsubRef.current = subscribeDownloadProgress(
        id,
        (t) => setTask(t),
        () => {
          onSuccess();
          if (task?.status === "done") toast.success(`${name} 下載完成`);
        }
      );
    } catch (e: any) {
      toast.error(e.message || "下載失敗");
    }
  };

  const handleCancel = () => {
    if (taskId) cancelDownload(taskId);
    unsubRef.current?.();
    setTask(null); setTaskId(null);
  };

  const isDownloading = task && ["running"].includes(task.status);

  return (
    <div className="border border-white/10 rounded-xl p-4 bg-white/5 space-y-3">
      <p className="text-xs font-semibold text-white/60 uppercase tracking-widest">新增模型</p>

      {/* URL 輸入 */}
      <div className="flex gap-2">
        <input
          value={url}
          onChange={e => setUrl(e.target.value)}
          onKeyDown={e => e.key === "Enter" && handleProbe()}
          placeholder="貼上連結（HuggingFace / Civitai / 直連…）"
          className="flex-1 px-3 py-2 rounded-lg bg-black/30 border border-white/10 text-sm text-white placeholder-white/30 outline-none focus:border-white/30"
          disabled={!!isDownloading}
        />
        <button
          onClick={handleProbe}
          disabled={probing || !!isDownloading}
          className="px-3 py-2 rounded-lg bg-white/10 hover:bg-white/15 text-xs text-white/80 transition-colors disabled:opacity-40"
        >
          {probing ? <Loader2 size={14} className="animate-spin" /> : "偵測"}
        </button>
      </div>

      {/* 偵測結果 */}
      {probe && (
        <div className="text-xs text-white/50 bg-white/5 rounded px-3 py-2 space-y-1">
          <div>
            偵測到：<span className="text-white/80">{probe.source}</span>
            {probe.category && <> · 類別：<span className="text-sky-400">{probe.category}</span></>}
          </div>
          {/* 主模型 */}
          <div className="flex items-center gap-1.5 text-white/70">
            <span className="px-1.5 py-0.5 rounded bg-sky-500/20 text-sky-400 text-[10px]">Model</span>
            <span className="truncate">{probe.name}</span>
          </div>
          {/* 附加檔案（VAE / Text Encoder） */}
          {probe.extra_files?.map(ef => (
            <div key={ef.name} className="flex items-center gap-1.5 text-white/55">
              <span className={`px-1.5 py-0.5 rounded text-[10px] ${
                ef.type === "VAE" ? "bg-violet-500/20 text-violet-400" : "bg-amber-500/20 text-amber-400"
              }`}>{ef.type}</span>
              <span className="truncate">{ef.name}</span>
              <span className="ml-auto shrink-0 text-white/30">{formatBytes(ef.size_bytes)}</span>
            </div>
          ))}
          {probe.extra_files && probe.extra_files.length > 0 && (
            <p className="text-white/30 text-[10px] pt-0.5">以上全部將一同下載</p>
          )}
        </div>
      )}

      {/* 設定列 */}
      <div className="flex gap-2">
        <input
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="顯示名稱"
          className="flex-1 px-3 py-2 rounded-lg bg-black/30 border border-white/10 text-sm text-white placeholder-white/30 outline-none focus:border-white/30"
          disabled={!!isDownloading}
        />
        <select
          value={category}
          onChange={e => setCategory(e.target.value as Category)}
          className="px-3 py-2 rounded-lg bg-black/30 border border-white/10 text-sm text-white/80 outline-none"
          disabled={!!isDownloading}
        >
          <option value="tts">語音合成</option>
          <option value="image">圖像生成</option>
          <option value="llm">語言模型</option>
        </select>
        {category === "llm" && (
          <select
            value={role}
            onChange={e => setRole(e.target.value as LLMRole)}
            className="px-3 py-2 rounded-lg bg-black/30 border border-white/10 text-sm text-white/80 outline-none"
            disabled={!!isDownloading}
          >
            <option value="chat">對話/擴寫</option>
            <option value="analysis">角色分析</option>
          </select>
        )}
      </div>

      {/* 下載進度 */}
      {task && (
        <div className="space-y-1.5">
          <div className="flex justify-between text-xs text-white/50">
            <span>{task.label}</span>
            <span>{formatBytes(task.downloaded)}{task.total ? ` / ${formatBytes(task.total)}` : ""} {formatSpeed(task.speed)}</span>
          </div>
          <div className="h-1.5 bg-white/10 rounded-full overflow-hidden">
            <div
              className="h-full bg-sky-500 rounded-full transition-all"
              style={{ width: `${task.progress}%` }}
            />
          </div>
          {task.status === "error" && (
            <p className="text-xs text-red-400">{task.error}</p>
          )}
        </div>
      )}

      {/* 操作按鈕 */}
      <div className="flex gap-2 justify-end">
        {isDownloading ? (
          <button
            onClick={handleCancel}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs bg-red-900/40 text-red-300 hover:bg-red-900/60 transition-colors"
          >
            <X size={13} /> 取消
          </button>
        ) : (
          <button
            onClick={handleDownload}
            disabled={!url.trim() || !name.trim()}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs bg-sky-600 text-white hover:bg-sky-500 transition-colors disabled:opacity-40"
          >
            <Download size={13} /> 開始下載
          </button>
        )}
      </div>
    </div>
  );
}

// ─── CivitAI Token 設定 ──────────────────────────────────────────────────────

function CivitaiTokenSection() {
  const [open,    setOpen]    = useState(false);
  const [input,   setInput]   = useState("");
  const [preview, setPreview] = useState("");
  const [isSet,   setIsSet]   = useState(false);
  const [saving,  setSaving]  = useState(false);

  useEffect(() => {
    getCivitaiToken().then(r => { setIsSet(r.set); setPreview(r.preview); });
  }, []);

  const handleSave = async () => {
    if (!input.trim()) return;
    setSaving(true);
    try {
      await setCivitaiToken(input.trim());
      const r = await getCivitaiToken();
      setIsSet(r.set); setPreview(r.preview);
      setInput(""); setOpen(false);
      toast.success("CivitAI Token 已儲存");
    } catch (e: any) {
      toast.error(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="border border-white/8 rounded-xl p-3 bg-white/3">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between text-xs"
      >
        <div className="flex items-center gap-2 text-white/50">
          <Key size={13} />
          <span>CivitAI API Token</span>
        </div>
        <span className={isSet ? "text-emerald-400 font-mono" : "text-yellow-500/70"}>
          {isSet ? preview : "未設定 — 下載 NSFW 模型需要"}
        </span>
      </button>
      {open && (
        <div className="mt-3 flex gap-2">
          <input
            type="password"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === "Enter" && handleSave()}
            placeholder="貼上你的 CivitAI API Token"
            className="flex-1 px-3 py-2 rounded-lg bg-black/30 border border-white/10 text-sm text-white placeholder-white/30 outline-none focus:border-white/30"
            autoFocus
          />
          <button
            onClick={handleSave}
            disabled={!input.trim() || saving}
            className="px-3 py-2 rounded-lg bg-sky-600 text-xs text-white hover:bg-sky-500 transition-colors disabled:opacity-40"
          >
            {saving ? <Loader2 size={13} className="animate-spin" /> : "儲存"}
          </button>
        </div>
      )}
    </div>
  );
}

// ─── 模型卡片 ─────────────────────────────────────────────────────────────────

interface ModelCardProps {
  model: ModelInfo;
  category: Category;
  llmRole?: LLMRole;
  onActivate: () => void;
  onDelete: () => void;
  onStyleChange?: (style: "anime" | "real") => void;
  activating: boolean;
  deleting: boolean;
}

function ModelCard({ model, category, llmRole, onActivate, onDelete, onStyleChange, activating, deleting }: ModelCardProps) {
  return (
    <div className={`flex flex-col gap-2 px-4 py-3 rounded-xl border transition-colors ${
      model.is_active
        ? "border-white/20 bg-white/8"
        : "border-white/8 bg-white/3 hover:bg-white/5"
    }`}>
      <div className="flex items-center gap-3">
        {/* 狀態指示 */}
        <div className="flex-shrink-0">
          {model.is_active
            ? <CheckCircle2 size={16} className="text-emerald-400" />
            : <Circle size={16} className="text-white/20" />
          }
        </div>

        {/* 模型資訊 */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-white truncate">{model.name}</span>
            {model.is_active && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 font-medium">
                {category === "llm" ? (llmRole === "chat" ? "對話" : "分析") : "使用中"}
              </span>
            )}
            {model.is_loaded && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-sky-500/20 text-sky-400">已載入</span>
            )}
          </div>
          <div className="text-xs text-white/35 mt-0.5 flex items-center gap-2">
            <span className="truncate">{model.source || model.local_path}</span>
            <span className="shrink-0">{formatBytes(model.size_bytes)}</span>
          </div>
          {/* VAE / Text Encoder 附加檔案標示 */}
          {(model.vae_path || model.text_encoder_path) && (
            <div className="flex gap-1.5 mt-1">
              {model.vae_path && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-violet-500/15 text-violet-400/80">VAE</span>
              )}
              {model.text_encoder_path && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400/80">Text Encoder</span>
              )}
            </div>
          )}
        </div>

        {/* 操作 */}
        <div className="flex items-center gap-1.5 flex-shrink-0">
          {!model.is_active && (
            <button
              onClick={onActivate}
              disabled={activating}
              className="px-2.5 py-1 rounded text-xs bg-white/10 hover:bg-white/15 text-white/70 transition-colors disabled:opacity-40"
            >
              {activating ? <Loader2 size={12} className="animate-spin" /> : "切換"}
            </button>
          )}
          <button
            onClick={onDelete}
            disabled={deleting || model.is_active}
            title={model.is_active ? "無法刪除使用中的模型" : "刪除模型檔案"}
            className="p-1.5 rounded text-white/30 hover:text-red-400 hover:bg-red-400/10 transition-colors disabled:opacity-30"
          >
            {deleting ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
          </button>
        </div>
      </div>

      {/* 圖像模型風格選擇器 */}
      {category === "image" && onStyleChange && (
        <div className="flex items-center gap-2 pt-1 border-t border-white/6">
          <span className="text-[10px] text-white/30 shrink-0">生圖風格</span>
          <div className="flex gap-1">
            {(["anime", "real"] as const).map(s => (
              <button
                key={s}
                onClick={() => onStyleChange(s)}
                className={`px-2 py-0.5 rounded text-[10px] font-medium border transition-colors ${
                  model.style === s
                    ? s === "anime"
                      ? "bg-violet-500/25 border-violet-500/60 text-violet-400"
                      : "bg-amber-500/25 border-amber-500/60 text-amber-400"
                    : "border-white/10 text-white/30 hover:text-white/55 hover:border-white/20"
                }`}
              >
                {s === "anime" ? "動畫" : "寫實"}
              </button>
            ))}
          </div>
          {!model.style && (
            <span className="text-[10px] text-yellow-500/60">⚠ 未設定，生圖時將找不到此模型</span>
          )}
        </div>
      )}
    </div>
  );
}

// ─── 主頁面 ───────────────────────────────────────────────────────────────────

export default function ModelManager() {
  const router = useRouter();
  const [models,  setModels]  = useState<AllModels | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab,     setTab]     = useState<Category>("tts");
  const [showAdd, setShowAdd] = useState(false);
  const [activatingId, setActivatingId] = useState<string | null>(null);
  const [deletingId,   setDeletingId]   = useState<string | null>(null);
  const [scanning,     setScanning]     = useState(false);

  // 圖像模型 VRAM 狀態
  const [illStatus,    setIllStatus]    = useState<{ llm_available: boolean; llm_model: string | null; model_loaded: boolean } | null>(null);
  const [illusLoading, setIllusLoading] = useState(false);

  const fetchModels = async () => {
    try {
      setModels(await getAllModels());
    } catch {
      toast.error("無法取得模型列表");
    } finally {
      setLoading(false);
    }
  };

  const fetchImageStatus = async () => {
    getIllustrationStatus().then(setIllStatus).catch(() => {});
  };

  useEffect(() => {
    fetchModels();
    fetchImageStatus();
  }, []);

  const handleActivate = async (category: Category, modelId: string, role: LLMRole = "chat") => {
    setActivatingId(modelId);
    try {
      await activateModel(category, modelId, category === "llm" ? role : "default");
      toast.success("已切換模型（Hot-swap 中…）");
      await fetchModels();
    } catch (e: any) {
      toast.error(e.message || "切換失敗");
    } finally {
      setActivatingId(null);
    }
  };

  const handleStyleChange = async (category: Category, modelId: string, style: "anime" | "real") => {
    try {
      await patchModel(category, modelId, { style });
      toast.success(`已設定為「${style === "anime" ? "動畫" : "寫實"}」風格`);
      await fetchModels();
    } catch (e: any) {
      toast.error(e.message || "設定失敗");
    }
  };

  const handleDelete = async (category: Category, modelId: string) => {
    if (!confirm(`確定刪除模型「${modelId}」？此操作將移除本地檔案。`)) return;
    setDeletingId(modelId);
    try {
      await deleteModel(category, modelId);
      toast.success("模型已刪除");
      await fetchModels();
    } catch (e: any) {
      toast.error(e.message || "刪除失敗");
    } finally {
      setDeletingId(null);
    }
  };

  // ── 渲染各類別的模型列表 ─────────────────────────────────────────────────────
  const renderCategory = (cat: Category) => {
    if (!models) return null;
    const data = models[cat];

    if (cat === "llm") {
      const llm = models.llm;
      const allModels = llm.models;
      return (
        <div className="space-y-6">
          {(["chat", "analysis"] as LLMRole[]).map(role => {
            const activeId = role === "chat" ? llm.chat : llm.analysis;
            const label = role === "chat" ? "對話 / 擴寫模型（4B 級）" : "角色分析模型（27B 級）";
            return (
              <div key={role}>
                <p className="text-xs text-white/40 uppercase tracking-widest mb-2">{label}</p>
                <div className="space-y-2">
                  {allModels.length === 0 && (
                    <p className="text-xs text-white/30 py-2">尚無已安裝的語言模型</p>
                  )}
                  {allModels.map(m => (
                    <ModelCard
                      key={m.id + role}
                      model={{ ...m, is_active: m.id === activeId }}
                      category="llm"
                      llmRole={role}
                      onActivate={() => handleActivate("llm", m.id, role)}
                      onDelete={() => handleDelete("llm", m.id)}
                      activating={activatingId === m.id}
                      deleting={deletingId === m.id}
                    />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      );
    }

    const catData = data as { active: string | null; models: ModelInfo[] };
    return (
      <div className="space-y-3">
        {catData.models.length === 0 && (
          <p className="text-xs text-white/30 py-2">尚無已安裝的模型</p>
        )}
        {catData.models.map(m => (
          <ModelCard
            key={m.id}
            model={m}
            category={cat}
            onActivate={() => handleActivate(cat, m.id)}
            onDelete={() => handleDelete(cat, m.id)}
            onStyleChange={cat === "image" ? (style) => handleStyleChange(cat, m.id, style) : undefined}
            activating={activatingId === m.id}
            deleting={deletingId === m.id}
          />
        ))}

        {/* 圖像模型專屬：VRAM 控制 + Transformer + LLM 狀態 */}
        {cat === "image" && (
          <div className="mt-2 space-y-3 border border-white/8 rounded-xl p-4 bg-white/3">
            <p className="text-xs font-semibold text-white/40 uppercase tracking-widest">VRAM 管理</p>

            {/* 載入狀態 + 按鈕 */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-xs">
                <div className={`w-2 h-2 rounded-full ${illStatus?.model_loaded ? "bg-emerald-500" : "bg-white/20"}`} />
                <span className="text-white/60">{illStatus?.model_loaded ? "模型已在 VRAM" : "模型未載入"}</span>
              </div>
              <div className="flex gap-2">
                {!illStatus?.model_loaded && (
                  <button
                    onClick={async () => {
                      setIllusLoading(true);
                      try { await preloadIllustrationModel(); toast.success("預載入中…"); fetchImageStatus(); }
                      catch { toast.error("預載入失敗"); }
                      finally { setIllusLoading(false); }
                    }}
                    disabled={illusLoading}
                    className="flex items-center gap-1 px-2.5 py-1 rounded text-xs bg-white/10 hover:bg-white/15 text-white/70 transition-colors disabled:opacity-40"
                  >
                    {illusLoading ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}
                    預載入
                  </button>
                )}
                {illStatus?.model_loaded && (
                  <button
                    onClick={async () => {
                      if (!confirm("卸載生圖模型以釋放 VRAM？")) return;
                      setIllusLoading(true);
                      try { await unloadIllustrationModel(); toast.success("已釋放 VRAM"); fetchImageStatus(); }
                      catch { toast.error("卸載失敗"); }
                      finally { setIllusLoading(false); }
                    }}
                    disabled={illusLoading}
                    className="flex items-center gap-1 px-2.5 py-1 rounded text-xs bg-white/10 hover:bg-white/15 text-white/60 transition-colors disabled:opacity-40"
                  >
                    {illusLoading ? <Loader2 size={12} className="animate-spin" /> : null}
                    釋放 VRAM
                  </button>
                )}
              </div>
            </div>

            {/* LLM 狀態 */}
            <div className="flex items-center justify-between text-xs">
              <span className="text-white/40">Prompt 優化 LLM</span>
              <div className="flex items-center gap-1.5">
                <div className={`w-1.5 h-1.5 rounded-full ${illStatus?.llm_available ? "bg-emerald-500" : "bg-yellow-500"}`} />
                <span className="text-white/50 font-mono truncate max-w-[140px]">
                  {illStatus === null ? "偵測中…" : illStatus.llm_available ? (illStatus.llm_model ?? "就緒") : "找不到 GGUF"}
                </span>
              </div>
            </div>
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="min-h-screen bg-[#0d0d0d] text-white">
      {/* 頂部導覽 */}
      <header className="sticky top-0 z-10 flex items-center gap-3 h-14 px-6 border-b border-white/8 bg-[#0d0d0d]/90 backdrop-blur-sm">
        <button
          onClick={() => router.history.back()}
          className="p-1.5 rounded hover:bg-white/10 text-white/50 hover:text-white transition-colors"
        >
          <ArrowLeft size={18} />
        </button>
        <Cpu size={18} className="text-emerald-400" />
        <h1 className="text-sm font-semibold">模型管理</h1>
      </header>

      <div className="max-w-2xl mx-auto px-6 py-8 space-y-6">
        {/* Tab */}
        <div className="flex gap-1 p-1 bg-white/5 rounded-xl">
          {(Object.entries(CATEGORY_META) as [Category, typeof CATEGORY_META[Category]][]).map(([cat, meta]) => (
            <button
              key={cat}
              onClick={() => setTab(cat)}
              className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-xs font-medium transition-colors ${
                tab === cat
                  ? "bg-white/15 text-white"
                  : "text-white/40 hover:text-white/60"
              }`}
            >
              <span className={tab === cat ? meta.color : ""}>{meta.icon}</span>
              {meta.label}
            </button>
          ))}
        </div>

        {/* 已安裝模型 */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <p className="text-xs text-white/40 uppercase tracking-widest">已安裝</p>
            <button
              onClick={async () => {
                setScanning(true);
                try {
                  const result = await scanLocalModels();
                  if (result.added > 0) {
                    toast.success(`發現 ${result.added} 個新模型已自動登錄`);
                    await fetchModels();
                  } else {
                    toast.info("未發現新模型");
                  }
                } catch (e: any) {
                  toast.error(e.message || "掃描失敗");
                } finally {
                  setScanning(false);
                }
              }}
              disabled={scanning}
              className="flex items-center gap-1 px-2.5 py-1 rounded text-xs bg-white/8 hover:bg-white/12 text-white/50 hover:text-white/70 transition-colors disabled:opacity-40"
            >
              {scanning ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />}
              掃描本機
            </button>
          </div>
          {loading
            ? <div className="flex justify-center py-8"><Loader2 size={20} className="animate-spin text-white/30" /></div>
            : renderCategory(tab)
          }
        </div>

        {/* CivitAI Token */}
        <CivitaiTokenSection />

        {/* 新增模型 */}
        <div>
          {showAdd ? (
            <AddModelForm
              defaultCategory={tab}
              onSuccess={() => { fetchModels(); setShowAdd(false); }}
            />
          ) : (
            <button
              onClick={() => setShowAdd(true)}
              className="w-full flex items-center justify-center gap-2 py-3 rounded-xl border border-dashed border-white/15 text-white/40 hover:border-white/25 hover:text-white/60 text-sm transition-colors"
            >
              <Plus size={15} /> 貼上連結新增模型
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
