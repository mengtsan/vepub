import { BACKEND_BASE_URL } from "./constants";
const BASE_URL = BACKEND_BASE_URL;

export interface Book {
  id: string;
  title: string;
  author: string | null;
  language: string;
  cover_base64: string | null;
  chapter_count: number;
  created_at: number;
  chapter_index: number | null;
  sentence_index: number | null;
  scroll_position: number | null;
}

export interface ChapterMeta {
  id: string;
  title: string;
  order: number;
  paragraph_count: number;
}

export interface ParseResult {
  book_id: string;
  duplicate?: boolean;
  meta: {
    title: string;
    author: string | null;
    language: string;
    cover_base64: string | null;
    chapter_count: number;
  };
  chapters: ChapterMeta[];
}

export interface Sentence {
  index: number;
  paragraph_index: number;
  text: string;
  char_start: number;
  char_end: number;
}

export interface HardwareInfo {
  platform: string;
  cpu: string;
  gpu: string | null;
  mlx_available: boolean;
  cuda_available: boolean;
  recommended_device: string;
  display_name: string;
  badge_color: string;
}

/**
 * 檢查後端健康狀態與硬體資訊。
 */
export async function getHardwareInfo(): Promise<HardwareInfo> {
  const res = await fetch(`${BASE_URL}/health`);
  if (!res.ok) throw new Error("無法連接至後端服務");
  const data = await res.json();
  return data.hardware;
}

/**
 * 上傳並解析 EPUB 電子書。
 */
export async function parseEpub(file: File): Promise<ParseResult> {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${BASE_URL}/epub/parse`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "解析 EPUB 檔案失敗");
  }

  return res.json();
}

/**
 * 取得書庫內所有書籍列表。
 */
export async function getBooks(): Promise<Book[]> {
  const res = await fetch(`${BASE_URL}/epub/books`);
  if (!res.ok) throw new Error("取得書庫失敗");
  return res.json();
}

/**
 * 刪除指定書籍。
 */
export async function deleteBook(bookId: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/epub/books/${bookId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("刪除書籍失敗");
}

/**
 * 取得指定章節切割後的句子清單。
 */
export async function getSentences(
  bookId: string,
  chapterId: string,
  paragraphs: string[],
  language: string = "zh"
): Promise<Sentence[]> {
  const res = await fetch(
    `${BASE_URL}/epub/${bookId}/chapter/${chapterId}/sentences?language=${language}`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(paragraphs),
    }
  );

  if (!res.ok) throw new Error("取得句子切割清單失敗");
  const data = await res.json();
  return data.sentences;
}

/**
 * 取得指定書籍的閱讀進度。
 */
export async function getProgress(
  bookId: string
): Promise<{ chapter_index: number; sentence_index: number; scroll_position: number }> {
  const res = await fetch(`${BASE_URL}/epub/${bookId}/progress`);
  if (!res.ok) throw new Error("取得閱讀進度失敗");
  return res.json();
}

/**
 * 儲存指定書籍的閱讀進度。
 */
export async function saveProgress(
  bookId: string,
  progress: { chapter_index: number; sentence_index: number; scroll_position: number }
): Promise<void> {
  const res = await fetch(`${BASE_URL}/epub/${bookId}/progress`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      chapter_index: progress.chapter_index,
      sentence_index: progress.sentence_index,
      scroll_position: progress.scroll_position,
    }),
  });
  if (!res.ok) throw new Error("儲存閱讀進度失敗");
}

/**
 * 取得使用者設定。
 */
export async function getSettings(): Promise<Record<string, string>> {
  const res = await fetch(`${BASE_URL}/epub/settings`);
  if (!res.ok) throw new Error("取得設定值失敗");
  return res.json();
}

/**
 * 儲存或更新使用者設定。
 */
export async function saveSettings(settings: Record<string, string>): Promise<void> {
  const res = await fetch(`${BASE_URL}/epub/settings`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(settings),
  });
  if (!res.ok) throw new Error("儲存設定值失敗");
}

/**
 * 取得指定書籍的章節列表。
 */
export async function getBookChapters(bookId: string): Promise<ChapterMeta[]> {
  const res = await fetch(`${BASE_URL}/epub/${bookId}/chapters`);
  if (!res.ok) throw new Error("取得書籍章節列表失敗");
  return res.json();
}

/**
 * 取得指定章節的段落文字內容。
 */
export async function getChapterParagraphs(bookId: string, chapterId: string): Promise<string[]> {
  const res = await fetch(`${BASE_URL}/epub/${bookId}/chapter/${chapterId}/paragraphs`);
  if (!res.ok) throw new Error("取得章節段落內容失敗");
  const data = await res.json();
  return data.paragraphs;
}

export interface Bookmark {
  id: number;
  chapter_index: number;
  sentence_index: number;
  note: string;
  created_at: number;
}

/**
 * 取得指定書籍的所有書籤。
 */
export async function getBookmarks(bookId: string): Promise<Bookmark[]> {
  const res = await fetch(`${BASE_URL}/epub/${bookId}/bookmarks`);
  if (!res.ok) throw new Error("取得書籤失敗");
  return res.json();
}

/**
 * 新增書籤。
 */
export async function createBookmark(
  bookId: string,
  chapterIndex: number,
  sentenceIndex: number,
  note: string = ""
): Promise<{ id: number }> {
  const res = await fetch(`${BASE_URL}/epub/${bookId}/bookmarks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chapter_index: chapterIndex, sentence_index: sentenceIndex, note }),
  });
  if (!res.ok) throw new Error("新增書籤失敗");
  return res.json();
}

