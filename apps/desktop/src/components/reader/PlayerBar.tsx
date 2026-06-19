import { useState, useEffect, useRef } from "react";
import { usePlayerStore } from "@/stores/player";
import { useReaderStore } from "@/stores/reader";
import {
  Play,
  Pause,
  SkipForward,
  SkipBack,
  ChevronRight,
  ChevronLeft,
  Volume2,
  Loader2,
  Bookmark,
  ImagePlus,
} from "lucide-react";
import HardwareBadge from "./HardwareBadge";
import type { IllustrationTask } from "@/lib/api";

interface PlayerBarProps {
  onSkipNextChapter: () => void;
  onSkipPrevChapter: () => void;
  chapterTitle: string;
  resumeAudio: () => void;
  changeVolume: (volume: number) => void;
  onBookmark?: () => void;
  illustrationTasks?: IllustrationTask[];
}

export default function PlayerBar({
  onSkipNextChapter,
  onSkipPrevChapter,
  chapterTitle,
  resumeAudio,
  changeVolume,
  onBookmark,
  illustrationTasks = [],
}: PlayerBarProps) {
  const {
    isPlaying,
    isLoading,
    currentSentenceIndex,
    sentences,
    speed,
    play,
    pause,
    skipNext,
    skipPrev,
    setSpeed,
  } = usePlayerStore();

  const [opacity, setOpacity] = useState(1);
  const hoverTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const { volume, setVolume } = useReaderStore();

  // 當元件載入或 changeVolume 改變時，初始化實體音量
  useEffect(() => {
    changeVolume(volume);
  }, [changeVolume]);


  // 播放速度循環列表
  const speedList = [0.75, 1.0, 1.25, 1.5, 2.0];

  const handleSpeedCycle = () => {
    const currentIndex = speedList.indexOf(speed);
    const nextIndex = (currentIndex + 1) % speedList.length;
    setSpeed(speedList[nextIndex]);
  };

  // 生圖進度摘要：semaphore=1，同時只有一個 running，其餘 pending
  const hasActiveIllustration = illustrationTasks.length > 0;
  const runningTask = illustrationTasks.find((t) => t.status === "running") ?? illustrationTasks[0];

  // 滑鼠靜止與移出自動淡出邏輯
  const resetFadeTimer = () => {
    setOpacity(1);
    if (hoverTimeoutRef.current) {
      clearTimeout(hoverTimeoutRef.current);
    }
    // 只有在朗讀播放且無生圖任務進行時才淡出，暫停或生圖中維持清晰
    if (isPlaying && !hasActiveIllustration) {
      hoverTimeoutRef.current = setTimeout(() => {
        setOpacity(0.15); // 淡出為超低不透明度
      }, 3000);
    }
  };

  useEffect(() => {
    resetFadeTimer();
    return () => {
      if (hoverTimeoutRef.current) clearTimeout(hoverTimeoutRef.current);
    };
  }, [isPlaying, hasActiveIllustration]);

  return (
    <div
      onMouseMove={resetFadeTimer}
      onMouseEnter={() => {
        setOpacity(1);
        if (hoverTimeoutRef.current) clearTimeout(hoverTimeoutRef.current);
      }}
      onMouseLeave={() => {
        if (isPlaying && !hasActiveIllustration) {
          hoverTimeoutRef.current = setTimeout(() => {
            setOpacity(0.15);
          }, 1500); // 移出時稍微加速淡出
        }
      }}
      className="player-bar shadow-2xl z-40 transition-all duration-500 hover:scale-[1.01]"
      style={{
        opacity: opacity,
        transform: `translateX(-50%)`,
      }}
    >
      {/* 1. 章節切換與單句切換按鈕組 */}
      <div className="flex items-center gap-1 border-r pr-4" style={{ borderColor: "var(--border)" }}>
        {/* 跳上章 */}
        <button
          onClick={onSkipPrevChapter}
          className="p-1.5 rounded-full hover:bg-white/10 active:scale-90 transition-all"
          title="上一章"
          style={{ color: "var(--text-secondary)" }}
        >
          <ChevronLeft size={18} />
        </button>

        {/* 退後一句 */}
        <button
          onClick={skipPrev}
          disabled={currentSentenceIndex === 0}
          className="p-1.5 rounded-full hover:bg-white/10 active:scale-90 transition-all disabled:opacity-30 disabled:pointer-events-none"
          title="後退一句"
          style={{ color: "var(--text-secondary)" }}
        >
          <SkipBack size={16} />
        </button>

        {/* 播放 / 暫停 (大按鈕) */}
        <button
          onClick={async () => {
            if (isPlaying) {
              pause();
            } else {
              // 在使用者點擊的同步 callstack 中立刻解凍 AudioContext，繞過 Autoplay 阻攔
              resumeAudio();
              play();
            }
          }}
          disabled={isLoading}
          className="p-2.5 rounded-full bg-amber-500 text-black hover:bg-amber-400 active:scale-90 transition-all mx-1 shadow-lg disabled:opacity-50 disabled:pointer-events-none flex items-center justify-center min-w-[40px] min-h-[40px]"
          title={isLoading ? "模型推理/音訊合成中..." : isPlaying ? "暫停" : "播放"}
        >
          {isLoading ? (
            <Loader2 size={20} className="animate-spin text-black" />
          ) : isPlaying ? (
            <Pause size={20} fill="#000" />
          ) : (
            <Play size={20} fill="#000" />
          )}
        </button>

        {/* 前進一句 */}
        <button
          onClick={skipNext}
          disabled={currentSentenceIndex === sentences.length - 1}
          className="p-1.5 rounded-full hover:bg-white/10 active:scale-90 transition-all disabled:opacity-30 disabled:pointer-events-none"
          title="前進一句"
          style={{ color: "var(--text-secondary)" }}
        >
          <SkipForward size={16} />
        </button>

        {/* 跳下章 */}
        <button
          onClick={onSkipNextChapter}
          className="p-1.5 rounded-full hover:bg-white/10 active:scale-90 transition-all"
          title="下一章"
          style={{ color: "var(--text-secondary)" }}
        >
          <ChevronRight size={18} />
        </button>
      </div>

      {/* 2. 播放速度顯示與點擊切換 */}
      <button
        onClick={handleSpeedCycle}
        className="px-2.5 py-1 rounded text-xs font-semibold hover:bg-white/10 active:scale-95 transition-all font-mono"
        style={{ color: "var(--text-primary)" }}
        title="點選切換朗讀語速"
      >
        {speed.toFixed(2)}×
      </button>

      {/* 3. 精美音量調節 Slider */}
      <div className="flex items-center gap-2 border-r pr-4" style={{ borderColor: "var(--border)" }}>
        <Volume2 size={15} style={{ color: "var(--text-secondary)" }} />
        <input
          type="range"
          min="0"
          max="100"
          value={volume}
          onChange={(e) => {
            const val = parseInt(e.target.value);
            changeVolume(val);
            setVolume(val);
          }}
          className="w-16 h-0.5 rounded bg-white/20 accent-amber-500 outline-none cursor-pointer"
          title={`音量: ${volume}%`}
        />
      </div>

      {/* 4. 當前章節標題 */}
      <div className="hidden lg:block max-w-[120px] truncate text-[10px] pr-2 border-r" style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }} title={chapterTitle}>
        {chapterTitle}
      </div>

      {/* 5. 書籤按鈕 */}
      {onBookmark && (
        <button
          onClick={onBookmark}
          className="p-1.5 rounded-full hover:bg-white/10 active:scale-90 transition-all"
          title="加入書籤（目前位置）"
          style={{ color: "var(--text-secondary)" }}
        >
          <Bookmark size={15} />
        </button>
      )}

      {/* 6. 生圖進度（有任務時顯示，含排隊數量與當前進度） */}
      {hasActiveIllustration && runningTask && (
        <div className="flex items-center gap-2 border-l pl-3" style={{ borderColor: "var(--border)" }} title={runningTask.label}>
          <div className="relative flex items-center">
            <ImagePlus size={15} className="text-amber-500" />
            <span className="absolute -top-2 -right-2 px-1 rounded-full text-[9px] font-bold bg-amber-500 text-black leading-none min-w-[14px] text-center">
              {illustrationTasks.length}
            </span>
          </div>
          <div className="hidden md:flex flex-col gap-0.5 w-28">
            <div className="flex items-center justify-between text-[9px] leading-none" style={{ color: "var(--text-secondary)" }}>
              <span className="truncate pr-1">{runningTask.label}</span>
              <span>{runningTask.progress}%</span>
            </div>
            <div className="h-1 rounded-full overflow-hidden" style={{ backgroundColor: "var(--border)" }}>
              <div
                className="h-full rounded-full bg-amber-500 transition-all duration-300"
                style={{ width: `${runningTask.progress}%` }}
              />
            </div>
          </div>
        </div>
      )}

      {/* 7. 硬體指示徽章 */}
      <div className="pl-1">
        <HardwareBadge />
      </div>
    </div>
  );
}
