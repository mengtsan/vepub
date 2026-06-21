# vepub 開發日誌

---

## 2026-06-21 — TTS Phase 2 角色配音：對白歸屬角色、依角色庫 gender/age 配聲線

承 Phase 0+1（旁白/對白自我錨定），這輪把對白進一步**歸屬到具體角色**，讓有聲書變成「一人一聲線」的全卡司——而且複用角色庫既有的 `gender`/`age_hint`，使用者零額外輸入。

### 核心洞察

角色分析時已填好的 `gender`（男/女）+ `age_hint`（幼兒/青年/中年/老年）**剛好就是 OmniVoice Voice Design instruct 需要的**（male/female + child/young adult/middle-aged/elderly）。同一份角色資料，原本驅動生圖一致性，現在也驅動聲線一致性。

### 後端

- **`services/tts_voice.py`（新）**：
  - `character_voice_instruct(gender, age_hint, name)` → 如 `"female, young adult, high pitch"`；同性別年齡者以**名字 hash 配不同音高**避免同聲（男聲偏低、女聲偏高的鄰近範圍微調）。
  - `attribute_speakers(sentences, names)` → 啟發式歸屬：引號標對白 + `名字+說話動詞`（說/道/問/笑道/低聲…）比對；回看前句**僅限旁白引言**（無引號，如「小巧問：」），避免從前一句對白延續造成「你一句我一句」交替誤判。保守、寧缺勿錯——無明確線索的對白不指名，退回通用對白聲線。**刻意獨立成模組，日後可整支換成 LLM 歸屬而不動其餘管線。**
- **`routers/epub.py`**：`get_sentences` 整合 `_attach_character_voices`——查角色庫 → 歸屬 → 把 `speaker`/`instruct` 附到每句（執行緒池跑、受開關控制、失敗則靜默退回）。
- **`services/tts_engine.py`**：`_synthesize_sync` 加 `speaker`；**錨定鍵改為 speaker（角色）優先**（無則退回旁白/對白）；把原本獨立的 Voice Design 分支併入錨定路徑——instruct 作為該角色「首句」聲線種子，錨定後改用 voice_clone_prompt 重用。即使角色無 gender/age，仍以名字為鍵錨定一個一致（隨機）聲線。
- **`services/tts_settings.py`**：`character_voices`（預設 True，可關回 Phase 1）。
- `tts_omnivoice.py`、`routers/tts.py`：全鏈轉發 `speaker`。

### 前端

`api.ts`/`player.ts` 的 Sentence 型別加 `speaker`/`instruct`（`voiceInstruct`）；`Reader.tsx` 對應；`useAudioStream.ts` 自動模式下帶上 `speaker`+`instruct`；`SettingsPanel` 加**「角色配音」開關**（綁 `character_voices`）。

### 驗證（皆通過）

- 聲線映射：秋月 `female, young adult, high pitch`、王老太后 `male, elderly, very low pitch`、同性別年齡不同名音高有別。
- 歸屬：旁白 / 同句具名（秋月說道「…」）/ 交替對白（前句對白→不延續）/ 旁白引言帶出（小巧問：→「…」）/ 引號後具名（「…」秋月說）全正確。
- 引擎：秋月→錨定→重用、小巧→獨立錨定、旁白→narrator，三鍵並存。
- 端點實測：真實角色「秋月（女/青年）」→ `speaker=秋月, instruct=female, young adult, high pitch`。
- `tsc --noEmit` 僅 2 個既有 `IllustrationTest.tsx` 錯誤；ruff 零新增。

### 限制與後續

- 啟發式歸屬覆蓋率有限（中文常省略「某某說」）；無明確線索者不指名（不誤判）。升級路徑：把 `attribute_speakers` 換成複用角色分析 pipeline 的 LLM 版本。
- **待實機聽感驗證**：`npm run dev` 後找有對白的章節，確認不同角色聽起來相異、同角色一致。

---

## 2026-06-21 — TTS 一致性：朗讀語系下拉、旁白/對白自我錨定聲線（Phase 0+1）、播放往回跳修復

承接上一輪 OmniVoice 落地，這輪聚焦「聽起來對不對」——語系可選、音色逐句一致，並修掉一個既有的播放競態。

### 1. 朗讀語系下拉（前端，A 方案：逐次播放覆寫）

後端 `language` 接線上輪已備妥，這輪補前端：`stores/player.ts` 加 `language: string | null`（預設 null=自動）＋ setter；`SettingsPanel.tsx`「語音合成設定」段新增**朗讀語系下拉**（自動偵測 / 普通話 / 粵語 / 日文 / 英文 / 韓文）；`useAudioStream.ts` 的 WS payload 補 `if (language) payload.language = language`。選定即逐句帶入，後端優先採用。

### 2. 「每句音色都不同」根因與修復（Phase 0+1）

**現象**：一段文字逐句播放，每句音色/語氣都不一樣。

**根因**：OmniVoice Auto 模式下，每次 `generate()` 先用**隨機聲音**生成 chunk 0 再以它為參考（`omnivoice.py:872-890`），所以單次呼叫內部一致；但閱讀器**逐句一次 `generate()`**，每句都重新隨機 → 每句一個聲音。官方無 seed，唯一一致機制是 `create_voice_clone_prompt()`。

**修法（自我錨定）**：`tts_engine.py` 為**旁白**與**對白**各維護一個 `VoiceClonePrompt` 快取。Auto 模式下某 role 首次合成後（輸出≥0.5s），用其音訊建 prompt 快取；後續同 role 重用 → 音色一致。引擎 `self._lock` 已序列化合成，「先錨定後重用」天然無競態。

- Phase 1 用全形引號`「『“`粗分旁白/對白（`classify_segment`）；角色歸屬留待 Phase 2。
- `tts_settings.py` 加 `voice_consistency`（預設 True，可關回每句隨機）；卸載/換模型時清空錨定（prompt 綁定當前 tokenizer）。
- `POST /v1/audio/voice/reset` 重新取聲（不喜歡目前隨機到的旁白）。
- 前端：`lib/tts-api.ts`（get/patch settings、reset）；`SettingsPanel` 加**「聲線一致」開關**與**「⟳ 重新隨機旁白聲音」按鈕**。

### 3. 從第 N 句開始播放會「往回跳」5→6→7→5→6→7

**現象**：從第 5 句起播，會週期性跳回重播。後端日誌顯示**同時兩條 WebSocket**。

**根因**：`useAudioStream.ts` 兩個 effect——A 監 `isPlaying`、B 監 `currentSentenceIndex`。從非 0 句起播時，兩者在同一次 render 一起變，A、B 都呼叫 `connectAndPlay()`；而其 guard 只擋 `OPEN`，第一條還在 `CONNECTING` 時被放行 → 開出第二條 WS → 兩股 5,6,7 交錯播。從第 0 句起播因 `currentSentenceIndex` 未變、Effect B 不觸發，故無此問題。

**修法**：guard 同時擋 `CONNECTING` 與 `OPEN`。順帶消除每句被合成兩次的浪費。屬既有競態，與本輪 language/錨定無關。

### 驗證

- 後端：`classify_segment` 旁白/對白正確；旁白首句錨定→次句重用→對白獨立錨定→reset 清空，全綠；ruff 零新增問題。
- 前端：`tsc --noEmit` 僅剩 2 個既有 `IllustrationTest.tsx` 錯誤，本輪改動零錯誤。
- **待實機**：雙 WS 修復需 `npm run dev` 後從第 5 句起播確認日誌只剩一條連線、播放不再往回跳。

---

## 2026-06-21 — TTS/OmniVoice 落地：模型目錄統一、registry 整併、粵語發音修復、優先語系設定

以「模型目錄是否合理」為起點，一路延伸到 TTS 實裝與發音修錯。核心是把散落的模型路徑收斂成 `models/<category>/` 分類佈局，並讓 TTS 真正納入統一的 registry 管理。

### 1. 模型目錄分類佈局與清理

- **磁碟實況盤點**：模型已按類別分到 `models/{llm,image,tts,embeddings,ip_adapters,loras}/`；`.zimage_cache/` 是 Z-Image 的共用元件（text_encoder/tokenizer/vae，`pipelines.py` 下載時刻意 `ignore_patterns=["transformer/*"]`），transformer 主權重才放 `models/image/`。
- **FaceID LoRA 路徑錯位（靜默 bug）**：`pipelines.py:257` 期待 `models/ip_adapters/ip-adapter-faceid_sdxl_lora.safetensors`，但檔案實際在 `models/loras/`，因 `os.path.isfile` 守門而**安靜跳過從未載入**。已把檔案移到 `ip_adapters/`。
- **registry 幽靈條目**：`model_registry.json` 移除磁碟上不存在的 `kodoranime_v101`、`zimageturbonsfw_90bf16fp8`。
- **.gitignore**：補上 `models/{ip_adapters,loras,embeddings}/`、`models/.cache/`（含 GB 級大檔，原本沒擋）。

### 2. TTS 路徑三套打架 → 統一 `models/tts/`

`model_registry.py`、`models_manager.py`、`downloader._CATEGORY_SUBDIR` 三處對 OmniVoice 該放哪各執一詞（頂層 `k2-fsa--OmniVoice` / `Serveurperso--OmniVoice-GGUF` / `models/tts/`）。趁磁碟上尚無 TTS 檔，全部統一到 `models/tts/`（`models_manager` 加 `TTS_DIR`/`GGUF_DIR` 常數消除三處重複字串；registry 偵測路徑同步）。

### 3. OmniVoice 實裝 + 對照官方 API 的兩個 bug

下載 `k2-fsa/OmniVoice`（0.6B，model.safetensors 2.45GB）到 `models/tts/k2-fsa--OmniVoice`。Introspect 已安裝套件的真實 `generate` 簽名，發現 `tts_engine._synthesize_sync` 兩個缺陷：

- **`num_step` 是 no-op**：它不是 `generate()` 頂層參數，被 `**kwargs` 吞掉。改走 `OmniVoiceGenerationConfig(num_step=…)`。
- **回傳是 `list[np.ndarray]`**：原本 `np.array(audio)` 會包成 `(1,T)`，改取 `audio[0]`。

冒煙測試實機合成通過（24kHz、2.18s）。

### 4. 模型管理徹底統一（方案 B）：models_manager 退場

現況其實有三層，TTS 跑在 fallback 上：`routers/models.py`+`model_registry` 是活躍的統一管理層，但 registry 的 `tts.models` 是空的（`scan_local_models` 只掃 llm/image），導致 `build_active_tts()` 回 None → 落到 `main.py` fallback → 靠 `models_manager` 硬編碼路徑。而 `models_manager.py`（~400 行：MODEL_CONFIGS/DB 設定/GGUF/下載執行緒）**已無任何 router 引用**，只剩 `tts_engine` import。

- `scan_local_models()` 新增 TTS 偵測，啟動時自動登錄 OmniVoice 並設 active。
- `TTSEngine.__init__` 改收 `local_path`（來自 registry），新增 `_resolve_model_source()`；切斷對 `models_manager` 的依賴；刪除死碼 `load_specific`/`_load_specific_sync` 與 `model_id` 追蹤。
- `_build_tts_backend(_raw)` 把 registry 的 `local_path` 傳進引擎。
- **刪除 `services/models_manager.py`**（git 追蹤，可還原）；無用的 GGUF 選項隨之消失。
- 端到端測試：啟動→登錄→建 backend→本地載入→合成，全綠，TTS 走 registry 單一來源。

### 5. 中文唸成粵語 → 根因與修復

`generate()` 的 `language` 從未傳入 → 一律 `None` → OmniVoice 落入「語言不可知」自動偵測（`_resolve_language` 回 None）。中文與粵語共用漢字，模型有時誤判成粵語(`yue`)。官方 ID：普通話 `zh`(cmn, 111k hr) vs 粵語 `yue`(13k hr)。

採「後端按字偵測」：新增 `detect_language()`（假名→`ja`、諺文→`ko`、漢字→`zh`、拉丁→`en`；**先驗假名後驗漢字**，否則日文被當中文）。把 `language` 接線貫穿 4 層（engine→`tts_omnivoice` 包裝層→`/speech`→WS），**順手修好包裝層原本把 `num_step`/`duration` 丟棄的問題**。

### 6. 優先手動語系設定

新增 `services/tts_settings.py`（沿用 `llm_settings` 樣板，持久化到 `tts_settings.json`）與 `GET/PATCH /v1/audio/settings`。決議優先序：**單次請求 language ＞ 全域 `forced_language` ＞ 自動偵測**；`forced_language` 設 `null`/`"auto"` 即恢復偵測。

### 驗證

- 各檔 `ast.parse` 通過；ruff 零新增問題（剩餘 I001 為既有 in-function import 排序）。
- `detect_language` 5/5；三層優先序（偵測 zh / 強制 en / 請求 ja）；設定持久化重載；全鏈路經 `OmniVoiceBackend` 合成出聲——皆通過。
- **未跑前端**：語系下拉 UI 尚未做（後端不傳即自動偵測，可不阻塞）。

---

## 2026-06-21 — 模型管理大整理：常用參數收斂、輔助模型、單一模型模式、架構偵測，與 Turbo 步數 bug

一整輪以「模型設定」為核心的整理與修錯，貫穿後端 routing 與前端 ModelManager / 閱讀器設定面板。

### 1. 模型設定提供常用參數（文字 + 影像）

- **LLM 全域取樣覆寫**（新）：`services/llm/settings.py` + `routers/llm.py`（`GET/PATCH /v1/llm/settings`），`server.py::_chat()` 在 `override_enabled` 時以全域值取代各任務的調校參數（temperature/top_p/top_k/repeat_penalty，max_tokens 留空不覆寫以免截斷全書分析）。**預設關閉**，沿用各任務刻意調過的值。掛在 `/v1/llm` 而非 `/v1/models`，避免和 `PATCH /{category}/{model_id}` 動態路徑衝突。
- **影像常用參數**：ModelManager 圖像分頁新增 `ImageParamsPanel`（步數、CFG、尺寸、Hires、ADetailer、反向提示詞），共用既有 `/illustration/settings`。

### 2. Turbo `_is_turbo` 從未被設定 → Z-Image Turbo 一直跑 28 步（bug）

`_resolve_effective_params` 用 `getattr(pipe, "_is_turbo", False)` 判定 turbo，但**兩個載入器都沒設 `pipe._is_turbo`**（Z-Image 算了卻只拿去印 log、SDXL 根本沒算）→ turbo 分支是死碼，Z-Image Turbo 跑成 28 步 + CFG 4.0。修正：兩個載入器都補 `pipe._is_turbo`。並新增「**手動覆寫 Turbo / Z-Image 步數與 CFG**」開關（`turbo_override`），預設沿用官方自動值（Turbo 8 步、Z-Image 基礎 28），開啟才改用滑桿；滑桿下限放寬到步數 4、CFG 1.0。

### 3. 模型管理以「磁碟實況」為準（使用者原則）

- `model_registry.is_model_available()`（檔案存在性）+ `verify_registry()` + `normalize_active_pointers()`（啟動時把指向孤兒的 active 導正）。
- `_is_orphan()` = 缺檔且無 `source`：清單隱藏；缺檔但有下載來源的「預設」保留並在 UI 顯示**下載鈕**（`ModelCard` 用 `model.source` 走既有下載流程）。
- `/activate` 端點擋下切換到缺檔模型（409）。
- 移除圖像分頁多餘的「Prompt 優化 LLM」唯讀狀態，LLM 設定統一在語言模型分頁；`角色分析模型` 標籤改為 **`角色分析 / 構圖模型`** 並加說明（它才是負責文章→構圖的模型）。

### 4. 輔助模型（VAE / Embedding / LoRA）依目錄掃描可設定

- `routers/illustration.py` 新增 `/embeddings`、`/vaes`（與 `/loras` 同款掃描）。
- `IllustrationSettings` 加 `active_embeddings`（空=全載入，保留現狀）、`active_vae`（空=模型內建）。
- `pipelines.py`：embeddings 改為掃描目錄 + 依啟用清單載入；VAE 優先序 = UI 選的全域 VAE > 模型自帶 > 內建。
- ModelManager 新增 `AuxModelsPanel`（目錄空則提示放置路徑）。CLIP/text encoder 為 checkpoint 內建（SDXL）或 Qwen3（Z-Image），不需也不該做成可選。

### 5. 介面收斂

