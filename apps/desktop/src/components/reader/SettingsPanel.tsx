import { useState, useEffect, useRef } from "react";
import { useReaderStore } from "@/stores/reader";
import { usePlayerStore } from "@/stores/player";
import {
  X, Sliders, Type, Volume2, HardDrive, Trash2,
  Download, Cpu, Mic, Wand2, Bot, ChevronDown, ChevronUp,
  Loader2, CheckCircle2, UploadCloud
} from "lucide-react";
import {
  ModelStatus,
  getModelsStatus,
  downloadModel,
  deleteModel,
  loadModel,
  unloadModel,
} from "@/lib/api";
import { TTSMode } from "@/stores/player";

interface SettingsPanelProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function SettingsPanel({ isOpen, onClose }: SettingsPanelProps) {
  const {
    theme,
    fontSize,
    fontFamily,
    lineHeight,
    hardwareInfo,
    setTheme,
    setFontSize,
    setFontFamily,
    setLineHeight,
  } = useReaderStore();

  const {
    speed,
    setSpeed,
    ttsMode,
    refAudioPath,
    refText,
    instruct,
    numStep,
    duration,
    setTTSMode,
    setRefAudioPath,
    setRefText,
    setInstruct,
    setNumStep,
    setDuration,
  } = usePlayerStore();

