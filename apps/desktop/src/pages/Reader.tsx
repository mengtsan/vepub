import { useEffect, useState, useRef, useCallback, useMemo, memo } from "react";
import { toast } from "sonner";
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
  getModelsStatus,
  createBookmark,
  generateIllustration,
  getChapterIllustrations,
  deleteIllustration,
  getIllustrationStatus,
  getIllustrationProgress,
  extractCharacterFeatures,
  IllustrationTask,
  IllustrationMeta,
  Character,
  Book,
} from "@/lib/api";
import { useAudioStream } from "@/hooks/useAudioStream";
import { useHighlight } from "@/hooks/useHighlight";
import { usePolling } from "@/hooks/usePolling";
import { POLL_ILLUSTRATION_MS } from "@/lib/constants";

import PlayerBar from "@/components/reader/PlayerBar";
import TableOfContents from "@/components/reader/TableOfContents";
import SettingsPanel from "@/components/reader/SettingsPanel";
import SelectionToolbar from "@/components/reader/SelectionToolbar";
import IllustrationCard from "@/components/reader/IllustrationCard";
import CharacterPanel from "@/components/reader/CharacterPanel";
import CharacterPickerModal from "@/components/reader/CharacterPickerModal";
import { ChevronLeft, Menu, Sliders, Loader2, AlertTriangle, Users } from "lucide-react";

