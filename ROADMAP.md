# vepub 剩餘工作實作規劃

> 建立日期：2026-06-12
> 範圍：OPTIMIZATION.md / plan.md 盤點後的 4 個剩餘大項 + 2 個選配項
> 性質：實作規劃（設計決策 + 步驟 + 驗收標準），不含程式碼

---

## 0. 總覽與建議順序

| 順序 | 項目 | 工作量 | 為什麼排這裡 |
|------|------|--------|--------------|
| 1 | §A 大檔案拆分 | 1–2 天 | 純搬移零風險；先做可降低後面兩項的改動面積（LoRA 會再往這些檔案加程式碼） |
| 2 | §B Tauri sidecar + 生產模式 | 2–3 天 | 解鎖「可發佈」能力；與 LoRA 完全獨立可並行 |
| 3 | §C LoRA 訓練 pipeline | 3–5 天 | 最大項，依賴拆分後的乾淨結構（prompt_builder、pipelines） |
| 4 | §D 選配：SSE / openapi-typescript | 各 0.5–1 天 | 錦上添花，隨時可插隊 |

每項完成的定義：通過該節「驗收標準」+ 現有 32 個單元測試全綠 + `tsc --noEmit` 無新錯誤。

---

## A. 大檔案拆分（OPTIMIZATION §4.1）

### 現況

| 檔案 | 行數 | 內容混雜度 |
|------|------|-----------|
| `routers/illustration.py` | ~1490 | 生圖任務、角色 CRUD、全書分析、設定圖/立繪 job、圖片檔案服務、DB migration，全在一檔 |
| `services/llm_engine.py` | ~1313 | server 生命週期、HTTP 推理、JSON 解析、角色 schema、預設值、別名合併、各推理任務 |
| `services/illustration_engine.py` | ~1150 | 設定、prompt 組合、負面詞、三種架構載入器、生成核心、三個生成入口 |

### 設計決策

1. **Facade 模式保留原模組名**。`services/llm_engine.py` 與 `services/illustration_engine.py` 保留為轉出口（re-export），拆出去的內容從子模組 import 回來。理由：
   - 32 個單元測試直接 import `services.llm_engine._parse_character_json` 等私有函式
   - routers 多處 `from services import llm_engine`
   - 拆分日後可漸進收斂 import 路徑，第一步不碰呼叫端
2. **純搬移，零邏輯變更**。任何行為調整（如 backend protocol 正式化）另開工作項，不混在拆分 commit 裡。
3. **URL 完全不變**。新 router 沿用 `/illustration` prefix 掛載，前端 `api.ts` / `model-api.ts` 不需要動。

### 拆分藍圖

#### A-1 `routers/illustration.py` → 三檔

| 新檔案 | 搬入內容（依現有行號區段） |
|--------|---------------------------|
| `routers/illustration_common.py` | `_evict_expired`、`_save_image_file`、`_delete_image_file`、`_queue_sem`、`_ensure_columns`、`init_illustration_tables`、`_persist_analysis_job`、各 in-memory job dict |
| `routers/illustration.py`（瘦身後） | GenerateRequest、`_run_task`、`/generate`、`/progress`、`/status`、`/load`、`/unload`、`/settings`、`/list`、`/item`、`/image/{id}`、`/char-image/{id}` |
| `routers/characters.py` | 角色 CRUD（upsert/list/delete/batch/dedup/fill_defaults）、角色圖片管理、全書分析（`_run_analysis` 等）、設定圖 job（`_run_angle_job`）、立繪 job（`_run_portrait_job`）、`extract_character` |

掛載方式：`main.py` 加一行 `app.include_router(characters.router, prefix="/illustration")`——兩個 router 共用 prefix，路徑不變。

注意點：
- `_queue_sem` 必須是**單一實例**被兩個 router 共用（生圖與角色設定圖共搶一個序列槽），所以放 common 模組。
- `init_illustration_tables()` 的 import 來源在 `main.py:17`，搬家後同步改。

#### A-2 `services/llm_engine.py` → 三檔 + facade