生圖設定（步數/CFG/Hires/ADetailer/LoRA/VAE/反向提示詞）統一移至 ModelManager；閱讀器設定面板只保留「閱讀當下的創作快捷」（畫風前綴、固定 Seed）。畫風前綴**依 anime/real 分組並與 ModelManager 的風格打通**——缺對應風格模型時整組停用。

### 6. 「選了 Z-Image 卻得到 SDXL 提示詞」——根因是路由 + 檔名誤導

- **機制**：實際使用的模型由 `is_anime`(anime/real) 路由 `_find_model_entry(style)` 決定，**不是**由 active 直接決定（active 只在風格相符時優先）。提示詞形式跟著實際載入的模型。
- **使用者選的方案：單一模型模式**（`single_model_mode`，預設關）。開啟後 `_single_model_entry()` 讓 `_find_model_entry`/`_active_model_arch`/`ensure_pipe` 一律指向 `image.active`，不分 anime/real（快取改為只看路徑）；anime/real 只影響語氣。
- **真相**：檔名會騙人——`zImageTurboNSFW` 檔案其實**遺失**（舊 `_detect_architecture` 讀檔失敗預設回 `sdxl` 造成誤標）；真正的 Z-Image 是 `luciddreamerZ`（active）與 `moodyProMix_zitV13`。
- **架構標籤**：新增 `inspect_arch()`（檔案不存在/讀不到回 `None`，不誤標 sdxl）；`GET /v1/models/` 圖像模型帶 `arch`/`is_turbo`；`ModelCard` 顯示 `SDXL` / `Z-Image` / `Z-Image·Turbo` 徽章——名字不可靠，看徽章認模型。

### 驗證

- 後端各檔 `ast.parse` 通過；`is_model_available` / `_is_orphan` / `normalize_active_pointers` / `_single_model_entry` / `inspect_arch` 以實際 `model_registry.json` 人工驗證（孤兒隱藏、預設保留、單一模式回 active、arch 正確、缺檔回 None）。
- 前端 `tsc --noEmit` 僅剩 2 個既有 `IllustrationTest.tsx` 錯誤，本輪改動零錯誤。
- **未跑 GPU 實機**：`_active_model_arch` 需 diffusers（uv 環境），純 python 無法測該行；建議啟動 dev 後實測單一模型模式 + 架構徽章。

---

## 2026-06-21 — 切換繪圖模型 VRAM 不釋放 + 同風格 activate 切換不生效

### 問題

實機回報：**切換繪圖模型時，VRAM 似乎沒有釋放前一個模型佔用的空間。**

### 根因（`services/illustration/pipelines.py`）

換模型的唯一路徑是 `ensure_pipe(style)`，但它有兩個缺陷：

1. **換模型前沒有先卸載舊 pipe**。原本邏輯是「載入新模型後直接覆寫 `_pipe`」：

   ```python
   _pipe = await loop.run_in_executor(None, _load_zimage_pipe_sync, ...)  # 直接覆寫
   _loaded_style = style
   ```

   - 載入新模型期間舊模型仍在 VRAM → 兩個模型同時佔用（ZImage 21GB ＋另一個直接逼近/超過 25.7GB 上限 → OOM 或爆顯存）。
   - 覆寫後**完全沒有** `gc.collect()` / `torch.cuda.empty_cache()`；舊 pipe 雖失去引用，但 PyTorch CUDA 配置器不會主動把快取歸還，`nvidia-smi` 看起來就是「沒釋放」。對比之下 `unload_pipe()` / `_unload_pipe_sync()` 都有正確 GC，只是換模型路徑根本沒呼叫到。

2. **快取鍵只用 `style`，沒看模型檔路徑**。`if _pipe is not None and _loaded_style == style: return _pipe` → 同一風格換不同模型檔時，直接回傳舊的 cached pipe，**切了不生效**。

### 修正

| 改動 | 內容 |
|------|------|
| 新增 `_loaded_path` 全域 | 記錄目前載入的模型檔路徑，作為快取鍵之一 |
| `ensure_pipe` 快取鍵 | 改為「風格 ＋ 模型檔路徑」都相符才重用；不符就重載 |
| `ensure_pipe` 換模型流程 | 載入新模型**前**先 `_unload_pipe_sync()`（卸載舊 pipe ＋ `gc.collect()` ＋ `empty_cache()`），避免新舊同時佔 VRAM、並確實歸還顯存 |
| `_unload_pipe_sync` / `unload_pipe` | 統一重置 `_loaded_path`，`unload_pipe` 改為呼叫 `_unload_pipe_sync` 共用同一套釋放邏輯 |

> 過程中曾試用 `old.to("cpu")` 再 del 來「保證」搬離 VRAM，但那會把整個模型（ZImage 達 21GB）暫時搬進系統 RAM 造成尖峰且較慢。實際上只要丟掉所有 Python 引用再 `empty_cache()`，配置器就會歸還顯存（diffusers 標準做法），故移除該段。

### 延伸：「同風格下 activate 切換不同模型檔」也生效（`_find_model_entry`）

`_find_model_entry(style)` 原本回傳「**第一個** style 欄位相符的模型」，完全不看 registry 的 `active`；而 image 的 activate 端點（`routers/models.py`）只更新 registry `active`、`_build_image_backend` 回傳 `None`，等於切換鈕對生圖毫無影響。

修正：`_find_model_entry` 改為**優先採用 `active` 模型（僅當其風格與請求風格相符）**，風格不符才回退「第一個該風格模型」。搭配上面的 `_loaded_path` 快取鍵，activate 後下一次生成會自動卸載舊模型並換載新的。

- 以目前 registry（`active = luciddreamerZ`，anime）驗證：`_find_model_entry("anime")` → 回傳 active 的 luciddreamerZ（不再是第一個 janku）；`_find_model_entry("real")` → active 是 anime、風格不符 → 回退唯一的 real（zImageTurbo）。✅
- **不需改前端 / registry schema**，沿用既有單一 `active` 徽章語意，採 lazy 換載（下次生成才換，與「VRAM 管理 → 預載入/釋放」流程一致）。

### 已知限制 / 設計取捨（刻意未做）

這次是在「**單一 `active` 欄位**」上打的補丁，而生圖風格是**每張圖依文字內容自動判定**（`_infer_is_anime`），一個欄位本質上無法同時表達「anime 用哪個、real 用哪個」。

- **目前資料下完全正確**：使用者只有 1 個 real 模型，real 的「回退第一個」永遠唯一無歧義；anime 三個靠 active 正確選擇。
- **露餡條件**：當**非 active 的那個風格也有 2 個以上模型**時會出現「另一風格被悄悄重設成第一個」——例：activate anime C 後再 activate real R2，下次 anime 生圖因 active=R2 風格不符而回退到第一個 anime（A），C 被默默丟掉。
- **真正乾淨的解**：依風格各記一個 active（registry `active_anime` / `active_real`），需動 schema、`GET /models` 的 `is_active` 計算、activate 端點與前端徽章。**結論：等實際加入第二個 real 模型時再升級**，現在做 per-style 的額外複雜度沒有實際回報。

### 驗證

- `python -c "ast.parse(...)"` 語法檢查通過（`pipelines.py`）。
- 邏輯以目前 `model_registry.json` 內容人工推演正確（見上）。
- **未跑 GPU 實機**：建議下次啟動 dev 後，在 ModelManager 切換 anime 模型再生一張圖，確認 `nvidia-smi` 顯存回落且輸出換成新模型。

### `_active_model_arch` 的邊界情況（未動）

`_active_model_arch()` 在「已載入同風格 pipe」時會直接回傳**目前已載入 pipe 的架構**來決定 GPU 鎖策略（`illustration_sdxl` vs `illustration_zimage`）。若在**同風格下、於兩個不同架構的模型間切換**（如同為 anime 但一 SDXL 一 Z-Image），切換後「第一次」生成會用舊架構判定鎖，之後才正確。目前 3 個 anime 都是 SDXL 無此問題，故維持原樣以免每次生成都去讀 safetensors 標頭。

---

## 2026-06-20 — 插圖場景 prompt 職責分離重構（根治外觀抄壞/性別錯/性愛幻覺）

### 問題

實機回報插圖「一直出問題」，連續幾種症狀：

1. 原文純對話場景（「樂天披外衣、權力美婦翻臉」），插圖卻生成
   `doggystyle, vaginal, cum` 等明確性愛標籤。
2. 多角色場景的標籤黏死：`1girl_mature_female`、`long hair 1girl short hair`、
   標籤開頭黏 `:`/`-`、整串外觀無逗號。
3. 明確的女性角色被標成 `middle-aged man`（性別錯）。

逐個補 parser（`_FUSED_COUNT_RE` / `_EMBEDDED_COUNT_RE` / 底線轉空格 / 開頭符號
strip / 場景解析加 `is_sexual` 欄位）能壓下個案，但症狀換個花樣又冒出來。

### 根因（設計層）

場景插圖 prompt 混了兩種本質不同的資訊，且**兩種都被丟給同一個不可靠的 LLM
文字生成步驟**：

| | 類型 A：角色固定外觀 | 類型 B：場景語意 |
|---|---|---|
| 內容 | 髮色/瞳色/臉型/體型/罩杯/服裝/性別/配件 | 動作、是否性愛+體位、地點、時間、光線、鏡頭 |
| 來源 | 已存 DB，已有決定性轉換器 `build_character_fragment_en()` | 需 LLM 讀原文 |

舊設計把類型 A 也餵進 `_build_composition_prompt` 要 LLM「抄回來」，最終 prompt
只有 LLM 那一行（`generation.py` 的 `full_prompt`）；那份乾淨的決定性外觀標籤，
除非 LLM 一字不差重打，否則到不了圖上。於是每個 bug 都是「LLM 抄壞了它本不該抄
的東西」：性別錯、黏接、性愛幻覺、塌縮整份外觀消失。下游 parser 修的是「自由格式
LLM 文字」，失敗面無限，永遠補不完。

### 修正（`services/llm/tasks.py`，職責分離）

```
最終 prompt = 品質詞, 人數標籤, [各角色外觀片段]  BREAK  [LLM 場景標籤]
                     └─ 決定性，不經 LLM ─┘            └─ LLM 只負責這段 ─┘
```

- `_build_composition_prompt` 改成**只輸出類型 B 場景標籤**（prefill `PROMPT: `，
  不含人數/外觀/角色名）；`_build_char_context_for_scene` 只給 LLM 名字+性別+身分
  當脈絡，不給外觀。
- 新增 `_assemble_prompt`：決定性組裝 `_subject_count_tag()` 人數 + 各角色
  `build_character_fragment_en()`（`_strip_lead_count` 去掉自帶的 1girl 前綴）
  `BREAK` 場景標籤。`expand_prompt` Step 3 取場景標籤、Step 4 組裝。
- **BREAK 分窗**：身份段與場景段各自在獨立 77-token CLIP 窗編碼（場景路徑原本無
  BREAK 會截斷尾端場景標籤；現在沿用既有 `_encode_with_break`，Z-Image/Wan 端
  BREAK 會被併成逗號無害）。
- `_extract_prompt_line` 由「修 LLM 爛字串的主力」降級為只清場景標籤的防呆
  （去重、丟棄洩漏的人數標籤）；移除已無用的 `_COUNT_PREFIX_RE`。

**過程中發現的關鍵坑**：抽離英文外觀脈絡後，abliterated 模型（huihui-qwen3-4b）
在場景標籤改吐中文（`从背后/性交/夜晚`），被 CJK 安全清除後塌縮成 `shot`。舊設計
因 in-context 有英文外觀標籤而意外維持英文。解法：system prompt 明寫「SCENE 是
中文，必須翻成英文 danbooru tags」+ 給具體英文範例錨定語言；**性愛場景在
`is_sexual` 分支內另給一個英文性愛範例**（只給非性愛範例時，模型遇 `性交` 等顯式
詞仍翻回中文）。範例措辭「pick the position matching THIS scene」避免體位偏置。

### 角色一致性對齊

職責分離後外觀改走決定性串接，連帶把一致性錨點補齊：

- **外觀標籤**：DB 直連，同角色每張圖 byte-identical（舊設計經 LLM 會變）。
- **素衣裝飾點綴**：`_assemble_prompt` 對有 `character_seed` 的角色把該 seed 傳進
  `build_character_fragment_en(seed=...)`，與立繪/設定圖同基準（立繪
  `routers/characters.py` 也用 character_seed）；無 seed 角色退 name 雜湊。seed 只
  影響素衣點綴，髮/眼/臉/主服裝走 name 雜湊本就穩定。
- **Seed / FaceID / 在場判定**不變，仍由 `resolve_present_chars` 的單一
  `char_contexts` 共同驅動。

### 驗證

- 三種場景（非性愛雙女有角色 / 非性愛無角色 / 性愛無角色）各跑兩遍，輸出穩定且
  正確：外觀段乾淨、性別正確、非性愛無幻覺、性愛輸出正確英文體位標籤；外觀段兩
  遍 byte-identical。
- 單元檢查：素衣點綴在立繪路徑與場景路徑一致；無 seed 角色兩次組裝相同；
  `build_character_fragment_en`/`_strip_lead_count`/engine import 正常。
- `ruff check services/llm/tasks.py` 11 個問題，全為 pre-existing（E701/E402/I001），
  零新增。
- **未跑 GPU 實機算圖**：BREAK 編碼是立繪/設定圖已在用的成熟路徑，場景路徑只是改
  成也帶 BREAK；建議下次啟動 dev 在 app 內生一張確認視覺效果。

### 已知限制（模型層，非本次能解）

多角色單圖無法把「綠髮綁 A、黑髮綁 B」（SDXL/danbooru 本質限制），且 seed/FaceID
只鎖 `char_contexts[0]` 主角；2 人以上要真正乾淨需 regional prompting 或只畫主角，
屬產品決策。

---

## 2026-06-17 — 修復 IP-Adapter 載入後其他生成路徑全部崩潰的 bug

### 問題

實機測試「生成角色設定圖」時報錯：

```
<class 'diffusers...UNet2DConditionModel'> has the config param
`encoder_hid_dim_type` set to 'ip_image_proj' which requires the keyword
argument `image_embeds` to be passed in `added_cond_kwargs`
```

**根因**：`_load_sdxl_pipe_sync` 在 SDXL 模型載入時**無條件**對 UNet 呼叫
`load_ip_adapter()`（FaceID），這會把 UNet 的 `encoder_hid_dim_type` 永久改成
`'ip_image_proj'`——此後任何用這顆 UNet 的 forward 呼叫，*不論這次生成要不要用
FaceID*，都結構性要求 `added_cond_kwargs` 帶 `image_embeds`，否則 diffusers
直接丟例外。`pipe.set_ip_adapter_scale(0.0)` 只能讓 FaceID 不產生實際影響，
無法移除這個簽名要求。

`_generate_sync` 原本只在 `ip_adapter_image is not None`（亦即 `use_ip=True`）
時才组裝 `ip_adapter_image_embeds`；角色設定圖／立繪（`generate_character_sheet`
/ `generate_portrait`）一律傳 `ip_adapter_image=None`（無參考圖），所以一旦
pipe 已載入過 FaceID（永遠如此），這兩個入口必定崩潰。

同樣的風險也存在於 `_hires_fix_sync`／`_adetailer_sync`／`_refine_face_sync`
（皆透過 `from_pipe(pipe)` 共用同一個 UNet 物件）——ADetailer 預設啟用
（`adetailer_enabled=True`），理論上同樣會炸，只是先被角色設定圖的路徑先觸發。

### 修正（`services/illustration/pipelines.py`）

- `_generate_sync`：拆出 `ip_adapter_ready = pipe._ip_adapter_loaded and not is_wan and not is_zimage`；
  `use_ip=False` 但 `ip_adapter_ready=True` 時，補一個 `(1,1,512)` 零向量
  + `scale=0` 滿足簽名要求，不影響輸出
- 新增共用 helper `_ip_adapter_passthrough_kwargs(pipe)`，回傳同樣的零向量
  kwargs（無 IP-Adapter 時回傳空 dict），`_hires_fix_sync` / `_adetailer_sync` /
  `_refine_face_sync` 的 `i2i(...)` / `inpaint(...)` 呼叫都補上
  `**_ip_adapter_passthrough_kwargs(pipe)`

### 驗證

`backend/tests/` 32 個單元測試全綠；語法檢查通過。**未跑 GPU 實機驗證**
（需要你下次啟動 dev 環境重新觸發「生成角色設定圖」確認不再報錯）。

