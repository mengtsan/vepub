# vepub 優化建議書

> 建立日期：2026-06-10
> 範圍：全專案（backend FastAPI / apps/desktop Tauri+React / 工程品質 / 打包發布）
> 性質：僅分析與建議，不含程式修改
> 依據：現行程式碼逐檔審閱 + DEVLOG.md / plan.md 歷史脈絡

---

## 0. 總覽

專案功能已相當完整（書庫、TTS 串流朗讀、句子高亮、全書角色分析、雙模型插圖生成、角色庫）。
本文件聚焦在四類問題：

| 類別 | 重點 |
|------|------|
| **P0 效能熱點** | 使用者每天感受到的延遲，多數可低成本修復 |
| **P1 正確性/穩定性** | 已存在的 bug 或在特定條件下會出錯的設計 |
| **P2 資料/架構/前端** | 長期維護成本與資料膨脹 |
| **P3 工程品質/發布** | 測試、CI、logging、打包 |

### 十大優先項目速覽

| # | 項目 | 等級 | 預估工作量 |
|---|------|------|-----------|
| 1 | spaCy 模型每次切句請求都重新載入 | P0 | 小 |
| 2 | 每句 TTS 合成都做 GPU 鎖 + `gc.collect()` + `empty_cache()` | P0 | 小 |
| 3 | LLM server 每次請求冷啟動（27B 載入數十秒） | P0 | 中 |
| 4 | 生圖期間 TTS 朗讀被全域互斥鎖完全阻塞 | P0 | 中 |
| 5 | `useAudioStream` 疑似每句自動前進都重建 WebSocket（需驗證） | P0 | 小–中 |
| 6 | TTS 為「假串流」：整句合成完才開始送 chunk | P0 | 中–大 |
| 7 | base64 圖片全部存 SQLite，列表 API 整批回傳 | P2 | 中 |
| 8 | `get_chapter_paragraphs` 的 404 被外層 except 轉成 500 | P1 | 小 |
| 9 | 同步 SQLite / 檔案 IO 直接跑在 async event loop 上 | P1 | 中 |
| 10 | `print` 取代 logging、巨型檔案（illustration.py 1174 行）拆分 | P2 | 中 |

---

## 1. P0 — 效能熱點（使用者可直接感知）

### 1.1 spaCy 模型每次請求重新載入

**位置**：`backend/routers/epub.py:247`、`backend/services/text_chunker.py:49-71`

每次呼叫 `POST /{book_id}/chapter/{chapter_id}/sentences`（= 每次翻章）都會 `TextChunker(language=...)` → `spacy.load("zh_core_web_sm")`。spaCy 模型載入需數百 ms 到秒級，且每次都重新配置記憶體。

**建議**：在 `text_chunker.py` 以模組級 dict 快取 `{language: nlp}`，`_load_nlp` 先查快取。一行改動即可讓翻章延遲明顯下降。

### 1.2 每句 TTS 合成都執行完整 GC 與 CUDA cache 清理

**位置**：`backend/services/tts_engine.py:229-238`、`backend/services/gpu_manager.py:46-57`

`synthesize_stream()` 每句話都 `acquire_gpu('tts')` → 合成 → `release_gpu()`，而 `release_gpu()` 內含 `gc.collect()` + `torch.cuda.empty_cache()`。連續朗讀時這兩個昂貴操作（empty_cache 會同步整個 CUDA stream）每句執行一次，直接拖慢句間銜接。

**建議**：
- GC / empty_cache 只在「模型卸載 / 任務型態切換」時執行，不要在每句釋放時執行。
- 更進一步：TTS 的 GPU 鎖提升到「朗讀 session」層級（WS 連線建立時 acquire、斷線時 release），而非每句 acquire。

### 1.3 LLM server 每次請求冷啟動

**位置**：`backend/services/llm_engine.py`（`expand_prompt` / `extract_character_features` / `find_alias_groups` / `infer_missing_fields`）

目前每次 LLM 推論都是「啟動 llama-server（27B，~15.7 GB 從磁碟載入，數十秒）→ 推理 → 關閉」。代價：

- **每生成一張插圖**都要冷啟動一次 27B（`expand_prompt`），再載入擴散模型。LLM 啟動時間經常超過實際推理時間。
- 「選取文字提取角色」這種互動操作也要等整個冷啟動。

