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
  getLLMSettings, patchLLMSettings, LLMSettings,
} from "@/lib/model-api";
import {
  getIllustrationStatus, preloadIllustrationModel, unloadIllustrationModel,
  getIllustrationSettings, patchIllustrationSettings, IllustrationEngineSettings,
  listLoras, listEmbeddings, listVaes, LoraInfo,
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
  onDownloaded?: () => void;
  activating: boolean;
  deleting: boolean;
}

function ModelCard({ model, category, llmRole, onActivate, onDelete, onStyleChange, onDownloaded, activating, deleting }: ModelCardProps) {
  const [dlProgress, setDlProgress] = useState<number | null>(null);
  const dlUnsubRef = useRef<(() => void) | null>(null);

  // 缺檔但有下載來源的「預設」：用 model.source 觸發既有下載流程
  const handleDownload = async () => {
    if (!model.source) return;
    try {
      setDlProgress(0);
      const id = await startDownload(model.source, category, model.name, llmRole ?? "chat");
      dlUnsubRef.current = subscribeDownloadProgress(
        id,
        (t) => setDlProgress(t.progress),
        () => {
          setDlProgress(null);
          onDownloaded?.();
        },
      );
    } catch (e: any) {
      setDlProgress(null);
      toast.error(e.message || "下載失敗");
    }
  };

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
            {model.available === false && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-red-500/20 text-red-400">未下載</span>
            )}
            {model.arch && (
              <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${
                model.arch === "zimage" ? "bg-teal-500/20 text-teal-300"
                : model.arch === "wan" ? "bg-white/15 text-white/60"
                : "bg-sky-500/20 text-sky-300"
              }`}>
                {model.arch === "zimage" ? "Z-Image" : model.arch === "wan" ? "WAN" : "SDXL"}{model.is_turbo ? "·Turbo" : ""}
              </span>
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
          {model.available === false ? (
            <button
              onClick={handleDownload}
              disabled={dlProgress !== null}
              title={`線上下載：${model.source}`}
              className="flex items-center gap-1 px-2.5 py-1 rounded text-xs bg-sky-600/80 hover:bg-sky-500 text-white transition-colors disabled:opacity-60"
            >
              {dlProgress !== null
                ? <><Loader2 size={12} className="animate-spin" /> {dlProgress}%</>
                : <><Download size={12} /> 下載</>}
            </button>
          ) : !model.is_active && (
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

// ─── 單一模型模式開關 ─────────────────────────────────────────────────────────

function SingleModelToggle() {
  const [on, setOn] = useState(false);
  useEffect(() => {
    getIllustrationSettings().then(s => setOn(s.single_model_mode ?? false)).catch(() => {});
  }, []);
  const toggle = () => setOn(v => {
    patchIllustrationSettings({ single_model_mode: !v }).catch(() => toast.error("儲存失敗"));
    return !v;
  });
  return (
    <div className="mt-2 border border-white/8 rounded-xl p-4 bg-white/3">
      <div className="flex items-center justify-between">
        <div className="flex flex-col pr-3">
          <span className="text-xs font-semibold text-white/60">單一模型模式</span>
          <span className="text-[10px] text-white/35 leading-relaxed">
            開啟後一律用上方「使用中」的模型生圖（不分動畫/寫實），提示詞形式跟著它
            （Z-Image→自然語言、SDXL→標籤）。
          </span>
        </div>
        <button
          onClick={toggle}
          className={`relative w-9 h-5 rounded-full transition-colors shrink-0 ${on ? "bg-emerald-500" : "bg-white/20"}`}
        >
          <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${on ? "translate-x-4" : ""}`} />
        </button>
      </div>
      {on && (
        <p className="text-[10px] text-white/35 mt-2 leading-relaxed">
          已關閉「依場景自動切換動畫/寫實雙模型」；動畫/寫實此時只影響風格語氣，不再切換模型。
        </p>
      )}
    </div>
  );
}

// ─── 影像模型常用參數 ─────────────────────────────────────────────────────────