---

## 2026-06-16 — 修復 primary_char/present_chars 架構分歧 + Z-Image 步數/CFG bug

依 06-15 留下的兩個待辦（風險 2、Z-Image bug）動手修正，並補寫了當時只提及、
未實際建立的 `plans/consistency-alignment-refactor.md`。

### 一、primary_char 與 present_chars 統一（風險 2）

**問題**：FaceID 參考圖／角色 seed 的判定（`routers/illustration.py` substring
比對）與構圖 prompt 的判定（LLM `present_chars`）各自獨立。LLM 能分辨「只被
提及未在場」，substring 比對不能——兩者選到不同角色時，prompt 描述 B、
FaceID 卻把 A 的臉貼上去。

**修正**：
- `services/llm/tasks.py`：把 `expand_prompt` 的 Step1+2（場景分析＋三層比對）
  拆成獨立函式 `resolve_present_chars()`，作為「誰在場」的唯一權威來源；
  `expand_prompt` 回傳值擴充為 `(prompt, is_anime, char_contexts)`
- `services/illustration/generation.py::generate_illustration`：新增
  `book_id`／`character_name` 參數，FaceID 參考圖與 seed 改用
  `character_name`（使用者手動選角）→ `char_contexts[0]`（LLM 確認在場）
  的優先序解析，不再由路由層獨立猜測；`direct_prompt` 情境（無 LLM 場景
  分析）保留簡單 substring fallback（`_find_text_primary_char`）
- `services/illustration/refs.py`（新檔）：把 `_load_char_ref_image` 從
  `routers/illustration_common.py` 搬到 service 層，router 端保留轉出口
- `routers/illustration.py::_run_task`：移除原本的 substring 掃描／seed
  解析／ip_ref 載入，整包 `text`/`character_descriptions`/`book_id`/
  `character_name` 直接交給 `generate_illustration`

詳細設計記錄於 `plans/consistency-alignment-refactor.md`。

### 二、Z-Image 步數/CFG 未生效 bug 修正

**問題**（06-15 上午已記錄）：`_resolve_effective_params` 對 turbo/zimage
回傳 `(8, 1.5)`，但只存進 meta，`_generate_sync` 實際仍讀 `s.steps`（30）／
呼叫端傳入 `s.guidance_scale`（6.0），從未套用。

**修正**：`pipelines.py::_generate_sync` 內 `num_steps = s.steps` 改為
`num_steps, guidance_scale = _resolve_effective_params(pipe, s)`，單一來源
同時覆寫步數與 CFG（非 turbo/zimage 時回傳值與原設定相同，不影響其他模型）。

### 三、風險 1 補一道文字層防線

`_build_composition_prompt` 的 real（中文）分支 system prompt 原本沒有
「外觀 tags 為基底、人設只推情緒」的衝突處理規則（anime 分支已有對稱規則），
已補上。仍是 prompt 層軟約束，實際生圖跨場景穩定度待後續觀察。

### 驗證

`backend/tests/` 32 個單元測試全綠；模組 import smoke test 通過。未跑 GPU
生圖驗證（FaceID 對齊效果需實際啟動 dev 環境人工確認）。

### 不在本次範圍

角色 LoRA 訓練 pipeline（ROADMAP §C）——使用者明確表示暫不需要。

---

## 2026-06-15（下午）— 插圖四步 Pipeline 重構：description 注入 + 場景分析 + 構圖融合

### 背景

原始設計的插圖生成是四步流程：①LLM 從段落構思可畫場景 ②調出在場角色的 `description`（人設敘述）＋結構化欄位 ③融合成構圖敘述 ④轉 ≤75 token 提示詞，最後搭 FaceID 鎖臉。但 2026-06-14 的「改回三段 BREAK 格式」把這流程壓成單一 LLM call，跳過了「先理解場景、再針對性調人物、再融合」，且 `description` 欄位在生圖端形同未用。

### 一、分析階段：讓 description 真正被記錄（前提）

| 檔案 | 改動 |
|------|------|
| `services/llm/char_schema.py` | `_CHAR_SCHEMA_PROMPT` 的 `description` 從選填改**必填**，明定四要素格式（①外貌概覽②個性氣質③身份背景④與主角關係）＋範例 |
| `routers/characters.py` | `_upsert_col_expr` 對 `description` 改「較長者優先」策略；舊版 `COALESCE(col, excluded.col)` 第一次寫入後永遠不更新，後面章節更完整的人設無法覆蓋 |

其餘結構化欄位維持 COALESCE（現有值優先，防 LLM 跨角色汙染）。

### 二、生圖階段：expand_prompt 重寫為四步（`services/llm/tasks.py`）

全程在同一 `_server_lock` 內依序執行（避免巢狀取鎖死鎖）：

1. **Step 1 場景分析** — `_SCENE_SYSTEM` + `_parse_scene_json`，輸出 JSON：`present_chars / action / location / time / atmosphere / visual_elements`。在場規則：主動說話/行動/被描寫才算在場，僅被提及不算。
2. **Step 2 篩在場角色** — 三層比對（見下）。
3. **Step 3+4 構圖融合** — `_build_composition_prompt`：每個在場角色組 `description`（人設）＋ `build_character_fragment_en()`（視覺 tags），system prompt 指示「視覺 tags 當外觀基底、人設只推情緒」；anime 輸出三段 BREAK，real 輸出結構化中文。

`build_character_fragment_en()` 刻意**不傳 seed** → 走 name-hash，服裝細節每角色固定，比 per-scene seed 更一致。

### 三、一致性審查中發現並修掉的缺陷

**Step 2 在場角色比對太脆弱**：原本只精確比對 + 「present_names 為空才 fallback」。LLM 回傳變體稱呼（「李大人」vs DB「李明」）時 0 命中卻不觸發 fallback → prompt 完全沒有外觀 tags、一致性硬錨點消失。改為三層：

1. 精確比對
2. substring 互含（容忍變體稱呼）
3. 掃原文找最長匹配名（保底，至少一個錨點）

### 四、未動的部分

Character Seed、FaceID/IP-Adapter（ArcFace embedding）、`_encode_with_break` BREAK 編碼、`_pop_composition` 構圖詞提前、`_build_negative_prompt`、DB schema 均未動。

### 待辦（已寫成 plan）

- **風險 2（架構性）**：`primary_char`（router substring → seed/FaceID）與 LLM `present_chars`（prompt 外觀）各自獨立判定，「僅被提及未在場」的角色可能被選為 primary_char → FaceID 把 A 的臉貼到描述 B 的 prompt。解法見 `plans/consistency-alignment-refactor.md`：場景分析上移 router、三者共用 `resolve_present_chars` 單一結果。
- **風險 1（待驗證）**：`description` 自由敘述可能與結構化視覺 tags 衝突（如 description「黑髮」蓋掉欄位 remap 的「dark blue hair」）。先靠生圖實測觀察跨場景穩定度再決定是否加硬約束。

---

## 2026-06-15 — §B 收尾：Library 啟動等待 UI + 人物一致性現況審查

### 一、Library.tsx 後端啟動等待 UI（§B 步驟 5）

**背景**：`lib.rs` 已實作 Job Object + sidecar 生產啟動，但前端在後端就緒前直接呼叫 API 會靜默失敗，使用者看不到任何提示。

**修正（`apps/desktop/src/pages/Library.tsx`）**：

- 新增 `backendReady` / `backendTimeout` state
- mount 時啟動輪詢：每 500ms ping `GET /health`，成功 → `backendReady=true`
- 30 秒無回應 → `backendTimeout=true`
- `fetchBooks / loadSettings / fetchHardwareInfo` 移進 `backendReady` effect，確保後端就緒後才執行
- 全屏遮罩（`z-[100]`）：
  - 等待中：amber spinner + 「後端啟動中…」
  - 逾時：`WifiOff` icon + 錯誤說明 + `npm run dev` 提示

Dev 模式下後端已由 `concurrently` 先啟，遮罩可見時間 < 500ms；生產 sidecar 模式下可優雅等待數秒。

**§B 已完成項目清單**：

| 項目 | 狀態 |
|------|------|
| `backend/config.py`（DATA_DIR / MODELS_DIR / LLAMA_BIN_DIR，frozen/dev 雙路徑） | ✅ |
| `backend/sidecar_main.py`（程式化 uvicorn，RotatingFileHandler log） | ✅ |
| `backend/vepub-backend.spec`（PyInstaller onedir spec） | ✅ |
| `lib.rs` Job Object + sidecar 啟動（dev 跳過，release 啟動） | ✅ |
| `Library.tsx` 啟動等待 UI | ✅ 本次補完 |

---

### 二、人物一致性現況審查（程式碼走讀）

全面走讀 `services/illustration/pipelines.py`、`generation.py`、`face_extractor.py`、`services/llm/tasks.py`、`routers/illustration.py`，彙整各機制的實際狀態。

#### 機制一：LLM 文字錨定 ✅ 正常

- Router 查詢所有角色，以 `char_descriptions: list[dict]` 傳入 `generate_illustration`
- `expand_prompt` 組成角色外觀區塊，LLM 依 PRESENT / NOT PRESENT 規則判斷誰在場景中
- SDXL 路徑：三段 BREAK 格式，每段獨立在 77-token 視窗編碼（截斷問題已解決）
- Z-Image 路徑：中文描述直傳 Qwen3 text encoder
- **效果**：髮色、服裝等外觀特徵跨場景穩定，但臉孔本身不一致（文字錨定的天花板）

#### 機制二：Character Seed ✅ 正常（軟約束）

同一書同一角色的 seed 固定（`md5(book_id + name)`）。相同 prompt + seed = 完全相同的圖；但不同場景 prompt 不同，seed 無法保證跨場景臉孔一致。

#### 機制三：IP-Adapter FaceID（SDXL 限定）⚠️ 有條件有效

程式碼路徑完整：角色參考圖 → InsightFace buffalo_l → ArcFace 512-dim embedding → `_generate_sync` → IP-Adapter SDXL。

**限制一**：`insightface buffalo_l` 在真人臉部資料訓練，對動畫風格角色偵測率低。偵測失敗時 `ip_face_emb = None`，IP-Adapter **靜默跳過**，退化成純文字錨定。`face_extractor.py` 已有備用降閾值重試（`det_thresh=0.3`），但效果有限。

**限制二**：Z-Image 完全不支援 IP-Adapter（`pipe._ip_adapter_loaded = False`），寫實風格只有文字錨定。

#### 機制四：ADetailer 臉部精修（SDXL 限定）✅ 正常

InsightFace 偵測人臉 → 生成羽化 mask → inpainting 精修。預設啟用（`adetailer_enabled=True`，denoise=0.4）。

---

### 三、發現 Bug：Z-Image 步數／CFG 未實際套用

**問題**：`_resolve_effective_params` 對 Z-Image 回傳 `(8, 1.5)`，但 `_generate_sync` 直接讀 `s.steps`（預設 30）而非使用此回傳值；`guidance_scale` 參數也傳入 `s.guidance_scale`（預設 6.0）。`_resolve_effective_params` 的回傳值只存進 meta dict，從未影響實際生成。

```python
# pipelines.py _generate_sync — 忽略 _resolve_effective_params 回傳值
num_steps = s.steps   # ← 讀 settings（30），Z-Image 應為 8–9
# 呼叫端傳入 guidance_scale=s.guidance_scale（6.0），Z-Image 應為 1.5
```

**後果**：Z-Image 用 30 步 + CFG 6.0（應為 9 步 + CFG 1.5）。生成不會失敗，但速度更慢，且 flow-matching 模型在高 CFG 下容易出現過飽和或 artifacts。

**待修**：在 `_generate_sync` 內部呼叫 `_resolve_effective_params` 覆寫實際使用的步數與 CFG，而非只存 meta。

---

### 現況總表

| 功能 | SDXL（動畫） | Z-Image（寫實） |
|------|------------|--------------|
| LLM 外觀描述注入 | ✅ | ✅ |
| BREAK 分段編碼 | ✅ | —（不需要）|
| IP-Adapter FaceID | ⚠️ 動畫臉偵測率低 | ❌ 不支援 |
| ADetailer 臉部精修 | ✅ | ❌（正確跳過）|
| Character Seed | ✅（軟約束） | ✅（軟約束）|
| 步數 / CFG | ✅ | ❌ bug（30/6.0，應為 9/1.5）|

---

## 2026-06-14～15 — 插圖一致性強化：IP-Adapter FaceID + BREAK 編碼 + LLM 全角色傳入

### 一、LLM 插圖 prompt：改傳所有角色描述（`routers/illustration.py`）

**問題**：舊版在 router 層對每個角色把結構化欄位手動拼成 danbooru tags（`char_tags` 組裝），再傳入 `generate_illustration`。這個做法繞過 LLM，無法根據場景文本判斷誰在場景中。

**修正**：
- 移除 `char_tags` 整個組裝區塊（原 ~80 行）
- 改為：輕量掃描文字找出 `primary_char`（僅供 IP-Adapter 取參考圖），然後查詢 DB 取出所有角色，以 `char_descriptions: list[dict]` 整包傳入 `generate_illustration`
- LLM 讀到角色資料庫後，自行判斷場景中哪些角色物理在場、哪些只是被提及

```python
char_descriptions = [dict(r) for r in conn.execute(
    "SELECT * FROM characters WHERE book_id=?", (req.book_id,)
).fetchall()]
```

---

### 二、IP-Adapter FaceID 修正（`services/illustration/pipelines.py`）

**問題一：`image_encoder_folder` 造成 "model.safetensors" 找不到**

FaceID 使用 ArcFace 人臉嵌入，不需要 CLIP image encoder。但 `load_ip_adapter` 預設會嘗試載入 `image_encoder/model.safetensors`，找不到就報錯。

**修正**：
```python
pipe.load_ip_adapter(..., image_encoder_folder=None)
```

**問題二：PIL Image 傳入 `ip_adapter_image_embeds` 格式錯誤**

`_generate_sync` 期望的是 `(512,)` numpy ArcFace 嵌入，但 router 傳入的是 PIL Image。

**修正（`services/illustration/generation.py`）**：
```python
# 在 _generate_sync 之前先提取嵌入
emb, _ = await loop.run_in_executor(None, extract_face, ip_adapter_image)
ip_face_emb = emb[0].numpy()  # (512,) float32

# _generate_sync 裡再 unsqueeze 成 (1, 1, 512)
ip_embeds = ip_adapter_image_embeds.unsqueeze(0).unsqueeze(0)
```

**結果**：`[illustration] IP-Adapter FaceID SDXL 已載入` 確認出現於 log ✅

---

### 三、LoRA 選擇 UI（`SettingsPanel.tsx` + `routers/illustration.py` + `services/illustration/settings.py`）

**新增 `LoraEntry` model**：
```python
class LoraEntry(BaseModel):
    filename: str
    weight: float = 1.0
    enabled: bool = True

class IllustrationSettings(BaseModel):
    ...
    active_loras: list[LoraEntry] = []
```

**新增 `GET /illustration/loras` 端點**：掃描 `models/loras/` 目錄，回傳可用 LoRA 清單（含 `size_mb`）。

**前端**：設定面板「LoRA」區塊，每個 LoRA 有 toggle（啟用/停用）+ weight 滑桿（0.1–2.0）。變更後需重新載入模型才生效（有提示）。

**FaceID LoRA 自動載入（`pipelines.py`）**：
```python
_FACEID_LORA = "ip_adapters/ip-adapter-faceid_sdxl_lora.safetensors"
if os.path.isfile(_FACEID_LORA) and pipe._ip_adapter_loaded:
    pipe.load_lora_weights(_FACEID_LORA, adapter_name="faceid_lora")
```

---

### 四、BREAK 編碼實作（`services/illustration/pipelines.py`）

**問題**：diffusers SDXL 的 CLIP tokenizer 嚴格限制 77 tokens，超出部分直接截斷。A1111 的 `BREAK` 關鍵字在 diffusers 裡只是普通英文單字，毫無作用。

**LLM 仍在輸出有效 prompt，只是被截斷**（確認自 log）：
```
Truncation was needed, but `truncation` is not set to `True` [...]
truncated: [', laughing, blushing, confused, indoor room, soft lighting, medium shot']
```

**正確解法**：在 diffusers 裡手動實作 BREAK 語義：每段獨立進行 CLIP 編碼（各自 77-token 視窗），然後沿 sequence 維度串接 hidden states 後傳入 pipeline。

