import React, { useState, useEffect, useRef } from "react";
import { toast } from "sonner";
import { useReaderStore } from "@/stores/reader";
import { usePlayerStore } from "@/stores/player";
import { getIllustrationSettings, patchIllustrationSettings, saveSettings, listLoras, LoraInfo } from "@/lib/api";
import {
  X, Sliders, Type, Volume2, HardDrive,
  Mic, Wand2, Bot, ChevronDown, ChevronUp,
  Loader2, CheckCircle2, UploadCloud, ImagePlus
} from "lucide-react";
import { TTSMode } from "@/stores/player";

interface SettingsPanelProps {
  isOpen: boolean;
  onClose: () => void;
}

// 預設繪圖風格前綴：label 顯示於 UI，value 為實際附加到 prompt 最前面的英文修飾詞
const STYLE_PRESETS: { label: string; value: string }[] = [
  { label: "動漫",     value: "anime style, vibrant colors, clean lineart, highly detailed" },
  { label: "插畫厚塗", value: "digital painting, painterly, soft cinematic lighting, concept art" },
  { label: "水彩",     value: "watercolor painting, soft washes, delicate, artistic" },
  { label: "吉卜力",   value: "studio ghibli style, soft colors, hand-drawn, whimsical, dreamy" },
  { label: "油畫",     value: "oil painting, thick brush strokes, classical, rich texture" },
  { label: "寫實",     value: "photorealistic, cinematic lighting, ultra-detailed, realistic" },
  { label: "賽博龐克", value: "cyberpunk, neon lights, futuristic, high contrast, atmospheric" },
  { label: "素描",     value: "pencil sketch, monochrome, detailed linework, hand-drawn" },
];