const SentenceSpan = memo(({ s, isCurrent, onClickIndex }: {
  s: Sentence;
  isCurrent: boolean;
  onClickIndex: (idx: number) => void;
}) => (
  <span
    id={`sentence-${s.index}`}
    onClick={() => onClickIndex(s.index)}
    className={`sentence rounded cursor-pointer transition-colors duration-200 ${
      isCurrent ? "tts-highlight font-medium" : "hover:bg-amber-500/10"
    }`}
  >
    {s.text}
  </span>
));

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
    isPlaying,
    sentences,
    currentSentenceIndex,
    play,
    pause,
    skipNext,
    skipPrev,
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
    loadSettings,
    illustrationPromptPrefix,
    illustrationWidth,
    illustrationHeight,
    illustrationSeed,
  } = useReaderStore();

  // 本地 UI 狀態
  const [loading, setLoading] = useState(true);
  const [isTocOpen, setIsTocOpen] = useState(false);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isModelLoaded, setIsModelLoaded] = useState(true);
  const isFirstLoadRef = useRef(true);

  // 插圖狀態
  const [isCharPanelOpen, setIsCharPanelOpen] = useState(false);
  const [selectedCharacter, setSelectedCharacter] = useState<Character | null>(null);
  const [illustrations, setIllustrations] = useState<Map<number, { id?: number; imageBase64?: string | null; imageUrl?: string | null; prompt: string; meta?: IllustrationMeta }>>(new Map());
  const [llmAvailable, setLlmAvailable] = useState<boolean | null>(null);
  const [charPanelRefreshKey, setCharPanelRefreshKey] = useState(0);
  const [pendingExtraction, setPendingExtraction] = useState<Partial<Character> | null>(null);
  const [pendingExtractions, setPendingExtractions] = useState<Partial<Character>[] | null>(null);
  // 任務隊列進度
  const [taskQueue, setTaskQueue] = useState<IllustrationTask[]>([]);
  const completedTaskIdsRef = useRef<Set<string>>(new Set());
  const currentChapterIndexRef = useRef(currentChapterIndex);


  // 1. 初始化讀取書籍章節列表與進度
  useEffect(() => {
    const book = currentBook;
    if (!book) return;

    async function initReader(b: Book) {
      try {
        setLoading(true);
        // 從 SQLite 恢復使用者設定（字型、插圖寬高、seed 等）
        await loadSettings();
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
    fetchHardwareInfo();

    getModelsStatus().then((models) => {
      setIsModelLoaded(models.some((m) => m.loaded));
    }).catch(() => {});

    getIllustrationStatus().then((s) => setLlmAvailable(s.llm_available)).catch(() => {});

    // 刷新後恢復後端仍在進行的任務（避免頁面刷新後進度消失）
    getIllustrationProgress().then(tasks => {
      const active = tasks.filter(t => t.status === "pending" || t.status === "running");
      if (active.length > 0) setTaskQueue(active);
    }).catch(() => {});
  }, [currentBook, setChapters, setCurrentChapterIndex, fetchHardwareInfo]);

  // 2. 當當前章節 Index 改變時，載入章節的段落與句子
  useEffect(() => {
    const book = currentBook;
    if (!book || chapters.length === 0) return;
    const currentChapter = chapters[currentChapterIndex];
    if (!currentChapter) return;

    // 先清空以避免顯示上一章的插圖，同時清空任務進度避免舊章節任務汙染新章節
    setIllustrations(new Map());
    setTaskQueue([]);
    completedTaskIdsRef.current.clear();
    currentChapterIndexRef.current = currentChapterIndex;
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

        // 從 DB 恢復本章節已生成的插圖
        try {
          const saved = await getChapterIllustrations(b.id, currentChapterIndex);
          if (saved.length > 0) {
            const map = new Map<number, { id?: number; imageBase64?: string | null; imageUrl?: string | null; prompt: string; meta?: IllustrationMeta }>();
            saved.forEach((i) => map.set(i.sentence_index, {
              id: i.id, imageUrl: i.image_url, prompt: i.prompt,
              meta: { model_name: i.model_name, steps: i.steps, guidance_scale: i.guidance_scale,
                      seed: i.seed, width: i.width, height: i.height, is_anime: !!i.is_anime },
            }));
            setIllustrations(map);
          }
        } catch { /* 無法取得時保持空 Map */ }

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

  // 4. 輪詢生圖任務進度
  const hasActiveTasks = taskQueue.some(t => t.status === "pending" || t.status === "running");
  usePolling(async () => {
    try {
      const tasks = await getIllustrationProgress();
      setTaskQueue(tasks);

      tasks.forEach(t => {
        // 完成：寫入插圖 Map，每個 task_id 只 toast 一次
        if (t.status === "done" && t.result && !completedTaskIdsRef.current.has(t.task_id)) {
          completedTaskIdsRef.current.add(t.task_id);
          // 僅插入屬於當前章節的任務結果，避免舊章節任務汙染新章節
          if (t.chapter_index === currentChapterIndexRef.current) {
            const { id, image_url, image_base64, prompt, model_name, steps, guidance_scale, seed, width, height, is_anime } = t.result;
            setIllustrations(prev => {
              if (prev.has(t.sentence_index)) return prev;
              const n = new Map(prev);
              n.set(t.sentence_index, {
                id: id ?? undefined,
                imageUrl: image_url ?? null,
                imageBase64: image_base64 ?? null,
                prompt,
                meta: { model_name, steps, guidance_scale, seed, width, height, is_anime },
              });
              return n;
            });
            toast.success("插圖已生成");
          }
        }
        if (t.status === "error" && !completedTaskIdsRef.current.has(t.task_id)) {
          completedTaskIdsRef.current.add(t.task_id);
          toast.error(`生圖失敗：${t.error}`);
        }
      });

      if (tasks.length > 0 && tasks.every(t => t.status === "done" || t.status === "error")) {
        setTaskQueue([]);
      }
    } catch { /* ignore */ }
  }, POLL_ILLUSTRATION_MS, hasActiveTasks);

  // 5. 章節朗讀完畢自動跳轉
  const handleChapterEnded = useCallback(() => {
    if (currentChapterIndex < chapters.length - 1) {
      setCurrentChapterIndex(currentChapterIndex + 1);
    } else {
      pause();
      toast.success("全書朗讀完畢", { description: "已到達最後一章" });
    }
  }, [currentChapterIndex, chapters, setCurrentChapterIndex, pause]);

  // 啟動朗讀串流與高亮 Hook
  const { resumeAudio, changeVolume } = useAudioStream(handleChapterEnded);
  useHighlight();

  // 手動上一章、下一章按鈕事件（useCallback 以利 useEffect deps）
  const handleSkipNextChapter = useCallback(() => {
    if (currentChapterIndex < chapters.length - 1) {
      setCurrentChapterIndex(currentChapterIndex + 1);
    } else {
      toast.info("已經是最後一章了");
    }
  }, [currentChapterIndex, chapters, setCurrentChapterIndex]);

  const handleSkipPrevChapter = useCallback(() => {
    if (currentChapterIndex > 0) {
      setCurrentChapterIndex(currentChapterIndex - 1);
    } else {
      toast.info("已經是第一章了");
    }
  }, [currentChapterIndex, setCurrentChapterIndex]);

  // 插圖生成（非阻塞：立即加入隊列）
  const handleGenerateIllustration = useCallback(async (text: string, sentenceIndex: number | null) => {
    if (!currentBook) return;
    // 優先使用選取位置的 sentence index，fallback 到 TTS 位置
    const sidx = sentenceIndex ?? currentSentenceIndex;
    try {
      const { task_id, queue_position } = await generateIllustration({
        text,
        character_name: selectedCharacter?.name,
        book_id: currentBook.id,
        chapter_index: currentChapterIndex,
        sentence_index: sidx,
        width: illustrationWidth,
        height: illustrationHeight,
        seed: illustrationSeed,
        prompt_prefix: illustrationPromptPrefix || undefined,
      });
      // 加入本地隊列，觸發輪詢
      setTaskQueue(prev => [...prev, {
        task_id,
        status: "pending",
        progress: 0,
        label: "排隊中",
        timings: [],
        sentence_index: sidx,
        chapter_index: currentChapterIndex,
        book_id: currentBook.id,
        result: null,
        error: null,
      }]);
      if (queue_position > 1) toast.info(`已加入隊列（第 ${queue_position} 個）`);
    } catch (err: any) {
      toast.error(err.message || "生圖失敗");
    }
  }, [currentBook, currentChapterIndex, currentSentenceIndex, selectedCharacter, illustrationPromptPrefix, illustrationWidth, illustrationHeight, illustrationSeed]);

  const handleExtractCharacter = useCallback(async (text: string) => {
    if (!currentBook) return;
    const toastId = toast.loading("分析角色特徵中…");
    try {
      const extracted = await extractCharacterFeatures(currentBook.id, text);
      toast.dismiss(toastId);
      if (extracted.length === 0) {
        toast.warning("未偵測到角色描述");
        return;
      }
      setIsCharPanelOpen(true);
      if (extracted.length === 1) {
        setPendingExtraction(extracted[0]);
      } else {
        setPendingExtractions(extracted);
      }
    } catch {
      toast.dismiss(toastId);
      toast.error("角色特徵提取失敗");
    }
  }, [currentBook]);


  // 書籤：新增當前位置
  const handleAddBookmark = useCallback(async () => {
    const book = currentBook;
    if (!book) return;
    try {
      await createBookmark(book.id, currentChapterIndex, currentSentenceIndex);
      toast.success("書籤已加入");
    } catch {
      toast.error("新增書籤失敗");
    }
  }, [currentBook, currentChapterIndex, currentSentenceIndex]);

  // 書籤：跳轉至指定章節與句子
  const handleJumpToBookmark = useCallback((chapterIndex: number, sentenceIndex: number) => {
    setCurrentChapterIndex(chapterIndex);
    setTimeout(() => _setCurrentIndex(sentenceIndex), 300);
  }, [setCurrentChapterIndex, _setCurrentIndex]);

  // 鍵盤快捷鍵（Space / ← → / [ ] / B）
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

      switch (e.key) {
        case " ":
          e.preventDefault();
          if (isPlaying) {
            pause();
          } else {
            resumeAudio();
            play();
          }
          break;
        case "ArrowRight":
          e.preventDefault();
          skipNext();
          break;
        case "ArrowLeft":
          e.preventDefault();
          skipPrev();
          break;
        case "]":
          e.preventDefault();
          handleSkipNextChapter();
          break;
        case "[":
          e.preventDefault();
          handleSkipPrevChapter();
          break;
        case "b":
        case "B":
          e.preventDefault();
          handleAddBookmark();
          break;
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isPlaying, play, pause, skipNext, skipPrev, resumeAudio,
      handleSkipNextChapter, handleSkipPrevChapter, handleAddBookmark]);

  if (!currentBook) return null;

  const currentChapter = chapters[currentChapterIndex];

  // 將句子依照段落 index 進行分組以渲染（useMemo 避免每次 render 重建）
  const paragraphsMap = useMemo(() => {
    const map: Record<number, Sentence[]> = {};
    sentences.forEach((s) => {
      if (!map[s.paragraphIndex]) map[s.paragraphIndex] = [];
      map[s.paragraphIndex].push(s);
    });
    return map;
  }, [sentences]);

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
          {/* 角色庫按鈕 */}
          <button
            onClick={() => setIsCharPanelOpen(true)}
            className={`p-2 rounded-full hover:bg-white/10 active:scale-95 transition-all flex items-center gap-1.5 text-xs ${selectedCharacter ? "text-amber-500" : ""}`}
            title={selectedCharacter ? `角色：${selectedCharacter.name}` : "角色庫"}
          >
            <Users size={18} />
            {selectedCharacter && <span className="hidden sm:inline text-[10px] font-semibold">{selectedCharacter.name}</span>}
          </button>

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

      {/* 本地 LLM 未找到提示 */}
      {llmAvailable === false && (
        <div className="flex items-center gap-2 px-6 py-2 text-xs border-b" style={{ backgroundColor: "var(--bg-surface)", borderColor: "var(--border)", color: "var(--text-secondary)" }}>
          <span className="text-blue-400 shrink-0">ℹ</span>
          <span>未偵測到本地 LLM 模型（backend/models/*.gguf），生圖時將直接使用原文作為 prompt</span>
        </div>
      )}

      {/* 模型未載入提示 Banner */}
      {!isModelLoaded && (
        <div className="flex items-center justify-between gap-3 px-6 py-2.5 text-xs bg-amber-500/10 border-b border-amber-500/30">
          <div className="flex items-center gap-2" style={{ color: "var(--text-primary)" }}>
            <AlertTriangle size={14} className="text-amber-500 shrink-0" />
            <span>TTS 模型尚未載入，語音朗讀功能暫時無法使用。</span>
          </div>
          <button
            onClick={() => setIsSettingsOpen(true)}
            className="shrink-0 px-3 py-1 rounded-full text-[11px] font-semibold bg-amber-500 text-black hover:bg-amber-400 active:scale-95 transition-all"
          >
            前往設定
          </button>
        </div>
      )}

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
          <>
          <SelectionToolbar
            onGenerate={handleGenerateIllustration}
            onExtractCharacter={handleExtractCharacter}
            queueCount={taskQueue.filter(t => t.status === "pending" || t.status === "running").length}
          />
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
                  // 找本段落內任何句子的插圖（不限定最後一句）
                  const illus = paragraphSentences
                    .map(s => illustrations.get(s.index))
                    .find((v): v is { id?: number; imageBase64?: string | null; imageUrl?: string | null; prompt: string; meta?: IllustrationMeta } => v !== undefined);
                  // 找到本段落任何句子的進行中任務
                  const activeTask = taskQueue.find(t =>
                    (t.status === "pending" || t.status === "running") &&
                    paragraphSentences.some(s => s.index === t.sentence_index)
                  );
                  return (
                    <div key={pIdx}>
                      <p className="paragraph text-justify select-text">
                        {paragraphSentences.map((s) => (
                          <SentenceSpan
                            key={s.index}
                            s={s}
                            isCurrent={s.index === currentSentenceIndex}
                            onClickIndex={_setCurrentIndex}
                          />
                        ))}
                      </p>
                      {activeTask && (
                        <div className="mt-2 mb-1 flex flex-col gap-1">
                          <div className="flex items-center justify-between text-[11px]" style={{ color: "var(--text-secondary)" }}>
                            <span>{activeTask.label}</span>
                            <span>{activeTask.progress}%</span>
                          </div>
                          <div className="h-1 rounded-full overflow-hidden" style={{ backgroundColor: "var(--border)" }}>
                            <div
                              className="h-full rounded-full bg-amber-500 transition-all duration-300"
                              style={{ width: `${activeTask.progress}%` }}
                            />
                          </div>
                        </div>
                      )}
                      {illus && currentBook && (
                        <IllustrationCard
                          imageBase64={illus.imageBase64 ?? undefined}
                          imageUrl={illus.imageUrl ?? undefined}
                          prompt={illus.prompt}
                          meta={illus.meta}
                          bookId={currentBook.id}
                          onDismiss={() => {
                            if (illus.id) deleteIllustration(illus.id).catch(() => {});
                            setIllustrations(prev => {
                              const n = new Map(prev);
                              for (const s of paragraphSentences) {
                                if (prev.get(s.index) === illus) { n.delete(s.index); break; }
                              }
                              return n;
                            });
                          }}
                          onImageSavedToCharacter={() => {
                            setCharPanelRefreshKey(k => k + 1);
                            setIsCharPanelOpen(true);
                          }}
                        />
                      )}
                    </div>
                  );
                })
            )}
          </article>
          </>
        )}
      </main>

      {/* 懸浮播放控制列（整合生圖進度與排隊數量） */}
      <PlayerBar
        onSkipNextChapter={handleSkipNextChapter}
        onSkipPrevChapter={handleSkipPrevChapter}
        chapterTitle={currentChapter?.title || "未命名章節"}
        resumeAudio={resumeAudio}
        changeVolume={changeVolume}
        onBookmark={handleAddBookmark}
        illustrationTasks={taskQueue.filter(t => t.status === "pending" || t.status === "running")}
      />

      {/* 左側目錄/書籤抽屜 */}
      <TableOfContents
        isOpen={isTocOpen}
        onClose={() => setIsTocOpen(false)}
        onSelectChapter={(idx) => setCurrentChapterIndex(idx)}
        bookId={currentBook?.id}
        onJumpToBookmark={handleJumpToBookmark}
      />

      {/* 右側設定抽屜 */}
      <SettingsPanel
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
      />

      {currentBook && (
        <CharacterPanel
          isOpen={isCharPanelOpen}
          onClose={() => setIsCharPanelOpen(false)}
          bookId={currentBook.id}
          selectedCharName={selectedCharacter?.name}
          refreshKey={charPanelRefreshKey}
          onSelectCharacter={(char) => {
            setSelectedCharacter(char);
            if (char) toast.success(`已選取角色「${char.name}」`);
          }}
          pendingExtraction={pendingExtraction}
          onExtractionConsumed={() => setPendingExtraction(null)}
        />
      )}

      {pendingExtractions && (
        <CharacterPickerModal
          candidates={pendingExtractions}
          onSelect={(char) => {
            setPendingExtractions(null);
            setPendingExtraction(char);
          }}
          onClose={() => setPendingExtractions(null)}
        />
      )}
    </div>
  );
}