| 新檔案 | 搬入內容 |
|--------|----------|
| `services/llm/server.py` | `find_llama_server`、`find_gguf`、`find_analysis_gguf`、`_kill_existing_server`、`_start_server_sync`、`_stop_server_sync`、`_ensure_server`、`_arm_idle_stop`、`stop_server_now`、`_chat` |
| `services/llm/char_schema.py` | 欄位 schema 常數、`_fmt_soft/_fmt_strict`、`_normalize_char`、`_parse_character_json`、`_strip_inline_thinking`、`_is_valid_char_name`、`_merge_aliases`、`_apply_defaults`、`_name_pick`、`_empty_character_fields` |
| `services/llm/tasks.py` | `expand_prompt`、`extract_character_features`、`analyze_characters`、`find_alias_groups`、`infer_missing_fields`、`_infer_contextual_fields`、`_detect_is_anime`、`_clean_llm`、`_trim_for_extraction` |
| `services/llm_engine.py`（facade） | `from services.llm.server import *` 等轉出口，含底線私有名也要顯式 re-export（測試在用） |

#### A-3 `services/illustration_engine.py` → 三檔 + facade

| 新檔案 | 搬入內容 |
|--------|----------|
| `services/illustration/prompt_builder.py` | `build_character_fragment(_en)`、`_match_kw` + keyword 表、`character_seed_for`、`_infer_is_anime`、`_build_negative_prompt(_sheet)` |
| `services/illustration/pipelines.py` | `_detect_architecture`、`_active_model_arch`、`_load_pipe_sync`、`_load_sdxl_pipe_sync`、`_ensure_zimage_components`、`_load_zimage_pipe_sync`、`_load_wan_pipe_sync`、`_unload_pipe_sync`、`_get_pipe` |
| `services/illustration/generation.py` | `_resolve_effective_params`、`_generate_sync`、`_pil_to_bytes`、`generate_character_sheet`、`generate_portrait`、`generate_illustration`、設定（IllustrationSettings、`_persist/_load_settings`） |
| `services/illustration_engine.py`（facade） | re-export 全部公開介面 + 測試用到的函式 |

注意點：pipeline 模組級狀態（目前載入的 pipe、style）只能存在一處——放 `pipelines.py`，`generation.py` 透過函式取用，不複製全域變數。

### 實作步驟

1. 建 `routers/illustration_common.py`，搬共用工具 → 兩個 router 改 import → 跑測試
2. 建 `routers/characters.py`，搬角色相關端點 → `main.py` 掛載 → 用 `/openapi.json` diff 確認路由集合不變
3. 拆 `llm_engine` → facade re-export → 跑 pytest（測試是這步的安全網）
4. 拆 `illustration_engine` → facade → 跑 pytest
5. 手動冒煙：啟動 dev、翻章、朗讀、生一張圖、開角色面板

### 驗收標準

- `GET /openapi.json` 拆分前後 diff 為空（路由、方法、參數完全一致）
- 32 個單元測試不改一行、全綠
- 每個新檔 < 600 行

### 風險

低。唯一陷阱是模組級可變狀態（job dicts、pipe 快取、`_settings`）被複製成兩份——規則：**狀態只住在一個模組，其他人 import 取用**。

---

## B. Tauri Sidecar + 生產模式（OPTIMIZATION §7.1 + §7.2）

### 現況問題

1. `lib.rs:17-26` 用相對路徑 `backend/.venv/Scripts/python.exe` + `backend/main.py`——只有「工作目錄恰好是 repo 根」才能動；打包後必壞。dev 模式靠根目錄 `npm run dev` 另行啟動掩蓋了這件事。
2. 模型資產在原始碼樹內：`backend/models/` 29 GB、`backend/llama_bin/` 683 MB、`.zimage_cache`——不可能進安裝包。
3. `--reload` 只存在於根 `package.json` 的 dev script；`main.py` 的 `uvicorn.run` 本身已無 reload，§7.2 實際剩「sidecar 入口的 log/lifecycle 整理」。
4. **隱藏殺手**：backend 會 spawn `llama-server.exe` 子行程。Tauri 退出時只 kill Python，llama-server 會變孤兒繼續佔 16 GB VRAM。

### 設計決策

**打包方式：PyInstaller onedir（非 onefile）**
- onefile 啟動時要解壓數 GB 到 temp，冷啟動慢到不可用；onedir 直接執行。
- torch CUDA 全家桶會讓 onedir 達 6–8 GB——可接受（本來就是本機 AI 應用），但 `llama_bin`、模型一律不進包。
- 備援方案（若 PyInstaller 對 diffusers git 版/spaCy/rembg 的 hidden import 地獄超過 1 天仍打不平）：改用 **python embeddable + 預建 venv** 方案——安裝器附 Python 3.12 embeddable，首次啟動跑 `uv sync`。體積更小、相容性最好，代價是首次啟動要裝依賴（需網路）。規劃以 PyInstaller 為主線，做到第 3 步若卡關即切換。