**建議**（擇一或組合）：
1. **常駐 + idle TTL**：server 啟動後保留 N 分鐘（如 5 分鐘），期間請求直接複用；逾時或 GPU 仲裁需要空間時才關閉。與 `gpu_manager` 整合（LLM 視為一種可被踢除的駐留引擎）。
2. **prompt 擴寫降級用 4B**：expand_prompt 任務簡單，4B（~4 GB、載入快數倍）已足夠；27B 留給全書分析與別名去重。目前 `find_gguf()` 一律回傳最大模型。
3. 27B（15.7 GB）+ SDXL（8 GB）= 23.7 GB，理論上可在 25.7 GB 內共存，動畫風格生圖可考慮不卸載 LLM（需留 buffer 實測）。

### 1.4 生圖期間 TTS 朗讀被完全阻塞

**位置**：`backend/services/gpu_manager.py:19-44`

`tts` 與 `illustration` 共用同一把互斥鎖。插圖生成全程（模型載入 ~20s + 擴散 ~25s+）持鎖，期間每句 TTS 的 `acquire_gpu('tts')` 都會排隊 → **使用者邊聽邊生圖時，朗讀會停頓 40 秒以上**。

實際 VRAM：TTS ~4 GB + SDXL ~8 GB = 12 GB，遠低於 25.7 GB，兩者本可共存；只有 Z-Image（~21 GB）才真的需要互斥。先前已對 analysis（27B + TTS 共存）做過同樣的解鎖（DEVLOG 2026-06-02），同邏輯應延伸到 SDXL。

**建議**：把「task 型態互斥」改為「VRAM 預算仲裁」：每個引擎登錄估計用量（TTS 4 / SDXL 8 / Z-Image 21 / 27B 16），acquire 時檢查總和是否超過上限，超過才踢除或排隊。順帶解決：
- `analysis_active` busy-wait（`while ... sleep(3)`）改 `asyncio.Event`。
- `release_gpu()` 用 `try/except RuntimeError` 吞掉「未持鎖卻釋放」——改成 async context manager（`async with gpu_manager.use('tts')`）讓 acquire/release 成對且異常安全。

### 1.5 `useAudioStream`：自動前進疑似觸發每句重連（需驗證）

**位置**：`apps/desktop/src/hooks/useAudioStream.ts:183-302`

推理鏈：`connectAndPlay` 的 `useCallback` 依賴 `currentSentenceIndex`（L240）→ 每次自動高亮前進（`_setCurrentIndex`）都產生新的 callback identity → 第一個 `useEffect`（L261-279，deps 含 `connectAndPlay`）cleanup 會 `ws.close()` + `stopAllAudio()`，再重新 `connectAndPlay()`。

若推理成立，後果是：每句結束時關閉連線、丟棄已預取合成的句子、重新合成當前句 —— 預取機制（PREFETCH=3）形同失效，且句間會有合成延遲的空隙。`isAutoTickingRef` 防護只擋了第二個 effect（L282-302），擋不住第一個。

**建議**：
1. 先實測驗證（觀察後端 log：自動播放時是否每句都出現「連線已建立」）。
2. 修法：`connectAndPlay` 不直接依賴 `currentSentenceIndex`，改在 `onopen` 時從 `usePlayerStore.getState()` 讀當前 index（或用 ref），讓 callback identity 穩定；effect 1 的 deps 只留 `isPlaying`。

### 1.6 TTS 假串流：整句合成完才開始送

**位置**：`backend/services/tts_engine.py:228-247`

`synthesize_stream()` 先在 executor 中完成**整句**合成，拿到完整 numpy 後才切 200ms chunk「串流」。首句聽到聲音的延遲 = 整句合成時間（80 字 × 32 steps 可達數秒）。

**建議**：
- 短期：把預設 `num_step` 從 32 降為 16 作為串流模式預設（品質模式才用 32）；CPU 模式已有句長上限，CUDA 模式也可考慮縮短首句長度（首句切短、後句恢復）讓播放更快開始。
- 中期：若 OmniVoice 支援 chunk/streaming 推理（diffusion TTS 通常可分段 decode），改成真串流。不支援則維持句級 pipeline 即可（預取已能掩蓋後續延遲，重點是首句）。

---

