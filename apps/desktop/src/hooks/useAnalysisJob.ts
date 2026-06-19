import { useState } from "react";
import { toast } from "sonner";
import { usePolling } from "./usePolling";
import { getAnalysisStatus, AnalysisJob } from "@/lib/api";
import { POLL_ANALYSIS_MS } from "@/lib/constants";

export function useAnalysisJob(bookId: string, fetchChars: () => void) {
  const [analysis, setAnalysis] = useState<AnalysisJob | null>(null);
  const analysisActive = !!analysis && analysis.status !== "done" && analysis.status !== "error";

  usePolling(async () => {
    const s = await getAnalysisStatus(bookId).catch(() => null);
    if (!s) return;
    setAnalysis(s);
    if (s.status === "done") {
      toast.success(s.label);
      fetchChars();
    } else if (s.status === "error") {
      toast.error(`分析失敗：${s.error}`);
    }
  }, POLL_ANALYSIS_MS, analysisActive);

  return { analysis, setAnalysis };
}
