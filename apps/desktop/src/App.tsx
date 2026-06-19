import { useEffect, useRef, useState } from "react";
import { Outlet } from "@tanstack/react-router";
import { Toaster } from "sonner";
import { BACKEND_BASE_URL } from "./lib/constants";
import "./App.css";

const HEALTH_POLL_MS = 600;
const BOOT_TIMEOUT_MS = 90_000;

function BackendLoader({ onReady }: { onReady: () => void }) {
  const [dots, setDots] = useState(".");
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const startRef = useRef(Date.now());

  // Animate ellipsis
  useEffect(() => {
    const t = setInterval(() => {
      setDots(d => (d.length >= 3 ? "." : d + "."));
      setElapsed(Math.round((Date.now() - startRef.current) / 1000));
    }, 400);
    return () => clearInterval(t);
  }, []);

  // Poll /health
  useEffect(() => {
    let cancelled = false;

    const timeout = setTimeout(() => {
      if (!cancelled) setError("後端啟動逾時（>90s），請重新啟動應用程式");
    }, BOOT_TIMEOUT_MS);

    const poll = async () => {
      if (cancelled) return;
      try {
        const res = await fetch(`${BACKEND_BASE_URL}/health`, { signal: AbortSignal.timeout(2000) });
        if (!cancelled && res.ok) {
          clearTimeout(timeout);
          onReady();
          return;
        }
      } catch {
        // backend not yet up — keep polling
      }
      if (!cancelled) {
        setTimeout(poll, HEALTH_POLL_MS);
      }
    };

    poll();
    return () => {
      cancelled = true;
      clearTimeout(timeout);
    };
  }, [onReady]);

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: "1.5rem",
        background: "var(--bg-primary)",
        color: "var(--text-primary)",
        userSelect: "none",
      }}
    >
      {error ? (
        <>
          <div style={{ fontSize: "1.5rem" }}>⚠</div>
          <div style={{ color: "var(--text-secondary)", fontSize: "0.9rem", textAlign: "center", maxWidth: 360 }}>
            {error}
          </div>
        </>
      ) : (
        <>
          {/* Spinner */}
          <svg
            width="40" height="40" viewBox="0 0 40 40"
            style={{ animation: "spin 1s linear infinite" }}
          >
            <circle
              cx="20" cy="20" r="16"
              fill="none"
              stroke="var(--accent)"
              strokeWidth="3"
              strokeLinecap="round"
              strokeDasharray="60 40"
            />
          </svg>

          <div style={{ fontSize: "1rem", letterSpacing: "0.05em" }}>
            後端啟動中{dots}
          </div>

          <div style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
            {elapsed > 0 ? `${elapsed}s` : ""}
          </div>
        </>
      )}

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}

function App() {
  const [ready, setReady] = useState(false);

  return (
    <>
      {!ready && <BackendLoader onReady={() => setReady(true)} />}
      {ready && <Outlet />}
      <Toaster position="top-center" richColors closeButton />
    </>
  );
}

export default App;