## 2. P1 — 正確性與穩定性

### 2.1 `get_chapter_paragraphs`：404 被轉成 500

**位置**：`backend/routers/epub.py:213-232`

`raise HTTPException(404, "找不到指定章節")` 在 `try` 區塊內，會被外層 `except Exception` 捕獲並包成 500。
**建議**：`except Exception` 前加 `except HTTPException: raise`，或把 404 移出 try。

### 2.2 任務狀態全部 in-memory，dev reload / crash 即丟失

**位置**：`backend/routers/illustration.py:37-47`（`_tasks` / `_analysis_jobs` / `_angle_jobs`）

uvicorn `--reload` 觸發時（DEVLOG 已踩過）所有任務狀態消失，正在生圖的任務變成幽靈。前端雖有「重新整理後恢復任務」邏輯，但 reload 後後端本身就忘了。

**建議**：
- 至少把 `_analysis_jobs`（最長時間的任務）狀態寫入 SQLite（checkpoint 機制已存在，補一個 job 狀態表即可）。
- 完成任務的清理改用「時間戳 + 查詢時惰性清除」，取代 `await asyncio.sleep(60)` 佔住 background task 的寫法（`illustration.py:378-380, 974-976, 1111-1112`）。

### 2.3 同步 IO 阻塞 event loop

**位置**：所有 router（`epub.py`、`illustration.py` 全部端點）

- `sqlite3` 同步呼叫直接在 `async def` 端點執行。一般查詢很快，但 `list_illustrations` / `list_characters` 會撈出多張 MB 級 base64 TEXT，序列化期間 event loop 卡住 —— 此時 TTS WebSocket 的訊息收發也會卡。
- `parse_epub` 的 `shutil.copyfileobj`（`epub.py:44-45`）同步寫大檔。

**建議**：二擇一：(a) 全面改 `run_in_executor` 包 DB 操作（已有先例：epub 解析）；(b) 引入 `aiosqlite`。配合 §4.1（圖片移出 DB）後，剩餘查詢都很輕，方案 (a) 成本最低。

### 2.4 Schema migration 用 `try/except pass`

**位置**：`backend/routers/illustration.py:96-100, 132-136`

24 條 `ALTER TABLE` 逐條 try/except 吞掉**所有**錯誤——不只「欄位已存在」，連磁碟錯誤、語法錯誤也被吞。每次啟動都執行 24 次注定失敗的 SQL。

**建議**：建 `schema_version` 表（PRAGMA user_version 亦可），啟動時依版本跑增量 migration；或至少先 `PRAGMA table_info(characters)` 取得現有欄位，再只 ALTER 缺少者，並讓非預期錯誤浮出。

### 2.5 全書分析批次的 ctx 餘裕估算偏緊

**位置**：`backend/services/llm_engine.py:806`（`_BATCH_CHARS = 55_000`）、`get_llm_ctx` 預設 65536

中文在 Qwen 系 tokenizer 下約 1–1.6 token/字，55K 字可能達 55K–80K token，加上 system prompt 與 `max_tokens=3000` 輸出，**有機率超過 65536 ctx** 導致截斷（表現為某批角色品質莫名變差，難以察覺）。

**建議**：批次大小改以「估算 token」為準（保守用 1.5 token/字），或啟動 server 後呼叫 `/props` 取得實際 ctx 再動態決定批次；至少把 `_BATCH_CHARS` 降到 ~35K 留足餘裕。

### 2.6 `_kill_existing_server` 可能誤殺別人的行程

**位置**：`backend/services/llm_engine.py:100-113`

只要 port 18765 的 `/health` 有回應就 kill 佔用該 port 的 PID，未驗證行程身分。
**建議**：kill 前確認 `psutil.Process(pid).name()` 是 `llama-server.exe`，否則改報錯提示使用者。

### 2.7 EPUB 快取與封面解析

**位置**：`backend/services/epub_parser.py:248-253, 65-73`

