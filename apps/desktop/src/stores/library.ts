import { create } from "zustand";
import { getBooks, parseEpub, deleteBook, Book } from "@/lib/api";

interface LibraryState {
  books: Book[];
  isLoading: boolean;
  currentBook: Book | null;

  fetchBooks: () => Promise<void>;
  importBook: (file: File) => Promise<void>;
  removeBook: (bookId: string) => Promise<void>;
  selectBook: (book: Book | null) => void;
}

export const useLibraryStore = create<LibraryState>((set, get) => ({
  books: [],
  isLoading: false,
  currentBook: null,

  fetchBooks: async () => {
    set({ isLoading: true });
    try {
      const books = await getBooks();
      set({ books, isLoading: false });
    } catch (e) {
      console.error("載入書庫失敗:", e);
      set({ isLoading: false });
    }
  },

  importBook: async (file: File) => {
    set({ isLoading: true });
    try {
      // 呼叫後端 API 上傳並解析圖書，後端會自動寫入資料庫
      await parseEpub(file);
      // 重新載入書庫
      const books = await getBooks();
      set({ books, isLoading: false });
    } catch (e) {
      console.error("匯入圖書失敗:", e);
      set({ isLoading: false });
      throw e;
    }
  },

  removeBook: async (bookId: string) => {
    set({ isLoading: true });
    try {
      await deleteBook(bookId);
      // 重新載入書庫
      const books = await getBooks();
      const { currentBook } = get();
      // 如果被刪除的是目前選中的書，則將 currentBook 設為 null
      const nextCurrentBook = currentBook?.id === bookId ? null : currentBook;
      set({ books, currentBook: nextCurrentBook, isLoading: false });
    } catch (e) {
      console.error("刪除圖書失敗:", e);
      set({ isLoading: false });
      throw e;
    }
  },

  selectBook: (book) => set({ currentBook: book }),
}));
