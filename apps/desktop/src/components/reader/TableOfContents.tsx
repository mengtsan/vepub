import { useEffect, useRef, useState, useCallback } from "react";
import { toast } from "sonner";
import { useReaderStore } from "@/stores/reader";
import { X, BookOpen, Bookmark, Trash2 } from "lucide-react";
import { Bookmark as BookmarkType, getBookmarks, deleteBookmark } from "@/lib/api";

interface TableOfContentsProps {
  isOpen: boolean;
  onClose: () => void;
  onSelectChapter: (chapterIndex: number) => void;
  bookId?: string;
  onJumpToBookmark?: (chapterIndex: number, sentenceIndex: number) => void;
}

export default function TableOfContents({
  isOpen,
  onClose,
  onSelectChapter,
  bookId,
  onJumpToBookmark,
}: TableOfContentsProps) {
  const { chapters, currentChapterIndex } = useReaderStore();
  const activeItemRef = useRef<HTMLButtonElement | null>(null);
  const [tab, setTab] = useState<"toc" | "bookmarks">("toc");
  const [bookmarks, setBookmarks] = useState<BookmarkType[]>([]);

  // 當目錄面板打開時，自動將目前閱讀的章節滾動至可視範圍中央
  useEffect(() => {
    if (isOpen && activeItemRef.current) {
      activeItemRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [isOpen, currentChapterIndex]);

  const fetchBookmarks = useCallback(async () => {
    if (!bookId) return;
    try {
      const data = await getBookmarks(bookId);
      setBookmarks(data);
    } catch {
      /* 靜默失敗 */
    }
  }, [bookId]);

  useEffect(() => {
    if (isOpen && tab === "bookmarks") {
      fetchBookmarks();
    }
  }, [isOpen, tab, fetchBookmarks]);

  const handleDeleteBookmark = async (bmId: number) => {
    if (!bookId) return;
    try {
      await deleteBookmark(bookId, bmId);
      setBookmarks((prev) => prev.filter((b) => b.id !== bmId));
      toast.success("書籤已刪除");
    } catch {
      toast.error("刪除書籤失敗");
    }
  };

  const formatDate = (ts: number) => {
    return new Date(ts * 1000).toLocaleDateString("zh-TW", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  return (
    <>
      {/* 背景半透明遮罩 */}
      {isOpen && (
        <div
          onClick={onClose}
          className="fixed inset-0 bg-black/40 backdrop-blur-xs z-40 transition-opacity duration-300"
        />
      )}

      {/* 左側抽屜面板 (寬 280px) */}
      <div
        className="fixed top-0 left-0 h-full w-[280px] shadow-2xl z-50 transition-transform duration-300 ease-out border-r flex flex-col"
        style={{
          backgroundColor: "var(--bg-surface)",
          borderColor: "var(--border)",
          color: "var(--text-primary)",
          transform: isOpen ? "translateX(0)" : "translateX(-100%)",
        }}
      >
        {/* 標題欄 */}
        <header className="flex justify-between items-center px-5 py-4 border-b" style={{ borderColor: "var(--border)" }}>
          <div className="flex items-center gap-2 font-bold text-sm tracking-wider">
            <BookOpen size={16} className="text-amber-500" />
            <span>書籍目錄</span>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-full hover:bg-white/10 active:scale-95 transition-all"
            style={{ color: "var(--text-secondary)" }}
          >
            <X size={18} />
          </button>
        </header>

        {/* 頁籤切換 */}
        <div className="flex border-b text-xs font-semibold" style={{ borderColor: "var(--border)" }}>
          <button
            onClick={() => setTab("toc")}
            className={`flex-1 flex items-center justify-center gap-1.5 py-2.5 border-b-2 transition-colors ${
              tab === "toc" ? "border-amber-500 text-amber-500" : "border-transparent hover:bg-white/5"
            }`}
            style={{ color: tab !== "toc" ? "var(--text-secondary)" : undefined }}
          >
            <BookOpen size={12} /> 目錄
          </button>
          <button
            onClick={() => setTab("bookmarks")}
            className={`flex-1 flex items-center justify-center gap-1.5 py-2.5 border-b-2 transition-colors ${
              tab === "bookmarks" ? "border-amber-500 text-amber-500" : "border-transparent hover:bg-white/5"
            }`}
            style={{ color: tab !== "bookmarks" ? "var(--text-secondary)" : undefined }}
          >
            <Bookmark size={12} /> 書籤
            {bookmarks.length > 0 && (
              <span className="ml-0.5 px-1 py-0.5 text-[9px] rounded-full bg-amber-500 text-black font-bold leading-none">
                {bookmarks.length}
              </span>
            )}
          </button>
        </div>

        {/* 內容區 */}
        <main className="flex-1 overflow-y-auto py-2">
          {tab === "toc" ? (
            chapters.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 text-center" style={{ color: "var(--text-secondary)" }}>
                <span className="text-xs">未加載章節資訊</span>
              </div>
            ) : (
              <div className="flex flex-col">
                {chapters.map((ch, idx) => {
                  const isActive = idx === currentChapterIndex;
                  const progressPercent = Math.round((idx / chapters.length) * 100);

                  return (
                    <button
                      key={ch.id}
                      ref={isActive ? activeItemRef : null}
                      onClick={() => {
                        onSelectChapter(idx);
                        onClose();
                      }}
                      className={`flex items-center justify-between px-5 py-3.5 text-left text-xs transition-all border-l-2 hover:bg-white/5 active:bg-white/10 ${
                        isActive
                          ? "text-amber-500 font-semibold border-amber-500 bg-amber-500/5"
                          : "border-transparent"
                      }`}
                      style={{ color: isActive ? "var(--accent)" : "var(--text-primary)" }}
                    >
                      <span className="line-clamp-2 pr-4 leading-relaxed">{ch.title}</span>
                      <span
                        className="font-mono text-[10px] shrink-0"
                        style={{ color: isActive ? "var(--accent)" : "var(--text-muted)" }}
                      >
                        {progressPercent}%
                      </span>
                    </button>
                  );
                })}
              </div>
            )
          ) : (
            bookmarks.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 text-center gap-2" style={{ color: "var(--text-secondary)" }}>
                <Bookmark size={28} className="opacity-30" />
                <span className="text-xs">尚無書籤</span>
                <span className="text-[10px] px-4" style={{ color: "var(--text-muted)" }}>
                  播放時點擊播放列的書籤圖示可新增書籤
                </span>
              </div>
            ) : (
              <div className="flex flex-col">
                {bookmarks.map((bm) => {
                  const chapterTitle = chapters[bm.chapter_index]?.title || `第 ${bm.chapter_index + 1} 章`;
                  return (
                    <div
                      key={bm.id}
                      className="flex items-start gap-2 px-4 py-3 border-b hover:bg-white/5 transition-all group"
                      style={{ borderColor: "var(--border)" }}
                    >
                      <Bookmark size={12} className="text-amber-500 mt-0.5 shrink-0" />
                      <button
                        className="flex-1 text-left"
                        onClick={() => {
                          onJumpToBookmark?.(bm.chapter_index, bm.sentence_index);
                          onClose();
                        }}
                      >
                        <div className="text-xs font-medium line-clamp-1" style={{ color: "var(--text-primary)" }}>
                          {chapterTitle}
                        </div>
                        {bm.note && (
                          <div className="text-[10px] mt-0.5 line-clamp-2" style={{ color: "var(--text-secondary)" }}>
                            {bm.note}
                          </div>
                        )}
                        <div className="text-[9px] mt-0.5" style={{ color: "var(--text-muted)" }}>
                          {formatDate(bm.created_at)}
                        </div>
                      </button>
                      <button
                        onClick={() => handleDeleteBookmark(bm.id)}
                        className="p-1 rounded opacity-0 group-hover:opacity-100 text-red-400 hover:bg-red-500/10 active:scale-90 transition-all shrink-0"
                        title="刪除書籤"
                      >
                        <Trash2 size={11} />
                      </button>
                    </div>
                  );
                })}
              </div>
            )
          )}
        </main>
      </div>
    </>
  );
}