- `invalidate_cache(filepath)` 註解寫「清除對應快取」，實作是 `cache_clear()` 清空全部 —— 刪一本書會讓其他書全部重新解析。建議自實作 dict 快取（路徑 → 結果）以支援單鍵失效，或維持現狀但修正註解。
- 封面只認 `get_item_with_id("cover-image")`，許多 EPUB 用 `<meta name="cover">` 或 `properties="cover-image"` 宣告，這些書封面會顯示不出來。建議補多種偵測路徑（metadata cover id → properties → 檔名啟發式）。
- BeautifulSoup 以 `"lxml"` 解析 XHTML 觸發 `XMLParsedAsHTMLWarning`（DEVLOG 已列）：改 `features="xml"`。
- `walk()` 為 Python 遞迴，極深 DOM 有 RecursionError 風險，可改顯式 stack（低優先）。

### 2.8 重複匯入無去重

`parse_epub` 對同一本書重複匯入會建立多筆記錄與多份檔案。建議以檔案 hash（sha256 前 16 bytes 即可）查重，命中時回傳既有 book_id。

---

## 3. P2 — 資料與儲存

### 3.1 base64 圖片存 SQLite（影響最大的資料問題）

**位置**：`illustrations.image_base64`、`character_images.image_base64`、`books.cover_base64`

- 1024×1024 PNG 約 1.5–2.5 MB，base64 再 +33%。一章生 10 張圖 = DB 增加 ~30 MB；library.db 會快速膨脹到 GB 級，備份、WAL checkpoint、任何全表查詢都被拖累。
- `GET /illustration/list/{book}/{chapter}` 與 `GET /epub/books` 一次回傳**所有**圖片/封面 base64，JSON 序列化 + 前端 `data:` URL 常駐 React state，記憶體雙倍佔用。

**建議**（一組配套改動）：
1. 圖片落地為檔案：`~/.epub-tts/images/{book_id}/{uuid}.png`，DB 只存相對路徑與 meta。
2. 新增 `GET /illustration/image/{id}` 以 `FileResponse` 供圖，加 `Cache-Control`，前端 `<img src="http://127.0.0.1:8765/...">` 由瀏覽器管快取與解碼。
3. 列表 API 只回 meta + 圖片 URL；`GET /epub/books` 的封面同理改縮圖檔案（匯入時產生一次 ~300px 縮圖）。
4. 一次性 migration：啟動時把既有 base64 倒出成檔案。

### 3.2 `/epub/parse` 回傳 `_chapters_data` 全書內文

**位置**：`backend/routers/epub.py:99-106`

匯入書籍的回應夾帶全書所有段落文字（一本小說可達數 MB JSON），但前端讀內文走的是 `GET /{book_id}/chapter/{id}/paragraphs`，這份資料疑似無人使用。**建議**：確認前端無引用後刪除此欄位。

### 3.3 缺索引

`illustrations(book_id, chapter_index)` 是高頻查詢卻無索引；`character_images(character_id)` 同理。資料量大後（§3.1 改善前尤其）會退化成全表掃描。**建議**：補 2–3 個複合索引。

### 3.4 設定儲存雙軌

繪圖設定存 `backend/illustration_settings.json`（`illustration_engine.py:46-83`），其他設定存 SQLite `settings` 表，且 `illustration_prompt_prefix` 又存在 settings 表（`illustration.py:1059-1064`）—— 三個來源。**建議**：統一收斂到 settings 表（或統一 JSON），單一讀寫介面。

---

## 4. P2 — 後端架構與可維護性

### 4.1 巨型檔案拆分

| 檔案 | 行數/大小 | 建議拆法 |
|------|----------|---------|
| `routers/illustration.py` | 1174 行 | 拆成 `illustration.py`（生圖任務）/ `characters.py`（角色 CRUD + 分析）/ `repository.py`（SQL 集中） |
| `services/llm_engine.py` | 1230 行 | 拆 `llm_server.py`（生命週期）/ `llm_tasks.py`（各推理任務）/ `char_schema.py`（schema、validation、defaults） |
| `services/illustration_engine.py` | 1015 行 | 拆 `pipelines/`（per-架構載入器，已有 backends/ 雛形未用上）/ `prompt_builder.py`（角色 fragment 與 keyword 表） |

`services/backends/` 已建立 protocol 抽象但只有 TTS 在用、image backend 在 `main.py` 固定為 `None`，`illustration.py` 裡每個端點都要 `if backend is not None: ... else: ...` 雙路徑。**建議**：把 `illustration_engine` 包成正式 backend 註冊進 `app.state.image`，刪除所有 fallback 分支。

### 4.2 effective steps/cfg 邏輯重複