**資產目錄統一到 `~/.epub-tts/`**
```
~/.epub-tts/
├── library.db          （現有）
├── images/             （現有）
├── models/             ← backend/models 遷移至此
│   ├── image/  llm/  loras/
├── bin/llama/          ← llama_bin 遷移至此（隨安裝器發佈或首次下載）
└── cache/zimage/       ← .zimage_cache 遷移至此
```

**啟動順序**：Tauri 視窗先建立但前端顯示「後端啟動中」狀態 → lib.rs spawn sidecar → 前端既有的 `/health` 輪詢（`api.ts:60` 已存在）偵測就緒後進入書庫。不採用「health 通過才開視窗」——後端冷啟動可達數秒，白屏體驗更差。

**行程樹清理**：Windows 用 Job Object（`CREATE_SUSPENDED` + `AssignProcessToJobObject` + `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`），Tauri 退出時整棵行程樹（python + llama-server）一起死。Rust 側用 `win32job` crate 或直接 windows-rs 呼叫。同時 backend 補一層保險：`lifespan` shutdown hook 呼叫 `stop_server_now()`。

### 實作步驟

1. **路徑遷移（backend 側，先做、獨立可測）**
   - `config.py` 新增 `DATA_DIR = ~/.epub-tts`，派生 `MODELS_DIR / BIN_DIR / CACHE_DIR`，支援 `VEPUB_DATA_DIR` 環境變數覆寫（CI 與測試用）
   - `llm_engine`（`_BASE_DIR/_BIN_DIR`）、`illustration_engine`（`_BASE_DIR`）、`model_registry`、`downloader` 全部改讀 config
   - 啟動時一次性遷移：偵測舊位置 `backend/models` 存在且新位置為空 → 移動（同磁碟 `os.rename` 即時完成）+ 重寫 `model_registry.json` 內的絕對路徑
   - 驗收：dev 模式照常可生圖、可朗讀；`backend/` 樹內無模型檔案

2. **sidecar 入口與生產 uvicorn（§7.2 一併在此完成）**
   - 新增 `backend/sidecar_main.py`：`uvicorn.run(app, ...)` 程式化啟動、無 reload、`log_level` 取自 `VEPUB_LOG_LEVEL` 環境變數（預設 info）、logging 輸出到 `~/.epub-tts/logs/backend.log`（RotatingFileHandler，stdout 同步保留給 Tauri 捕捉）
   - `lifespan` shutdown 段補 `stop_server_now()`（殺 llama-server 的後端側保險）

3. **PyInstaller spec**
   - `backend/vepub-backend.spec`：入口 `sidecar_main.py`，onedir，`--noconsole`
   - 已知需處理的 hidden imports / data：uvicorn 的 loop/protocol 動態 import、`transformers`/`diffusers` 動態模組、spaCy 語言模型（`zh_core_web_sm` 等以 data 收集）、`rembg` 的 onnx 模型、`ebooklib` 資源
   - 產出驗證腳本：dist 目錄直接執行 → `/health` 200 → 解析一本 epub → 合成一句 TTS（無 GPU 機器跳過生圖）
   - **此步是整個 §B 的風險集中點**，預留 1 天打 import 地獄；超時即切備援方案

4. **Tauri 整合**
   - `tauri.conf.json`：onedir 整目錄走 `bundle.resources`（externalBin 只支援單檔，不適用 onedir）；`productName` 順手改成 `vepub`
   - `lib.rs` 重寫 `start_backend()`：
     - `cfg(debug_assertions)` dev 分支：維持現狀（npm run dev 另起後端時直接跳過 spawn，偵測 8765 已有人聽就不啟動）
     - release 分支：`app.path().resource_dir()` 解析 sidecar 路徑 → Job Object 包裹 spawn → 失敗時彈 dialog 而非默默 println
   - 移除 `greet` 示範 command

5. **前端啟動體驗**
   - `Library.tsx` 在 `/health` 未就緒時顯示「後端啟動中…」全屏狀態（含 30 秒逾時後的錯誤指引），取代現在的請求失敗 toast

6. **端到端驗證**
   - `npm run tauri build` → 安裝到乾淨路徑（非 repo 目錄）→ 啟動 → 匯入書、朗讀、生圖 → 關閉 app → 工作管理員確認無 python / llama-server 殘留

### 驗收標準

- 打包後的安裝版在「repo 不存在」的前提下完整可用
- App 關閉後 5 秒內 python.exe 與 llama-server.exe 全部消失
- dev 工作流（`npm run dev`）完全不受影響
- `backend/` 原始碼樹內無模型、無 cache（`.gitignore` 同步清理）