/**
 * 刪除書籤。
 */
export async function deleteBookmark(bookId: string, bookmarkId: number): Promise<void> {
  const res = await fetch(`${BASE_URL}/epub/${bookId}/bookmarks/${bookmarkId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("刪除書籤失敗");
}

// ─── 插圖 API ────────────────────────────────────────────────────────────────

export interface CharacterImage {
  id: number;
  angle: string;        // 正面/側面/半身/全身/其他
  is_primary: number;   // 1 = primary
  created_at: number;
  prompt?: string | null;
}

export interface Character {
  id: number;
  name: string;
  // ── 基本 ──
  gender: string | null;
  age_hint: string | null;
  // ── 面部特徵 ──
  skin_tone: string | null;
  face_shape: string | null;
  hair_color: string | null;
  hair_style: string | null;
  eye_color: string | null;
  eye_shape: string | null;
  // ── 體型 ──
  body_type: string | null;
  height_cm: number | null;
  weight_kg: number | null;
  bwh: string | null;
  cup_size: string | null;
  // ── 服飾配件 ──
  era_style: string | null;
  signature_outfit: string | null;
  color_palette: string | null;
  accessories: string | null;
  // ── 特殊特徵 ──
  distinctive_marks: string | null;
  special_traits: string | null;
  other_features: string | null;
  // ── 系統 ──
  character_seed: number;
  locked: number;
  // ── 相容舊版 ──
  description: string;
  ref_image_base64: string | null;
  // ── 後端組合 ──
  primary_image_url: string | null;
  images: CharacterImage[];
  created_at: number;
}

export async function getIllustrationStatus(): Promise<{ llm_available: boolean; llm_model: string | null; model_loaded: boolean }> {
  const res = await fetch(`${BASE_URL}/illustration/status`);
  if (!res.ok) return { llm_available: false, llm_model: null, model_loaded: false };
  return res.json();
}

export async function preloadIllustrationModel(): Promise<void> {
  await fetch(`${BASE_URL}/illustration/load`, { method: "POST" });
}

export async function unloadIllustrationModel(): Promise<void> {
  await fetch(`${BASE_URL}/illustration/unload`, { method: "POST" });
}

export interface IllustrationMeta {
  model_name?: string;
  steps?: number;
  guidance_scale?: number;
  seed?: number;
  width?: number;
  height?: number;
  is_anime?: boolean;
}

export interface IllustrationTaskResult extends IllustrationMeta {
  id: number | null;
  image_url?: string | null;
  image_base64?: string | null;
  prompt: string;
}

export interface TimingEntry {
  pct: number;
  label: string;
  ts: number;  // Unix timestamp (seconds, float)
}

export interface IllustrationTask {
  task_id: string;
  status: "pending" | "running" | "done" | "error";
  progress: number;
  label: string;
  sentence_index: number;
  chapter_index: number;
  book_id: string;
  timings: TimingEntry[];
  result: IllustrationTaskResult | null;
  error: string | null;
}

export async function generateIllustration(params: {
  text?: string;
  direct_prompt?: string;
  character_name?: string;
  book_id?: string;
  chapter_index?: number;
  sentence_index?: number;
  width?: number;
  height?: number;
  seed?: number;
  prompt_prefix?: string;
}): Promise<{ task_id: string; queue_position: number }> {
  const res = await fetch(`${BASE_URL}/illustration/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "生圖失敗");
  }
  return res.json();
}