  const [models, setModels] = useState<ModelStatus[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [modelActionLoading, setModelActionLoading] = useState<string | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const fetchModels = async (showLoading = false) => {
    if (showLoading) setLoadingModels(true);
    try {
      const data = await getModelsStatus();
      setModels(data);
    } catch (err) {
      console.error("載入模型列表失敗:", err);
    } finally {
      if (showLoading) setLoadingModels(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchModels(true);
    }
  }, [isOpen]);

  // 下載中時每 1.5 秒輪詢進度
  useEffect(() => {
    let timer: NodeJS.Timeout | null = null;
    const hasDownloading = models.some((m) => m.status === "downloading");

    if (hasDownloading && isOpen) {
      timer = setInterval(() => {
        fetchModels();
      }, 1500);
    }

    return () => {
      if (timer) clearInterval(timer);
    };
  }, [models, isOpen]);

  const handleDownload = async (modelId: string) => {
    try {
      setModelActionLoading(modelId + "_download");
      await downloadModel(modelId);
      fetchModels();
    } catch (err: any) {
      alert(`啟動下載失敗: ${err.message}`);
    } finally {
      setModelActionLoading(null);
    }
  };

  const handleLoad = async (modelId: string) => {
    if (!confirm(`確定要將「${modelId}」載入至 TTS 引擎嗎？\n這需要一些時間，載入期間 TTS 無法使用。`)) return;
    try {
      setModelActionLoading(modelId + "_load");
      await loadModel(modelId);
      await fetchModels();
    } catch (err: any) {
      alert(`載入模型失敗: ${err.message}`);
    } finally {
      setModelActionLoading(null);
    }
  };

  const handleUnload = async (modelId: string) => {
    if (!confirm("確定要從記憶體中卸載此模型嗎？\n卸載後 TTS 將無法運作，需重新載入才能繼續使用。")) return;
    try {
      setModelActionLoading(modelId + "_unload");
      await unloadModel();
      await fetchModels();
    } catch (err: any) {
      alert(`卸載模型失敗: ${err.message}`);
    } finally {
      setModelActionLoading(null);
    }
  };

  const handleDelete = async (modelId: string) => {
    if (!confirm("確定要刪除此模型檔案嗎？\n若模型正在下載中，將自動取消下載。")) return;
    try {
      setModelActionLoading(modelId + "_delete");
      await deleteModel(modelId);
      await fetchModels();
    } catch (err: any) {
      alert(`刪除模型失敗: ${err.message}`);
    } finally {
      setModelActionLoading(null);
    }
  };

  // 處理參考音訊檔案選擇
  const handleRefAudioSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      // 使用 file:// 協定的絕對路徑（Tauri 環境）或 blob URL（瀏覽器環境）
      const filePath = (file as any).path || URL.createObjectURL(file);
      setRefAudioPath(filePath);
    }
  };

  const modeOptions: { id: TTSMode; label: string; desc: string; icon: JSX.Element }[] = [
    {
      id: "clone",
      label: "聲音複製",
      desc: "上傳 3-10 秒參考音訊",
      icon: <Mic size={13} />,
    },
    {
      id: "design",
      label: "聲音設計",
      desc: "文字描述聲音風格",
      icon: <Wand2 size={13} />,
    },
    {
      id: "auto",
      label: "自動",
      desc: "使用模型預設聲音",
      icon: <Bot size={13} />,
    },
  ];

  return (
    <>
      {/* 背景半透明遮罩 */}
      {isOpen && (
        <div
          onClick={onClose}
          className="fixed inset-0 bg-black/40 backdrop-blur-xs z-40 transition-opacity duration-300"
        />
      )}

      {/* 右側設定抽屜面板 */}
      <div
        className="fixed top-0 right-0 h-full w-[340px] shadow-2xl z-50 transition-transform duration-300 ease-out border-l flex flex-col"
        style={{
          backgroundColor: "var(--bg-surface)",
          borderColor: "var(--border)",
          color: "var(--text-primary)",
          transform: isOpen ? "translateX(0)" : "translateX(100%)",
        }}
      >
        {/* 標題欄 */}
        <header className="flex justify-between items-center px-6 py-4 border-b" style={{ borderColor: "var(--border)" }}>
          <div className="flex items-center gap-2 font-bold text-sm tracking-wider">
            <Sliders size={16} className="text-amber-500" />
            <span>閱讀器設定</span>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-full hover:bg-white/10 active:scale-95 transition-all"
            style={{ color: "var(--text-secondary)" }}
          >
            <X size={18} />
          </button>
        </header>

        {/* 設定內容區 */}
        <main className="flex-1 overflow-y-auto p-6 flex flex-col gap-6">

          {/* Section 1: 顯示設定 */}
          <section className="flex flex-col gap-4">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-amber-500 uppercase tracking-widest">
              <Type size={14} />
              <span>顯示設定</span>
            </div>

            {/* 字型大小 */}
            <div className="flex flex-col gap-1.5 text-xs">
              <div className="flex justify-between text-xs" style={{ color: "var(--text-secondary)" }}>
                <span>字型大小</span>
                <span className="font-semibold">{fontSize}px</span>
              </div>
              <input
                type="range"
                min="14"
                max="28"
                value={fontSize}
                onChange={(e) => setFontSize(parseInt(e.target.value, 10))}
                className="w-full h-1 rounded bg-white/15 accent-amber-500 cursor-pointer"
              />
            </div>

            {/* 行距 */}
            <div className="flex flex-col gap-1.5 text-xs">
              <div className="flex justify-between text-xs" style={{ color: "var(--text-secondary)" }}>
                <span>行距</span>
                <span className="font-semibold">{lineHeight.toFixed(1)}</span>
              </div>
              <input
                type="range"
                min="1.4"
                max="2.0"
                step="0.1"
                value={lineHeight}
                onChange={(e) => setLineHeight(parseFloat(e.target.value))}
                className="w-full h-1 rounded bg-white/15 accent-amber-500 cursor-pointer"
              />
            </div>

            {/* 字體 */}
            <div className="flex flex-col gap-1.5 text-xs">
              <span style={{ color: "var(--text-secondary)" }}>字體選擇</span>
              <div className="flex gap-2">
                <button
                  onClick={() => setFontFamily("sans")}
                  className={`flex-1 py-1.5 rounded text-xs transition-all border ${
                    fontFamily === "sans"
                      ? "border-amber-500 text-amber-500 bg-amber-500/5 font-semibold"
                      : "border-transparent hover:bg-white/5"
                  }`}
                  style={{ backgroundColor: fontFamily !== "sans" ? "var(--bg-hover)" : undefined }}
                >
                  黑體 (Sans)
                </button>
                <button
                  onClick={() => setFontFamily("serif")}
                  className={`flex-1 py-1.5 rounded text-xs transition-all border ${
                    fontFamily === "serif"
                      ? "border-amber-500 text-amber-500 bg-amber-500/5 font-semibold"
                      : "border-transparent hover:bg-white/5"
                  }`}
                  style={{ backgroundColor: fontFamily !== "serif" ? "var(--bg-hover)" : undefined }}
                >
                  明體 (Serif)
                </button>
              </div>
            </div>

            {/* 主題 */}
            <div className="flex flex-col gap-1.5 text-xs">
              <span style={{ color: "var(--text-secondary)" }}>閱讀主題</span>
              <div className="flex gap-2">
                {(["dark", "light", "paper"] as const).map((t) => (
                  <button
                    key={t}
                    onClick={() => setTheme(t)}
                    className={`flex-1 py-1.5 rounded text-xs transition-all border capitalize ${
                      theme === t
                        ? "border-amber-500 text-amber-500 bg-amber-500/5 font-semibold"
                        : "border-transparent hover:bg-white/5"
                    }`}
                    style={{ backgroundColor: theme !== t ? "var(--bg-hover)" : undefined }}
                  >
                    {t === "dark" ? "深色" : t === "light" ? "淺色" : "紙張"}
                  </button>
                ))}
              </div>
            </div>
          </section>

          <hr style={{ borderColor: "var(--border)" }} />

          {/* Section 2: 朗讀設定 */}
          <section className="flex flex-col gap-4">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-amber-500 uppercase tracking-widest">
              <Volume2 size={14} />
              <span>語音合成設定</span>
            </div>

            {/* 語速 */}
            <div className="flex flex-col gap-1.5 text-xs">
              <div className="flex justify-between text-xs" style={{ color: "var(--text-secondary)" }}>
                <span>語速</span>
                <span className="font-semibold">{speed.toFixed(2)}×</span>
              </div>
              <input
                type="range"
                min="0.5"
                max="2.0"
                step="0.05"
                value={speed}
                onChange={(e) => setSpeed(parseFloat(e.target.value))}
                className="w-full h-1 rounded bg-white/15 accent-amber-500 cursor-pointer"
              />
            </div>

            {/* 語音模式選擇 */}
            <div className="flex flex-col gap-2 text-xs">
              <span style={{ color: "var(--text-secondary)" }}>語音模式</span>
              <div className="flex flex-col gap-1.5">
                {modeOptions.map((m) => (
                  <button
                    key={m.id}
                    onClick={() => setTTSMode(m.id)}
                    className={`flex items-center gap-2.5 px-3 py-2 rounded-lg border transition-all text-left ${
                      ttsMode === m.id
                        ? "border-amber-500/60 bg-amber-500/8"
                        : "border-transparent hover:border-white/10"
                    }`}
                    style={{
                      backgroundColor: ttsMode !== m.id ? "var(--bg-hover)" : undefined,
                    }}
                  >
                    <span className={ttsMode === m.id ? "text-amber-400" : "text-gray-500"}>{m.icon}</span>
                    <div className="flex flex-col">
                      <span className={`font-semibold ${ttsMode === m.id ? "text-amber-400" : ""}`}>{m.label}</span>
                      <span className="text-[10px]" style={{ color: "var(--text-secondary)" }}>{m.desc}</span>
                    </div>
                    {ttsMode === m.id && (
                      <CheckCircle2 size={13} className="ml-auto text-amber-500 shrink-0" />
                    )}
                  </button>
                ))}
              </div>
            </div>

            {/* 聲音複製設定 */}
            {ttsMode === "clone" && (
              <div className="flex flex-col gap-2.5 text-xs p-3 rounded-lg border" style={{ borderColor: "var(--border)", backgroundColor: "var(--bg-hover)" }}>
                <span className="font-semibold text-amber-400/80">聲音複製設定</span>

                {/* 參考音訊上傳 */}
                <div className="flex flex-col gap-1">
                  <span style={{ color: "var(--text-secondary)" }}>參考音訊（3-10 秒）</span>
                  <div
                    className="flex items-center gap-2 px-2.5 py-2 rounded border border-dashed cursor-pointer hover:bg-white/5 transition-all"
                    style={{ borderColor: "var(--border)" }}
                    onClick={() => fileInputRef.current?.click()}
                  >
                    <UploadCloud size={14} className="text-amber-500 shrink-0" />
                    <span className="text-[10px] truncate flex-1" style={{ color: refAudioPath ? "var(--text-primary)" : "var(--text-secondary)" }}>
                      {refAudioPath ? refAudioPath.split(/[/\\]/).pop() : "點擊選擇音訊檔案..."}
                    </span>
                    {refAudioPath && (
                      <button
                        onClick={(e) => { e.stopPropagation(); setRefAudioPath(""); }}
                        className="p-0.5 rounded hover:bg-red-500/20 text-red-400"
                      >
                        <X size={10} />
                      </button>
                    )}
                  </div>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept="audio/*,.wav,.mp3,.flac,.ogg,.m4a"
                    className="hidden"
                    onChange={handleRefAudioSelect}
                  />
                </div>

                {/* 逐字稿（選填） */}
                <div className="flex flex-col gap-1">
                  <span style={{ color: "var(--text-secondary)" }}>
                    參考音訊逐字稿
                    <span className="ml-1 opacity-60">（選填，可提升品質）</span>
                  </span>
                  <textarea
                    value={refText}
                    onChange={(e) => setRefText(e.target.value)}
                    placeholder="輸入參考音訊的逐字稿內容，省略時將自動辨識..."
                    rows={2}
                    className="w-full px-2.5 py-2 rounded border text-[10px] outline-none resize-none"
                    style={{
                      backgroundColor: "var(--bg-surface)",
                      borderColor: "var(--border)",
                      color: "var(--text-primary)",
                    }}
                  />
                </div>
              </div>
            )}

            {/* 聲音設計設定 */}
            {ttsMode === "design" && (
              <div className="flex flex-col gap-2.5 text-xs p-3 rounded-lg border" style={{ borderColor: "var(--border)", backgroundColor: "var(--bg-hover)" }}>
                <span className="font-semibold text-amber-400/80">聲音設計設定</span>
                <div className="flex flex-col gap-1">
                  <span style={{ color: "var(--text-secondary)" }}>聲音屬性描述</span>
                  <textarea
                    value={instruct}
                    onChange={(e) => setInstruct(e.target.value)}
                    placeholder="例如：female, young adult, cheerful, taiwanese mandarin"
                    rows={3}
                    className="w-full px-2.5 py-2 rounded border text-[10px] outline-none resize-none"
                    style={{
                      backgroundColor: "var(--bg-surface)",
                      borderColor: "var(--border)",
                      color: "var(--text-primary)",
                    }}
                  />
                  <span className="text-[9px] leading-relaxed mt-0.5" style={{ color: "var(--text-secondary)" }}>
                    可設定：gender · age · pitch · accent · style（如 whisper）<br />
                    非語言：文字中插入 [laughter]、[sigh] 等
                  </span>
                </div>
              </div>
            )}

            {/* 進階推理設定 */}
            <button
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="flex items-center gap-1.5 text-[10px] font-semibold hover:opacity-80 transition-all"
              style={{ color: "var(--text-secondary)" }}
            >
              {showAdvanced ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              進階推理設定
            </button>

            {showAdvanced && (
              <div className="flex flex-col gap-3 text-xs p-3 rounded-lg border" style={{ borderColor: "var(--border)", backgroundColor: "var(--bg-hover)" }}>
                {/* 擴散步數 */}
                <div className="flex flex-col gap-1.5">
                  <div className="flex justify-between" style={{ color: "var(--text-secondary)" }}>
                    <span>擴散步數 (num_step)</span>
                    <span className="font-mono font-bold">{numStep}</span>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => setNumStep(16)}
                      className={`flex-1 py-1.5 rounded text-[10px] border transition-all ${
                        numStep === 16 ? "border-amber-500 text-amber-500 font-bold" : "border-transparent hover:bg-white/5"
                      }`}
                      style={{ backgroundColor: numStep !== 16 ? "var(--bg-surface)" : undefined }}
                    >
                      16 步（快速）
                    </button>
                    <button
                      onClick={() => setNumStep(32)}
                      className={`flex-1 py-1.5 rounded text-[10px] border transition-all ${
                        numStep === 32 ? "border-amber-500 text-amber-500 font-bold" : "border-transparent hover:bg-white/5"
                      }`}
                      style={{ backgroundColor: numStep !== 32 ? "var(--bg-surface)" : undefined }}
                    >
                      32 步（高品質）
                    </button>
                  </div>
                </div>

                {/* 固定輸出時長 */}
                <div className="flex flex-col gap-1">
                  <div className="flex justify-between" style={{ color: "var(--text-secondary)" }}>
                    <span>固定輸出時長（秒）</span>
                    <span className="font-mono text-[10px]">{duration === null ? "不限制" : `${duration}s`}</span>
                  </div>
                  <div className="flex gap-2 items-center">
                    <input
                      type="number"
                      min="1"
                      max="60"
                      step="0.5"
                      value={duration ?? ""}
                      onChange={(e) => {
                        const v = parseFloat(e.target.value);
                        setDuration(isNaN(v) ? null : v);
                      }}
                      placeholder="留空表示不限制"
                      className="flex-1 px-2 py-1.5 rounded border text-[10px] outline-none"
                      style={{
                        backgroundColor: "var(--bg-surface)",
                        borderColor: "var(--border)",
                        color: "var(--text-primary)",
                      }}
                    />
                    {duration !== null && (
                      <button
                        onClick={() => setDuration(null)}
                        className="px-2 py-1.5 rounded text-[10px] text-red-400 hover:bg-red-500/10"
                      >
                        清除
                      </button>
                    )}
                  </div>
                  <span className="text-[9px]" style={{ color: "var(--text-secondary)" }}>
                    設定後將覆蓋語速設定，強制輸出此長度的音訊
                  </span>
                </div>
              </div>
            )}
          </section>

          <hr style={{ borderColor: "var(--border)" }} />

          {/* Section 3: 模型管理 */}
          <section className="flex flex-col gap-4">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-amber-500 uppercase tracking-widest">
              <Download size={14} />
              <span>模型管理</span>
            </div>

            {/* 無模型載入時的提示 */}
            {!loadingModels && models.length > 0 && !models.some(m => m.loaded) && (
              <div className="flex items-start gap-2 px-3 py-2.5 rounded-lg border border-amber-500/30 bg-amber-500/5 text-xs" style={{ color: "var(--text-secondary)" }}>
                <span className="text-amber-400 mt-0.5 shrink-0">⚠</span>
                <span>目前無模型載入，語音朗讀功能無法使用。請下載並載入一個模型。</span>
              </div>
            )}

            {loadingModels && models.length === 0 ? (
              <div className="text-center py-4 text-xs animate-pulse" style={{ color: "var(--text-secondary)" }}>
                載入模型列表中...
              </div>
            ) : (
              <div className="flex flex-col gap-3">
                {models.map((m) => {
                  const isActionLoading = (suffix: string) => modelActionLoading === m.id + suffix;

                  return (
                    <div
                      key={m.id}
                      className="p-3 rounded-lg border flex flex-col gap-2 transition-all duration-300 relative overflow-hidden"
                      style={{
                        backgroundColor: m.loaded ? "rgba(245,158,11,0.06)" : m.active ? "var(--bg-hover)" : "transparent",
                        borderColor: m.loaded
                          ? "rgba(245,158,11,0.5)"
                          : m.active
                          ? "rgba(245,158,11,0.25)"
                          : "var(--border)",
                      }}
                    >
                      {/* 載入中的發光裝飾 */}
                      {m.loaded && (
                        <div className="absolute top-0 right-0 w-16 h-16 bg-amber-500/10 rounded-full blur-xl pointer-events-none" />
                      )}

                      {/* 模型名稱與狀態標籤 */}
                      <div className="flex justify-between items-start">
                        <div className="flex flex-col gap-0.5">
                          <span className="text-xs font-bold flex items-center gap-1.5 flex-wrap">
                            {m.name}
                            {m.loaded && (
                              <span className="px-1.5 py-0.5 text-[9px] rounded bg-amber-500 text-black font-extrabold uppercase tracking-wider">
                                已載入
                              </span>
                            )}
                            {m.active && !m.loaded && (
                              <span className="px-1.5 py-0.5 text-[9px] rounded border border-amber-500/40 text-amber-500 font-bold uppercase tracking-wider">
                                已選取
                              </span>
                            )}
                          </span>
                          <span className="text-[10px]" style={{ color: "var(--text-secondary)" }}>
                            {m.type} · {m.size_str}
                          </span>
                        </div>

                        {/* 操作按鈕群組 */}
                        <div className="flex items-center gap-1 flex-shrink-0 ml-1">
                          {/* 尚未下載 → 下載按鈕 */}
                          {m.status === "not_downloaded" && (
                            <button
                              onClick={() => handleDownload(m.id)}
                              disabled={!!modelActionLoading}
                              className="px-2.5 py-1 rounded text-[10px] font-semibold bg-amber-500 text-black hover:bg-amber-600 active:scale-95 transition-all cursor-pointer disabled:opacity-50"
                            >
                              {isActionLoading("_download") ? (
                                <Loader2 size={10} className="animate-spin" />
                              ) : (
                                "下載"
                              )}
                            </button>
                          )}

                          {/* 已下載且未載入 → 載入按鈕 + 刪除 */}
                          {m.status === "downloaded" && !m.loaded && (
                            <>
                              <button
                                onClick={() => handleLoad(m.id)}
                                disabled={!!modelActionLoading}
                                className="px-2.5 py-1 rounded text-[10px] font-semibold border border-amber-500/50 text-amber-500 hover:bg-amber-500/10 active:scale-95 transition-all cursor-pointer disabled:opacity-50 flex items-center gap-1"
                              >
                                {isActionLoading("_load") ? (
                                  <Loader2 size={10} className="animate-spin" />
                                ) : (
                                  <><Cpu size={9} /> 載入</>
                                )}
                              </button>
                              <button
                                onClick={() => handleDelete(m.id)}
                                disabled={!!modelActionLoading}
                                className="p-1 rounded text-red-400 hover:bg-red-500/10 active:scale-95 transition-all cursor-pointer disabled:opacity-50"
                                title="刪除模型"
                              >
                                {isActionLoading("_delete") ? (
                                  <Loader2 size={11} className="animate-spin" />
                                ) : (
                                  <Trash2 size={11} />
                                )}
                              </button>
                            </>
                          )}

                          {/* 已載入 → 卸載按鈕 + 刪除 */}
                          {m.loaded && (
                            <>
                              <button
                                onClick={() => handleUnload(m.id)}
                                disabled={!!modelActionLoading}
                                className="px-2.5 py-1 rounded text-[10px] font-semibold border border-white/20 text-gray-400 hover:bg-white/5 active:scale-95 transition-all cursor-pointer disabled:opacity-50 flex items-center gap-1"
                              >
                                {isActionLoading("_unload") ? (
                                  <Loader2 size={10} className="animate-spin" />
                                ) : (
                                  "卸載"
                                )}
                              </button>
                              <button
                                onClick={() => handleDelete(m.id)}
                                disabled={!!modelActionLoading}
                                className="p-1 rounded text-red-400 hover:bg-red-500/10 active:scale-95 transition-all cursor-pointer disabled:opacity-50"
                                title="刪除模型"
                              >
                                {isActionLoading("_delete") ? (
                                  <Loader2 size={11} className="animate-spin" />
                                ) : (
                                  <Trash2 size={11} />
                                )}
                              </button>
                            </>
                          )}
                        </div>
                      </div>

                      {/* 下載進度條 */}
                      {m.status === "downloading" && (
                        <div className="flex flex-col gap-1 mt-1">
                          <div className="flex justify-between text-[10px] font-semibold" style={{ color: "var(--text-secondary)" }}>
                            <span>下載中...</span>
                            <span className="font-mono">{m.progress}%</span>
                          </div>
                          <div className="w-full h-1.5 rounded-full overflow-hidden bg-white/10 relative">
                            <div
                              className="h-full bg-amber-500 rounded-full transition-all duration-300 relative overflow-hidden"
                              style={{ width: `${m.progress}%` }}
                            >
                              <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/20 to-transparent animate-pulse" />
                            </div>
                          </div>
                          {/* 正在下載的模型也提供取消（刪除）按鈕 */}
                          <button
                            onClick={() => handleDelete(m.id)}
                            disabled={!!modelActionLoading}
                            className="self-end text-[9px] text-red-400 hover:underline mt-0.5"
                          >
                            取消下載
                          </button>
                        </div>
                      )}

                      {m.error && (
                        <span className="text-[10px] text-red-400 leading-tight">
                          錯誤: {m.error}
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </section>

          <hr style={{ borderColor: "var(--border)" }} />

          {/* Section 4: 硬體資訊 */}
          <section className="flex flex-col gap-4">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-amber-500 uppercase tracking-widest">
              <HardDrive size={14} />
              <span>硬體資訊</span>
            </div>

            <div className="flex flex-col gap-1 text-[11px]" style={{ color: "var(--text-secondary)" }}>
              <div className="flex justify-between">
                <span>推理裝置:</span>
                <span className="font-mono text-amber-500">{hardwareInfo?.display_name || "CPU (偵測中)"}</span>
              </div>
              <div className="flex justify-between mt-1">
                <span>模型:</span>
                <span className="font-mono">k2-fsa/OmniVoice</span>
              </div>
            </div>
          </section>

        </main>
      </div>
    </>
  );
}