### 風險

| 風險 | 緩解 |
|------|------|
| PyInstaller × torch/diffusers hidden import 反覆失敗 | 預留 1 天上限；切換 embeddable Python 備援方案 |
| onedir 體積 6–8 GB，安裝器打包時間長 | NSIS 改 zip 自解壓或接受現狀；模型本來就另行下載 |
| 模型遷移途中斷電/中斷 | 遷移採「先複製驗證再刪舊」或同磁碟 rename（原子） |
| 8765 port 被占 | 啟動偵測 + 前端錯誤指引（換 port 需動 BASE_URL 常數，列為後續項不在此做） |

---

## C. 角色 LoRA 訓練 Pipeline（plan.md P3 / 階段 3）

### 已就緒的地基

- 可行性已實測（plan.md §五）：ZImage `load_lora_weights` 可用、PEFT 已裝、LoRA key 格式已驗證（30 層 × `to_q/to_k/to_v/to_out.0` = 120 個插入點）
- `characters` 表已有 `lora_path`、`lora_trained_at` 欄位（migration 已跑，無人寫入）
- `models/loras/` 目錄已存在
- `bitsandbytes`（8-bit optimizer）、`accelerate` 已在依賴中
- UI 規劃已寫在 plan.md §6.6（「訓練」按鈕，≥3 張圖才可用）

### 設計決策

1. **範圍限定 Z-Image（寫實風）**。SDXL 動畫風的 LoRA 訓練是另一套標準流程（kohya 式），且 plan.md 只驗證了 ZImage——第一版不做 SDXL，UI 上動畫風角色不顯示訓練按鈕。
2. **訓練資料 = character_images 的圖 + 結構化特徵 caption**。每張圖的 caption 固定為 `角色名（觸發詞） + build_character_fragment(char)`，不做逐圖打標（3–5 張圖不值得）。觸發詞用角色名本身，生圖時 prompt 已含角色名，無縫銜接。
3. **VRAM 策略（25.7 GB 預算）**：
   - 前置一次性：VAE encode 所有訓練圖 → cache latents；4B text encoder encode caption → cache embedding。之後 VAE 與 text encoder 完全不進 GPU。
   - 訓練中只有 transformer（bf16，~12 GB）+ LoRA 參數 + 梯度；開 gradient checkpointing；optimizer 用 bnb 8-bit AdamW
   - 估算 < 20 GB，留有餘裕；若實測爆，解析度從 1024 降 768
4. **訓練超參數起點**（之後實測調整）：rank 16 / alpha 16、lr 1e-4、batch 1 + grad accum 4、500–1000 steps、flow-matching loss（Z-Image 是 flow-matching DiT，訓練迴圈參考 diffusers 的 Flux/Lumina LoRA 範例改寫，**不能**用 epsilon-prediction 的 SD 範例）
5. **GPU 仲裁**：`gpu_manager` 新增 task type `lora_training`，行為同 `illustration_zimage`（持 lock，TTS 排隊）。訓練是長任務（5–10 分鐘），UI 必須明示「訓練期間朗讀與生圖暫停」。
6. **產物與掛載**：safetensors 存 `~/.epub-tts/models/loras/{book_id}/{name}.safetensors`（配合 §B 的目錄遷移）；寫回 `characters.lora_path` + `lora_trained_at`。生圖時若選中角色有 `lora_path` → pipe 載入後 `load_lora_weights` + adapter scale 0.8（可調）→ 生成完卸載 adapter（避免污染下一個無 LoRA 的請求）；連續同角色生圖時跳過重複載入（記錄目前掛載的 lora path）。

### 實作步驟

1. **訓練核心** `services/lora_trainer.py`
   - `prepare_dataset(book_id, name)`：讀 character_images 檔案 → resize/crop 到目標解析度 → VAE encode latents cache → caption embedding cache
   - `train_lora(book_id, name, on_progress) -> path`：PEFT 注入 → flow-matching 訓練迴圈 → 每 N step 回報進度 → 存 safetensors
   - 先以**獨立腳本模式**開發（`python -m services.lora_trainer <book_id> <name>`），不接 API，快速迭代到「能訓練出有效果的 LoRA」為止——這是整個 §C 最不確定的部分，先驗證再接管線