**新增 `_encode_with_break(pipe, text, device, clip_skip=2)`**：
```python
def _encode_with_break(pipe, text, device, clip_skip=2):
    segments = [s.strip() for s in text.split("BREAK") if s.strip()]
    for seg in segments:
        # CLIP-L: hidden_states[-(clip_skip+1)]
        # CLIP-G: hidden_states[-2]
    e1 = torch.cat(all_e1, dim=1)   # (1, 77*n, 768)
    e2 = torch.cat(all_e2, dim=1)   # (1, 77*n, 1280)
    return torch.cat([e1, e2], dim=-1), pooled  # (1, 77*n, 2048)
```

**`_generate_sync` BREAK-aware 分支**：
```python
_use_break = "BREAK" in prompt and not is_wan and not is_zimage
if _use_break:
    kwargs["prompt_embeds"] = _p_emb
    kwargs["negative_prompt_embeds"] = _n_emb
    kwargs["pooled_prompt_embeds"] = _p_pool
    kwargs["negative_pooled_prompt_embeds"] = _n_pool
```

**Hires Fix / ADetailer 相容**：兩者為 img2img/inpainting，構圖已定；只取第一 BREAK 段（品質+外觀 tags）傳入：
```python
_prompt_hires = prompt.split("BREAK")[0].strip() if "BREAK" in prompt else prompt
```

---

### 五、LLM system prompt 改回三段 BREAK 格式（`services/llm/tasks.py`）

底層 BREAK 編碼確認可用後，恢復三段式輸出，每段都不超過 77 tokens：

| 段 | 內容 | 上限 |
|----|------|------|
| Segment 1 | subject count、髮色、眼色、服裝 | ≤15 tags |
| Segment 2 | 動作、姿勢、表情、服裝細節 | ≤12 tags |
| Segment 3 | 背景、時間、打光（限1）、構圖（限1） | ≤8 tags |

含品質前綴（`lazypos, score_9, ...` ~11 tokens）後，每段仍遠低於 77-token 限制，不再有任何截斷。

**角色 PRESENCE 規則**：
- `PRESENT` = 角色在片段中物理出現（說話、行動、外觀被描寫）
- `NOT PRESENT` = 角色只在他人對話中被提及，不列入 subject count

---

### 修正摘要

| 檔案 | 變更 |
|------|------|
| `routers/illustration.py` | 移除 char_tags 組裝，改傳 `char_descriptions: list[dict]` 給 LLM；新增 `GET /loras` |
| `services/illustration/pipelines.py` | `load_ip_adapter` 加 `image_encoder_folder=None`；新增 `_encode_with_break()`；`_generate_sync` BREAK-aware 分支；hires/adetailer 取第一段 |
| `services/illustration/generation.py` | IP-Adapter 路徑：先 `extract_face()` 取嵌入，再傳 numpy 給 `_generate_sync` |
| `services/illustration/settings.py` | 新增 `LoraEntry` model；`IllustrationSettings` 加 `active_loras` |
| `services/llm/tasks.py` | system prompt 改三段 BREAK 格式，每段限 8–15 tags |
| `apps/desktop/src/components/reader/SettingsPanel.tsx` | LoRA 選擇 UI（toggle + weight 滑桿） |
| `apps/desktop/src/lib/api.ts` | `LoraInfo` interface；`listLoras()`；`active_loras` 欄位 |

---

## 2026-06-10～11 — 全專案優化：效能熱點、穩定性修正、前端重構

依據 `OPTIMIZATION.md` 的分析結果，系統性處理 P0 效能熱點、P1 正確性問題，以及中低風險的 P2/P3 項目。

---

### 一、P0 效能熱點（第一批 quick wins）

#### §1.1 spaCy 模型快取（`backend/services/text_chunker.py`）

**問題**：每次翻章呼叫 `TextChunker(language=...)` 都重新執行 `spacy.load()`，耗時數百 ms 到秒級。

**修正**：在模組層級建立 `_nlp_cache: dict[str, Any] = {}`，`_load_nlp()` 先查快取再載入，同語言模型全行程只載入一次。

```python
_nlp_cache: dict[str, Any] = {}
def _load_nlp(language):
    lang_key = next((k for k in _MODEL_MAP if language.startswith(k)), None)
    if lang_key in _nlp_cache: return _nlp_cache[lang_key]
    nlp = spacy.load(_MODEL_MAP[lang_key])
    _nlp_cache[lang_key] = nlp
    return nlp
```

#### §1.2 移除每句 TTS 的 GC（`backend/services/gpu_manager.py`）

**問題**：`release_gpu()` 對所有任務都執行 `gc.collect()` + `torch.cuda.empty_cache()`，連續朗讀時每句都觸發一次，直接拖慢句間銜接。

**修正**：`release_gpu()` 只在插圖任務（`illustration_sdxl` / `illustration_zimage`）完成後執行 GC，TTS 的 `release_gpu()` 跳過。

#### §1.6 串流模式預設步數（`apps/desktop/src/stores/player.ts`）

**修正**：`numStep` 預設值從 32 改為 16，首句延遲砍半；SettingsPanel 保留「32 步（高品質）」選項供使用者切換。

---

### 二、P0 效能熱點（第二批核心體驗）

#### §1.4 VRAM 雙鎖仲裁（`backend/services/gpu_manager.py` 完整重寫）

**問題**：TTS（4 GB）與 SDXL（8 GB）共用同一把互斥鎖，生圖全程（模型載入 ~20s + 擴散 ~25s+）持鎖，邊聽邊生圖時朗讀停頓超過 40 秒。

**新設計**：兩鎖架構
- `self.lock`：TTS ↔ ZImage 互斥（ZImage 21GB + TTS 4GB = 25GB，貼近上限）
- `self.illus_lock`：插圖序列化（防止多張同時生圖）
- `asyncio.Event _analysis_done`：取代 `while ... sleep(3)` busy-wait

| 任務 | 持鎖行為 |
|------|---------|
| `tts` | 僅 `lock` |
| `illustration_sdxl` | 僅 `illus_lock`（TTS 可並行） |
| `illustration_zimage` | `illus_lock` + `lock`（TTS 排隊） |
| `analysis` | 不持鎖，但卸載插圖模型並清除 `_analysis_done` |

#### §1.3 LLM server keep-alive（`backend/services/llm_engine.py`）

**問題**：每次 LLM 推論都冷啟動 27B（磁碟載入數十秒）再關閉，`expand_prompt` 的 LLM 啟動時間常超過實際推理時間。

**新設計**：
- `_ensure_server(path, n_ctx)`：若目前 server 同模型且 `_server_ctx >= n_ctx`，直接複用，不重啟
- `_arm_idle_stop()`：推論結束後啟動 300 秒 idle TTL 計時器，逾時才關閉
- `stop_server_now()`：插圖任務啟動前主動踢除 LLM（釋放 VRAM）
- 所有五個推論函式從「啟動→推理→關閉」改為「ensure→推理→arm_idle」

#### §1.5 useAudioStream 每句重連修正（`apps/desktop/src/hooks/useAudioStream.ts`）

**問題**：`connectAndPlay` 的 `useCallback` 依賴 `currentSentenceIndex`，每次自動高亮前進都產生新 callback identity，觸發 effect cleanup → `ws.close()` + 重連，PREFETCH=3 的預取效果形同失效。

**修正**：
- `ws.onopen` 改從 `usePlayerStore.getState().currentSentenceIndex` 即時讀取，不放入 closure
- `connectAndPlay` 的 deps 移除 `currentSentenceIndex`
- `BACKEND_WS` 改從 `@/lib/constants` 的 `BACKEND_WS_URL` 衍生

---

### 三、P1 正確性與穩定性

#### §2.1 404 被外層 except 吃掉（`backend/routers/epub.py`）

在 `get_chapter_paragraphs` 的 `except Exception` 前加 `except HTTPException: raise`，確保 404 正確回傳而非被包裝成 500。

#### §2.3 同步 IO 移出 event loop

- **`illustration.py`**：`list_illustrations`、`list_characters` 的 SQLite 查詢（含 MB 級 base64）改用 `run_in_executor` 包覆，避免序列化期間阻塞 TTS WebSocket 訊息收發
- **`epub.py`**：`shutil.copyfileobj` 大檔寫入改為 `await file.read()` + `loop.run_in_executor(None, save_path.write_bytes, file_bytes)`；模組內重複的函式內 `import asyncio` 全部提升至檔案頂層

#### §2.4 Schema migration 改 PRAGMA 查詢（`backend/routers/illustration.py`）

**問題**：24 條 `ALTER TABLE` 逐條 `try/except pass` 吞掉所有錯誤，每次啟動都執行 24 次注定失敗的 SQL，且磁碟錯誤也無聲消失。

**修正**：抽出 `_ensure_columns(conn, table, col_defs)` helper，先 `PRAGMA table_info()` 取得現有欄位集合，只 ALTER 缺少的欄，非預期錯誤以 `print` 記錄（不吞）。

#### §2.5 批次字元上限下調（`backend/services/llm_engine.py`）

`_BATCH_CHARS` 從 55,000 降至 35,000，避免中文 token 估算偏緊時超出 65536 ctx 導致截斷。

#### §2.6 kill 驗證行程名（`backend/services/llm_engine.py`）

`_kill_existing_server()` 在 kill 前確認 `proc.name().lower() in ("llama-server.exe", "llama-server")`，避免誤殺同 port 的其他行程。

#### §2.7 EPUB 解析三項修正（`backend/services/epub_parser.py`）

| 子項 | 問題 | 修正 |
|------|------|------|
| §2.7a 快取 | `lru_cache` 的 `cache_clear()` 清空全部，刪一本書導致其他書重新解析 | 改 dict 快取 + `invalidate_cache(filepath)` 單鍵失效 |
| §2.7b 封面 | 只認 `get_item_with_id("cover-image")`，許多 EPUB 封面顯示不出來 | 補 4 段 fallback：OPF meta name / EPUB3 properties / 檔名啟發式 |
| §2.7c 解析器 | `BeautifulSoup(..., "lxml")` 觸發 `XMLParsedAsHTMLWarning` | 改 `"html.parser"` |

---

### 四、P2 後端架構

#### §3.2 刪除 `_chapters_data`（`backend/routers/epub.py`、`apps/desktop/src/lib/api.ts`）

`/epub/parse` 回傳移除全書段落內文（前端未使用，一本小說可達數 MB）；`api.ts` 的 `ParseResult` interface 同步刪除 `_chapters_data` 欄位。

#### §3.3 補資料庫索引（`backend/routers/illustration.py`）

```sql
CREATE INDEX IF NOT EXISTS idx_illustrations_book_chapter
    ON illustrations(book_id, chapter_index);
CREATE INDEX IF NOT EXISTS idx_character_images_character_id
    ON character_images(character_id);
```

#### §4.2 effective params 單一來源（`backend/services/illustration_engine.py`）

抽出 `_resolve_effective_params(pipe, settings) -> (steps, cfg)`，`_generate_sync` 與 `generate_illustration` meta 計算共用同一套邏輯，消除兩份重複規則（turbo→8步CFG1 / zimage→28步CFG4 / wan→clamp）。

`acquire_gpu` 的任務型態依架構動態決定：`"illustration_sdxl"` 或 `"illustration_zimage"`，不再一律傳 `"illustration"`。

#### §4.3 print → logging（`tts_engine.py`、`gpu_manager.py`）

兩個檔案全部 `print()` 改為 `logging` 模組：

- 模型載入、切換、卸載 → `logger.info`
- GPU 鎖取得/釋放 → `logger.debug`（高頻，不需預設顯示）
- 模型未載入警告 → `logger.warning`
- 合成模式（clone/design/auto）→ `logger.debug`

---

### 五、P2 前端重構

#### §5.1 usePolling 共用 hook（`apps/desktop/src/hooks/usePolling.ts`）

新增：

```ts
export function usePolling(
  callback: () => void | Promise<void>,
  intervalMs: number,
  enabled: boolean,
) {
  const callbackRef = useRef(callback);
  callbackRef.current = callback;
  useEffect(() => {
    if (!enabled) return;
    const id = setInterval(() => { callbackRef.current(); }, intervalMs);
    return () => clearInterval(id);
  }, [enabled, intervalMs]);
}
```

- `Reader.tsx`：移除 `pollRef`，生圖任務輪詢改用 `usePolling(..., 1000, hasActiveTasks)`
- `CharacterPanel.tsx`：移除 `analysisTimer`、`angleTimer`，全書分析（2.5s）、多視角任務（3s）各改用 `usePolling`

#### §5.2 paragraphsMap useMemo（`apps/desktop/src/pages/Reader.tsx`）

`paragraphsMap` 以 `useMemo([sentences])` 包覆，避免每秒輪詢觸發的 render 都重建句子→段落映射（長章節千句時明顯）。

#### §5.5a 後端 URL 常數（`apps/desktop/src/lib/constants.ts`）

新增 `constants.ts`，抽出 `BACKEND_BASE_URL` 與 `BACKEND_WS_URL`；`api.ts`、`model-api.ts`、`useAudioStream.ts` 改從此處 import，消除散落的硬編碼位址。

#### §5.5b 音量持久化（`reader.ts`、`PlayerBar.tsx`、`useAudioStream.ts`）

- `reader.ts`：新增 `volume: number`（預設 80）、`setVolume` action，`loadSettings` / `saveSettings` 連動 SQLite `settings` 表的 `volume` 鍵
- `PlayerBar.tsx`：本地 `useState(80)` 改從 `useReaderStore()` 讀取；滑桿變更時同步呼叫 `changeVolume(val)`（更新 GainNode）與 `setVolume(val)`（持久化）
- `useAudioStream.ts`：GainNode 初始化改從 `useReaderStore.getState().volume / 100` 讀取，重啟後音量立即恢復

#### §5.5c Library 刪除確認 Modal（`apps/desktop/src/pages/Library.tsx`）

將 `window.confirm()` 替換為 React 狀態驅動的確認對話框：

- `deleteTargetId` state 控制開關
- `handleDeleteBook` 只設定 state，`confirmDelete` 才執行刪除
- Modal：背景半透明 + backdrop-blur，點擊遮罩或「取消」關閉，「刪除」按鈕紅色強調

---

### 六、已知問題與後續

| 優先 | 項目 | 說明 |
|------|------|------|
| 中 | §2.8 重複匯入去重 | 同一 EPUB 重複匯入建多筆記錄，建議 sha256 前 16 bytes 查重 |
| 中 | §3.1 圖片移出 DB | base64 存 SQLite 導致 DB 快速膨脹，需落地為檔案 + 圖片 URL endpoint |
| 中 | §3.4 設定雙軌統一 | `illustration_settings.json` 與 SQLite `settings` 表並存，需整合 |
| 低 | §6.3 後端常數集中 | port 18765、VRAM 估計值、polling 間隔等 magic number 散落各檔 |
| 低 | §4.1 巨型檔案拆分 | `illustration.py`（1174行）、`llm_engine.py`（1230行）|
| 低 | §6.1 單元測試 + CI | 純函數（JSON 解析、別名合併、TextChunker）補 pytest，不需 GPU |

---

## 2026-06-07 — 插圖 Pipeline 重構：兩階段生成 + 雙模型角色特徵格式 + 詳情面板

### 一、兩階段 prompt 生成（同一 server session）

**問題根源**：舊版 `expand_prompt()` 單一 LLM call 同時承擔「理解劇情、套用角色特徵、決定構圖、輸出格式化標籤」四件事，互相干擾，構圖隨機性高，角色特徵容易被稀釋。

**新架構（`backend/services/llm_engine.py`）**：

```
detect_is_anime()               ← 同步，查 registry，不需 LLM

start 27B server
  │
  ├─ Stage A  [兩種模型共用]
  │   輸入：段落原文 + 已知角色中文外觀
  │   輸出：結構化視覺腳本（人物/環境/光線/構圖/情緒）
  │   max_tokens=150, temp=0.3
  │
  ├─ Stage B  [按模型分叉]
  │   ┌ anime (Hassaku SDXL)
  │   │  輸入：Stage A 腳本 + character_caption_en（English danbooru tags）
  │   │  輸出：英文 danbooru tags（30-50 個）
  │   │  prefill="masterpiece, best quality, ..."
  │   │
  │   └ real (Z-Image Turbo)
  │      跳過 LLM：直接組合 Stage A 腳本 + character_caption（中文）
  │      Qwen3 text encoder 可直接理解結構化中文
  │
stop 27B server
```

