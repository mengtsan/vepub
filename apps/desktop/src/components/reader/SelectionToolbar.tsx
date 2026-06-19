import { useEffect, useRef, useState } from "react";
import { ImagePlus, UserPlus } from "lucide-react";

interface SelectionToolbarProps {
  onGenerate: (text: string, sentenceIndex: number | null) => void;
  onExtractCharacter: (text: string) => void;
  queueCount: number;
}

export default function SelectionToolbar({ onGenerate, onExtractCharacter, queueCount }: SelectionToolbarProps) {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const [selText, setSelText] = useState("");
  const [selSentenceIndex, setSelSentenceIndex] = useState<number | null>(null);
  const toolbarRef = useRef<HTMLDivElement>(null);
  const hideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const handleMouseUp = (e: MouseEvent) => {
      if (toolbarRef.current?.contains(e.target as Node)) return;

      requestAnimationFrame(() => {
        const sel = window.getSelection();
        if (!sel || sel.isCollapsed) return;
        const text = sel.toString().trim();
        if (text.length < 5) return;

        try {
          const range = sel.getRangeAt(0);
          const rect = range.getBoundingClientRect();
          if (!rect.width && !rect.height) return;

          // 從選取起點向上找最近的 sentence-N span
          let sentenceIdx: number | null = null;
          let node: Node | null = sel.anchorNode;
          while (node && node !== document.body) {
            if (node instanceof Element) {
              const m = node.id?.match(/^sentence-(\d+)$/);
              if (m) { sentenceIdx = parseInt(m[1], 10); break; }
            }
            node = node.parentNode;
          }

          const TOOLBAR_HALF_W = 110;
          const x = Math.max(TOOLBAR_HALF_W, Math.min(window.innerWidth - TOOLBAR_HALF_W, rect.left + rect.width / 2));
          const y = rect.top < 60 ? rect.bottom + 10 : rect.top - 48;

          setPos({ x, y });
          setSelText(text);
          setSelSentenceIndex(sentenceIdx);
        } catch {
          // range 無效時靜默略過
        }
      });
    };

    document.addEventListener("mouseup", handleMouseUp);
    return () => document.removeEventListener("mouseup", handleMouseUp);
  }, []);

  useEffect(() => {
    const handleSelectionChange = () => {
      if (hideTimerRef.current) clearTimeout(hideTimerRef.current);
      hideTimerRef.current = setTimeout(() => {
        const sel = window.getSelection();
        if (!sel || sel.isCollapsed || !sel.toString().trim()) {
          setPos(null);
        }
      }, 100);
    };

    document.addEventListener("selectionchange", handleSelectionChange);
    return () => {
      document.removeEventListener("selectionchange", handleSelectionChange);
      if (hideTimerRef.current) clearTimeout(hideTimerRef.current);
    };
  }, []);

  if (!pos) return null;

  return (
    <div
      ref={toolbarRef}
      className="fixed z-50 flex items-center gap-1.5 px-3 py-1.5 rounded-full shadow-xl border text-xs font-semibold select-none"
      style={{
        left: pos.x,
        top: pos.y,
        transform: "translateX(-50%)",
        backgroundColor: "var(--bg-surface)",
        borderColor: "var(--border)",
        color: "var(--text-primary)",
      }}
    >
      <button
        onClick={() => {
          const text = selText;
          const sidx = selSentenceIndex;
          window.getSelection()?.removeAllRanges();
          setPos(null);
          onGenerate(text, sidx);
        }}
        className="flex items-center gap-1.5 text-amber-500 hover:text-amber-400 transition-colors"
      >
        <ImagePlus size={13} />
        <span>生成插圖</span>
        {queueCount > 0 && (
          <span className="ml-0.5 px-1.5 py-0.5 rounded-full text-[10px] font-bold bg-amber-500 text-black leading-none">
            {queueCount}
          </span>
        )}
      </button>

      <span className="w-px h-3.5 shrink-0" style={{ backgroundColor: "var(--border)" }} />

      <button
        onClick={() => {
          const text = selText;
          window.getSelection()?.removeAllRanges();
          setPos(null);
          onExtractCharacter(text);
        }}
        className="flex items-center gap-1.5 text-sky-400 hover:text-sky-300 transition-colors"
      >
        <UserPlus size={13} />
        <span>提取角色</span>
      </button>
    </div>
  );
}