export default function SettingsPanel({ isOpen, onClose }: SettingsPanelProps) {
  const {
    theme,
    fontSize,
    fontFamily,
    lineHeight,
    volume,
    hardwareInfo,
    setTheme,
    setFontSize,
    setFontFamily,
    setLineHeight,
    setVolume,
    illustrationPromptPrefix,
    illustrationWidth,
    illustrationHeight,
    illustrationSeed,
    setIllustrationPromptPrefix,
    setIllustrationWidth,
    setIllustrationHeight,
    setIllustrationSeed,
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

  const [showAdvanced, setShowAdvanced] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [negativePrompt, setNegativePrompt] = useState("");
  const negSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 生圖參數（與後端同步）
  const [illSteps,         setIllSteps]         = useState(30);
  const [illCfg,           setIllCfg]           = useState(6.0);
  const [hiresEnabled,     setHiresEnabled]     = useState(false);
  const [hiresDenoise,     setHiresDenoise]     = useState(0.35);
  const [adetailerEnabled, setAdetailerEnabled] = useState(true);
  const [adetailerDenoise, setAdetailerDenoise] = useState(0.4);
  const illSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // LoRA 管理
  const [availableLoras, setAvailableLoras] = useState<LoraInfo[]>([]);
  const [activeLoras, setActiveLoras] = useState<{ filename: string; weight: number; enabled: boolean }[]>([]);

  // 開啟面板時載入所有插圖設定
  useEffect(() => {
    if (!isOpen) return;
    getIllustrationSettings().then(s => {
      setNegativePrompt(s.negative_prompt);
      setIllSteps(s.steps ?? 30);
      setIllCfg(s.guidance_scale ?? 6.0);
      setHiresEnabled(s.hires_fix_enabled ?? false);
      setHiresDenoise(s.hires_denoise ?? 0.35);
      setAdetailerEnabled(s.adetailer_enabled ?? true);
      setAdetailerDenoise(s.adetailer_denoise ?? 0.4);
      setActiveLoras(s.active_loras ?? []);
    }).catch(() => {});
    listLoras().then(setAvailableLoras).catch(() => {});
  }, [isOpen]);

  const updateLoras = (updated: typeof activeLoras) => {
    setActiveLoras(updated);
    patchIllustrationSettings({ active_loras: updated }).catch(() => toast.error("儲存 LoRA 設定失敗"));
  };

  const toggleLora = (filename: string) => {
    const existing = activeLoras.find(l => l.filename === filename);
    let updated: typeof activeLoras;
    if (existing) {
      updated = activeLoras.map(l =>
        l.filename === filename ? { ...l, enabled: !l.enabled } : l
      );
    } else {
      updated = [...activeLoras, { filename, weight: 1.0, enabled: true }];
    }
    updateLoras(updated);
  };

  const setLoraWeight = (filename: string, weight: number) => {
    const exists = activeLoras.some(l => l.filename === filename);
    const updated = exists
      ? activeLoras.map(l => l.filename === filename ? { ...l, weight } : l)
      : [...activeLoras, { filename, weight, enabled: true }];
    updateLoras(updated);
  };

  const getLoraState = (filename: string) =>
    activeLoras.find(l => l.filename === filename) ?? { enabled: false, weight: 1.0 };

  const patchIll = (patch: Parameters<typeof patchIllustrationSettings>[0]) => {
    if (illSaveTimerRef.current) clearTimeout(illSaveTimerRef.current);
    illSaveTimerRef.current = setTimeout(() => {
      patchIllustrationSettings(patch).catch(() => toast.error("儲存生圖設定失敗"));
    }, 600);
  };

  const handleNegativePromptChange = (v: string) => {
    setNegativePrompt(v);
    if (negSaveTimerRef.current) clearTimeout(negSaveTimerRef.current);
    negSaveTimerRef.current = setTimeout(async () => {
      if (!v.trim()) return;
      try {
        await patchIllustrationSettings({ negative_prompt: v });
        await saveSettings({ illustration_negative_prompt: v });
      } catch {
        toast.error("儲存反向提示詞失敗");
      }
    }, 800);
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

  const modeOptions: { id: TTSMode; label: string; desc: string; icon: React.ReactNode }[] = [
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

          {/* Section 3: 插圖生成 */}
          <section className="flex flex-col gap-4">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-amber-500 uppercase tracking-widest">
              <ImagePlus size={14} />
              <span>插圖生成</span>
            </div>

            {/* 人物一致性說明 */}
            <div className="flex flex-col gap-1 pt-1 px-2.5 py-2 rounded border text-[10px]" style={{ borderColor: "var(--border)", backgroundColor: "var(--bg-hover)", color: "var(--text-secondary)" }}>
              <span className="font-semibold" style={{ color: "var(--text-primary)" }}>人物一致性</span>
              <span>選取角色後，生圖時自動注入結構化外觀描述（髮色、髮型、瞳色、體型等）至提示詞。</span>
              <span>前往角色庫填寫角色外觀，可顯著提升同角色的一致性。</span>
            </div>

            {/* Prompt 風格前綴 */}
            <div className="flex flex-col gap-1.5 pt-1">
              <span className="text-[11px] font-semibold" style={{ color: "var(--text-secondary)" }}>繪圖提示詞前綴（風格修飾）</span>

              {/* 預設風格快選 */}
              <div className="flex flex-wrap gap-1.5">
                {STYLE_PRESETS.map((p) => {
                  const active = illustrationPromptPrefix.trim() === p.value;
                  return (
                    <button
                      key={p.label}
                      onClick={() => setIllustrationPromptPrefix(active ? "" : p.value)}
                      title={p.value}
                      className={`px-2 py-1 rounded-full text-[10px] border transition-all ${
                        active
                          ? "border-amber-500 text-amber-500 font-bold bg-amber-500/10"
                          : "border-transparent hover:bg-white/5"
                      }`}
                      style={{ backgroundColor: active ? undefined : "var(--bg-hover)", color: active ? undefined : "var(--text-secondary)" }}
                    >
                      {p.label}
                    </button>
                  );
                })}
              </div>

              <textarea
                value={illustrationPromptPrefix}
                onChange={(e) => setIllustrationPromptPrefix(e.target.value)}
                placeholder="點上方風格快選，或自行輸入：anime style, watercolor, highly detailed"
                rows={2}
                className="w-full px-2.5 py-2 rounded border text-[10px] outline-none resize-none"
                style={{ backgroundColor: "var(--bg-surface)", borderColor: "var(--border)", color: "var(--text-primary)" }}
              />
              <span className="text-[9px] leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                每次生圖時附加在 LLM 生成的 prompt 前，可指定畫風、藝術風格等
              </span>
            </div>

            {/* 圖片尺寸 */}
            <div className="flex flex-col gap-1.5">
              <span className="text-[11px] font-semibold" style={{ color: "var(--text-secondary)" }}>圖片尺寸</span>
              <div className="flex gap-2">
                {([512, 768, 1024] as const).map((size) => (
                  <button
                    key={size}
                    onClick={() => { setIllustrationWidth(size); setIllustrationHeight(size); }}
                    className={`flex-1 py-1.5 rounded text-[10px] border transition-all ${
                      illustrationWidth === size && illustrationHeight === size
                        ? "border-amber-500 text-amber-500 font-bold bg-amber-500/5"
                        : "border-transparent hover:bg-white/5"
                    }`}
                    style={{ backgroundColor: (illustrationWidth !== size || illustrationHeight !== size) ? "var(--bg-hover)" : undefined }}
                  >
                    {size}px
                  </button>
                ))}
              </div>
            </div>

            {/* 固定 Seed */}
            <div className="flex flex-col gap-1">
              <div className="flex justify-between text-[11px]" style={{ color: "var(--text-secondary)" }}>
                <span className="font-semibold">固定 Seed</span>
                <span className="font-mono text-amber-500">{illustrationSeed === -1 ? "隨機" : illustrationSeed}</span>
              </div>
              <div className="flex gap-2 items-center">
                <input
                  type="number"
                  min="-1"
                  max="4294967295"
                  value={illustrationSeed === -1 ? "" : illustrationSeed}
                  onChange={(e) => {
                    const v = parseInt(e.target.value, 10);
                    setIllustrationSeed(isNaN(v) ? -1 : v);
                  }}
                  placeholder="-1（每次隨機）"
                  className="flex-1 px-2 py-1.5 rounded border text-[10px] outline-none font-mono"
                  style={{ backgroundColor: "var(--bg-surface)", borderColor: "var(--border)", color: "var(--text-primary)" }}
                />
                {illustrationSeed !== -1 && (
                  <button
                    onClick={() => setIllustrationSeed(-1)}
                    className="px-2 py-1.5 rounded text-[10px] text-red-400 hover:bg-red-500/10"
                  >
                    清除
                  </button>
                )}
              </div>
              <span className="text-[9px]" style={{ color: "var(--text-secondary)" }}>
                填入固定數字可重現同一張圖，-1 表示每次隨機
              </span>
            </div>
            {/* 生圖核心參數 */}
            <div className="flex flex-col gap-3 pt-1 px-2.5 py-2.5 rounded border" style={{ borderColor: "var(--border)", backgroundColor: "var(--bg-hover)" }}>
              <span className="text-[11px] font-semibold" style={{ color: "var(--text-primary)" }}>擴散參數</span>

              {/* Steps */}
              <div className="flex flex-col gap-1">
                <div className="flex justify-between text-[10px]" style={{ color: "var(--text-secondary)" }}>
                  <span>採樣步數</span>
                  <span className="font-mono font-bold text-amber-400">{illSteps}</span>
                </div>
                <input type="range" min="20" max="40" step="1" value={illSteps}
                  onChange={e => { const v = +e.target.value; setIllSteps(v); patchIll({ steps: v }); }}
                  className="w-full h-1 rounded accent-amber-500 cursor-pointer" />
                <div className="flex justify-between text-[9px]" style={{ color: "var(--text-secondary)" }}>
                  <span>20（快速）</span><span>30（建議）</span><span>40（精細）</span>
                </div>
              </div>

              {/* CFG */}
              <div className="flex flex-col gap-1">
                <div className="flex justify-between text-[10px]" style={{ color: "var(--text-secondary)" }}>
                  <span>CFG Scale（提示詞相關性）</span>
                  <span className="font-mono font-bold text-amber-400">{illCfg.toFixed(1)}</span>
                </div>
                <input type="range" min="4.0" max="8.0" step="0.5" value={illCfg}
                  onChange={e => { const v = +e.target.value; setIllCfg(v); patchIll({ guidance_scale: v }); }}
                  className="w-full h-1 rounded accent-amber-500 cursor-pointer" />
                <div className="flex justify-between text-[9px]" style={{ color: "var(--text-secondary)" }}>
                  <span>4.0（柔和）</span><span>6.0（建議）</span><span>8.0（強烈）</span>
                </div>
              </div>

              {/* Hires Fix */}
              <div className="flex flex-col gap-1.5">
                <div className="flex items-center justify-between">
                  <div className="flex flex-col">
                    <span className="text-[10px] font-semibold" style={{ color: "var(--text-primary)" }}>Hires Fix 高解析度精修</span>
                    <span className="text-[9px]" style={{ color: "var(--text-secondary)" }}>
                      生圖後上採樣 {Math.round(1024 * 1.5)}px × img2img 補細節（臉、手）
                    </span>
                  </div>
                  <button
                    onClick={() => { setHiresEnabled(v => { patchIll({ hires_fix_enabled: !v }); return !v; }); }}
                    className={`relative w-9 h-5 rounded-full transition-colors ${hiresEnabled ? "bg-amber-500" : "bg-white/20"}`}
                  >
                    <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${hiresEnabled ? "translate-x-4" : ""}`} />
                  </button>
                </div>

                {hiresEnabled && (
                  <div className="flex flex-col gap-1">
                    <div className="flex justify-between text-[10px]" style={{ color: "var(--text-secondary)" }}>
                      <span>重繪強度（Denoise）</span>
                      <span className="font-mono font-bold text-amber-400">{hiresDenoise.toFixed(2)}</span>
                    </div>
                    <input type="range" min="0.25" max="0.5" step="0.05" value={hiresDenoise}
                      onChange={e => { const v = +e.target.value; setHiresDenoise(v); patchIll({ hires_denoise: v }); }}
                      className="w-full h-1 rounded accent-amber-500 cursor-pointer" />
                    <div className="flex justify-between text-[9px]" style={{ color: "var(--text-secondary)" }}>
                      <span>0.25（保留原構圖）</span><span>0.5（較大重繪）</span>
                    </div>
                  </div>
                )}
              </div>

              {/* ADetailer */}
              <div className="flex flex-col gap-1.5">
                <div className="flex items-center justify-between">
                  <div className="flex flex-col">
                    <span className="text-[10px] font-semibold" style={{ color: "var(--text-primary)" }}>ADetailer 臉部精修</span>
                    <span className="text-[9px]" style={{ color: "var(--text-secondary)" }}>
                      InsightFace 偵測臉部 → 局部 img2img 重繪 → 羽化貼回
                    </span>
                  </div>
                  <button
                    onClick={() => { setAdetailerEnabled(v => { patchIll({ adetailer_enabled: !v }); return !v; }); }}
                    className={`relative w-9 h-5 rounded-full transition-colors ${adetailerEnabled ? "bg-amber-500" : "bg-white/20"}`}
                  >
                    <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${adetailerEnabled ? "translate-x-4" : ""}`} />
                  </button>
                </div>

                {adetailerEnabled && (
                  <div className="flex flex-col gap-1">
                    <div className="flex justify-between text-[10px]" style={{ color: "var(--text-secondary)" }}>
                      <span>重繪強度（Denoise）</span>
                      <span className="font-mono font-bold text-amber-400">{adetailerDenoise.toFixed(2)}</span>
                    </div>
                    <input type="range" min="0.25" max="0.55" step="0.05" value={adetailerDenoise}
                      onChange={e => { const v = +e.target.value; setAdetailerDenoise(v); patchIll({ adetailer_denoise: v }); }}
                      className="w-full h-1 rounded accent-amber-500 cursor-pointer" />
                    <div className="flex justify-between text-[9px]" style={{ color: "var(--text-secondary)" }}>
                      <span>0.25（微調）</span><span>0.4（建議）</span><span>0.55（大重繪）</span>
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* LoRA 模組 */}
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-semibold" style={{ color: "var(--text-secondary)" }}>LoRA 模組</span>
                <span className="text-[9px]" style={{ color: "var(--text-secondary)" }}>變更後需重新載入模型</span>
              </div>
              {availableLoras.length === 0 ? (
                <div className="text-[10px] px-2.5 py-2 rounded border" style={{ borderColor: "var(--border)", color: "var(--text-secondary)", backgroundColor: "var(--bg-hover)" }}>
                  找不到 LoRA（請將 .safetensors 放入 models/loras/）
                </div>
              ) : (
                <div className="flex flex-col gap-1.5">
                  {availableLoras.map(lora => {
                    const state = getLoraState(lora.filename);
                    const shortName = lora.filename.replace(/\.(safetensors|bin|pt)$/, "").slice(0, 32);
                    return (
                      <div key={lora.filename} className="flex flex-col gap-1 px-2.5 py-2 rounded border"
                        style={{ borderColor: state.enabled ? "var(--border-accent, #f59e0b66)" : "var(--border)", backgroundColor: "var(--bg-hover)" }}>
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => toggleLora(lora.filename)}
                            className={`relative w-8 h-4 rounded-full transition-colors shrink-0 ${state.enabled ? "bg-amber-500" : "bg-white/20"}`}
                          >
                            <span className={`absolute top-0.5 left-0.5 w-3 h-3 bg-white rounded-full shadow transition-transform ${state.enabled ? "translate-x-4" : ""}`} />
                          </button>
                          <span className="flex-1 text-[10px] truncate" title={lora.filename} style={{ color: state.enabled ? "var(--text-primary)" : "var(--text-secondary)" }}>
                            {shortName}
                          </span>
                          <span className="text-[9px] shrink-0" style={{ color: "var(--text-secondary)" }}>{lora.size_mb}MB</span>
                        </div>
                        {state.enabled && (
                          <div className="flex items-center gap-2 mt-0.5">
                            <span className="text-[9px] shrink-0" style={{ color: "var(--text-secondary)" }}>強度</span>
                            <input type="range" min="0.1" max="1.5" step="0.05" value={state.weight}
                              onChange={e => setLoraWeight(lora.filename, +e.target.value)}
                              className="flex-1 h-1 rounded accent-amber-500 cursor-pointer" />
                            <span className="text-[9px] font-mono w-7 text-right text-amber-400">{state.weight.toFixed(2)}</span>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* 反向提示詞 */}
            <div className="flex flex-col gap-1.5">
              <span className="text-[11px] font-semibold" style={{ color: "var(--text-secondary)" }}>反向提示詞（不希望出現的元素）</span>
              <textarea
                value={negativePrompt}
                onChange={(e) => handleNegativePromptChange(e.target.value)}
                placeholder="輸入不希望出現的元素，例如：extra limbs, blurry, watermark"
                rows={3}
                className="w-full px-2.5 py-2 rounded border text-[10px] outline-none resize-none"
                style={{ backgroundColor: "var(--bg-surface)", borderColor: "var(--border)", color: "var(--text-primary)" }}
              />
              <span className="text-[9px] leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                修改後自動儲存（0.8 秒延遲），重啟後保留
              </span>
            </div>
          </section>

          <hr style={{ borderColor: "var(--border)" }} />

          {/* 硬體資訊 */}
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