- real 模型省掉一次 LLM inference，延遲比舊版更短
- 抽出 `_clean_llm(text)` helper，Stage A / Stage B 共用，不重複
- Stage B system prompt 明確禁止輸出 quality prefix tags（修正重複 `masterpiece, best quality…` 的 bug）

---

### 二、雙模型角色特徵格式

**問題**：`build_character_fragment()` 只輸出中文自然語言，傳給 SDXL/Illustrious 的 CLIP text encoder 效果差；應用 danbooru tag 格式。多角色時片段沒有角色名前綴，LLM 無法區分特徵所屬。

**修正（`backend/routers/illustration.py`）**：

| | 舊版 | 新版 |
|---|---|---|
| 角色特徵格式 | 單一 `character_desc`（中文） | `character_desc`（中文）+ `character_desc_en`（English danbooru tags）|
| 多角色前綴 | 無（`"女，銀髮，藍瞳"` 直接拼接） | 有（`"玲：女，銀髮，藍瞳；樂天：男，黑髮"` / `"玲: 1girl, silver hair; 樂天: 1boy"`) |

`character_caption_en` 貫通三層介面：
```
_run_task() → generate_illustration() → _expand_prompt() → expand_prompt()
```

`expand_prompt()` 新增 `character_caption_en` 參數，anime 分支優先用 danbooru tags，real 分支用中文自然語言。

---

### 三、插圖元資料儲存與展示

**`backend/services/illustration_engine.py`**：

`generate_illustration()` 回傳由 3-tuple 改為 4-tuple `(bytes, prompt, is_anime, meta)`：

```python
meta = {
    "model_name":     entry.get("name"),   # 模型名稱（從 registry 取）
    "steps":          effective_steps,      # 已套用各模型 override 後的實際步數
    "guidance_scale": effective_cfg,        # 已套用 override 後的實際 CFG
    "seed":           seed,                 # 實際使用的 seed（含隨機生成的）
    "width":          width,
    "height":         height,
}
```

**`backend/routers/illustration.py`**：

- `illustrations` 表新增 7 欄：`model_name, steps, guidance_scale, seed, width, height, is_anime`（向下相容 ALTER TABLE）
- INSERT 寫入 meta；task result 和 `list` API 均回傳完整 meta
- backend adapter 路徑（`backend.generate()`）兼容回傳 3 或 4 元素 tuple

**前端（`IllustrationCard.tsx`）**：

ℹ️ 按鈕展開 inline 詳情面板（與「存為角色」互斥）：

| 欄位 | 顯示 |
|------|------|
| 完整提示詞 | 可捲動 monospace 區塊 + 一鍵複製 |
| 模型 | 去除 `.safetensors` 後綴顯示 |
| 風格 | 動畫（粉色）/ 寫實（藍色）|
| 步數 / CFG / Seed / 解析度 | 2 欄格線排列 |

`api.ts` 抽出 `IllustrationMeta` interface，`IllustrationTaskResult` extends 它；`getChapterIllustrations` 回傳型別同步更新，重新載入章節時可從 DB 恢復 meta。

---

### 四、已知問題

| 項目 | 說明 |
|------|------|
| 角色識別仍用 substring match | `name in text`，代詞/暱稱/稱謂 會漏偵測；後續可用 LLM 在 Stage A 之前做一次輕量角色識別 |
| `build_character_fragment_en()` 無特殊特徵對應 | `special_traits / accessories / distinctive_marks` 等欄位在英文版被捨棄，後續可直接把原文附進 user_msg 讓 LLM 自行翻譯 |

---

## 2026-06-06 — 圖像模型遷移：WAI ANIMA 棄用 → Hassaku XL + Z-Image 元件修復

### 一、WAI ANIMA 架構誤判 → 棄用

**問題**：角色設定圖輸出全為 noise。

**根本原因**：WAI ANIMA 實際架構為 **NVIDIA Cosmos / Anima BASE 1.0**（不是 Wan2.1）。用 `WanTransformer3DModel` 載入時有 825 個 missing key / 685 個 unexpected key，模型根本沒有正確初始化。

**處置**：
- 棄用 WAI ANIMA，清除 `.wan_cache/`
- 切換到 **Hassaku XL Illustrious v3.4**（標準 SDXL，CivitAI）
- `_load_sdxl_pipe_sync`：從 `AutoPipelineForText2Image.from_single_file`（0.39.0.dev0 不支援）改為 `StableDiffusionXLPipeline.from_single_file`

---

### 二、模型目錄組織

- `downloader.py` 的 `_dest_path()` 加入 `_CATEGORY_SUBDIR`，依類型將模型分配至 `models/image/`、`models/llm/`、`models/tts/`
- `.gitignore` 加入三個子目錄

---

### 三、LLM prompt 語言修正（SDXL 需要英文）

**問題**：Illustrious XL / Hassaku XL 只支援英文 danbooru tag 格式，原本 `expand_prompt` 輸出中文句子。

**修正（`backend/services/llm_engine.py`）**：
- System prompt 改為要求輸出英文逗號分隔 danbooru 標籤（30–60 tags）
- `is_anime` 偵測：先看 `style_hint` 關鍵詞，找不到時 fallback 讀 registry active model 的 `style` 欄位

---

### 四、角色設定圖提示詞重構

**問題**：生成幾十個 Q 版人物、品質低劣。

**根本原因**：舊提示詞使用 `"character design sheet"`, `"multiple views"`, `"side profile"`, `"3/4 view"` → SDXL 把整張畫塞進多個小人，觸發 chibi 風格。

**修正（`backend/services/illustration_engine.py`）**：

| 項目 | 變更 |
|------|------|
| `steps` | 28 → 20 |
| `guidance_scale` | 7.0 → 6.5 |
| `sheet_width × sheet_height` | 1216×832（橫向）→ 832×1216（直向） |
| `negative_prompt` 基底 | 改為 Illustrious XL 標準：`worst quality, bad quality, ...` |

**新增函數**：

- `build_character_fragment_en(char)` — char dict → 英文 danbooru tag（gender, hair color/style, eye color, skin tone, body type）
- `_build_negative_prompt_sheet(is_anime, is_turbo)` — 在基底負向上加 `chibi, multiple characters, multiple views, reference sheet, q version, super deformed`

**`generate_character_sheet` 分支邏輯**：
```
is_anime=True  (Hassaku XL/SDXL)
  → 英文 danbooru tags：masterpiece, best quality, absurdres, highres, very aesthetic, {en_tags},
      solo, full body, standing, simple white background, looking at viewer, front view...

is_anime=False (Z-Image/Qwen)
  → 中英混合：超高清, 极致细节, 顶级画质, masterpiece, best quality, ultra detailed, 8k,
      full body portrait of {name}, {zh_desc}, standing, white background...
```

---

### 五、`_infer_is_anime` fallback 修正

**問題**：切換到 Z-Image 後，角色設定圖仍走 Hassaku XL 分支（`_infer_is_anime` 在 `prompt_prefix` 為空時一律回傳 `True`）。

**修正**：無關鍵詞時，fallback 讀 registry `image.active` model 的 `style` 欄位：
```python
return m.get("style", "anime") != "real"
```

---

### 六、Z-Image 參數校正

依實際使用者參考資料（cfgScale=1, steps=9, sampler=sa_solver）修正：

| 項目 | 改前 | 改後 |
|------|------|------|
| `guidance_scale` (turbo) | 0.0 | 1.0 |
| `steps` (turbo) | `min(steps, 8)` | `min(steps, 9)` |
| negative prompt (turbo) | 完整 base | `"blurry, ugly, bad quality, deformed"` 極簡 |

`is_turbo` 的判斷移到 `pipe` 載入後（`getattr(pipe, "_is_turbo", False)`），確保 negative prompt 在知道模型類型後才構建。

---

### 七、Z-Image 元件載入修正

**問題**：CivitAI 下載的 `.safetensors` 只含 DiT transformer 權重，`text_encoder` / `vae` 均缺失，`from_single_file` 連續報錯。

**架構說明**：
- Z-Image text encoder = Qwen3-4B（36 層，hidden_size=2560，~8 GB bfloat16）
- VAE、tokenizer、scheduler 同樣需從 HuggingFace 取得
- `Tongyi-MAI/Z-Image-Turbo` 完整 repo = 32.9 GB；transformer 部分 ≈ 12 GB（跳過，用 CivitAI 檔案）

**修正（`backend/services/illustration_engine.py`）**：

新增 `_ensure_zimage_components()`：
```python
snapshot_download(
    repo_id="Tongyi-MAI/Z-Image-Turbo",
    local_dir=_ZIMAGE_CACHE,
    local_dir_use_symlinks=False,
    ignore_patterns=["transformer/*", "*.md", "assets/*"],
)
```
首次執行下載 ~8–10 GB（text_encoder + tokenizer + vae + scheduler），之後直接讀快取。

`_load_zimage_pipe_sync` 更新：
```python
text_encoder = Qwen3Model.from_pretrained(te_path, torch_dtype=torch.bfloat16)
tokenizer    = Qwen2Tokenizer.from_pretrained(tok_path)
vae          = AutoencoderKL.from_pretrained(vae_path, torch_dtype=torch.bfloat16)
pipe = ZImagePipeline.from_single_file(model_path,
    text_encoder=text_encoder, tokenizer=tokenizer, vae=vae,
    torch_dtype=torch.bfloat16)
```

`.gitignore` 加入 `.zimage_cache/`。

**預估 VRAM（Z-Image 完整載入）**：
- DiT transformer（CivitAI）：~12 GB
- Qwen3-4B text encoder：~8 GB
- VAE：~0.3 GB
- 合計：≈ 20 GB（25.7 GB 上限內）

---

### 已知狀態

| 項目 | 狀態 |
|------|------|
| Hassaku XL（anime）人設圖 | prompt 格式已修正，待生圖驗證 |
| Z-Image（real）人設圖 | 元件載入修正，首次需下載 ~8–10 GB |
| Z-Image scheduler 相容性 | 參考使用 `sa_solver`；diffusers 內建 `FlowMatchEulerDiscreteScheduler`，若有差異可能需再調整 |

---

## 2026-06-05 — 全書掃描取樣策略改良：外觀偏置取樣 + 句子窗口

### 問題

原有 `analyze_characters` 對每個 100 句 block 做**均勻取樣**（每 10 句取 1 句），造成兩個根本問題：

1. **外觀段命中率低**：小說的外觀描寫高度集中（初見特寫），但均勻取樣可能整個 block 10 句全是對話或打鬥，外觀段全部跳過。
2. **缺少角色名稱上下文**：孤立的 1 句（如「她的眼眸如星」）LLM 無法確定指誰，提取品質差。

### 修正（`backend/services/llm_engine.py`）

**新增 4 個輔助函式（不改 LLM 呼叫次數）：**

| 函式 | 說明 |
|------|------|
| `_APPEARANCE_KW` | 外觀關鍵詞 frozenset（眼/髮/臉/穿/英俊/苗條…等 37 個詞） |
| `_appearance_score(s)` | 計算一句話包含幾個外觀關鍵詞，O(n) 字串掃描 |
| `_biased_sample(sentences, k)` | 取代均勻取樣：2/3 選外觀分最高的句子，1/3 均勻分布確保角色名覆蓋 |
| `_with_context(sentences, selected, window=1)` | 為每個選出句補前後 1 句，讓 LLM 同時看到角色名與外觀描述；輸出保持原始順序不重複 |

**`analyze_characters` 取樣邏輯（~760 行）**：

```python
# 改前：均勻取樣
step    = blen / sample_k
sampled = [block[int(j * step)] for j in range(sample_k)]

# 改後：偏置取樣 + 上下文窗口
sampled = _biased_sample(block, sample_k)
sampled = _with_context(block, sampled, window=1)
```

### 預期效果

| 指標 | 改前 | 改後 |
|------|------|------|
| LLM 呼叫次數 | 基準 | 不變 |
| 額外計算成本 | — | O(n) 字符串掃描（毫秒級） |
| 外觀段命中率 | ~10%（均勻） | ~60–70%（偏置） |
| 每句角色識別率 | 低（無上下文） | 高（有前後句） |
| 每次輸入 token 量 | 基準 | +10–20%（窗口句） |

---

## 2026-06-03 — LoRA 整合 + 統一繪圖設定 + 多人提取修正

### 一、CharacterDesign LoRA 整合

**檔案**：`backend/services/illustration_engine.py`

`models/loras/CharacterDesign-IZT-V1.safetensors`（YeiyeiArt，Civitai #100435）整合進生圖 pipeline。

- `_LORA_DIR`、`_CHARDESIGN_LORA` 常數指向 `models/loras/` 目錄
- `_load_chardesign_lora_sync(pipe, weight)` — 載入 LoRA 並設強度，失敗 graceful fallback
- `_unload_lora_sync(pipe)` — 生成後立即卸載，不污染後續普通插圖
- `list_loras()` — 掃描 `models/loras/*.safetensors`
- **兩個 generate 函數都能套用 LoRA**（`lora_weight > 0` 時自動載入）
- `generate_character_sheet` 的角色設定圖：加入觸發詞 `CharacterDesignIZT`，三視角（正面全身、頭像、側面）+ 色盤，解析度從 1536×1024 改為 1216×832（Civitai 推薦橫幅）

---

### 二、統一繪圖設定（IllustrationSettings）

**問題**：`steps=8`、`guidance_scale=1.0`、quality suffix、LoRA 強度、預設解析度各自散落在不同地方，且部分設定只有 character sheet 能用。

**新增 `IllustrationSettings`（Pydantic model）**：

| 欄位 | 預設 | 說明 |
|------|------|------|
| `steps` | 8 | 擴散步數 |
| `guidance_scale` | 1.0 | CFG Scale |
| `lora_weight` | 0.8 | LoRA 強度（0 = 停用） |
| `style` | `"anime"` | `anime` / `semi_realistic` / `realistic` |
| `width` / `height` | 1024 | 一般插圖預設解析度 |
| `sheet_width` / `sheet_height` | 1216 / 832 | 角色設定圖預設解析度 |

- `QUALITY_SUFFIX_REAL/ANIME` 合併成 `QUALITY_SUFFIX` dict，by style key
- `_generate_sync` 從 `_settings` 讀 steps / guidance_scale
- 設定持久化到 `backend/illustration_settings.json`，重啟不丟失
- `get_settings()` / `update_settings(patch)` 公開介面

**新增 API（`backend/routers/illustration.py`）**：
- `GET /illustration/settings` — 讀目前設定
- `PATCH /illustration/settings` — 部分更新（只傳要改的欄位）
- `GET /illustration/loras` — 列出可用 LoRA 檔案
- 移除 router 裡的 `_SHEET_WIDTH/HEIGHT` 重複常數
- `GenerateAnglesRequest.width/height` 改為 `None`，runtime 從設定解析

---

### 三、選取段落提取角色 → 改用 27B 模型

`extract_character_features` 改呼叫 `find_analysis_gguf()`（優先選 27B），比原本 4B 對長段落和複雜情境的理解更準。

---

### 四、選取提取支援多人 + CharacterPickerModal

**動機**：一段文字可能同時描述多個角色，原本只回傳一個物件，資訊丟失。

**後端（`llm_engine.py`）**：
- `extract_character_features` 改回傳 `list[dict]`
- System prompt 改為陣列格式，提取段落中所有有外觀描寫的角色
- 每個角色已套用 `_apply_defaults`，router 不再重複呼叫

**前端**：
- `api.ts`：`extractCharacterFeatures` 回傳型別改 `Promise<Partial<Character>[]>`
- `Reader.tsx`：
  - 0 人 → toast 提示「未偵測到角色描述」
  - 1 人 → 直接開 `CharacterEditModal`（舊行為）
  - 多人 → 開 `CharacterPickerModal`
- 新建 `CharacterPickerModal.tsx`：列出所有候選角色（名字、性別、簡短外觀），點選任一進 edit modal

---

### 五、JSON 解析修正（`_parse_character_json`）

**根本問題鏈**：

1. `prefill="["` + 模型輸出 `[{...}]` = raw `[[{...}]]`（雙括號）
2. 舊處理：移掉開頭 `[` → `[{...}]]`，regex 貪婪抓到最後 `]`，`json.loads` 失敗
3. 即使修正 `]]` → `]`，若模型在 JSON 後面加說明文字（含 `]`），regex 仍失效
4. `max_tokens=1200` 不足以裝下兩個角色的完整 JSON → JSON 截斷，任何 parser 都失敗

