import { create } from "zustand";

export interface Sentence {
  index: number;
  paragraphIndex: number;
  text: string;
  charStart: number;
  charEnd: number;
  cfi?: string; // 保存當前句子在 epub 內部的 CFI 定位
  speaker?: string | null;      // 角色配音：歸屬到的角色名
  voiceInstruct?: string | null; // 該角色的聲線 instruct
}

// 語音合成模式
export type TTSMode = "clone" | "design" | "auto";

interface PlayerState {
  // 狀態
  isPlaying: boolean;
  isLoading: boolean;
  currentSentenceIndex: number;
  sentences: Sentence[];
  speed: number;           // 播放速度：0.5 ~ 2.0
  voice: string;           // 聲音名稱（保留相容性）

  // OmniVoice 語音設定
  ttsMode: TTSMode;        // 推理模式：clone / design / auto
  refAudioPath: string;    // Voice Cloning：參考音訊路徑
  refText: string;         // Voice Cloning：參考音訊逐字稿（選填）
  instruct: string;        // Voice Design：聲音屬性描述
  numStep: number;         // 擴散步數（16 或 32）
  duration: number | null; // 固定輸出時長（秒），null 表示不限制
  language: string | null; // 朗讀語系（OmniVoice ID，如 'zh'）；null = 後端自動偵測

  // WebSocket 連線實例
  ws: WebSocket | null;

  // 動作與狀態修改器
  play: () => void;
  pause: () => void;
  skipNext: () => void;
  skipPrev: () => void;
  setSpeed: (speed: number) => void;
  setVoice: (voice: string) => void;
  loadSentences: (sentences: Sentence[]) => void;
  setWs: (ws: WebSocket | null) => void;
  setIsLoading: (isLoading: boolean) => void;
  _setCurrentIndex: (index: number) => void;

  // 語音設定 setters
  setTTSMode: (mode: TTSMode) => void;
  setRefAudioPath: (path: string) => void;
  setRefText: (text: string) => void;
  setInstruct: (instruct: string) => void;
  setNumStep: (numStep: number) => void;
  setDuration: (duration: number | null) => void;
  setLanguage: (language: string | null) => void;
}

export const usePlayerStore = create<PlayerState>((set, get) => ({
  isPlaying: false,
  isLoading: false,
  currentSentenceIndex: 0,
  sentences: [],
  speed: 1.0,
  voice: "default",
  ws: null,

  // 語音設定初始值
  ttsMode: "auto",
  refAudioPath: "",
  refText: "",
  instruct: "",
  numStep: 16,
  duration: null,
  language: null,

  play: () => set({ isPlaying: true }),
  pause: () => {
    const { ws } = get();
    if (ws) {
      try {
        ws.close();
      } catch (e) {
        console.warn("關閉 WebSocket 時發生異常:", e);
      }
    }
    set({ isPlaying: false, ws: null });
  },
  skipNext: () => {
    const { currentSentenceIndex, sentences } = get();
    const next = Math.min(currentSentenceIndex + 1, sentences.length - 1);
    set({ currentSentenceIndex: next });
  },
  skipPrev: () => {
    const { currentSentenceIndex } = get();
    set({ currentSentenceIndex: Math.max(currentSentenceIndex - 1, 0) });
  },
  setSpeed: (speed) => set({ speed }),
  setVoice: (voice) => set({ voice }),
  loadSentences: (sentences) => set({ sentences, currentSentenceIndex: 0 }),
  setWs: (ws) => set({ ws }),
  setIsLoading: (isLoading) => set({ isLoading }),
  _setCurrentIndex: (index) => set({ currentSentenceIndex: index }),

  // 語音設定 setters
  setTTSMode: (ttsMode) => set({ ttsMode }),
  setRefAudioPath: (refAudioPath) => set({ refAudioPath }),
  setRefText: (refText) => set({ refText }),
  setInstruct: (instruct) => set({ instruct }),
  setNumStep: (numStep) => set({ numStep }),
  setDuration: (duration) => set({ duration }),
  setLanguage: (language) => set({ language }),
}));
