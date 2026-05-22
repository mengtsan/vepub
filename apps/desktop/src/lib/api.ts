const BASE_URL = "http://127.0.0.1:8765";

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
  meta: {
    title: string;
    author: string | null;
    language: string;
    cover_base64: string | null;
    chapter_count: number;
  };
  chapters: ChapterMeta[];
  _chapters_data: {
    id: string;
    paragraphs: string[];
  }[];
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
