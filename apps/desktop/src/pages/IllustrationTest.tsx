import { useEffect, useRef, useState } from "react";
import { useRouter } from "@tanstack/react-router";
import { ArrowLeft, Shuffle, Zap, RefreshCw } from "lucide-react";
import {
  generateIllustration,
  getIllustrationProgress,
  IllustrationTask,
  TimingEntry,
} from "@/lib/api";

const STYLE_PRESETS = [
  { label: "動漫",     value: "anime style, vibrant colors, clean lineart, highly detailed" },
  { label: "插畫厚塗", value: "digital painting, painterly, soft cinematic lighting, concept art" },
  { label: "水彩",     value: "watercolor painting, soft washes, delicate, artistic" },
  { label: "真實",     value: "photorealistic, cinematic, 8k, sharp focus, professional photography" },
];

export default function IllustrationTest() {
  const router = useRouter();

  // ── 輸入狀態 ───────────────────────────────────────────────
  const [text, setText] = useState("");
  const [promptPrefix, setPromptPrefix] = useState("");
  const [width, setWidth] = useState(1024);
  const [height, setHeight] = useState(1024);
  const [seed, setSeed] = useState(-1);

  // ── 任務狀態 ───────────────────────────────────────────────
  const [taskId, setTaskId] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [progressLabel, setProgressLabel] = useState("");
  const [status, setStatus] = useState<"idle" | "pending" | "running" | "done" | "error">("idle");
  const [resultImage, setResultImage] = useState<string | null>(null);
  const [resultPrompt, setResultPrompt] = useState<string | null>(null);
  const [resultIsAnime, setResultIsAnime] = useState<boolean | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [timings, setTimings] = useState<TimingEntry[]>([]);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── 輪詢進度 ──────────────────────────────────────────────
  useEffect(() => {
    if (!taskId || status === "done" || status === "error") return;

    pollRef.current = setInterval(async () => {
      const tasks: IllustrationTask[] = await getIllustrationProgress();
      const t = tasks.find((x) => x.task_id === taskId);
      if (!t) return;

      setProgress(t.progress);
      setProgressLabel(t.label);
      setStatus(t.status as typeof status);
      if (t.timings?.length) setTimings(t.timings);

      if (t.status === "done" && t.result) {
        setResultImage(t.result.image_base64);
        setResultPrompt(t.result.prompt);
        setResultIsAnime(t.result.is_anime);
        clearInterval(pollRef.current!);
      } else if (t.status === "error") {
        setErrorMsg(t.error ?? "未知錯誤");
        clearInterval(pollRef.current!);
      }
    }, 800);

    return () => clearInterval(pollRef.current!);
  }, [taskId, status]);

  // ── 送出生圖 ──────────────────────────────────────────────
  async function handleGenerate() {
    if (!text.trim()) return;
    setStatus("pending");
    setProgress(0);
    setProgressLabel("排隊中");
    setResultImage(null);
    setResultPrompt(null);
    setResultIsAnime(null);
    setErrorMsg(null);
    setTimings([]);

    try {
      const { task_id } = await generateIllustration({
        direct_prompt: text,
        prompt_prefix: promptPrefix || undefined,
        width,
        height,
        seed,
      });
      setTaskId(task_id);
    } catch (e: unknown) {
      setStatus("error");
      setErrorMsg(e instanceof Error ? e.message : String(e));
    }
  }

  const isRunning = status === "pending" || status === "running";

  return (
    <div className="min-h-screen p-6 flex flex-col gap-6" style={{ backgroundColor: "var(--bg-primary)", color: "var(--text-primary)" }}>

      {/* Header */}
      <header className="flex items-center gap-3 border-b pb-4" style={{ borderColor: "var(--border)" }}>
        <button
          onClick={() => router.history.back()}
          className="p-1.5 rounded hover:bg-white/10 transition-colors"
        >
          <ArrowLeft size={18} />
        </button>
        <h1 className="text-lg font-bold">插圖生成測試台</h1>
      </header>

      <div className="flex gap-6 flex-1">

        {/* ── 左欄：輸入控制 ── */}
        <div className="flex flex-col gap-4 w-[420px] shrink-0">

          {/* 繪圖提示詞 */}
          <section>
            <label className="block text-xs font-semibold mb-1.5 opacity-70">繪圖提示詞（Prompt）</label>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={7}
              placeholder="輸入英文繪圖提示詞，直接送入模型..."
              className="w-full px-3 py-2 rounded border text-sm resize-none outline-none focus:border-amber-400"
              style={{ backgroundColor: "var(--bg-secondary)", borderColor: "var(--border)" }}
            />
          </section>

          {/* 畫風 */}
          <section>
            <label className="block text-xs font-semibold mb-1.5 opacity-70">畫風</label>
            <div className="flex flex-wrap gap-1.5 mb-2">
              {STYLE_PRESETS.map((p) => {
                const active = promptPrefix.trim() === p.value;
                return (
                  <button
                    key={p.value}
                    onClick={() => setPromptPrefix(active ? "" : p.value)}
                    className="px-2.5 py-1 rounded text-xs border transition-colors"
                    style={{
                      backgroundColor: active ? "var(--accent, #f59e0b)" : "var(--bg-secondary)",
                      borderColor: active ? "transparent" : "var(--border)",
                      color: active ? "#fff" : "inherit",
                    }}
                  >
                    {p.label}
                  </button>
                );
              })}
            </div>
            <input
              value={promptPrefix}
              onChange={(e) => setPromptPrefix(e.target.value)}
              placeholder="自訂畫風（英文 keywords）"
              className="w-full px-2.5 py-1.5 rounded border text-xs outline-none"
              style={{ backgroundColor: "var(--bg-secondary)", borderColor: "var(--border)" }}
            />
          </section>

          {/* 尺寸 + Seed */}
          <section className="grid grid-cols-3 gap-3">
            <div>
              <label className="block text-xs opacity-70 mb-1">寬</label>
              <input
                type="number" step={64} min={256} max={2048}
                value={width}
                onChange={(e) => setWidth(Number(e.target.value))}
                className="w-full px-2 py-1.5 rounded border text-xs outline-none"
                style={{ backgroundColor: "var(--bg-secondary)", borderColor: "var(--border)" }}
              />
            </div>
            <div>
              <label className="block text-xs opacity-70 mb-1">高</label>
              <input
                type="number" step={64} min={256} max={2048}
                value={height}
                onChange={(e) => setHeight(Number(e.target.value))}
                className="w-full px-2 py-1.5 rounded border text-xs outline-none"
                style={{ backgroundColor: "var(--bg-secondary)", borderColor: "var(--border)" }}
              />
            </div>
            <div>
              <label className="block text-xs opacity-70 mb-1">Seed</label>
              <div className="flex gap-1">
                <input
                  type="number" min={-1}
                  value={seed}
                  onChange={(e) => setSeed(Number(e.target.value))}
                  className="flex-1 min-w-0 px-2 py-1.5 rounded border text-xs outline-none"
                  style={{ backgroundColor: "var(--bg-secondary)", borderColor: "var(--border)" }}
                />
                <button
                  onClick={() => setSeed(Math.floor(Math.random() * 2 ** 31))}
                  className="p-1.5 rounded border hover:bg-white/10 transition-colors"
                  style={{ borderColor: "var(--border)" }}
                  title="隨機 seed"
                >
                  <Shuffle size={12} />
                </button>
              </div>
            </div>
          </section>



          {/* 生成按鈕 */}
          <button
            onClick={handleGenerate}
            disabled={isRunning || !text.trim()}
            className="flex items-center justify-center gap-2 py-2.5 rounded font-semibold text-sm transition-colors disabled:opacity-40"
            style={{ backgroundColor: "var(--accent, #f59e0b)", color: "#fff" }}
          >
            {isRunning ? <RefreshCw size={15} className="animate-spin" /> : <Zap size={15} />}
            {isRunning ? "生成中…" : "生成插圖"}
          </button>

          {/* 進度條 */}
          {(isRunning || status === "done" || status === "error") && (
            <div>
              <div className="flex justify-between text-xs opacity-60 mb-1">
                <span>{progressLabel || (status === "done" ? "完成" : status === "error" ? "錯誤" : "")}</span>
                <span>{progress}%</span>
              </div>
              <div className="w-full rounded-full h-1.5 overflow-hidden" style={{ backgroundColor: "var(--border)" }}>
                <div
                  className="h-full rounded-full transition-all duration-300"
                  style={{
                    width: `${progress}%`,
                    backgroundColor: status === "error" ? "#ef4444" : "var(--accent, #f59e0b)",
                  }}
                />
              </div>
              {errorMsg && (
                <p className="text-xs text-red-400 mt-1.5">{errorMsg}</p>
              )}
            </div>
          )}

          {/* 步驟時間軸 */}
          {timings.length > 0 && (
            <div
              className="rounded-lg border p-3 text-xs font-mono"
              style={{ backgroundColor: "var(--bg-secondary)", borderColor: "var(--border)" }}
            >
              <p className="font-sans font-semibold opacity-60 mb-2 text-[11px] tracking-wide uppercase">
                步驟時間軸
              </p>
              <div className="flex flex-col gap-0.5">
                {timings.map((entry, i) => {
                  const start   = timings[0].ts;
                  const elapsed = entry.ts - start;
                  const delta   = i > 0 ? entry.ts - timings[i - 1].ts : 0;
                  return (
                    <div key={i} className="flex items-center gap-2">
                      <span
                        className="w-7 text-right shrink-0"
                        style={{ color: "var(--accent, #f59e0b)", opacity: 0.9 }}
                      >
                        {entry.pct}%
                      </span>
                      <span className="flex-1 opacity-80 truncate">{entry.label}</span>
                      {i === 0 ? (
                        <span className="opacity-30 shrink-0">← 開始</span>
                      ) : (
                        <>
                          <span className="opacity-50 shrink-0 w-14 text-right">
                            +{elapsed.toFixed(1)}s
                          </span>
                          <span className="opacity-30 shrink-0 w-16 text-right">
                            ({delta.toFixed(1)}s)
                          </span>
                        </>
                      )}
                    </div>
                  );
                })}
              </div>
              {(status === "done" || status === "error") && timings.length >= 2 && (
                <div
                  className="mt-2 pt-2 flex justify-between font-sans"
                  style={{ borderTop: "1px solid var(--border)" }}
                >
                  <span className="opacity-50">總計</span>
                  <span className="font-bold" style={{ color: "var(--accent, #f59e0b)" }}>
                    {(timings[timings.length - 1].ts - timings[0].ts).toFixed(1)}s
                  </span>
                </div>
              )}
            </div>
          )}
        </div>

        {/* ── 右欄：結果 ── */}
        <div className="flex-1 flex flex-col gap-4">
          {resultImage ? (
            <>
              <img
                src={`data:image/png;base64,${resultImage}`}
                alt="generated"
                className="rounded-lg border max-w-full object-contain"
                style={{ maxHeight: "70vh", borderColor: "var(--border)" }}
              />
              {resultPrompt && (
                <div
                  className="rounded-lg border p-3"
                  style={{ backgroundColor: "var(--bg-secondary)", borderColor: "var(--border)" }}
                >
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="text-xs font-semibold opacity-60">實際 Prompt</span>
                    {resultIsAnime !== null && (
                      <span
                        className="text-[10px] px-1.5 py-0.5 rounded font-medium"
                        style={{
                          backgroundColor: resultIsAnime ? "#7c3aed22" : "#06452222",
                          color: resultIsAnime ? "#a78bfa" : "#34d399",
                        }}
                      >
                        {resultIsAnime ? "anime" : "real"}
                      </span>
                    )}
                  </div>
                  <p className="text-xs opacity-80 leading-relaxed">{resultPrompt}</p>
                </div>
              )}
            </>
          ) : (
            <div
              className="flex-1 flex items-center justify-center rounded-lg border"
              style={{
                borderColor: "var(--border)",
                borderStyle: "dashed",
                minHeight: 300,
                backgroundColor: "var(--bg-secondary)",
              }}
            >
              <p className="text-sm opacity-30">
                {isRunning ? "生成中，請稍候…" : "結果會顯示在這裡"}
              </p>
            </div>
          )}
        </div>

      </div>
    </div>
  );
}