2. **效果驗證（gate）**：固定 seed + 同 prompt，比較掛/不掛 LoRA 的輸出與訓練圖的相似度（目測即可）。無效果就調超參數，**通過此關卡才繼續第 3 步**
3. **API 層**（拆分後加在 `routers/characters.py`）
   - `POST /illustration/characters/{book_id}/train_lora`（body 帶 name；檢查 ≥3 張圖、角色為寫實風書籍、無進行中訓練）→ job dict 模式（同 `_angle_jobs` 慣例：status/progress/label/done_at + 惰性清除）
   - `GET /illustration/lora_jobs/{job_id}`：進度輪詢
   - `DELETE /illustration/characters/{book_id}/lora`：刪除 LoRA（檔案 + 欄位清空）
4. **生圖整合**：`generate_illustration` / `generate_portrait` / `generate_character_sheet` 在取得 pipe 後檢查角色 `lora_path` → 掛載邏輯集中寫一個 helper（拆分後放 `pipelines.py`），三個入口共用
5. **前端**
   - `api.ts`：`trainCharacterLora` / `getLoraJob` / `deleteLora` + Character 型別補 `lora_path`/`lora_trained_at`
   - `CharacterCard` / `CharacterPanel`：圖 ≥3 顯示「訓練 LoRA」按鈕；訓練中顯示進度條（用既有 `usePolling`）；已訓練顯示徽章 + 重訓/刪除；訓練前 modal 確認（明示「約 5–10 分鐘，期間朗讀暫停」）
6. **回歸**：無 LoRA 角色生圖行為不變；LoRA 角色連續生圖不重複載入；切換角色正確卸載

### 驗收標準

- 對同一角色 4 張參考圖訓練後，固定 seed 下「新場景 prompt」生成的人物面部/髮型與參考圖一致性目測明顯優於純文字錨定
- 訓練全程不 OOM（25.7 GB 內），單次訓練 ≤ 15 分鐘
- 訓練期間 TTS 請求排隊不報錯，訓練結束自動恢復
- 不選 LoRA 角色時生成行為與現狀完全相同

### 風險

| 風險 | 緩解 |
|------|------|
| flow-matching 訓練迴圈寫錯（loss 收斂但無效果） | 步驟 1 獨立腳本先行 + 步驟 2 效果 gate；參考 diffusers Flux LoRA 範例的 sigma/timestep 取樣 |
| 3–5 張訓練圖過少導致過擬合（背景/姿勢烙印） | caption 帶完整特徵描述分散注意力；steps 保守；必要時隨機水平翻轉增強 |
| ZImage 自訂 attention 與 PEFT 注入互動異常 | 已實測 dummy load 成功；訓練注入若異常，fallback 手寫 LoRA Linear 包裹（key 格式已知） |
| VRAM 爆 | 降解析度 768 → 梯度累積補 batch；最壞 rank 降 8 |

---

## D. 選配項

### D-1 SSE 取代輪詢（OPTIMIZATION §5.1 中期方案）

- 後端：新增 `GET /events` 單一 SSE 端點（`sse-starlette`），把 `_tasks` / `_analysis_jobs` / `_angle_jobs` / `_portrait_jobs` / lora jobs 的狀態變更推送為事件（job dict 寫入處集中後，加一個 `notify()` 很自然——**建議在 §A 拆分時就把 job dict 操作收斂成 helper**，為此鋪路）
- 前端：一個 `useEventSource` hook 取代 `usePolling` 的四處使用；保留輪詢作為 SSE 斷線 fallback
- 時機：等 §C 完成後做（屆時輪詢已有 5 種，收益最大）；工作量 1 天

### D-2 openapi-typescript 型別自動生成（OPTIMIZATION §6.2 選項）

- `npx openapi-typescript http://127.0.0.1:8765/openapi.json -o src/lib/api-types.gen.ts`，加進 package.json script（`npm run gen:types`，手動觸發即可，不進 CI——CI 無活的後端）
- `api.ts` 手寫型別逐步改 import 生成型別；先換最常漂移的 `Character` / `IllustrationMeta`
- 前置：後端 response 需要補 `response_model`（目前多數端點回裸 dict，生成出來會是 unknown）——這是隱藏成本，估 0.5 天補主要端點的 Pydantic response model
- 時機：任何時候；工作量 1 天（含補 response_model）

---

## E. 明確不做（本輪範圍外）

- SDXL（動畫風）LoRA 訓練——等 ZImage 路線驗證價值後再評估
- 後端 port 可設定化——牽動 BASE_URL 常數與 Tauri 溝通機制，目前固定 8765 夠用
- IP-Adapter——已實測排除（plan.md §五）
- mypy——ruff 已覆蓋主要問題面，型別漸進補
