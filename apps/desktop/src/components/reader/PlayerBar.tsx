import { useState, useEffect, useRef } from "react";
import { usePlayerStore } from "@/stores/player";
import {
  Play,
  Pause,
  SkipForward,
  SkipBack,
  ChevronRight,
  ChevronLeft,
  Volume2,
  Loader2,
} from "lucide-react";
import HardwareBadge from "./HardwareBadge";

interface PlayerBarProps {
  onSkipNextChapter: () => void;
  onSkipPrevChapter: () => void;
  chapterTitle: string;
  resumeAudio: () => void;
  changeVolume: (volume: number) => void;
}

export default function PlayerBar({
  onSkipNextChapter,
  onSkipPrevChapter,
  chapterTitle,
  resumeAudio,
  changeVolume,
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
  const [volume, setVolume] = useState(80); // 音量控制 (0 ~ 100)

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

  // 滑鼠靜止與移出自動淡出邏輯
  const resetFadeTimer = () => {
    setOpacity(1);
    if (hoverTimeoutRef.current) {
      clearTimeout(hoverTimeoutRef.current);
    }
    // 只有在朗讀播放時才進行淡出，暫停時維持清晰
    if (isPlaying) {
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
  }, [isPlaying]);

  return (
    <div
      onMouseMove={resetFadeTimer}
      onMouseEnter={() => {
        setOpacity(1);
        if (hoverTimeoutRef.current) clearTimeout(hoverTimeoutRef.current);
      }}
      onMouseLeave={() => {
        if (isPlaying) {
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
            setVolume(val);
            changeVolume(val);
          }}
          className="w-16 h-0.5 rounded bg-white/20 accent-amber-500 outline-none cursor-pointer"
          title={`音量: ${volume}%`}
        />
      </div>

      {/* 4. 當前章節標題 */}
      <div className="hidden lg:block max-w-[120px] truncate text-[10px] pr-2 border-r" style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }} title={chapterTitle}>
        {chapterTitle}
      </div>

      {/* 5. 硬體指示徽章 */}
      <div className="pl-1">
        <HardwareBadge />
      </div>
    </div>
  );
}
