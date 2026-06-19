import { create } from "zustand";
import { getSettings, saveSettings, getHardwareInfo, HardwareInfo, ChapterMeta } from "@/lib/api";

type ThemeType = "dark" | "light" | "paper";
type FontFamilyType = "sans" | "serif";

interface ReaderState {
  theme: ThemeType;
  fontSize: number;
  fontFamily: FontFamilyType;
  lineHeight: number;
  volume: number;
  currentChapterIndex: number;
  chapters: ChapterMeta[];
  hardwareInfo: HardwareInfo | null;

  // 插圖 prompt 與尺寸設定
  illustrationPromptPrefix: string;
  illustrationWidth: number;
  illustrationHeight: number;
  illustrationSeed: number;

  loadSettings: () => Promise<void>;
  setTheme: (theme: ThemeType) => Promise<void>;
  setFontSize: (fontSize: number) => Promise<void>;
  setFontFamily: (fontFamily: FontFamilyType) => Promise<void>;
  setLineHeight: (lineHeight: number) => Promise<void>;
  setVolume: (volume: number) => Promise<void>;
  setCurrentChapterIndex: (index: number) => void;
  setChapters: (chapters: ChapterMeta[]) => void;
  fetchHardwareInfo: () => Promise<void>;

  setIllustrationPromptPrefix: (v: string) => Promise<void>;
  setIllustrationWidth: (v: number) => Promise<void>;
  setIllustrationHeight: (v: number) => Promise<void>;
  setIllustrationSeed: (v: number) => Promise<void>;
}

export const useReaderStore = create<ReaderState>((set) => ({
  theme: "dark",
  fontSize: 18,
  fontFamily: "sans",
  lineHeight: 1.7,
  volume: 80,
  currentChapterIndex: 0,
  chapters: [],
  hardwareInfo: null,

  illustrationPromptPrefix: "",
  illustrationWidth: 1024,
  illustrationHeight: 1024,
  illustrationSeed: -1,

  loadSettings: async () => {
    try {
      const settings = await getSettings();
      set({
        theme: (settings.theme as ThemeType) || "dark",
        fontSize: parseInt(settings.font_size, 10) || 18,
        fontFamily: (settings.font_family as FontFamilyType) || "sans",
        lineHeight: parseFloat(settings.line_height) || 1.7,
        volume: settings.volume ? parseInt(settings.volume, 10) : 80,
        illustrationPromptPrefix: settings.illustration_prompt_prefix ?? "",
        illustrationWidth: settings.illustration_width ? parseInt(settings.illustration_width, 10) : 1024,
        illustrationHeight: settings.illustration_height ? parseInt(settings.illustration_height, 10) : 1024,
        illustrationSeed: settings.illustration_seed ? parseInt(settings.illustration_seed, 10) : -1,
      });

      // 同時套用主題到 body tag 上，便於全域 CSS 修改
      document.body.className = `theme-${(settings.theme as ThemeType) || "dark"}`;
    } catch (e) {
      console.error("載入使用者設定失敗:", e);
    }
  },

  setTheme: async (theme) => {
    set({ theme });
    document.body.className = `theme-${theme}`;
    try {
      await saveSettings({ theme });
    } catch (e) {
      console.error("儲存主題設定失敗:", e);
    }
  },

  setFontSize: async (fontSize) => {
    set({ fontSize });
    try {
      await saveSettings({ font_size: fontSize.toString() });
    } catch (e) {
      console.error("儲存字型大小設定失敗:", e);
    }
  },

  setFontFamily: async (fontFamily) => {
    set({ fontFamily });
    try {
      await saveSettings({ font_family: fontFamily });
    } catch (e) {
      console.error("儲存字型設定失敗:", e);
    }
  },

  setLineHeight: async (lineHeight) => {
    set({ lineHeight });
    try {
      await saveSettings({ line_height: lineHeight.toString() });
    } catch (e) {
      console.error("儲存行高設定失敗:", e);
    }
  },

  setVolume: async (volume) => {
    set({ volume });
    try {
      await saveSettings({ volume: volume.toString() });
    } catch (e) {
      console.error("儲存音量設定失敗:", e);
    }
  },

  setCurrentChapterIndex: (currentChapterIndex) => set({ currentChapterIndex }),
  setChapters: (chapters) => set({ chapters }),

  fetchHardwareInfo: async () => {
    try {
      const info = await getHardwareInfo();
      set({ hardwareInfo: info });
    } catch (e) {
      console.error("獲取硬體資訊失敗:", e);
    }
  },

  setIllustrationPromptPrefix: async (illustrationPromptPrefix) => {
    set({ illustrationPromptPrefix });
    try {
      await saveSettings({ illustration_prompt_prefix: illustrationPromptPrefix });
    } catch (e) {
      console.error("儲存繪圖提示詞前綴失敗:", e);
    }
  },

  setIllustrationWidth: async (illustrationWidth) => {
    set({ illustrationWidth });
    try {
      await saveSettings({ illustration_width: illustrationWidth.toString() });
    } catch (e) {
      console.error("儲存繪圖寬度失敗:", e);
    }
  },

  setIllustrationHeight: async (illustrationHeight) => {
    set({ illustrationHeight });
    try {
      await saveSettings({ illustration_height: illustrationHeight.toString() });
    } catch (e) {
      console.error("儲存繪圖高度失敗:", e);
    }
  },

  setIllustrationSeed: async (illustrationSeed) => {
    set({ illustrationSeed });
    try {
      await saveSettings({ illustration_seed: illustrationSeed.toString() });
    } catch (e) {
      console.error("儲存繪圖 seed 失敗:", e);
    }
  },
}));
