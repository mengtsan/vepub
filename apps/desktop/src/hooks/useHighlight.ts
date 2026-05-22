import { useEffect } from "react";
import { usePlayerStore } from "@/stores/player";

export function useHighlight(renditionRef?: React.RefObject<any>) {
  const { currentSentenceIndex, sentences } = usePlayerStore();

  useEffect(() => {
    if (sentences.length === 0) return;
    const sentence = sentences[currentSentenceIndex];
    if (!sentence) return;

    // 1. 優先使用 HTML DOM 模式高亮與滾動（React 直推文字時最為流暢）
    const element = document.getElementById(`sentence-${currentSentenceIndex}`);
    if (element) {
      // 移除其他句子的舊高亮
      document.querySelectorAll(".tts-highlight").forEach((el) => {
        el.classList.remove("tts-highlight");
      });
      // 加上高亮樣式
      element.classList.add("tts-highlight");

      // 平滑滾動置中
      element.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }

    // 2. 備用方案：如果使用的是 epub.js iframe 渲染，利用 CFI 進行高亮
    if (renditionRef && renditionRef.current && sentence.cfi) {
      const rendition = renditionRef.current;
      try {
        rendition.annotations.remove("highlight", "tts-highlight");
        rendition.annotations.highlight(
          sentence.cfi,
          {},
          undefined,
          "tts-highlight",
          { fill: "rgba(251, 191, 36, 0.35)" }
        );
        rendition.display(sentence.cfi);
      } catch (e) {
        console.warn("epub.js 標註高亮失敗:", e);
      }
    }
  }, [currentSentenceIndex, sentences, renditionRef]);
}