function ImageParamsPanel() {
  const [steps,  setSteps]  = useState(30);
  const [cfg,    setCfg]    = useState(6.0);
  const [width,  setWidth]  = useState(1024);
  const [height, setHeight] = useState(1024);
  const [turboOverride, setTurboOverride] = useState(false);
  const [hiresEnabled, setHiresEnabled] = useState(false);
  const [hiresDenoise, setHiresDenoise] = useState(0.35);
  const [adEnabled,    setAdEnabled]    = useState(true);
  const [adDenoise,    setAdDenoise]    = useState(0.4);
  const [neg,          setNeg]          = useState("");
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const negTimer  = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    getIllustrationSettings().then(s => {
      setSteps(s.steps ?? 30);
      setCfg(s.guidance_scale ?? 6.0);
      setWidth(s.width ?? 1024);
      setHeight(s.height ?? 1024);
      setTurboOverride(s.turbo_override ?? false);
      setHiresEnabled(s.hires_fix_enabled ?? false);
      setHiresDenoise(s.hires_denoise ?? 0.35);
      setAdEnabled(s.adetailer_enabled ?? true);
      setAdDenoise(s.adetailer_denoise ?? 0.4);
      setNeg(s.negative_prompt ?? "");
    }).catch(() => {});
  }, []);

  const patch = (p: Partial<IllustrationEngineSettings>) => {
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      patchIllustrationSettings(p).catch(() => toast.error("儲存生圖參數失敗"));
    }, 500);
  };

  return (
    <div className="mt-2 space-y-4 border border-white/8 rounded-xl p-4 bg-white/3">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-white/40 uppercase tracking-widest">常用參數</p>
        <span className="text-[10px] text-white/30">所有生圖共用，閱讀器設定同步</span>
      </div>
      <p className="text-[10px] text-white/35 leading-relaxed -mt-1">
        以下步數與 CFG 適用於標準 SDXL 模型，永遠生效。
      </p>

      {/* 採樣步數 */}
      <div className="flex flex-col gap-1">
        <div className="flex justify-between text-[11px] text-white/50">
          <span>採樣步數 (steps)</span>
          <span className="font-mono font-bold text-violet-400">{steps}</span>
        </div>
        <input type="range" min="4" max="40" step="1" value={steps}
          onChange={e => { const v = +e.target.value; setSteps(v); patch({ steps: v }); }}
          className="w-full h-1 rounded accent-violet-500 cursor-pointer" />
        <div className="flex justify-between text-[9px] text-white/25">
          <span>4 / 8（Turbo）</span><span>30（SDXL 建議）</span><span>40（精細）</span>
        </div>
      </div>

      {/* CFG */}
      <div className="flex flex-col gap-1">
        <div className="flex justify-between text-[11px] text-white/50">
          <span>CFG Scale（提示詞相關性）</span>
          <span className="font-mono font-bold text-violet-400">{cfg.toFixed(1)}</span>
        </div>
        <input type="range" min="1.0" max="8.0" step="0.5" value={cfg}
          onChange={e => { const v = +e.target.value; setCfg(v); patch({ guidance_scale: v }); }}
          className="w-full h-1 rounded accent-violet-500 cursor-pointer" />
        <div className="flex justify-between text-[9px] text-white/25">
          <span>1.0（Turbo）</span><span>6.0（SDXL 建議）</span><span>8.0（強烈）</span>
        </div>
      </div>

      {/* Turbo / Z-Image 專屬覆寫（不影響標準 SDXL）*/}
      <div className="flex flex-col gap-1.5 px-3 py-2.5 rounded-lg border border-violet-500/20 bg-violet-500/5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] font-semibold text-white/70">手動覆寫步數與 CFG</span>
            <span className="text-[8px] px-1.5 py-0.5 rounded-full bg-violet-500/20 text-violet-300 shrink-0">僅 Turbo / Z-Image</span>
          </div>
          <button
            onClick={() => { setTurboOverride(v => { patch({ turbo_override: !v }); return !v; }); }}
            className={`relative w-9 h-5 rounded-full transition-colors shrink-0 ${turboOverride ? "bg-violet-500" : "bg-white/20"}`}
          >
            <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${turboOverride ? "translate-x-4" : ""}`} />
          </button>
        </div>
        <span className="text-[9px] text-white/40 leading-relaxed">
          Turbo / Z-Image 預設自動套用官方優化值（Turbo 8 步、Z-Image 基礎 28 步）。
          開啟此項才改用上方滑桿；<span className="text-white/30">標準 SDXL 不受此開關影響，滑桿一律生效。</span>
        </span>
        {turboOverride && (
          <span className="text-[9px] text-yellow-500/70">⚠ Z-Image Turbo 的 CFG&gt;1 易退化，建議維持 1.0</span>
        )}
      </div>

      {/* Hires Fix */}
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between">
          <div className="flex flex-col">
            <span className="text-[11px] font-semibold text-white/60">Hires Fix 高解析度精修</span>
            <span className="text-[9px] text-white/35">生圖後上採樣 × img2img 補細節（臉、手）</span>
          </div>
          <button
            onClick={() => setHiresEnabled(v => { patch({ hires_fix_enabled: !v }); return !v; })}
            className={`relative w-9 h-5 rounded-full transition-colors shrink-0 ${hiresEnabled ? "bg-violet-500" : "bg-white/20"}`}
          >
            <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${hiresEnabled ? "translate-x-4" : ""}`} />
          </button>
        </div>
        {hiresEnabled && (
          <div className="flex flex-col gap-1">
            <div className="flex justify-between text-[10px] text-white/50">
              <span>重繪強度（Denoise）</span>
              <span className="font-mono font-bold text-violet-400">{hiresDenoise.toFixed(2)}</span>
            </div>
            <input type="range" min="0.25" max="0.5" step="0.05" value={hiresDenoise}
              onChange={e => { const v = +e.target.value; setHiresDenoise(v); patch({ hires_denoise: v }); }}
              className="w-full h-1 rounded accent-violet-500 cursor-pointer" />
          </div>
        )}
      </div>

      {/* ADetailer */}
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between">
          <div className="flex flex-col">
            <span className="text-[11px] font-semibold text-white/60">ADetailer 臉部精修</span>
            <span className="text-[9px] text-white/35">偵測臉部 → 局部 img2img 重繪 → 羽化貼回</span>
          </div>
          <button
            onClick={() => setAdEnabled(v => { patch({ adetailer_enabled: !v }); return !v; })}
            className={`relative w-9 h-5 rounded-full transition-colors shrink-0 ${adEnabled ? "bg-violet-500" : "bg-white/20"}`}
          >
            <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${adEnabled ? "translate-x-4" : ""}`} />
          </button>
        </div>
        {adEnabled && (
          <div className="flex flex-col gap-1">
            <div className="flex justify-between text-[10px] text-white/50">
              <span>重繪強度（Denoise）</span>
              <span className="font-mono font-bold text-violet-400">{adDenoise.toFixed(2)}</span>
            </div>
            <input type="range" min="0.25" max="0.55" step="0.05" value={adDenoise}
              onChange={e => { const v = +e.target.value; setAdDenoise(v); patch({ adetailer_denoise: v }); }}
              className="w-full h-1 rounded accent-violet-500 cursor-pointer" />
          </div>
        )}
      </div>

      {/* 圖片尺寸 */}
      <div className="flex flex-col gap-1.5">
        <span className="text-[11px] text-white/50">圖片尺寸</span>
        <div className="flex gap-2">
          {([512, 768, 1024] as const).map(size => {
            const active = width === size && height === size;
            return (
              <button
                key={size}
                onClick={() => { setWidth(size); setHeight(size); patch({ width: size, height: size }); }}
                className={`flex-1 py-1.5 rounded text-[11px] border transition-colors ${
                  active
                    ? "border-violet-500/60 text-violet-400 bg-violet-500/10 font-semibold"
                    : "border-white/10 text-white/40 hover:text-white/60 hover:border-white/20"
                }`}
              >
                {size}px
              </button>
            );
          })}
        </div>
        {width !== height && (
          <span className="text-[9px] text-white/30">目前為 {width}×{height}</span>
        )}
      </div>

      {/* 反向提示詞 */}
      <div className="flex flex-col gap-1.5">
        <span className="text-[11px] font-semibold text-white/55">反向提示詞（不希望出現的元素）</span>
        <textarea
          value={neg}
          onChange={e => {
            const v = e.target.value;
            setNeg(v);
            if (negTimer.current) clearTimeout(negTimer.current);
            negTimer.current = setTimeout(() => {
              if (v.trim()) patchIllustrationSettings({ negative_prompt: v }).catch(() => toast.error("儲存反向提示詞失敗"));
            }, 600);
          }}
          placeholder="例如：extra limbs, blurry, watermark"
          rows={3}
          className="w-full px-2.5 py-2 rounded border border-white/10 bg-black/30 text-[10px] text-white outline-none resize-none focus:border-white/30"
        />
      </div>
    </div>
  );
}

// ─── 輔助模型（VAE / Embedding / LoRA，皆依目錄掃描）────────────────────────────

function AuxModelsPanel() {
  const [loras,      setLoras]      = useState<LoraInfo[]>([]);
  const [embeddings, setEmbeddings] = useState<LoraInfo[]>([]);
  const [vaes,       setVaes]       = useState<LoraInfo[]>([]);
  const [activeLoras, setActiveLoras] = useState<{ filename: string; weight: number; enabled: boolean }[]>([]);
  const [activeEmb,   setActiveEmb]   = useState<string[]>([]);
  const [activeVae,   setActiveVae]   = useState("");
  const weightTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    getIllustrationSettings().then(s => {
      setActiveLoras(s.active_loras ?? []);
      setActiveEmb(s.active_embeddings ?? []);
      setActiveVae(s.active_vae ?? "");
    }).catch(() => {});
    // 內部使用的 FaceID LoRA 不列給使用者切換
    listLoras().then(l => setLoras(l.filter(x => !x.filename.toLowerCase().includes("ip-adapter-faceid")))).catch(() => {});
    listEmbeddings().then(setEmbeddings).catch(() => {});
    listVaes().then(setVaes).catch(() => {});
  }, []);

  const save = (p: Partial<IllustrationEngineSettings>) =>
    patchIllustrationSettings(p).catch(() => toast.error("儲存輔助模型設定失敗"));

  // ── LoRA ──
  const loraOf = (f: string) => activeLoras.find(l => l.filename === f) ?? { enabled: false, weight: 1.0 };
  const commitLoras = (updated: typeof activeLoras) => { setActiveLoras(updated); save({ active_loras: updated }); };
  const toggleLora = (f: string) => {
    const ex = activeLoras.find(l => l.filename === f);
    commitLoras(ex
      ? activeLoras.map(l => l.filename === f ? { ...l, enabled: !l.enabled } : l)
      : [...activeLoras, { filename: f, weight: 1.0, enabled: true }]);
  };
  const setLoraWeight = (f: string, w: number) => {
    const ex = activeLoras.some(l => l.filename === f);
    const updated = ex ? activeLoras.map(l => l.filename === f ? { ...l, weight: w } : l)
                       : [...activeLoras, { filename: f, weight: w, enabled: true }];
    setActiveLoras(updated);
    if (weightTimer.current) clearTimeout(weightTimer.current);
    weightTimer.current = setTimeout(() => save({ active_loras: updated }), 400);
  };

  // ── Embedding（active_embeddings 空 = 全部載入；非空 = 只載入清單內）──
  const embEnabled = (f: string) => activeEmb.length === 0 || activeEmb.includes(f);
  const toggleEmb = (f: string) => {
    const base = activeEmb.length === 0 ? embeddings.map(e => e.filename) : [...activeEmb];
    const updated = base.includes(f) ? base.filter(x => x !== f) : [...base, f];
    setActiveEmb(updated); save({ active_embeddings: updated });
  };

  // ── VAE（單選，"" = 模型內建）──
  const chooseVae = (f: string) => { setActiveVae(f); save({ active_vae: f }); };

  const EmptyHint = ({ dir }: { dir: string }) => (
    <div className="text-[10px] px-2.5 py-2 rounded border border-white/8 text-white/30 bg-white/3">
      目錄無檔案（放入 models/{dir}/ 即可在此設定）
    </div>
  );

  return (
    <div className="mt-2 space-y-5 border border-white/8 rounded-xl p-4 bg-white/3">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-white/40 uppercase tracking-widest">輔助模型</p>
        <span className="text-[10px] text-white/30">依目錄掃描 · 變更後需重新載入模型</span>
      </div>

      {/* VAE */}
      <div className="flex flex-col gap-1.5">
        <span className="text-[11px] font-semibold text-white/55">VAE</span>
        {vaes.length === 0 ? <EmptyHint dir="vae" /> : (
          <div className="flex flex-col gap-1">
            <button
              onClick={() => chooseVae("")}
              className={`flex items-center justify-between px-2.5 py-1.5 rounded border text-[11px] transition-colors ${
                activeVae === "" ? "border-violet-500/60 bg-violet-500/10 text-violet-300" : "border-white/10 text-white/50 hover:border-white/20"
              }`}
            >
              <span>模型內建（預設）</span>
              {activeVae === "" && <CheckCircle2 size={13} className="text-violet-400" />}
            </button>
            {vaes.map(v => (
              <button
                key={v.filename}
                onClick={() => chooseVae(v.filename)}
                className={`flex items-center justify-between px-2.5 py-1.5 rounded border text-[11px] transition-colors ${
                  activeVae === v.filename ? "border-violet-500/60 bg-violet-500/10 text-violet-300" : "border-white/10 text-white/50 hover:border-white/20"
                }`}
              >
                <span className="truncate">{v.filename}</span>
                <span className="flex items-center gap-2 shrink-0">
                  <span className="text-white/25">{v.size_mb}MB</span>
                  {activeVae === v.filename && <CheckCircle2 size={13} className="text-violet-400" />}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Embedding（文字編碼增強）*/}
      <div className="flex flex-col gap-1.5">
        <span className="text-[11px] font-semibold text-white/55">文字編碼增強（Embedding）</span>
        {embeddings.length === 0 ? <EmptyHint dir="embeddings" /> : (
          <div className="flex flex-col gap-1">
            {embeddings.map(e => {
              const on = embEnabled(e.filename);
              return (
                <div key={e.filename} className="flex items-center gap-2 px-2.5 py-1.5 rounded border border-white/10 bg-white/3">
                  <button
                    onClick={() => toggleEmb(e.filename)}
                    className={`relative w-8 h-4 rounded-full transition-colors shrink-0 ${on ? "bg-violet-500" : "bg-white/20"}`}
                  >
                    <span className={`absolute top-0.5 left-0.5 w-3 h-3 bg-white rounded-full shadow transition-transform ${on ? "translate-x-4" : ""}`} />
                  </button>
                  <span className="flex-1 text-[11px] truncate" style={{ color: on ? undefined : "rgba(255,255,255,0.4)" }}>
                    {e.filename.replace(/\.(safetensors|pt|bin)$/, "")}
                  </span>
                  <span className="text-[9px] text-white/25 shrink-0">{e.size_mb}MB</span>
                </div>
              );
            })}
            <span className="text-[9px] text-white/30">未選任何項＝全部載入（預設）</span>
          </div>
        )}
      </div>

      {/* LoRA */}
      <div className="flex flex-col gap-1.5">
        <span className="text-[11px] font-semibold text-white/55">LoRA</span>
        {loras.length === 0 ? <EmptyHint dir="loras" /> : (
          <div className="flex flex-col gap-1.5">
            {loras.map(lora => {
              const st = loraOf(lora.filename);
              return (
                <div key={lora.filename} className="flex flex-col gap-1 px-2.5 py-2 rounded border"
                  style={{ borderColor: st.enabled ? "#8b5cf680" : "rgba(255,255,255,0.1)", backgroundColor: "rgba(255,255,255,0.03)" }}>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => toggleLora(lora.filename)}
                      className={`relative w-8 h-4 rounded-full transition-colors shrink-0 ${st.enabled ? "bg-violet-500" : "bg-white/20"}`}
                    >
                      <span className={`absolute top-0.5 left-0.5 w-3 h-3 bg-white rounded-full shadow transition-transform ${st.enabled ? "translate-x-4" : ""}`} />
                    </button>
                    <span className="flex-1 text-[11px] truncate" title={lora.filename} style={{ color: st.enabled ? undefined : "rgba(255,255,255,0.4)" }}>
                      {lora.filename.replace(/\.(safetensors|bin|pt)$/, "").slice(0, 36)}
                    </span>
                    <span className="text-[9px] text-white/25 shrink-0">{lora.size_mb}MB</span>
                  </div>
                  {st.enabled && (
                    <div className="flex items-center gap-2 mt-0.5">
                      <span className="text-[9px] text-white/40 shrink-0">強度</span>
                      <input type="range" min="0.1" max="1.5" step="0.05" value={st.weight}
                        onChange={e => setLoraWeight(lora.filename, +e.target.value)}
                        className="flex-1 h-1 rounded accent-violet-500 cursor-pointer" />
                      <span className="text-[9px] font-mono w-7 text-right text-violet-300">{st.weight.toFixed(2)}</span>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── 文字模型常用參數（全域取樣覆寫）────────────────────────────────────────────

function LLMParamsPanel() {
  const [s, setS] = useState<LLMSettings | null>(null);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    getLLMSettings().then(setS).catch(() => {});
  }, []);

  const update = (patch: Partial<LLMSettings>) => {
    setS(prev => (prev ? { ...prev, ...patch } : prev));
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      patchLLMSettings(patch).catch(() => toast.error("儲存 LLM 設定失敗"));
    }, 500);
  };

  if (!s) return null;
  const on = s.override_enabled;

  return (
    <div className="mt-2 space-y-4 border border-white/8 rounded-xl p-4 bg-white/3">
      {/* 總開關 */}
      <div className="flex items-center justify-between">
        <div className="flex flex-col">
          <span className="text-xs font-semibold text-white/60">全域取樣覆寫</span>
          <span className="text-[10px] text-white/35">關閉時沿用各任務的內建調校值（建議）</span>
        </div>
        <button
          onClick={() => update({ override_enabled: !on })}
          className={`relative w-9 h-5 rounded-full transition-colors ${on ? "bg-emerald-500" : "bg-white/20"}`}
        >
          <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${on ? "translate-x-4" : ""}`} />
        </button>
      </div>

      {on && (
        <div className="space-y-4">
          <p className="text-[10px] text-yellow-500/70 leading-relaxed">
            ⚠ 覆寫會以單一值套用到所有任務（角色分析、場景解析、構圖擴寫），
            可能降低提示詞品質的一致性。
          </p>

          {/* Temperature */}
          <div className="flex flex-col gap-1">
            <div className="flex justify-between text-[11px] text-white/50">
              <span>Temperature（隨機性）</span>
              <span className="font-mono font-bold text-emerald-400">{s.temperature.toFixed(2)}</span>
            </div>
            <input type="range" min="0" max="1.5" step="0.05" value={s.temperature}
              onChange={e => update({ temperature: +e.target.value })}
              className="w-full h-1 rounded accent-emerald-500 cursor-pointer" />
            <div className="flex justify-between text-[9px] text-white/25">
              <span>0（穩定）</span><span>0.7（平衡）</span><span>1.5（發散）</span>
            </div>
          </div>

          {/* Top-P */}
          <div className="flex flex-col gap-1">
            <div className="flex justify-between text-[11px] text-white/50">
              <span>Top-P（核採樣）</span>
              <span className="font-mono font-bold text-emerald-400">{s.top_p.toFixed(2)}</span>
            </div>
            <input type="range" min="0.1" max="1.0" step="0.05" value={s.top_p}
              onChange={e => update({ top_p: +e.target.value })}
              className="w-full h-1 rounded accent-emerald-500 cursor-pointer" />
          </div>

          {/* Top-K */}
          <div className="flex flex-col gap-1">
            <div className="flex justify-between text-[11px] text-white/50">
              <span>Top-K（候選數）</span>
              <span className="font-mono font-bold text-emerald-400">{s.top_k}</span>
            </div>
            <input type="range" min="0" max="100" step="1" value={s.top_k}
              onChange={e => update({ top_k: +e.target.value })}
              className="w-full h-1 rounded accent-emerald-500 cursor-pointer" />
          </div>

          {/* Repeat penalty */}
          <div className="flex flex-col gap-1">
            <div className="flex justify-between text-[11px] text-white/50">
              <span>Repeat Penalty（重複懲罰）</span>
              <span className="font-mono font-bold text-emerald-400">{s.repeat_penalty.toFixed(2)}</span>
            </div>
            <input type="range" min="1.0" max="1.5" step="0.05" value={s.repeat_penalty}
              onChange={e => update({ repeat_penalty: +e.target.value })}
              className="w-full h-1 rounded accent-emerald-500 cursor-pointer" />
          </div>

          {/* Max tokens（選填）*/}
          <div className="flex flex-col gap-1">
            <div className="flex justify-between text-[11px] text-white/50">
              <span>最大輸出長度 (max_tokens)</span>
              <span className="font-mono text-emerald-400">{s.max_tokens === null ? "不覆寫" : s.max_tokens}</span>
            </div>
            <div className="flex gap-2 items-center">
              <input
                type="number"
                min="64"
                max="8192"
                value={s.max_tokens ?? ""}
                onChange={e => {
                  const v = parseInt(e.target.value, 10);
                  update({ max_tokens: isNaN(v) ? null : v });
                }}
                placeholder="留空＝沿用各任務值"
                className="flex-1 px-2 py-1.5 rounded border border-white/10 bg-black/30 text-[11px] text-white outline-none font-mono focus:border-white/30"
              />
              {s.max_tokens !== null && (
                <button
                  onClick={() => update({ max_tokens: null })}
                  className="px-2 py-1.5 rounded text-[10px] text-red-400 hover:bg-red-500/10"
                >
                  清除
                </button>
              )}
            </div>
            <span className="text-[9px] text-white/30">留空避免截斷較長輸出（如全書角色分析）</span>
          </div>
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
            const label = role === "chat" ? "對話 / 擴寫模型" : "角色分析 / 構圖模型";
            const hint  = role === "chat"
              ? "備援角色；亦作為 Z-Image 文字編碼器"
              : "全書角色分析，並把段落轉成插圖構圖（場景解析＋構圖擴寫）";
            return (
              <div key={role}>
                <p className="text-xs text-white/40 uppercase tracking-widest mb-0.5">{label}</p>
                <p className="text-[10px] text-white/30 mb-2">{hint}</p>
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
                      onDownloaded={fetchModels}
                      activating={activatingId === m.id}
                      deleting={deletingId === m.id}
                    />
                  ))}
                </div>
              </div>
            );
          })}

          {/* 文字模型常用參數 */}
          <LLMParamsPanel />
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
            onDownloaded={fetchModels}
            activating={activatingId === m.id}
            deleting={deletingId === m.id}
          />
        ))}

        {/* 圖像模型專屬：單一模型模式 */}
        {cat === "image" && <SingleModelToggle />}

        {/* 圖像模型專屬：VRAM 載入/釋放（LLM 狀態與設定統一移至「語言模型」分頁）*/}
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
          </div>
        )}

        {/* 圖像模型專屬：常用生圖參數 + 輔助模型 */}
        {cat === "image" && <ImageParamsPanel />}
        {cat === "image" && <AuxModelsPanel />}
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
