import React, { useEffect, useState, useRef } from "react";
import { useRouter } from "@tanstack/react-router";
import { useLibraryStore } from "@/stores/library";
import { useReaderStore } from "@/stores/reader";
import { Plus, Search, Trash2, Loader, Book as BookIcon } from "lucide-react";
import { Book } from "@/lib/api";

export default function Library() {
  const router = useRouter();
  const { books, isLoading, fetchBooks, importBook, removeBook, selectBook } = useLibraryStore();
  const { loadSettings, fetchHardwareInfo } = useReaderStore();
  const [searchQuery, setSearchQuery] = useState("");
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // 初始化載入書庫與硬體狀態
  useEffect(() => {
    fetchBooks();
    loadSettings();
    fetchHardwareInfo();
  }, [fetchBooks, loadSettings, fetchHardwareInfo]);

  // 篩選書籍
  const filteredBooks = books.filter((book) => {
    const query = searchQuery.toLowerCase();
    return (
      book.title.toLowerCase().includes(query) ||
      (book.author && book.author.toLowerCase().includes(query))
    );
  });

  // 處理點選書籍
  const handleSelectBook = (book: Book) => {
    selectBook(book);
    router.navigate({ to: "/reader" });
  };

  // 處理刪除書籍
  const handleDeleteBook = async (e: React.MouseEvent, bookId: string) => {
    e.stopPropagation();
    if (confirm("您確定要將這本書自書庫中刪除嗎？檔案也將一併移除。")) {
      try {
        await removeBook(bookId);
      } catch (err) {
        alert("刪除書籍失敗");
      }
    }
  };

  // 處理檔案選擇匯入
  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      try {
        await importBook(files[0]);
      } catch (err) {
        alert("匯入書籍失敗，請確認檔案格式是否正確。");
      }
    }
  };

  // 處理拖放檔案匯入
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const files = Array.from(e.dataTransfer.files);
    const epubFile = files.find((file) => file.name.endsWith(".epub"));
    if (epubFile) {
      try {
        await importBook(epubFile);
      } catch (err) {
        alert("拖放匯入書籍失敗，請確認檔案格式是否正確。");
      }
    } else {
      alert("僅支援匯入 .epub 格式的電子書！");
    }
  };

  return (
    <div
      className={`min-h-screen p-8 transition-colors duration-300 ${
        isDragging ? "bg-opacity-50 border-4 border-dashed border-amber-500" : ""
      }`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      style={{ backgroundColor: "var(--bg-primary)", color: "var(--text-primary)" }}
    >
      {/* 隱藏的 File Input */}
      <input
        type="file"
        ref={fileInputRef}
        onChange={handleFileChange}
        accept=".epub"
        className="hidden"
      />

      {/* 頂部導航列 (高 56px) */}
      <header className="flex justify-between items-center h-14 border-b mb-8" style={{ borderColor: "var(--border)" }}>
        <div className="flex items-center gap-2">
          <BookIcon className="text-amber-500" size={24} />
          <h1 className="text-xl font-bold tracking-wider">EPUB TTS Reader</h1>
        </div>

        <div className="flex items-center gap-4">
          {/* 搜尋欄 */}
          <div className="relative flex items-center">
            <Search className="absolute left-3 text-gray-500" size={16} />
            <input
              type="text"
              placeholder="搜尋書名或作者..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9 pr-4 py-1.5 rounded-full text-sm outline-none transition-all w-48 focus:w-64"
              style={{
                backgroundColor: "var(--bg-surface)",
                border: "1px solid var(--border)",
                color: "var(--text-primary)",
              }}
            />
          </div>

          {/* 匯入按鈕 */}
          <button
            onClick={() => fileInputRef.current?.click()}
            className="flex items-center gap-1.5 px-4 py-1.5 rounded-full text-sm font-semibold transition-all hover:brightness-110 active:scale-95"
            style={{ backgroundColor: "var(--accent)", color: "#000" }}
          >
            <Plus size={16} />
            匯入書籍
          </button>
        </div>
      </header>

      {/* 載入中狀態 */}
      {isLoading && (
        <div className="fixed inset-0 flex flex-col items-center justify-center bg-black/40 backdrop-blur-sm z-50">
          <Loader className="animate-spin text-amber-500 mb-2" size={36} />
          <p className="text-sm tracking-widest text-amber-500">正在解析書籍，請稍候...</p>
        </div>
      )}

      {/* 拖放提示遮罩 */}
      {isDragging && (
        <div className="fixed inset-0 flex items-center justify-center bg-amber-500/10 pointer-events-none z-40">
          <div className="bg-black/85 px-8 py-6 rounded-2xl border border-amber-500/40 text-center shadow-2xl">
            <Plus className="mx-auto text-amber-500 mb-2 animate-bounce" size={48} />
            <p className="text-lg font-bold text-amber-500">拖放到任意處以匯入 EPUB 書籍</p>
          </div>
        </div>
      )}

      {/* 書籍格狀區塊 */}
      {filteredBooks.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <BookIcon className="text-gray-600 mb-4" size={64} />
          <p className="text-lg font-semibold" style={{ color: "var(--text-secondary)" }}>
            {searchQuery ? "沒有符合搜尋條件的書籍" : "書庫空空如也"}
          </p>
          {!searchQuery && (
            <p className="text-sm mt-1" style={{ color: "var(--text-muted)" }}>
              點選右上角按鈕，或拖放 .epub 檔案到此處來新增書籍。
            </p>
          )}
        </div>
      ) : (
        <main className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-8 justify-items-center">
          {filteredBooks.map((book) => {
            // 計算閱讀百分比
            const totalCh = book.chapter_count || 1;
            const currentCh = book.chapter_index || 0;
            const progressPercent = Math.min(Math.round((currentCh / totalCh) * 100), 100);

            return (
              <div
                key={book.id}
                onClick={() => handleSelectBook(book)}
                className="group relative w-[160px] cursor-pointer flex flex-col transition-all duration-300 hover:-translate-y-1"
              >
                {/* 封面區 (寬 160px, 高 220px, 3:4 比例) */}
                <div
                  className="relative w-full h-[220px] rounded-lg overflow-hidden shadow-md group-hover:shadow-2xl transition-all duration-300 border"
                  style={{
                    backgroundColor: "var(--bg-surface)",
                    borderColor: "var(--border)",
                  }}
                >
                  {book.cover_base64 ? (
                    <img
                      src={`data:image/png;base64,${book.cover_base64}`}
                      alt={book.title}
                      className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105"
                    />
                  ) : (
                    <div className="w-full h-full flex flex-col items-center justify-center p-4 text-center">
                      <div
                        className="w-12 h-12 rounded-full flex items-center justify-center mb-3 text-lg font-bold"
                        style={{ backgroundColor: "var(--bg-hover)", color: "var(--accent)" }}
                      >
                        {book.title.trim().charAt(0)}
                      </div>
                      <span className="text-xs font-semibold px-2 line-clamp-3 leading-relaxed">
                        {book.title}
                      </span>
                    </div>
                  )}

                  {/* 懸浮垃圾桶刪除按鈕 */}
                  <button
                    onClick={(e) => handleDeleteBook(e, book.id)}
                    className="absolute top-2 right-2 p-1.5 rounded-full bg-black/60 text-red-400 opacity-0 group-hover:opacity-100 hover:bg-black/90 active:scale-90 transition-all z-10"
                    title="刪除此書"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>

                {/* 資訊區 */}
                <div className="mt-3 flex flex-col">
                  {/* 書名 (14px 500weight, 最多 2 行) */}
                  <h3
                    className="text-sm font-medium line-clamp-2 leading-snug group-hover:text-amber-500 transition-colors"
                    style={{ color: "var(--text-primary)" }}
                  >
                    {book.title}
                  </h3>

                  {/* 作者 (12px) */}
                  <span
                    className="text-xs mt-1 truncate"
                    style={{ color: "var(--text-secondary)" }}
                  >
                    {book.author || "未知作者"}
                  </span>

                  {/* 進度條 (高 4px) */}
                  <div className="mt-3 w-full flex flex-col gap-1">
                    <div
                      className="w-full h-1 rounded-full overflow-hidden"
                      style={{ backgroundColor: "var(--bg-hover)" }}
                    >
                      <div
                        className="h-full rounded-full transition-all duration-500"
                        style={{
                          backgroundColor: "var(--accent)",
                          width: `${progressPercent}%`,
                        }}
                      />
                    </div>
                    <div className="flex justify-between items-center text-[10px]" style={{ color: "var(--text-muted)" }}>
                      <span>讀了 {progressPercent}%</span>
                      <span>{book.chapter_count} 章</span>
                    </div>
                  </div>
                </div>
              </div>
            );
          })}

          {/* 快捷匯入虛線卡片 */}
          <div
            onClick={() => fileInputRef.current?.click()}
            className="w-[160px] h-[220px] rounded-lg border-2 border-dashed flex flex-col items-center justify-center cursor-pointer transition-all hover:bg-white/5 active:scale-95"
            style={{ borderColor: "var(--border)" }}
          >
            <Plus className="text-gray-500 mb-2 group-hover:text-amber-500" size={32} />
            <span className="text-xs" style={{ color: "var(--text-secondary)" }}>匯入電子書</span>
          </div>
        </main>
      )}
    </div>
  );
}