export async function getIllustrationProgress(): Promise<IllustrationTask[]> {
  const res = await fetch(`${BASE_URL}/illustration/progress`);
  if (!res.ok) return [];
  return res.json();
}

export interface IllustrationEngineSettings {
  steps: number;
  guidance_scale: number;
  width: number;
  height: number;
  sheet_width: number;
  sheet_height: number;
  turbo_override: boolean;
  prompt_prefix: string;
  ip_adapter_scale: number;
  hires_fix_enabled: boolean;
  hires_upscale: number;
  hires_denoise: number;
  adetailer_enabled: boolean;
  adetailer_denoise: number;
  active_loras: { filename: string; weight: number; enabled: boolean }[];
  active_embeddings: string[];
  active_vae: string;
  single_model_mode: boolean;
  negative_prompt: string;
}

export interface LoraInfo {
  filename: string;
  size_mb: number;
}

export async function listLoras(): Promise<LoraInfo[]> {
  const res = await fetch(`${BASE_URL}/illustration/loras`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.loras ?? [];
}

export async function listEmbeddings(): Promise<LoraInfo[]> {
  const res = await fetch(`${BASE_URL}/illustration/embeddings`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.embeddings ?? [];
}

export async function listVaes(): Promise<LoraInfo[]> {
  const res = await fetch(`${BASE_URL}/illustration/vaes`);
  if (!res.ok) return [];
  const data = await res.json();
  return data.vaes ?? [];
}

export async function getIllustrationSettings(): Promise<IllustrationEngineSettings> {
  const res = await fetch(`${BASE_URL}/illustration/settings`);
  if (!res.ok) throw new Error("取得繪圖設定失敗");
  return res.json();
}

export async function patchIllustrationSettings(patch: Partial<IllustrationEngineSettings>): Promise<void> {
  await fetch(`${BASE_URL}/illustration/settings`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

export async function getChapterIllustrations(bookId: string, chapterIndex: number): Promise<
  Array<{ id: number; sentence_index: number; prompt: string; image_url: string } & IllustrationMeta>
> {
  const res = await fetch(`${BASE_URL}/illustration/list/${bookId}/${chapterIndex}`);
  if (!res.ok) throw new Error("取得章節插圖失敗");
  return res.json();
}

export async function deleteIllustration(illustrationId: number): Promise<void> {
  await fetch(`${BASE_URL}/illustration/item/${illustrationId}`, { method: "DELETE" });
}

export async function extractCharacterFeatures(
  bookId: string,
  text: string,
): Promise<Partial<Character>[]> {
  const res = await fetch(`${BASE_URL}/illustration/extract_character`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, book_id: bookId }),
  });
  if (!res.ok) throw new Error("提取角色特徵失敗");
  return res.json();
}

export async function getCharacters(bookId: string): Promise<Character[]> {
  const res = await fetch(`${BASE_URL}/illustration/characters/${bookId}`);
  if (!res.ok) throw new Error("取得角色庫失敗");
  return res.json();
}

export async function upsertCharacter(bookId: string, char: Partial<Character> & { name: string }): Promise<void> {
  const res = await fetch(`${BASE_URL}/illustration/characters/${bookId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(char),
  });
  if (!res.ok) throw new Error("儲存角色失敗");
}

export async function addCharacterImage(bookId: string, name: string, body: {
  image_base64: string;
  angle: string;
  is_primary?: boolean;
}): Promise<{ id: number }> {
  const res = await fetch(
    `${BASE_URL}/illustration/characters/${bookId}/images?name=${encodeURIComponent(name)}`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
  );
  if (!res.ok) throw new Error("新增角色圖片失敗");
  return res.json();
}

export async function deleteCharacterImage(bookId: string, _name: string, imgId: number): Promise<void> {
  await fetch(
    `${BASE_URL}/illustration/characters/${bookId}/image/${imgId}`,
    { method: "DELETE" }
  );
}

export async function setPrimaryCharacterImage(bookId: string, _name: string, imgId: number): Promise<void> {
  await fetch(
    `${BASE_URL}/illustration/characters/${bookId}/set_primary/${imgId}`,
    { method: "POST" }
  );
}

export async function getCharacterImage(bookId: string, _name: string, imgId: number): Promise<{ image_url: string; angle: string }> {
  const res = await fetch(
    `${BASE_URL}/illustration/characters/${bookId}/image/${imgId}`
  );
  if (!res.ok) throw new Error("取得圖片失敗");
  return res.json();
}

export function charImageUrl(imgId: number): string {
  return `${BASE_URL}/illustration/char-image/${imgId}`;
}

export function illustrationImageUrl(illustrationId: number): string {
  return `${BASE_URL}/illustration/image/${illustrationId}`;
}

export async function deleteCharacter(bookId: string, name: string): Promise<void> {
  const res = await fetch(
    `${BASE_URL}/illustration/characters/${bookId}?name=${encodeURIComponent(name)}`,
    { method: "DELETE" }
  );
  if (!res.ok) throw new Error("刪除角色失敗");
}

// ─── 角色去重合併 ─────────────────────────────────────────────────────────────

export interface DedupResult {
  merged: number;
  groups: { canonical: string; aliases: string[] }[];
}

export async function fillCharacterDefaults(bookId: string): Promise<{ updated: number; total: number }> {
  const res = await fetch(
    `${BASE_URL}/illustration/characters/${bookId}/fill_defaults`,
    { method: "POST" }
  );
  if (!res.ok) throw new Error("補完欄位失敗");
  return res.json();
}

export async function batchDeleteCharacters(bookId: string, names: string[]): Promise<{ deleted: number }> {
  const res = await fetch(
    `${BASE_URL}/illustration/characters/${bookId}/batch_delete`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ names }),
    }
  );
  if (!res.ok) throw new Error("批次刪除失敗");
  return res.json();
}

export async function dedupCharacters(bookId: string): Promise<DedupResult> {
  const res = await fetch(
    `${BASE_URL}/illustration/characters/${bookId}/dedup`,
    { method: "POST" }
  );
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "整理失敗");
  }
  return res.json();
}

// ─── 全書角色分析 ─────────────────────────────────────────────────────────────

export interface AnalysisJob {
  status: "pending" | "running" | "done" | "error";
  progress: number;
  label: string;
  result: { added: number; total: number } | null;
  error: string | null;
}

export async function analyzeCharacters(
  bookId: string,
  opts?: { maxChapters?: number; restart?: boolean }
): Promise<void> {
  const url = new URL(`${BASE_URL}/illustration/analyze_characters/${bookId}`);
  if (opts?.maxChapters && opts.maxChapters > 0) {
    url.searchParams.set("max_chapters", String(opts.maxChapters));
  }
  if (opts?.restart) {
    url.searchParams.set("restart", "true");
  }
  const res = await fetch(url.toString(), { method: "POST" });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "啟動分析失敗");
  }
}

export async function getAnalysisStatus(bookId: string): Promise<AnalysisJob | null> {
  const res = await fetch(`${BASE_URL}/illustration/analyze_characters/${bookId}/status`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error("取得分析狀態失敗");
  return res.json();
}

export async function getAnalysisCheckpoint(
  bookId: string
): Promise<{ completed_chapters: number[]; count: number }> {
  const res = await fetch(
    `${BASE_URL}/illustration/analyze_characters/${bookId}/checkpoint`
  );
  if (!res.ok) return { completed_chapters: [], count: 0 };
  return res.json();
}

// ─── 多視角批次生圖 ───────────────────────────────────────────────────────────

export interface AngleJob {
  status: "pending" | "running" | "done" | "error";
  progress: number;
  label: string;
  done: number;
  total: number;
  error: string | null;
}

export async function generateCharacterAngles(
  bookId: string,
  name: string,
  width?: number,
  height?: number,
  promptPrefix?: string,
): Promise<{ job_id: string }> {
  const res = await fetch(
    `${BASE_URL}/illustration/characters/${bookId}/generate_angles`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        ...(width        ? { width }         : {}),
        ...(height       ? { height }        : {}),
        ...(promptPrefix !== undefined ? { prompt_prefix: promptPrefix } : {}),
      }),
    }
  );
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "生成多視角失敗");
  }
  return res.json();
}

export async function getAngleJobStatus(jobId: string): Promise<AngleJob | null> {
  const res = await fetch(`${BASE_URL}/illustration/angle_jobs/${jobId}`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error("取得生成狀態失敗");
  return res.json();
}

export interface ModelStatus {
  id: string;
  name: string;
  type: string;
  size_str: string;
  status: "not_downloaded" | "downloading" | "downloaded";
  progress: number;
  active: boolean;
  loaded: boolean;   // 是否已載入至 TTS 引擎記憶體中
  error: string | null;
}

/**
 * 取得所有模型狀態列表。
 */
export async function getModelsStatus(): Promise<ModelStatus[]> {
  const res = await fetch(`${BASE_URL}/v1/models/status`);
  if (!res.ok) throw new Error("取得模型狀態失敗");
  const data = await res.json();
  return data.models;
}

/**
 * 發起模型下載。
 */
export async function downloadModel(modelId: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/v1/models/download`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ model_id: modelId }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "啟動模型下載失敗");
  }
}

/**
 * 刪除模型檔案（若正在下載中則自動取消下載）。
 */
export async function deleteModel(modelId: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/v1/models/delete`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ model_id: modelId }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "刪除模型失敗");
  }
}

/**
 * 設定啟用的模型（僅更新資料庫設定，不立即切換引擎）。
 */
export async function selectModel(modelId: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/v1/models/select`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ model_id: modelId }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "切換啟用模型失敗");
  }
}

/**
 * 動態載入指定模型至 TTS 引擎記憶體（會先卸載當前模型再載入）。
 * 注意：此為長時間操作，需等待後端完成模型載入。
 */
export async function loadModel(modelId: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/v1/models/load`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ model_id: modelId }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "載入模型至引擎失敗");
  }
}

/**
 * 從 TTS 引擎記憶體中卸載目前載入的模型，釋放資源。
 */
export async function unloadModel(): Promise<void> {
  const res = await fetch(`${BASE_URL}/v1/models/unload`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({}),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "卸載模型失敗");
  }
}

