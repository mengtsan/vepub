import { BACKEND_BASE_URL } from "./constants";
const BASE_URL = BACKEND_BASE_URL;

// ─── Types ────────────────────────────────────────────────────────────────────

export interface ModelInfo {
  id: string;
  name: string;
  type: string;
  style?: string;
  local_path: string;
  vae_path?: string;
  text_encoder_path?: string;
  size_bytes: number;
  source: string;
  is_active: boolean;
  is_loaded: boolean;
  available?: boolean;   // 檔案是否實際存在於磁碟（登錄但未下載者為 false）
  arch?: "sdxl" | "zimage" | "wan" | null;  // 圖像模型實際架構（即時偵測，檔名可能誤導）
  is_turbo?: boolean;
}

export interface CategoryModels {
  active: string | null;
  models: ModelInfo[];
}

export interface LLMModels {
  chat: string | null;
  analysis: string | null;
  models: ModelInfo[];
}

export interface AllModels {
  tts: CategoryModels;
  image: CategoryModels;
  llm: LLMModels;
}

export interface ExtraFile {
  name: string;
  type: "VAE" | "Text Encoder" | string;
  download_url: string;
  size_bytes: number;
}

export interface ProbeResult {
  source: "hf_repo" | "hf_file" | "civitai" | "direct";
  category: "tts" | "image" | "llm" | null;
  name: string;
  repo: string | null;
  filename: string | null;
  download_url: string;
  extra_files?: ExtraFile[];
}

export interface DownloadTask {
  task_id: string;
  status: "running" | "done" | "error" | "cancelled";
  progress: number;
  total: number;
  downloaded: number;
  speed: number;
  label: string;
  error: string | null;
  result: { model_id: string; local_path: string; size_bytes: number } | null;
  name: string;
  category: string;
}

// ─── API functions ────────────────────────────────────────────────────────────

export async function scanLocalModels(): Promise<{ added: number; message: string }> {
  const res = await fetch(`${BASE_URL}/v1/models/scan`, { method: "POST" });
  if (!res.ok) throw new Error("掃描本機模型失敗");
  return res.json();
}

export async function getAllModels(): Promise<AllModels> {
  const res = await fetch(`${BASE_URL}/v1/models/`);
  if (!res.ok) throw new Error("取得模型列表失敗");
  return res.json();
}

export async function probeUrl(url: string): Promise<ProbeResult> {
  const res = await fetch(`${BASE_URL}/v1/models/probe`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "連結偵測失敗");
  }
  return res.json();
}

export async function startDownload(
  url: string,
  category: string,
  name: string,
  role: string = "chat"
): Promise<string> {
  const res = await fetch(`${BASE_URL}/v1/models/download`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, category, name, role }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "啟動下載失敗");
  }
  const data = await res.json();
  return data.task_id;
}

export function subscribeDownloadProgress(
  taskId: string,
  onUpdate: (task: DownloadTask) => void,
  onDone: () => void
): () => void {
  const es = new EventSource(`${BASE_URL}/v1/models/download/${taskId}`);
  es.onmessage = (e) => {
    const task: DownloadTask = JSON.parse(e.data);
    onUpdate(task);
    if (["done", "error", "cancelled"].includes(task.status)) {
      es.close();
      onDone();
    }
  };
  es.onerror = () => { es.close(); onDone(); };
  return () => es.close();
}

export async function cancelDownload(taskId: string): Promise<void> {
  await fetch(`${BASE_URL}/v1/models/download/${taskId}`, { method: "DELETE" });
}

export async function activateModel(
  category: string,
  modelId: string,
  role: string = "default"
): Promise<void> {
  const res = await fetch(`${BASE_URL}/v1/models/${category}/activate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model_id: modelId, role }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "切換模型失敗");
  }
}

export async function patchModel(
  category: string,
  modelId: string,
  patch: { style?: string | null },
): Promise<void> {
  const res = await fetch(`${BASE_URL}/v1/models/${category}/${modelId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "更新模型屬性失敗");
  }
}

export async function deleteModel(category: string, modelId: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/v1/models/${category}/${modelId}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "刪除模型失敗");
  }
}

export async function getCivitaiToken(): Promise<{ set: boolean; preview: string }> {
  const res = await fetch(`${BASE_URL}/v1/models/civitai-token`);
  if (!res.ok) return { set: false, preview: "" };
  return res.json();
}

export async function setCivitaiToken(token: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/v1/models/civitai-token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
  if (!res.ok) throw new Error("儲存 Token 失敗");
}

// ─── LLM 全域取樣設定 ──────────────────────────────────────────────────────────

export interface LLMSettings {
  override_enabled: boolean;
  temperature: number;
  top_p: number;
  top_k: number;
  repeat_penalty: number;
  max_tokens: number | null;
}

export async function getLLMSettings(): Promise<LLMSettings> {
  const res = await fetch(`${BASE_URL}/v1/llm/settings`);
  if (!res.ok) throw new Error("取得 LLM 設定失敗");
  return res.json();
}

export async function patchLLMSettings(patch: Partial<LLMSettings>): Promise<void> {
  const res = await fetch(`${BASE_URL}/v1/llm/settings`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "更新 LLM 設定失敗");
  }
}

export function formatBytes(bytes: number): string {
  if (!bytes) return "—";
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

export function formatSpeed(bytesPerSec: number): string {
  if (!bytesPerSec) return "";
  return `${formatBytes(bytesPerSec)}/s`;
}