**位置**：`illustration_engine.py:763-775`（`_generate_sync`）與 `955-965`（`generate_illustration` meta 計算）

同一套「turbo→8 步 CFG1 / zimage→28 步 CFG4 / wan→clamp」規則寫了兩份，已經出現過一次只改一邊的風險（meta 與實際參數可能不一致）。**建議**：抽 `resolve_effective_params(pipe, settings) -> (steps, cfg)` 單一來源，兩處共用。

### 4.3 print → logging

全後端以 `print` 輸出（含每句 TTS、每個 WS 訊息兩行 log）。**建議**：
- 改用 `logging`，模組級 logger，等級區分（DEBUG：WS 逐句、LLM raw；INFO：任務起迄；WARNING+：異常）。
- DEVLOG 已列的暫留 debug print（`llm_engine.py` 角色提取三行）順勢降為 DEBUG。

### 4.4 已知技術債（DEVLOG / plan.md 已列，集中追蹤）

| 項目 | 來源 |
|------|------|
| 角色識別仍用 substring match（`name in text`，代詞/暱稱漏偵測）→ 規劃以輕量 LLM NER 前置 | DEVLOG 06-07 |
| `build_character_fragment_en()` 丟棄 special_traits 等欄位的非關鍵字內容 | DEVLOG 06-07 |
| 角色 LoRA 訓練 pipeline（plan.md 階段 3，已驗證 ZImage LoRA 可載入） | plan.md |
| plan.md / 舊 DEVLOG 中 ControlNet、Florence2 等描述與現碼脫節 → 文件標註「已廢棄」 | plan.md §二 P5 |
| Tauri `lib.rs` 以相對路徑找 `backend/main.py` 失敗（見 §7.1） | DEVLOG 06-02 |

---

## 5. P2 — 前端

### 5.1 輪詢統一

目前三套各自為政的 polling：生圖任務 1s（Reader.tsx:241-283）、全書分析 2.5s、多視角 3s（CharacterPanel）。每套都有自己的 interval 管理、完成判定與清理。

**建議**：
- 短期：抽共用 `usePolling(fetcher, intervalMs, isActive)` hook，集中錯誤處理與 interval 生命週期。
- 中期：後端任務狀態改 SSE（FastAPI `EventSourceResponse`）單一事件流，前端一個 EventSource 訂閱所有任務，去掉全部輪詢。

### 5.2 渲染效能

- `Reader.tsx:443-449` 的 `paragraphsMap` 每次 render 重建（含每秒輪詢觸發的 render）。長章節（千句）時值得 `useMemo([sentences])`。
- 句子高亮變更會 re-render 整篇文章。可把段落抽成 `React.memo` 子元件，只有含當前句的段落重繪。
- 插圖 base64 存於 state、以 data URL 內嵌 —— 配合 §3.1 改成 URL 後，state 只剩輕量 meta，此問題自動消失。

### 5.3 元件拆分

`CharacterPanel.tsx`（38.5 KB）集角色列表、批次選取、分析任務、多視角任務、燈箱、排序搜尋於一身。建議拆出 `CharacterCard` / `AnalysisProgress` / `ImageLightbox` / `useAnalysisJob`，降低每次小改動的 regression 面積。

### 5.4 WS 協定缺 cancel / 序號

換句、暫停目前唯一手段是關閉整條 WebSocket（也是 §1.5 重連問題的根源之一）。**建議**：協定加 `{"type":"cancel"}` 與請求自帶遞增 `request_id`，後端丟棄過期請求的輸出，前端依 id 過濾遲到的 chunk —— 連線得以長存，跳轉只是改送新 id。

### 5.5 其他小項

- `api.ts` 後端位址 `127.0.0.1:8765` 硬編碼散落多處（含 useAudioStream 的 WS URL）——抽單一 `BASE_URL` 常數，為日後 port 可設定鋪路。
- `Library.tsx` 刪除書籍用原生 `confirm()`，與整體 UI 風格不符，可換成既有 modal 樣式。
- 音量目前只存在 GainNode（預設 0.8），重啟即失——納入 settings 持久化。

---

## 6. P3 — 工程品質

### 6.1 測試與 CI

