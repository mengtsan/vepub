import { useEffect, useRef } from "react";
import { useReaderStore } from "@/stores/reader";
import { X, BookOpen } from "lucide-react";

interface TableOfContentsProps {
  isOpen: boolean;
  onClose: () => void;
  onSelectChapter: (chapterIndex: number) => void;
}

export default function TableOfContents({
  isOpen,
  onClose,
  onSelectChapter,
}: TableOfContentsProps) {
  const { chapters, currentChapterIndex } = useReaderStore();
  const activeItemRef = useRef<HTMLButtonElement | null>(null);

  // 當目錄面板打開時，自動將目前閱讀的章節滾動至可視範圍中央
  useEffect(() => {
    if (isOpen && activeItemRef.current) {
      activeItemRef.current.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
    }
  }, [isOpen, currentChapterIndex]);

  return (
    <>
      {/* 背景半透明遮罩 */}
      {isOpen && (
        <div
          onClick={onClose}
          className="fixed inset-0 bg-black/40 backdrop-blur-xs z-40 transition-opacity duration-300"
        />
      )}

      {/* 左側目錄抽屜面板 (寬 280px) */}
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

        {/* 章節列表 */}
        <main className="flex-1 overflow-y-auto py-2">
          {chapters.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center" style={{ color: "var(--text-secondary)" }}>
              <span className="text-xs">未加載章節資訊</span>
            </div>
          ) : (
            <div className="flex flex-col">
              {chapters.map((ch, idx) => {
                const isActive = idx === currentChapterIndex;
                
                // 粗略計算這章讀了多少的進度標籤 (假設每章為 100% / 總章數)
                const totalCh = chapters.length;
                const progressPercent = Math.round((idx / totalCh) * 100);

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
                    style={{
                      color: isActive ? "var(--accent)" : "var(--text-primary)",
                    }}
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
          )}
        </main>
      </div>
    </>
  );
}
