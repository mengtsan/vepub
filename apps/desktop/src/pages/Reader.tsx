import { useEffect, useState, useRef, useCallback } from "react";
import { useNavigate } from "@tanstack/react-router";
import { useLibraryStore } from "@/stores/library";
import { usePlayerStore, Sentence } from "@/stores/player";
import { useReaderStore } from "@/stores/reader";
import {
  getBookChapters,
  getChapterParagraphs,
  getSentences,
  getProgress,
  saveProgress,
  Book,
} from "@/lib/api";
import { useAudioStream } from "@/hooks/useAudioStream";
import { useHighlight } from "@/hooks/useHighlight";

import PlayerBar from "@/components/reader/PlayerBar";
import TableOfContents from "@/components/reader/TableOfContents";
import SettingsPanel from "@/components/reader/SettingsPanel";
import { ChevronLeft, Menu, Sliders, Loader2 } from "lucide-react";

export default function Reader() {
  const navigate = useNavigate();
  const currentBook = useLibraryStore((state) => state.currentBook);

  // 若目前無選中書籍，返回首頁
  useEffect(() => {
    if (!currentBook) {
      navigate({ to: "/" });
    }
  }, [currentBook, navigate]);

  // Player Store
  const {
    sentences,
    currentSentenceIndex,
    pause,
    loadSentences,
    _setCurrentIndex,
  } = usePlayerStore();

  // Reader Store
  const {
    fontSize,
    fontFamily,
    lineHeight,
    chapters,
    currentChapterIndex,
    setCurrentChapterIndex,
    setChapters,
    fetchHardwareInfo,
  } = useReaderStore();

  // 本地 UI 狀態
  const [loading, setLoading] = useState(true);
  const [isTocOpen, setIsTocOpen] = useState(false);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const isFirstLoadRef = useRef(true);

  // 1. 初始化讀取書籍章節列表與進度
  useEffect(() => {
    const book = currentBook;
    if (!book) return;

    async function initReader(b: Book) {
      try {
        setLoading(true);
        // 載入章節目錄
        const chs = await getBookChapters(b.id);
        setChapters(chs);

        // 載入當前書籍的進度
        const progress = await getProgress(b.id);
        setCurrentChapterIndex(progress.chapter_index || 0);

        isFirstLoadRef.current = true;
      } catch (e) {
        console.error("初始化閱讀器失敗:", e);
      } finally {
        setLoading(false);
      }
    }

    initReader(book);
    fetchHardwareInfo(); // 獲取當前硬體資訊
  }, [currentBook, setChapters, setCurrentChapterIndex, fetchHardwareInfo]);

  // 2. 當當前章節 Index 改變時，載入章節的段落與句子
  useEffect(() => {
    const book = currentBook;
    if (!book || chapters.length === 0) return;
    const currentChapter = chapters[currentChapterIndex];
    if (!currentChapter) return;

    // 開始載入新章節內容前，先暫停播放以中斷舊連線與音訊排程，防止換章節時連線殘留與語音錯亂
    pause();

    async function loadChapterContent(b: Book) {
      try {
        setLoading(true);
        // 獲取段落內容
        const paragraphs = await getChapterParagraphs(b.id, currentChapter.id);
        // 切割段落為句子
        const apiSentences = await getSentences(
          b.id,
          currentChapter.id,
          paragraphs,
          b.language || "zh"
        );

        const formatted = apiSentences.map((s) => ({
          index: s.index,
          paragraphIndex: s.paragraph_index,
          text: s.text,
          charStart: s.char_start,
          charEnd: s.char_end,
        }));

        loadSentences(formatted);

        // 判斷是否為首次載入以恢復細粒度句子進度
        if (isFirstLoadRef.current) {
          const progress = await getProgress(b.id);
          const idx = Math.min(progress.sentence_index || 0, formatted.length - 1);
          _setCurrentIndex(idx);
          isFirstLoadRef.current = false;
        } else {
          _setCurrentIndex(0);
        }
      } catch (e) {
        console.error("載入章節內容失敗:", e);
      } finally {
        setLoading(false);
      }
    }

    loadChapterContent(book);
  }, [currentBook, currentChapterIndex, chapters, loadSentences, _setCurrentIndex]);

  // 3. 當前句子與章節變化時，儲存進度至 SQLite 資料庫
  useEffect(() => {
    const book = currentBook;
    if (!book) return;
    if (sentences.length === 0) return;

    const save = async () => {
      try {
        await saveProgress(book.id, {
          chapter_index: currentChapterIndex,
          sentence_index: currentSentenceIndex,
          scroll_position: 0.0,
        });
      } catch (e) {
        console.error("儲存進度失敗:", e);
      }
    };

    const timer = setTimeout(save, 500);
    return () => clearTimeout(timer);
  }, [currentBook, currentChapterIndex, currentSentenceIndex, sentences]);

  // 4. 章節朗讀完畢自動跳轉
  const handleChapterEnded = useCallback(() => {
    if (currentChapterIndex < chapters.length - 1) {
      setCurrentChapterIndex(currentChapterIndex + 1);
    } else {
      pause();
      alert("全書朗讀完畢。");
    }
  }, [currentChapterIndex, chapters, setCurrentChapterIndex, pause]);

  // 啟動朗讀串流與高亮 Hook
  const { resumeAudio, changeVolume } = useAudioStream(handleChapterEnded);
  useHighlight();

  // 手動上一章、下一章按鈕事件
  const handleSkipNextChapter = () => {
    if (currentChapterIndex < chapters.length - 1) {
      setCurrentChapterIndex(currentChapterIndex + 1);
    } else {
      alert("已經是最後一章了");
    }
  };

  const handleSkipPrevChapter = () => {
    if (currentChapterIndex > 0) {
      setCurrentChapterIndex(currentChapterIndex - 1);
    } else {
      alert("已經是第一章了");
    }
  };

  if (!currentBook) return null;

  const currentChapter = chapters[currentChapterIndex];

  // 將句子依照段落 index 進行分組以渲染
  const paragraphsMap: Record<number, Sentence[]> = {};
  sentences.forEach((s) => {
    if (!paragraphsMap[s.paragraphIndex]) {
      paragraphsMap[s.paragraphIndex] = [];
    }
    paragraphsMap[s.paragraphIndex].push(s);
  });

  return (
    <div className="min-h-screen flex flex-col transition-colors duration-300 pb-32" style={{ backgroundColor: "var(--bg-primary)" }}>
      {/* 頂部導覽列 (毛玻璃效果) */}
      <header
        className="sticky top-0 z-30 flex items-center justify-between px-6 py-3 border-b backdrop-blur-md"
        style={{
          backgroundColor: "var(--bg-surface)",
          borderColor: "var(--border)",
          color: "var(--text-primary)",
        }}
      >
        <div className="flex items-center gap-3">
          <button
            onClick={() => {
              pause();
              navigate({ to: "/" });
            }}
            className="p-1.5 rounded-full hover:bg-white/10 active:scale-95 transition-all"
            title="返回書庫"
          >
            <ChevronLeft size={20} />
          </button>
          <div className="flex flex-col">
            <h1 className="text-sm font-bold truncate max-w-[200px] sm:max-w-[400px]">
              {currentBook?.title}
            </h1>
            {currentBook?.author && (
              <span className="text-[10px]" style={{ color: "var(--text-secondary)" }}>
                {currentBook?.author}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* 目錄按鈕 */}
          <button
            onClick={() => setIsTocOpen(true)}
            className="p-2 rounded-full hover:bg-white/10 active:scale-95 transition-all flex items-center gap-1.5 text-xs"
            title="開啟目錄"
          >
            <Menu size={18} />
            <span className="hidden sm:inline">目錄</span>
          </button>

          {/* 設定按鈕 */}
          <button
            onClick={() => setIsSettingsOpen(true)}
            className="p-2 rounded-full hover:bg-white/10 active:scale-95 transition-all flex items-center gap-1.5 text-xs"
            title="開啟設定"
          >
            <Sliders size={18} />
            <span className="hidden sm:inline">設定</span>
          </button>
        </div>
      </header>

      {/* 閱讀內文區 */}
      <main className="flex-1 w-full overflow-y-auto px-6">
        {loading ? (
          <div className="flex flex-col items-center justify-center py-40 gap-3">
            <Loader2 className="animate-spin text-amber-500" size={32} />
            <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
              載入內容中，請稍候...
            </span>
          </div>
        ) : (
          <article
            className={`reader-content py-12 flex flex-col gap-6 font-${fontFamily}`}
            style={{
              fontSize: `${fontSize}px`,
              lineHeight: lineHeight,
              color: "var(--text-primary)",
            }}
          >
            <h2 className="text-2xl font-bold mb-6 border-b pb-4 leading-relaxed" style={{ borderColor: "var(--border)" }}>
              {currentChapter?.title || "未命名章節"}
            </h2>

            {sentences.length === 0 ? (
              <div className="py-20 text-center" style={{ color: "var(--text-secondary)" }}>
                無內容可供朗讀或解析。
              </div>
            ) : (
              Object.keys(paragraphsMap)
                .sort((a, b) => Number(a) - Number(b))
                .map((pIdx) => {
                  const paragraphSentences = paragraphsMap[Number(pIdx)];
                  return (
                    <p key={pIdx} className="paragraph text-justify select-text">
                      {paragraphSentences.map((s) => {
                        const isCurrent = s.index === currentSentenceIndex;
                        return (
                          <span
                            key={s.index}
                            id={`sentence-${s.index}`}
                            onClick={() => _setCurrentIndex(s.index)}
                            className={`sentence rounded cursor-pointer transition-colors duration-200 ${
                              isCurrent ? "tts-highlight font-medium" : "hover:bg-amber-500/10"
                            }`}
                          >
                            {s.text}
                          </span>
                        );
                      })}
                    </p>
                  );
                })
            )}
          </article>
        )}
      </main>

      {/* 懸浮播放控制列 */}
      <PlayerBar
        onSkipNextChapter={handleSkipNextChapter}
        onSkipPrevChapter={handleSkipPrevChapter}
        chapterTitle={currentChapter?.title || "未命名章節"}
        resumeAudio={resumeAudio}
        changeVolume={changeVolume}
      />

      {/* 左側目錄抽屜 */}
      <TableOfContents
        isOpen={isTocOpen}
        onClose={() => setIsTocOpen(false)}
        onSelectChapter={(idx) => setCurrentChapterIndex(idx)}
      />

      {/* 右側設定抽屜 */}
      <SettingsPanel
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
      />
    </div>
  );
}
