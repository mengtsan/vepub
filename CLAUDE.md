# vepub — 開發說明

## 啟動服務

```powershell
npm run dev
```

在**單一視窗**用 `concurrently` 同時啟動：

| 服務 | 指令 | 位址 |
|------|------|------|
| Backend (FastAPI) | `uv run uvicorn main:app --reload --port 8765` | http://127.0.0.1:8765 |
| Frontend (Tauri + Vite) | `npm run tauri dev` | http://localhost:5173（dev） |

如果出現 `Port 5173 is already in use`，表示有殘留行程，執行後再重試：

```powershell
Get-NetTCPConnection -LocalPort 5173,8765 -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
```

## 專案結構

```
vepub/
├── backend/              FastAPI 後端
│   ├── main.py
│   ├── routers/
│   │   ├── epub.py       書籍、章節、進度、書籤 API
│   │   ├── tts.py        語音合成 API
│   │   └── illustration.py  插圖生成 API
│   └── services/
│       ├── epub_parser.py
│       ├── tts_engine.py     OmniVoice TTS
│       └── illustration_engine.py  Z-Image pipeline
├── apps/desktop/         Tauri + React 前端
│   └── src/
│       ├── pages/        Reader.tsx、Library.tsx
│       ├── components/reader/
│       └── stores/       reader.ts、player.ts
└── package.json          根目錄，`npm run dev` 入口
```

## 環境

| 項目 | 值 |
|------|----|
| GPU | NVIDIA GeForce RTX 5090 Laptop GPU |
| VRAM | 25.7 GB |
| Backend port | 8765 |