**最終修正**：

```
策略 1（正常路徑）：
  raw_decode(s, idx) 從第一個 [ 開始精確解析，
  遇到合法 JSON 結尾就停止，完全無視後面的 ]]、說明文字等

策略 2（截斷 fallback）：
  逐個用 raw_decode 擷取已完整的 {...} 物件，
  部分截斷時至少能拿到前面完整的角色
```

- `max_tokens` 從 1200 → 4096（8192 context 框架下安全上限）
- `n_ctx` 從 4096 → 8192（配合多角色輸出需求）
- 輸入文字截斷改為前後各 1000 字（保留開頭介紹和結尾描寫）
- 同樣修正套用到 `find_alias_groups` 的 inline 解析

**除錯工具（暫留）**：
- `extract_character_features` 有 `parsed=N chars, names=[...]` 和 `returning=...` 兩行 debug print，待確認穩定後移除

---

### 已知待辦

| 項目 | 說明 |
|------|------|
| debug print 清理 | `llm_engine.py` 提取角色的詳細 log 待移除 |
| BeautifulSoup XMLParsedAsHTMLWarning | `epub_parser.py` 解析 epub 時觸發，改用 `features="xml"` 可消除 |

---

## 2026-06-02（下午）— 角色庫全面重構：LLM 情境推斷 + 批次操作

### 一、角色屬性補完架構重構

**問題根源**：原本 `_apply_defaults` 使用硬編碼 keyword 推斷情境欄位（如「帝/皇 → 龍袍」、「太后 → 盤髮」），換一本書就完全失效。

**新架構**（`backend/services/llm_engine.py`）：

| 欄位類型 | 決策者 | 說明 |
|----------|--------|------|
| `age_hint` / `body_type` / `hair_style` / `signature_outfit` | **LLM** | 由 `_infer_contextual_fields` 批次推斷 |
| `hair_color` / `eye_color` | 程式碼 | 預設「黑色」，東亞小說普遍適用 |
| `height_cm` / `weight_kg` | 程式碼 | 性別平均值（女 162/男 175） |
| `bwh` / `cup_size` | 程式碼 | 體型公式計算 |
| `gender` | LLM → 名字後綴 fallback | 從文字推斷，空時看姑/妹/姐等後綴 |

**新增函數**：
- `_infer_contextual_fields(chars)` — 使用已啟動的 server，批次推斷缺少的情境欄位
- `_infer_and_merge(accumulated)` — 分析期間 server 活著時呼叫（27B，零額外啟動成本）
- `infer_missing_fields(chars)` — 公開介面，自行啟動 4B server，供補完端點使用
- `_apply_defaults(char)` — **大幅精簡**，移除所有 keyword-based 情境推斷，只保留純計算預設

**流程變更**：
```
analyze_characters 原流程：
  逐章提取 → 停止 server → _apply_defaults

新流程：
  逐章提取 → [趁 27B 還活著] _infer_contextual_fields → 停止 server → _apply_defaults
```

---

### 二、body_type 欄位擴充

**問題**：LLM 從文字提取「消瘦」，但 system prompt 只允許 `嬌小|苗條|高挑|豐滿|魁梧`，導致非標準值進 DB 或直接變 null。

**修正**：
- System prompt 允許值改為：`嬌小|消瘦|苗條|適中|高挑|豐滿|高挑豐滿|魁梧`
- `CharacterEditModal` 下拉同步新增「消瘦」
- `_apply_defaults` 改用 `_VALID_BODY_TYPES` frozenset 判斷有效性，不再強制覆蓋有效的非標準值
- bwh 計算：消瘦 → `82-58-84`（同苗條）

---

### 三、「補完欄位」功能

**背景**：全書分析的 `_run_analysis` 使用 `COALESCE` SQL 語意，若角色在分析前已存在 DB（手動新增或舊版殘留），空欄位不會被新值覆寫。

**修正**：
- 新增 `POST /illustration/characters/{book_id}/fill_defaults` 端點
  1. 呼叫 `infer_missing_fields`（4B LLM 推斷情境欄位）
  2. 呼叫 `_apply_defaults`（補剩餘數值欄位）
  3. 只 UPDATE 有實際變動的欄位
- CharacterPanel Header 新增「**補完**」按鈕（emerald 綠，Sparkles icon）
- `extract_character_endpoint`（手動選取文字）也同步套用 `_apply_defaults`，確保兩條路行為一致

---

### 四、角色批次選取與刪除

**功能**：
- Header 新增「**選取**」按鈕，進入選取模式
- 選取模式：點卡片切換勾選（縮圖顯示 ✓ overlay），底部換成操作列
- 操作列：全選 / 清除 / 刪除 N 個
- 批次刪除使用 `POST /characters/{book_id}/batch_delete`（body 傳名稱 list，單一 transaction）

**修正刪除失敗**（兩個 root cause）：
1. 原本用 `Promise.all` 並行打多個 DELETE → SQLite 並發鎖。改為 `batch_delete` 端點，body JSON 傳名稱列表，一個 transaction 完成
2. `get_db_connection()` 加 `PRAGMA journal_mode=WAL`，允許並發讀寫，根本解決鎖定問題

---

### 五、CharacterPanel 卡片高度修正

**問題**：`<main className="flex-1 overflow-y-auto flex flex-col gap-2">` 同時身為 flex 子項與 flex 容器，子卡片被 flex 壓縮演算法壓成 ~5px。

**修正**：
- `main` 加 `min-h-0`（允許 flex 子項縮小，觸發 overflow scroll）
- `flex flex-col gap-2` → `space-y-2`（移除 flex 容器角色，卡片回歸 block flow，高度由內容決定）
- 操作按鈕從右側垂直堆疊改為卡片底部水平排列，帶文字標籤
- 視窗預設尺寸從 800×600 改為 1280×860

---

### 六、LLM 別名去重（整理重複）

- 「整理重複」按鈕改用 **27B 模型**（原為 4B），對語義別名識別更準確（如「福臨」vs「順治」）
- `backend/services/llm_engine.py` `find_alias_groups` 改呼叫 `find_analysis_gguf()`

---

## 2026-06-02 — GPU 鎖解除 + LLM 角色名稱品質修正

### 修復一：全書分析不再阻塞 TTS

**問題**：`_run_analysis` 呼叫 `gpu_manager.acquire_gpu('analysis')` 後持有互斥鎖長達 ~2.5 分鐘，TTS 合成被完全封鎖。

**根本原因**：原設計把分析、TTS、繪圖三種任務納入同一把互斥鎖，但實際上 27B LLM (~15.7 GB) + TTS (~4 GB) = ~20 GB，遠低於 25.7 GB VRAM 上限，根本不需要互斥。

**修正（`backend/services/gpu_manager.py`）**：
- 新增 `analysis_active: bool` flag（取代分析用鎖）
- `acquire_gpu('analysis')` 不再持互斥鎖，只卸載繪圖模型（Z-Image 21 GB + 27B = OOM，必須排除）並設 flag
- `acquire_gpu('illustration')` 改為等待 `analysis_active == False`（while loop + sleep 3s）
- 新增 `end_analysis()` 方法，分析結束後清除 flag

**修正（`backend/routers/illustration.py`）**：
- `_run_analysis` finally 改呼叫 `gpu_manager.end_analysis()`（不再呼叫 `release_gpu()`）

**效果**：
- 分析進行中：TTS 完全正常，繪圖請求自動排隊等候分析結束
- 分析結束：繪圖立即恢復可用

---

### 修復二：LLM 分析角色品質 — 代詞/描述詞過濾

**問題**：LLM 輸出「他」「逆賊」「奸細」「那傢伙」等代詞/描述詞作為角色名稱寫入 DB。

**修正（`backend/services/llm_engine.py`）**：

1. 新增 `_is_valid_char_name(name)` 過濾函數：
   - 單字代詞（他/她/它/你/我/咱/俺…）→ 拒絕
   - 已知非名稱詞彙（逆賊/奸細/刺客/那傢伙…）→ 拒絕
   - 「那X」「這X」開頭短語（≤4字）→ 拒絕

2. System prompt 新增明確禁令：
   - 禁止代詞（他/她/此人/那人…）作為 name
   - 同一角色多稱呼統一為最常用的簡短稱呼

---

### 修復三：同一角色多名合併

**問題**：「順治」「小順治」「福臨」「愛新覺羅·福臨」各自獨立存入 DB。

**修正（`backend/services/llm_engine.py`）**：

新增 `_merge_aliases(accumulated)` 後處理函數：
- Pattern 1：`clan·name` 格式（含「·」）→ 取 `·` 後的短名作為正名（`愛新覺羅·福臨` → `福臨`）
- Pattern 2：前綴 + 短名（`小`/`老`/`大` 開頭）→ 去前綴（`小順治` → `順治`）
- 合併後，來源別名的非空欄位補充到目標正名

**已知限制**：同一人跨語境的完全不同別名（如「福臨」vs「順治」）已可透過「整理重複」功能讓 LLM 識別並合併。

---

### 新增四：角色庫「整理重複」功能（LLM 別名去重）

**設計**：自動分析（逐章提取）刻意不做別名合併，避免誤判。改由使用者在角色庫看到結果後，手動觸發「整理重複」做一次性清洗。

**後端（`backend/services/llm_engine.py`）**：
- 新增 `find_alias_groups(names)` — 用 4B LLM，將全書角色名稱清單一次丟給 LLM，輸出確定相同的別名分組
- 只使用輸入清單中存在的名稱，不自行補充，防止幻覺

**後端（`backend/routers/illustration.py`）**：
- 新增 `POST /illustration/characters/{book_id}/dedup`
  - 合併規則：每組保留最短名為正名，別名的圖片移轉、缺失欄位補充到正名，副本刪除
  - 已鎖定角色不會被刪除

**前端（`CharacterPanel.tsx` + `api.ts`）**：
- Header 新增「整理重複」按鈕（violet，`GitMerge` icon），執行中顯示 spinner
- Toast 顯示合併明細（e.g., 「福臨（合併 順治、愛新覺羅·福臨）」）

---

### 其他已知問題（尚未修復）

| 問題 | 說明 |
|------|------|
| Tauri 後端自啟失敗 | `lib.rs` 查找 `backend/main.py` 以 `apps/desktop` 為相對路徑，找不到 → 警告但繼續運行 |

---

---

## 2026-06-01 — CharacterPanel 修復：全書分析進度條 + 捲動穿透 + 卡片可見性

### 問題診斷與修復

#### 1. 全書分析「失效」根本原因：`bg-sky-450` 無效色階

**檔案**：`apps/desktop/src/components/reader/CharacterPanel.tsx:275`

`bg-sky-450` 是無效的 Tailwind CSS 類別（Tailwind 的 sky 色階只有 400、500，沒有 450）。進度條容器（灰色底線）存在，但填充色完全透明，導致分析執行中時看不到任何進度，用戶誤以為功能無反應。同檔案的多視角生圖進度條（L415）正確使用 `bg-sky-400`。

**修復**：`bg-sky-450` → `bg-sky-400`

**後端分析實測驗證**：
- 3 章測試：~35 秒，找到 12 個角色 ✅
- 41 章全書：155 秒，找到 29 個角色 ✅
- 後端分析本身完全正常，問題純屬前端視覺 bug

---

#### 2. CharacterPanel 捲動穿透

**症狀**：在角色庫面板範圍內捲動，底層文章內文跟著動。

**根本原因**：面板的 backdrop overlay（`fixed inset-0 z-40`）只攔截了 `onClick`，沒有攔截 `onWheel` 事件，導致 wheel 事件穿透到底層文章的捲動容器。面板的 `<main>` 也缺少 `overscroll-contain`，在清單頂/底邊界時捲動事件也會逃逸到父層。

**修復**：
```tsx
// backdrop：加 onWheel 阻止穿透
{isOpen && <div onClick={onClose} onWheel={e => e.stopPropagation()} ... />}

// main：加 overscroll-contain 防止邊界逃逸
<main className="flex-1 overflow-y-auto overscroll-contain p-3 ...">
```

---

#### 3. 角色卡片文字不可見（只看到黑格）

**症狀**：CharacterPanel 開啟後，清單區域只看到 48×48 的黑色方塊，沒有角色名稱或其他內容。

**根本原因（多重）**：
1. 卡片背景色（`--bg-hover: #242424`）與面板背景色（`--bg-surface: #1a1a1a`）差距極小，加上卡片 border 為 `border-transparent`，卡片邊界完全不可辨
2. 角色名稱 `<div>` 無明確 `color` 宣告，在 Tailwind v4 某些繼承情境下可能不穩定
3. 縮圖佔位符 `bg-amber-500/10`（10% 透明度）在深色背景幾乎不可見

**修復**：
- 卡片 border 從 `border-transparent` 改為 `border-white/10`（常態顯示極細邊框）
- 卡片 div 加上明確 `color: "var(--text-primary)"`
- 角色名稱 div 加上明確 `color: "var(--text-primary)"`
- 縮圖佔位符從 `bg-amber-500/10 text-amber-500` 改為 `bg-amber-500/20 text-amber-400`

---

### 其他已知問題（尚未修復）

| 問題 | 說明 |
|------|------|
| LLM 分析角色品質 | 部分章節回傳代詞（「他」）、描述詞（「逆賊」、「那傢伙/奸細/偷牛賊」）當作角色名寫入 DB |
| 同一角色多名 | 「順治」、「小順治」、「福臨」、「愛新覺羅·福臨」各自獨立存入 DB |
| GPU 鎖阻塞 | 全書分析期間（~2.5 分鐘）持有 `gpu_manager.lock`，TTS 和插圖生成均被排隊等待 |
| Tauri 後端自啟失敗 | `lib.rs` 查找 `backend/main.py` 以 `apps/desktop` 為相對路徑，找不到 → 啟動時印出警告但繼續運行（後端已由 `npm run dev` 另行啟動，不影響功能） |

---

## 2026-05-31（夜間）— 專案結構確認與全書分析背景運作中

### 當前系統運作狀態
1. **背景分析與推理進度**：
   - 目前後端正在執行《清朝其實很有趣兒》（ID: `189f0968-34e2-4522-a86c-7a4bb63b2e7c`，共 41 章）的全書角色自動分析任務。
   - 角色分析任務啟動 Gaston 27B 思考型大模型（在 `llama-server.exe` 子行程，監聽 `18765` 連接埠），進行「合理外觀推論」與「特徵隨讀隨新合併」。
2. **GPU 顯存與 VRAM 鎖定**：
   - 透過 `nvidia-smi` 確認，`llama-server.exe` 目前佔用約 18.2 GB VRAM，GPU 使用率 98%，推論流暢。
   - `GPUManager` 顯存仲裁單例已鎖定於 `'analysis'`（分析）狀態，已主動釋放 TTS 與 Z-Image 模型，確保單一 GPU 任務獨佔顯存，安全防範 CUDA OOM 崩潰。
3. **資料庫與 CRUD 整合**：
   - `characters` 資料表結構已更新，欄位擴充至 15 個，新增 `weight_kg`（體重）、`bwh`（三圍）與 `cup_size`（罩杯，限女性）。
   - 後端已打通隨讀隨新的 `ON CONFLICT DO UPDATE` 機制，並新增後端防禦性 Fallback 邏輯（如自動填充太后 `85-60-86`/`C罩杯` 等預設特徵）。
   - 自動化端對端測試 `test_e2e.py` (70/70) 與真實 Qwen-27B 測試 `scratch_test.py` 均順利通過。

---

## 2026-05-31（深夜）— 全域 GPU 顯存仲裁 + 角色特徵推論優化 + 隨讀隨新合併

### 專案架構結構

