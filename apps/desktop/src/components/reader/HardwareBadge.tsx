import { useState } from "react";
import { useReaderStore } from "@/stores/reader";
import { Cpu } from "lucide-react";

export default function HardwareBadge() {
  const { hardwareInfo } = useReaderStore();
  const [showTooltip, setShowTooltip] = useState(false);

  if (!hardwareInfo) return null;

  const { recommended_device, display_name, badge_color } = hardwareInfo;

  // 根據 badge_color 決定指示燈的顏色
  const dotColor =
    badge_color === "green"
      ? "bg-emerald-500 shadow-[0_0_8px_#10b981]"
      : badge_color === "blue"
      ? "bg-sky-500 shadow-[0_0_8px_#0ea5e9]"
      : "bg-gray-500";

  return (
    <div className="relative inline-block">
      {/* 徽章按鈕 */}
      <button
        onClick={() => setShowTooltip(!showTooltip)}
        onMouseEnter={() => setShowTooltip(true)}
        onMouseLeave={() => setShowTooltip(false)}
        className="flex items-center gap-1.5 px-2 py-1 rounded text-[11px] font-mono transition-all hover:brightness-125"
        style={{
          backgroundColor: "var(--bg-hover)",
          border: "1px solid var(--border)",
          color: "var(--text-secondary)",
        }}
      >
        <span className={`w-2 h-2 rounded-full ${dotColor}`} />
        <span>{recommended_device.toUpperCase()}</span>
      </button>

      {/* Tooltip 詳細硬體面板 */}
      {showTooltip && (
        <div
          className="absolute bottom-full mb-2 right-0 w-64 p-4 rounded-xl shadow-2xl z-50 text-xs flex flex-col gap-2 border animate-in fade-in slide-in-from-bottom-2 duration-150"
          style={{
            backgroundColor: "var(--bg-surface)",
            borderColor: "var(--border)",
            color: "var(--text-primary)",
          }}
        >
          <div className="flex items-center gap-1.5 font-semibold text-amber-500 pb-1 border-b" style={{ borderColor: "var(--border)" }}>
            <Cpu size={14} />
            <span>推理硬體詳情</span>
          </div>

          <div className="flex flex-col gap-1.5">
            <div className="flex justify-between">
              <span style={{ color: "var(--text-secondary)" }}>作業系統:</span>
              <span className="font-mono">{hardwareInfo.platform.toUpperCase()}</span>
            </div>
            <div className="flex flex-col">
              <span style={{ color: "var(--text-secondary)" }}>處理器 (CPU):</span>
              <span className="font-medium mt-0.5 line-clamp-2">{hardwareInfo.cpu}</span>
            </div>
            {hardwareInfo.gpu && (
              <div className="flex flex-col">
                <span style={{ color: "var(--text-secondary)" }}>顯示卡 (GPU):</span>
                <span className="font-medium mt-0.5">{hardwareInfo.gpu}</span>
              </div>
            )}
            <div className="flex justify-between">
              <span style={{ color: "var(--text-secondary)" }}>推薦推理模式:</span>
              <span className="font-semibold text-amber-500">{display_name}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