- `test_e2e.py`（70 項）需要活的 server + 模型環境，屬於手動驗證腳本。建議補一層**不需 GPU 的純單元測試**（pytest）：`_parse_character_json`、`_merge_aliases`、`_apply_defaults`、`_is_valid_char_name`、`build_character_fragment(_en)`、`TextChunker`、`flatten_toc` 都是純函數，幾乎零成本可測，而且正是歷史上反覆出 bug 的地方（JSON 解析、別名合併）。
- GitHub Actions：lint + 單元測試 + `tsc --noEmit` + `vite build`，不跑 GPU。

### 6.2 Lint / 型別

- 後端：`pyproject.toml` 加 `ruff`（含 import 排序）與可選 `mypy`；現碼有大量函式內 import（部分是刻意延遲載入 torch，可保留並註明）。
- 前端：ESLint + typescript-eslint；`api.ts` 手寫型別與後端 Pydantic 模型靠人工同步，可改由 FastAPI 的 `/openapi.json` 用 `openapi-typescript` 自動生成，杜絕欄位漂移（如 `IllustrationMeta` 這類已經手動同步過多次的型別）。

### 6.3 設定常數集中

散落的 magic number 建議集中到單一 config 模組：port 8765 / 18765、PREFETCH=3、`_DONE_TTL=60`、`_BATCH_CHARS`、輪詢間隔、VRAM 估計值等。

---

## 7. P3 — 打包與發布

### 7.1 Tauri 生產模式後端啟動

已知問題：`lib.rs` 以 `apps/desktop` 相對路徑找 `backend/main.py`，dev 下靠 `npm run dev` 另行啟動掩蓋。正式打包時建議：
1. 後端以 PyInstaller / pyoxidizer 打成單一 exe，作為 Tauri **sidecar**（`tauri.conf.json` 的 `externalBin`），由 Tauri 啟停並監控。
2. 啟動順序：sidecar health check 通過後才載入前端頁面，避免白屏期間 API 全失敗。
3. 模型目錄移出 `backend/`（現在模型、`.zimage_cache`、`llama_bin` 都在原始碼樹內），統一到 `~/.epub-tts/models/`，打包體積與更新都乾淨。

### 7.2 生產模式 uvicorn

`--reload` 僅限 dev（目前 `package.json` 即是 dev 入口，但 sidecar 模式務必去掉 reload，並把 `log_level` 與 §4.3 logging 整合）。

---

## 8. 建議實施順序

| 階段 | 內容 | 效果 |
|------|------|------|
| **第一批（quick wins，1–2 天）** | §1.1 spaCy 快取、§1.2 移除每句 GC、§2.1 404 修正、§2.6 kill 驗證行程名、§3.2 刪 `_chapters_data`、§3.3 補索引、§2.5 調低 `_BATCH_CHARS` | 翻章/朗讀立即變快，零風險 |
| **第二批（核心體驗，3–5 天）** | §1.5 驗證並修 useAudioStream、§1.4 VRAM 預算仲裁（TTS+SDXL 共存）、§1.3 LLM keep-alive、§1.6 串流模式預設 16 步 | 朗讀不再被生圖打斷；生圖延遲砍半 |
| **第三批（資料層，3–5 天）** | §3.1 圖片落地檔案 + 圖片 endpoint + migration、§2.3 DB 呼叫移出 event loop、§2.4 schema version、§3.4 設定統一 | DB 不再膨脹、後端不卡頓 |
| **第四批（維護性，持續）** | §4.1 檔案拆分、§4.2 參數單一來源、§4.3 logging、§5.x 前端重構、§6 測試/CI、§7 打包 | 長期開發速度與穩定度 |

---

## 9. 附錄：本次審閱涵蓋檔案

- backend：`main.py`、`routers/{epub,tts,illustration}.py`、`services/{gpu_manager,db,tts_engine,epub_parser,text_chunker,llm_engine,illustration_engine,model_registry}.py`
- frontend：`hooks/useAudioStream.ts`、`pages/{Reader,Library}.tsx`、`stores/{player,reader}.ts`
- 文件：`DEVLOG.md`（全部）、`plan.md`、`CLAUDE.md`、根 `package.json`
- 未逐行審閱（僅依大小與職責給拆分建議）：`CharacterPanel.tsx`、`ModelManager.tsx`、`SettingsPanel.tsx`、`api.ts`、`downloader.py`、`models_manager.py`