目前專案採前後端分離架構，結構如下：
- **`apps/desktop/`** (Tauri + React + Vite 前端桌面端專案)
  - `src/components/reader/`：閱讀器核心 UI 元件
    - [CharacterPanel.tsx](file:///c:/Users/holy_/Downloads/vepub/apps/desktop/src/components/reader/CharacterPanel.tsx)：右側角色抽屜（包含自動分析、多角度生圖、大圖預覽燈箱、名稱/時間排序與搜尋過濾）
    - [IllustrationCard.tsx](file:///c:/Users/holy_/Downloads/vepub/apps/desktop/src/components/reader/IllustrationCard.tsx)：生圖卡片（ComboBox 下拉式選取現有角色並支援角度選擇存入圖庫）
  - `src/lib/api.ts`：與後端連線的 API 定義
- **`backend/`** (FastAPI + SQLite + Uvicorn + 本地模型後端專案)
  - [main.py](file:///c:/Users/holy_/Downloads/vepub/backend/main.py)：後端啟動入口，lifespan 註冊 VRAM 仲裁
  - `routers/`：FastAPI 路由
    - [illustration.py](file:///c:/Users/holy_/Downloads/vepub/backend/routers/illustration.py)：角色管理與全書分析 API，插圖與多角度生圖 API（已將寫入改為 `ON CONFLICT DO UPDATE`）
  - `services/`：核心 AI 推理與基礎服務
    - [db.py](file:///c:/Users/holy_/Downloads/vepub/backend/services/db.py)：SQLite 資料庫連線與預設設定
    - [gpu_manager.py](file:///c:/Users/holy_/Downloads/vepub/backend/services/gpu_manager.py) **[NEW]**：全域 VRAM 互斥仲裁管理器，負責 TTS、Z-Image 與 Qwen-27B 進程的顯存加鎖與主動踢除調度，防止並行推理導致 CUDA OOM 崩潰
    - [llm_engine.py](file:///c:/Users/holy_/Downloads/vepub/backend/services/llm_engine.py)：`llama-server.exe` 封裝。支援 Qwen-27B 角色擷取、特徵推論合併與 Fallback
    - [illustration_engine.py](file:///c:/Users/holy_/Downloads/vepub/backend/services/illustration_engine.py)：Z-Image 繪圖引擎（已新增體重、三圍、罩杯 Prompt 組裝）
    - [tts_engine.py](file:///c:/Users/holy_/Downloads/vepub/backend/services/tts_engine.py)：OmniVoice 語音引擎，具備主動卸載與重載機制
  - `測試與驗證工具`
    - [test_e2e.py](file:///c:/Users/holy_/Downloads/vepub/backend/test_e2e.py)：70 項 API 端對端單元與整合測試腳本
    - [scratch_test.py](file:///c:/Users/holy_/Downloads/vepub/backend/scratch_test.py)：Qwen-27B Gaston 模型真實推理、合併與 Fallback 驗證腳本

---

### 本期開發進度與成果

#### 1. 結構化角色特徵擴充與寫入最佳化
- **DB & API 欄位新增**：`characters` 表新增了 `weight_kg` (INTEGER)、`bwh` (TEXT) 與 `cup_size` (TEXT) 三個特徵欄位（三圍與罩杯限女性），並更新前端 `CharacterUpsert` 型別與後端新增/修改 SQL。
- **隨讀隨新支援**：修改 `/analyze_characters` 與 `/characters` 寫入 SQL 為 `INSERT ... ON CONFLICT(book_id, name) DO UPDATE SET`，使後續章節或手動編輯時能成功覆蓋更新已存在角色的特徵。

#### 2. LLM 擷取提示詞優化與「合理外觀推論」
- **System Prompt 優化**：移除了 prompt 枚舉與範例中的所有 `"不明"` 與 `null` 欄位（`height_cm`/`weight_kg` 為整數）。要求 LLM 無外觀描寫時，必須根據角色的性別、身份、年齡與歷史背景（例如清朝皇帝、滿族太后、攝政王等），發揮想像力進行合理外觀推論（如：皇帝推論為 "身穿明黃色龍袍"，將領為 "身穿精緻的清代鎧甲"），若推論不出則「隨意決定」填寫合乎背景的具體值。
- **大上下文支援**：為配合長思考推理過程（避免 truncated 造成 JSON 格式錯誤），將啟動 llama-server 的 ctx 大小由 `4096` 調整為 `16384`（支援 `max_tokens=8000`）。

#### 3. 「隨讀隨新」合併更新機制 (Merge) 與防禦性 Fallback
- **隨讀隨新合併機制**：輸出格式新增 `inferred_fields` 標明哪些欄位是推論值。在逐章分析合併角色時：若新資訊為「明確描述」，則覆蓋舊欄位；若新資訊為「推論值」，則僅在舊欄位不存在或也是推論值時才更新，明確描述不會被後續的推論值所覆蓋。
- **後端防禦性 Fallback**：若 LLM 輸出殘留的空值或不明，後端在 `analyze_characters` 返回前會強行補足符合其性別與身份背景的預設特徵值，徹底保證寫入資料庫的角色特徵決不為空或不明（如：太后補足 `85-60-86`/`C罩杯`；男性 `bwh`/`cup_size` 自動補 `None`）。
- **prompt 拼裝強化**：`build_character_fragment` 已同步加入體重、三圍與罩杯的 prompt 拼裝支援（女性如：`三圍85-60-86，C罩杯`）。

---

### 驗證結果與測試
- **E2E 自動化測試**：`uv run python test_e2e.py` 回報 **70 / 70 測試點全部 100% 通過**，新欄位 CRUD 運作正常。
- **27B 模型真實推理驗證**：跑通 `scratch_test.py`，調用 Gaston 27B 真實提取多章節特徵：
  - 成功擷取「多爾袞」與「順治」，並推論出「明黃色龍袍」與「精緻的清代鎧甲」。
  - 「孝莊太后」的身高/體重成功在第二章的明確描述中被更新覆蓋（`165cm/52kg`），而第一章推論出的三圍/罩杯被成功保留並進行 Fallback 填充。
  - 所有欄位驗證 Assertion 全數通過。

---

## 2026-05-31（晚）— 角色庫自動分析 + 多視角生圖 + LLM 引擎重構

### 目標

1. 由 LLM 讀入整本小說，自動分析人物特徵並儲存至角色庫（手動填寫的補充，不是取代）
2. 角色庫提供「生成多視角」按鈕，依序生成正面/背面/左側/斜前方/半身 5 張圖
3. 內文生圖時：若未手動指定角色，自動偵測文字中是否含角色庫名稱，有則自動注入外觀描述

---

### 已完成

#### 後端

**`backend/routers/illustration.py`**
- 新增 `_analysis_jobs` dict（per book_id）、`_angle_jobs` dict（per job_id）
- 新增 `_ANGLE_DEFS`：正面/背面/左側/斜前方/半身的英文 prompt prefix
- `_run_task` 加入自動角色偵測：`character_name` 未填時，掃描 `req.text` 中有無角色庫名稱，命中即自動注入外觀
- `_run_analysis(book_id, file_path, max_chapters=0)`：啟動 27B server → 逐章分析 → `INSERT OR IGNORE` 存入 DB → 關閉 server
- `_run_angle_job(job_id, ...)`：在 `_queue_sem` 內依序對 5 個視角各呼叫 `generate_illustration`，全部完成後統一 `unload_model()`
- 新增端點：
  - `POST /illustration/analyze_characters/{book_id}?max_chapters=N`（N=0 = 全書）
  - `GET  /illustration/analyze_characters/{book_id}/status`
  - `POST /illustration/characters/{book_id}/{name}/generate_angles`
  - `GET  /illustration/angle_jobs/{job_id}`

**`backend/services/llm_engine.py`（完整重寫）**
- **舊版**：`llama-cpp-python` Python binding 直接載入 GGUF
- **新版**：`llama-server.exe` subprocess + `/v1/chat/completions` HTTP API
- 動機：`llama-cpp-python 0.3.23`（含 cu124、cu125）遇到 Qwen3.6 hybrid SSM+Transformer 架構報錯 `missing tensor 'blk.64.ssm_conv1d.weight'`，根本原因是 bundled llama.cpp 版本不支援此架構，且無 MSVC 無法從原始碼 build
- 解法：下載 llama.cpp 官方 binary `b9441`（CUDA 13.3 / sm100+sm120 Blackwell），放入 `backend/llama_bin/`
- VRAM 管理：`_start_server_sync` → 推理 → `_stop_server_sync`，`proc.terminate()` 後整個 server 行程結束，VRAM 完整釋放
- 對外介面 `expand_prompt()` / `analyze_characters()` 簽名完全不變，`illustration.py` 零改動

#### 前端

**`apps/desktop/src/lib/api.ts`**
- 新增 `analyzeCharacters(bookId)` / `getAnalysisStatus(bookId)` / `generateCharacterAngles(...)` / `getAngleJobStatus(jobId)`
- 新增 `AnalysisJob` / `AngleJob` interface

**`apps/desktop/src/components/reader/CharacterPanel.tsx`**
- Header 加「分析全書」按鈕（sky 藍色，分析中 disabled）
- Header 下方：分析進度條（`sky-400`，完成後可手動關閉）
- 每個角色展開後：「生成多視角（5 張）」按鈕 + inline 進度條
- 兩套獨立 polling：分析 2.5s / 角度生圖 3s，完成後自動 `fetchChars()` 刷新

---

### LLM 引擎切換詳細記錄

| 項目 | 舊版 | 新版 |
|------|------|------|
| 推理方式 | `llama_cpp.Llama()` Python binding | `llama-server.exe` subprocess |
| CUDA | cu124 wheel（不支援 RTX 5090 Blackwell 原生） | CUDA 13.3 / sm120 |
| 架構支援 | 純 transformer（Mamba hybrid 不支援） | b9441 完整支援 Qwen3.6 hybrid SSM |
| VRAM 釋放 | `del _llm; torch.cuda.empty_cache()` | `proc.terminate(); proc.wait()` |
| prompt 擴寫模型 | `huihui-qwen3-4b-abliterated-v2-q8_0.gguf` | 同上（4B，n_ctx=2048） |
| 角色分析模型 | 同 4B（無 27B 支援） | `Qwen3.6-27B-abliterated-Gaston-MTP-Q4_K_M.gguf`（n_ctx=4096） |
| server port | N/A | 18765（避開 backend 8765） |

**驗證結果**：
- llama-server b9441 在 RTX 5090 上成功載入 Qwen3.6-27B（15.7GB Q4_K_M）
- `/health` 回傳 `{"status":"ok"}` → 推理 `Hi` → 正常回傳 content
- 分析任務已實測 running（第 4/41 章進行中）

---

### 尚未完成

1. **`max_chapters` 前端支援**：目前後端已有 `?max_chapters=N` query 參數，前端「分析全書」按鈕寫死呼叫全書（`analyzeCharacters(bookId)` 不傳 max_chapters）。如需 UI 可選，要在 CharacterPanel 加一個數字輸入或選單。

2. **驗證分析完成後角色資料正確性**：已觸發 `max_chapters=3` 測試，尚未確認回傳的 JSON 角色資料格式正確、欄位對應到 DB 結構化欄位、CharacterPanel 正確顯示。

3. **多視角生圖端對端測試**：`generate_angles` 端點寫完但尚未實際生圖測試（需角色先存在 DB）。

4. **llama_bin 加入 .gitignore**：`llama_bin/` 目錄（約 524 MB）不應 commit 至 git，需確認已排除。

---

### 已知環境（更新）

| 項目 | 值 |
|------|----|
| GPU | NVIDIA GeForce RTX 5090 Laptop GPU |
| VRAM | 25.7 GB |
| CUDA Toolkit | 13.0（nvcc 確認） |
| llama-server | b9441 / CUDA 13.3 / sm100+sm120，位於 `backend/llama_bin/` |
| prompt 擴寫 LLM | 4B Q8（4.0 GB），server port 18765 |
| 角色分析 LLM | 27B Q4_K_M（15.7 GB），server port 18765 |
| Z-Image pipeline | 載入時約佔 21 GB VRAM |
| VRAM 峰值（分析中） | ~15.7 GB（27B server 獨佔） |
| VRAM 峰值（生圖中） | ~25 GB（4B server ~4 GB + Z-Image ~21 GB） |

---

## 2026-05-31（下午）— 插圖系統重構：移除 Ollama、角色庫升級、VRAM 管理

### 背景

本次變更範圍涵蓋插圖生成系統的核心架構調整，並根據問題追蹤分析出的六類落差逐一修正。

---

### 一、移除 Ollama，改用本地 GGUF 推理

**動機：** Ollama 是外部服務，佔用 VRAM 且無法從程式內部控管其生命週期。

**`backend/services/llm_engine.py`（新建）**
- 以 `llama-cpp-python` 載入 `backend/models/*.gguf`
- 流程：載入 → 推理 → **立刻卸載**，完整自管 VRAM
- `/no_think` directive 關閉 Qwen3 思考鏈，避免 token 浪費
- raw completion 預填 `<|im_start|>assistant\n`，強制模型直接輸出（不再要求 JSON 格式，減少解析失敗）
- `is_anime` 改由 style_hint 關鍵字判斷，不依賴 LLM

**`backend/services/illustration_engine.py`**
- 移除 `httpx`、Ollama HTTP 呼叫、`_check_ollama()`
- `_expand_prompt` 改委派給 `llm_engine.expand_prompt()`
- **Prompt 語言改為中文：** `中文 → LLM 濃縮中文 → Z-Image`（Z-Image 的 Qwen3 text encoder 原生支援中文，不需翻譯）

**`backend/routers/illustration.py`**
- `/status` 端點：`ollama_available` 改為 `llm_available + llm_model`

**安裝**
```powershell
uv pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124
```
已於 `pyproject.toml` 加入對應 index（`llama-cpp-cu124`）。

---

### 二、VRAM 生命週期管理

**問題：** 任務結束後 pipeline 常駐，導致跨 session 的 VRAM 累積。

**修正：**
- `_run_task` 加 `finally: await unload_model()`：任務結束（成功或失敗）**立刻釋放** Z-Image pipeline
- `generate_illustration()` 中，Florence2 分析完後立刻呼叫 `_unload_florence_sync()`
- `unload_model()` 加 log：`[illustration] VRAM 已釋放：Z-Image pipeline`
- **圖片出現時機修正：** 原先 unload 在 `task["status"] = "done"` 之前執行（用戶要等 VRAM 釋放才看到圖）。改為先 `task["status"] = "done"` → 圖立刻出現 → 再 unload

**實測時間軸（1024×1024，RTX 5090）：**
```
LLM 推理（載入→推理→卸載）   ~6s
Z-Image pipeline 載入          ~20s（從本機磁碟，非下載）
擴散 8 步                      ~24s（約 3s/step）
任務後 VRAM                    447 MiB（從 24GB 完整釋放）
```

---

### 三、熱重載問題修正

**問題：** WatchFiles 監控了 `.venv` 和 `__pycache__`，導致安裝套件或 import 時觸發不必要的 hot-reload，進而清空 `_tasks`、kill 正在生圖的任務。

**修正（`package.json`）：**
```json
"dev:backend": "cd backend && uv run uvicorn main:app --reload --reload-dir . --reload-exclude .venv --reload-exclude __pycache__ --port 8765"
```

**並行行程孤兒問題：** `concurrently --kill-others-on-fail` 只在失敗時殺掉其他行程，Tauri 正常關閉（exit 0）時 backend 繼續存活，下次啟動造成多個 backend 搶同一個 port 8765。

**修正：** 改用 `--kill-others`（任一行程退出即殺掉所有）。

---

### 四、步驟時間軸（timing 功能）

**`backend/routers/illustration.py`**
- 任務 dict 加 `timings: []`
- `_cb` 每次回呼追加 `{"pct", "label", "ts": time.time()}`
- `/progress` 回應加入 `timings`

**`apps/desktop/src/pages/IllustrationTest.tsx`**
- 新增「步驟時間軸」區塊：每個步驟顯示累計耗時 `+Xs` 與步間耗時 `(Xs)`，完成後顯示總計

---

### 五、角色庫系統重構

#### 問題診斷

原本「人物一致性」的實作（DEVLOG 2026-05-30 下午的 ControlNet + Canny + character LoRA 版本）已在某次重寫時移除。grep 確認：**`ControlNet` / `character_lora` / `Canny` 代碼庫 0 匹配**。

原有機制的根本問題：
- **I2I（Image-to-Image）工具誤用**：I2I 語義是「保留構圖重繪細節」，用於「同一張臉出現在新場景」是方向錯誤
- **參考圖是整張場景插圖**：含背景、光線、其他物件，I2I 會把舊構圖帶進新圖，產生世代漂移
- **Florence2 英文 caption**：和中文 prompt 流程語言混雜，且鎖不住面部特徵
- **文字描述自由欄位**：無法穩定輸出，每次生成面孔不同

#### Z-Image LoRA 可行性實測

以 `test_zimage_compat.py` 對實際 pipeline 測試：
- **LoRA：✅ 確認可用**（`load_lora_weights` 實測成功，key 格式：`transformer.layers.N.attention.to_q.lora_A.weight`）
- **IP-Adapter：❌ 不支援**（無 `load_ip_adapter`，transformer 無 `attn_processors`，自定義 attention 無法注入）

#### 新設計

**資料層**
- `characters` 表：新增 11 個結構化欄位（`gender / age_hint / hair_color / hair_style / eye_color / body_type / height_cm / signature_outfit / other_features / character_seed / lora_path`）
- 新建 `character_images` 表：一個角色可存多張圖，帶角度標記（正面/側面/半身/全身）

**後端（`illustration_engine.py`）**
- 新增 `build_character_fragment(char: dict) -> str`：把結構化欄位組成中文描述（`女，青年，黑色長直，棕色瞳，高挑豐滿，172cm，白色教師套裝`）
- 新增 `character_seed_for(book_id, name) -> int`：以 md5 hash 給角色穩定 seed
- 移除 Florence2 分析路徑
- 移除 I2I 一致性路徑（`generate_illustration` 簽名大幅簡化）

**後端 API 新增**
- `POST /illustration/characters/{book_id}/{name}/images`：新增角色參考圖（含 angle / is_primary）
- `GET /illustration/characters/{book_id}/{name}/images/{id}`：取得單張圖的 base64（懶載入）
- `DELETE /illustration/characters/{book_id}/{name}/images/{id}`
- `POST /illustration/characters/{book_id}/{name}/set_primary/{id}`：設主要圖片

**前端**
- `CharacterEditModal.tsx`（新建）：結構化欄位 Chip 選擇器 + 即時 prompt fragment 預覽
- `CharacterPanel.tsx`（大幅改造）：展示結構化欄位、圖庫縮圖（懶載入）、編輯/刪除/設 primary
- `IllustrationCard.tsx`：「存為角色」加角度選擇，圖片存入 `character_images`；儲存後回呼開啟角色庫（`onImageSavedToCharacter`）

---

### 六、殘留問題修正（功能落差清除）

| # | 項目 | 修正 |
|---|------|------|
| 1 | `Reader.tsx` 仍用 `ollama_available` 存取已不存在的欄位 | 改為 `llm_available`，banner 文字更新 |
| 2 | `Reader.tsx` 仍解構 `i2iStrength / removeBackground`（已無用） | 移除解構與 dependency array 中的殘留 |
| 3 | taskQueue 初始化缺 `timings: []` → TypeScript 型別錯誤 | 補上 `timings: []` |
| 4 | `IllustrationCard` 存角色後沒有直接入口填寫結構化欄位 | 儲存完自動開啟角色庫（`onImageSavedToCharacter` callback）並觸發 CharacterPanel 刷新 |
| 5 | `CharacterPanel` 已開啟時存完圖不刷新 | 加 `refreshKey` prop，`IllustrationCard` 存圖後遞增 |
| 6 | `SettingsPanel` I2I/RMBG 滑桿標題仍說「人物一致性（選取角色後生效）」→ 誤導 | 改為說明文字，明確描述現在的文字錨定機制 |
| 7 | `api.ts` / `IllustrationTest.tsx` 仍傳 `i2i_strength / remove_background` | 從 type 定義和呼叫處全部移除 |

---

### 七、已知環境（更新）

| 項目 | 值 |
|------|----|
| GPU | NVIDIA GeForce RTX 5090 Laptop GPU |
| VRAM | 25.7 GB |
| CUDA | 可用（cu128） |
| LLM 推理 | llama-cpp-python 0.3.23（cu124 wheel），本地 GGUF |
| 本地 LLM 模型 | `huihui-qwen3-4b-abliterated-v2-q8_0.gguf`（Q8，約 4.7GB） |
| 後端 | FastAPI @ 127.0.0.1:8765 |
| 前端 | Tauri + React (Vite dev mode) |
| 可選 Transformer | 目錄下第一個 `.safetensors`（自動偵測） |
| 角色一致性機制 | 結構化中文特徵注入 + character_seed（Phase 1）；角色 LoRA 已驗證可行（Phase 2，使用者主動觸發） |

---

## 2026-05-31 — 效能修正 + Ollama VRAM 管理 + Transformer 模型選擇

### 問題修正：「卡在分析書籍」

**根本原因**：epub 解析（`epub.read_epub` + BeautifulSoup）與文字分句（`TextChunker.chunk_paragraphs`）為 CPU 密集同步操作，直接寫在 `async` handler 裡，整個 FastAPI event loop 被鎖住。174 章書籍可能需要數秒到數十秒，期間所有其他 API 請求（fetchBooks、getProgress、getSentences）全部排隊等待，前端各種 loading 永遠不結束。

**修正（`backend/routers/epub.py`）**：

| 端點 | 修改內容 |
|------|---------|
| `POST /epub/parse` | `get_meta_cached` + `get_chapters_cached` 改用 `asyncio.run_in_executor` |
| `GET /epub/{id}/chapters` | 同上 |
| `GET /epub/{id}/chapter/{cid}/paragraphs` | 同上 |
| `POST /epub/{id}/chapter/{cid}/sentences` | `TextChunker` 初始化 + 分句整包丟入 thread pool |

**修正（`backend/services/text_chunker.py`）**：
- 之前每次 `TextChunker.__init__` 都呼叫 `detect_hardware()`（內含 `import torch` + `torch.cuda.is_available()`）
- 改為模組層級快取 `_get_hw_max_chars()`，整個進程生命週期只偵測一次

---

### Ollama VRAM 管理：用後立刻卸載

**動機**：Ollama qwen3:8b 約佔 8–9 GB VRAM；Z-Image pipeline 約佔 21 GB。若兩者同時在記憶體中，在 25.7 GB 的 RTX 5090 上可能擠壓 TTS 模型空間。

**修正（`backend/services/illustration_engine.py`）**：
- `_expand_prompt` 的 Ollama generate 請求加入 `"keep_alive": 0`
- Ollama 回傳 prompt 的瞬間即從 VRAM 卸載，Z-Image pipeline 載入前記憶體已釋放

流程：`Ollama 擴寫 prompt (25%) → [Ollama 自動卸載] → Z-Image 載入 (35%) → 擴散生圖 (50-95%)`

---

### 新功能：Z-Image Transformer 模型選擇

**背景**：`backend/models/` 目前有兩個 transformer：
- `darkBeast_dbzit8SDAFOK.safetensors`（預設）
- `luciddreamerZ_v078AnimeZib.safetensors`

**後端（`backend/services/illustration_engine.py`）**：
- 新增 `_active_transformer` 全域變數（`None` = 預設使用目錄第一個 `.safetensors`）
- `list_transformers()` — 掃描 `backend/models/*.safetensors`，回傳清單 + 標記哪個 active
- `set_active_transformer(filename)` — 切換時自動卸載現有 pipeline（下次生圖重新載入新模型）
- `_load_pipe_sync` 改用 `_resolve_transformer_path()` 動態取路徑，不再硬編碼

**後端（`backend/routers/illustration.py`）**：
- `GET /illustration/transformers` — 回傳可選模型清單
- `POST /illustration/transformers/select` — 切換 transformer，傳 `{"filename": "xxx.safetensors"}` 或 `{"filename": null}` 重置

**前端（`SettingsPanel.tsx` + `api.ts`）**：
- 設定面板 → 插圖生成 → Z-Image 狀態下方新增 **Transformer 模型下拉選單**
- 切換時：顯示「切換中...」spinner、自動將載入狀態改為「未載入」、toast 提示
- 未來只需把新 `.safetensors` 丟進 `backend/models/`，下拉自動出現

---

### 已知環境（更新）

| 項目 | 值 |
|------|----|
| GPU | NVIDIA GeForce RTX 5090 Laptop GPU |
| VRAM | 25.7 GB |
| CUDA | 可用 |
| Ollama | 線上（qwen3:8b），生圖後自動卸載（keep_alive: 0） |
| 後端 | FastAPI @ 127.0.0.1:8765 |
| 前端 | Tauri + React (Vite dev mode) |
| 可選 Transformer | `darkBeast_dbzit8SDAFOK.safetensors`（預設）、`luciddreamerZ_v078AnimeZib.safetensors` |

---

## 2026-05-30（下午）— ~~插圖系統改版：情境 B（I2I + ControlNet 人物一致性）~~ ⚠️ 已廢棄

> **此整節已被後續版本完全移除。** ControlNet / Florence2 / Character LoRA / I2I 一致性路徑均不再存在於代碼庫（grep 0 匹配）。
> 詳見 2026-05-31（下午）的重構記錄與 plan.md §二 P5。

採用 ComfyUI Z-Image workflow 建議的模型，捨棄原本的 darkBeast / hentai LoRA。

### 模型變更（放在 `backend/models/`）
- **Transformer**：`projectAnime_v10FP16.safetensors`（取代 darkBeast）
- **ControlNet**：`Z-Image-Turbo-Fun-Controlnet-Union-2.1.safetensors`（新增）
- **Character LoRA**：放 `backend/models/character_loras/`，可在設定面板選用
- **Florence2**：`MiaoshouAI/Florence-2-base-PromptGen-v2.0`（首次使用自動下載，分析參考圖外觀）
- **RMBG-2.0**：透過 `rembg` 自動去背
- 三者皆缺檔時優雅退化：無 transformer → HF base；無 ControlNet → 純 I2I；pipeline 不支援 I2I → 退回 T2I

### 後端
- `illustration_engine.py` 重寫：角色參考圖 →（RMBG 去背）→ Florence2 自動描述 → Canny 邊緣 → Z-Image I2I + ControlNet
  - 參數：`i2i_strength`(0.65)、`controlnet_strength`(0.6)、`character_lora`、`remove_bg`
  - LoRA 動態切換 `_switch_lora_sync`，`list_character_loras()` 掃描資料夾
- `routers/illustration.py`：`generate` 接受一致性參數、自 DB 取角色參考圖；新增 `GET /illustration/character_loras`
- `pyproject.toml`：新增 `opencv-python-headless`、`rembg`、`transformers`、`timm`、`einops`、`pillow`

### 前端
- `api.ts`：`generateIllustration` 加一致性參數；新增 `getCharacterLoras()`
- `stores/reader.ts`：新增 `i2iStrength / controlnetStrength / characterLora / removeBackground`，持久化到 settings
- `SettingsPanel.tsx`：插圖區塊加入 I2I 強度、ControlNet 強度滑桿、LoRA 下拉、去背開關
- `Reader.tsx`：選取角色時才套用 I2I + ControlNet 參數

### 啟動腳本
- 根目錄 `package.json` + `concurrently`：`npm run dev` 一鍵啟動 backend(8765) + Tauri
- 修正 `tauri.conf.json` devUrl → 5173、backend 啟動補 `--port 8765`

---

## 2026-05-30 ⚠️ 部分已廢棄

> **注意**：`hentai_quality_studio` LoRA、Ollama (qwen3:8b)、darkBeast 模型等描述已過時，對應代碼已被移除或替換。此節作為歷史記錄保留。

### 插圖生成系統（全新功能）

#### 後端

- **`backend/services/illustration_engine.py`**（新增）
  - Z-Image-Turbo pipeline 封裝，使用本地 safetensors 載入
  - Ollama (qwen3:8b) prompt 擴寫：輸入小說原文 → 輸出繪圖描述 JSON，含 `is_anime` 風格判斷
  - 動畫/二次元模式自動掛載 `hentai_quality_studio_z_image_turbo.safetensors` LoRA，生完後卸載
  - 品質後綴自動注入：寫實用 `masterpiece, photorealistic…`；動畫用 `masterpiece, anime style, clean lineart…`
  - 硬體自動偵測：CUDA → MPS → CPU，對應選擇 bfloat16 / float16 / float32
  - `unload_model()`：`del _pipe` + `torch.cuda.empty_cache()` 完整釋放 VRAM

- **`backend/routers/illustration.py`**（新增）
  - `POST /illustration/generate`：生圖、持久化至 SQLite、回傳 `{id, image_base64, prompt, is_anime}`
  - `GET  /illustration/status`：Ollama 狀態 + 模型載入狀態
  - `POST /illustration/load`：背景預熱模型
  - `POST /illustration/unload`：從 VRAM 卸載
  - `GET  /illustration/list/{book_id}/{chapter_index}`：載回指定章節的歷史插圖
  - `DELETE /illustration/item/{id}`：刪除單張插圖
  - `GET/POST/DELETE /illustration/characters/{book_id}`：角色庫 CRUD

- **DB schema**：新增 `illustrations` 表（book_id, chapter_index, sentence_index, prompt, image_base64）、`characters` 表（book_id, name, description, ref_image_base64）

#### 前端

- **`SelectionToolbar.tsx`**（新增）
  - 選取 5 字以上文字後，`mouseup` 觸發顯示浮動生圖按鈕
  - 改用 `mouseup` 觸發（原 `selectionchange` 在拖曳中誤觸，導致工具列不穩定出現）
  - `selectionchange` 加 100ms debounce，僅用於隱藏
  - viewport 邊界保護：x 軸夾住、靠近頂部時改顯示於選取文字下方
  - 零尺寸 rect 守衛（`getBoundingClientRect` 在節點邊界可能回傳無效值）

- **`IllustrationCard.tsx`**（新增）
  - 生成結果卡片：圖片縮略、lightbox 放大、下載、移除
  - 「存為角色」表單：輸入角色名稱與外觀描述，存入角色庫

- **`CharacterPanel.tsx`**（新增）
  - 右側抽屜面板，顯示書籍角色庫
  - 選取角色後，後續生圖自動注入角色外觀描述至 prompt（文字錨定策略）

- **`Reader.tsx`** 整合三個新元件；新增邏輯：
  - 章節載入時從 DB 恢復歷史插圖（`Map<sentenceIndex, {id, imageBase64, prompt}>`）
  - 切換章節時清空 Map
  - dismiss 插圖時同步呼叫 DELETE 端點
  - Ollama 離線時顯示 info banner

- **`api.ts`** 新增插圖相關 API：`generateIllustration`、`getChapterIllustrations`、`deleteIllustration`、`getIllustrationStatus`、`preloadIllustrationModel`、`unloadIllustrationModel`、`getCharacters`、`upsertCharacter`、`deleteCharacter`

#### 設定面板

- **`SettingsPanel.tsx`** 新增「插圖生成」區塊：
  - Ollama 狀態燈（線上/未偵測）
  - Z-Image 模型載入狀態
  - 未載入時：「預先載入 Z-Image 模型」按鈕
  - 已載入時：「卸載生圖模型（釋放 VRAM）」按鈕
  - Ollama 離線時顯示安裝指引（`ollama pull qwen3:8b`）

---

### 書籤系統

- **`backend/routers/epub.py`** 新增書籤 CRUD：`GET/POST /epub/{book_id}/bookmarks`、`DELETE /epub/{book_id}/bookmarks/{id}`
- **`TableOfContents.tsx`** 新增「書籤」Tab：顯示所有書籤、點擊跳轉至對應章節＋句子、hover 顯示刪除按鈕、時間戳格式化
- **`Reader.tsx`** 鍵盤快捷鍵 `B` 新增書籤；`handleJumpToBookmark` 跨章節回跳（`setCurrentChapterIndex` + `setTimeout(_setCurrentIndex)`）

---

### 模型載入修正

- **問題**：`darkBeast_dbzit8SDAFOK.safetensors`（11.46 GB）只含 transformer 權重；`ZImagePipeline.from_single_file` 因找不到 Qwen3 text encoder 而失敗
- **解法**：改為 `ZImageTransformer2DModel.from_single_file(LOCAL_PATH)` 載入 transformer，其餘元件（text encoder、VAE、scheduler）從本機 HuggingFace cache（`Tongyi-MAI/Z-Image-Turbo`）載入；整體 `pipe.to("cuda")`
- **結果**：RTX 5090 Laptop 25.7 GB VRAM，載入後佔用約 21 GB（transformer 11.5 GB + Qwen3 encoder ~9 GB）

---

### 已知環境

| 項目 | 值 |
|------|----|
| GPU | NVIDIA GeForce RTX 5090 Laptop GPU |
| VRAM | 25.7 GB |
| CUDA | 可用 |
| Ollama | 線上（qwen3:8b） |
| 後端 | FastAPI @ 127.0.0.1:8765 |
| 前端 | Tauri + React (Vite dev mode) |
| 主模型 | darkBeast_dbzit8SDAFOK.safetensors |
| LoRA | hentai_quality_studio_z_image_turbo.safetensors |
