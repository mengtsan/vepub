import { X, ClipboardCopy } from "lucide-react";
import { useState } from "react";

interface Props {
  src: string;
  prompt?: string | null;
  onClose: () => void;
}

export function ImageLightbox({ src, prompt, onClose }: Props) {
  const [copied, setCopied] = useState(false);

  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!prompt) return;
    navigator.clipboard.writeText(prompt).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  return (
    <div
      className="fixed inset-0 z-[100] bg-black/90 flex flex-col items-center justify-center p-4 gap-3"
      onClick={onClose}
    >
      <button
        className="absolute top-4 right-4 p-2.5 rounded-full bg-white/10 hover:bg-white/20 transition-colors"
        onClick={onClose}
      >
        <X size={20} className="text-white" />
      </button>
      <img
        src={src}
        alt="圖片預覽"
        className="max-w-full max-h-[80vh] object-contain rounded-lg shadow-2xl"
        onClick={e => e.stopPropagation()}
      />
      {prompt && (
        <div
          className="max-w-2xl w-full rounded-lg border border-white/10 bg-black/60 px-4 py-3 text-[11px] text-white/60 leading-relaxed relative"
          onClick={e => e.stopPropagation()}
        >
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[10px] text-white/30 font-semibold tracking-wider uppercase">Prompt</span>
            <button
              onClick={handleCopy}
              className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] bg-white/5 hover:bg-white/15 text-white/40 hover:text-white/70 transition-colors"
            >
              <ClipboardCopy size={10} />
              {copied ? "已複製" : "複製"}
            </button>
          </div>
          <p className="break-all whitespace-pre-wrap">{prompt}</p>
        </div>
      )}
    </div>
  );
}
