import { AnalysisJob } from "@/lib/api";

interface Props {
  analysis: AnalysisJob;
  onDismiss: () => void;
}

export function AnalysisProgress({ analysis, onDismiss }: Props) {
  return (
    <div className="px-4 py-2 border-b text-[10px]" style={{ borderColor: "var(--border)" }}>
      <div className="flex items-center justify-between mb-1">
        <span style={{ color: analysis.status === "error" ? "#f87171" : "var(--text-secondary)" }}>
          {analysis.label}
        </span>
        {analysis.status === "done" && (
          <button onClick={onDismiss} className="text-[9px] opacity-50 hover:opacity-100">✕</button>
        )}
      </div>
      {(analysis.status === "running" || analysis.status === "pending") && (
        <div className="w-full h-1 rounded-full overflow-hidden" style={{ backgroundColor: "var(--border)" }}>
          <div
            className="h-full rounded-full bg-sky-400 transition-all duration-500"
            style={{ width: `${analysis.progress}%` }}
          />
        </div>
      )}
    </div>
  );
}
