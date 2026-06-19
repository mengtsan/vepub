# 人物一致性 — 盤點、問題與規劃

> 建立日期：2026-05-31
> 範圍：插圖生成的「人物一致性」機制

---

## 一、當前實際做法（代碼與 DEVLOG 已脫節）

grep 確認：**`ControlNet` / `character_lora` / `Canny` 在整個代碼庫 0 匹配**。
DEVLOG 2026-05-30 下午記載的那套（projectAnime + ControlNet Union + Canny + 角色 LoRA）
已在某次重寫時整個移除，當前是更簡化的版本。

### 鏈路

```
存角色：IllustrationCard「存為角色」
  → 把【這次生成的整張插圖】當參考圖 + 手動填文字描述
  → characters 表 (book_id, name, description, ref_image_base64)

選角色：Reader.tsx selectedCharacter
  → generateIllustration(character_name, i2i_strength)
  → 後端 _run_task 從 DB 取 description + ref_image_base64

生圖：generate_illustration() 走兩條一致性路徑
  ├─ 路徑 A 文字錨定：description（手動）或 Florence2 caption（自動）→ 注入 LLM prompt
  └─ 路徑 B 圖像錨定：參考圖 →(可選 RMBG 去背)→ pipe(image=ref, strength=i2i_strength)  ← I2I
```

備註：測試台（IllustrationTest.tsx）未接角色流程，只有閱讀器（Reader.tsx）會走。

### 涉及檔案

| 檔案 | 角色 |
|------|------|
| `backend/services/illustration_engine.py` | `generate_illustration()` 兩條路徑、Florence2、RMBG、I2I |
| `backend/routers/illustration.py` | `_run_task` 從 DB 取角色、characters 表 CRUD |
| `apps/desktop/src/components/reader/CharacterPanel.tsx` | 角色庫 UI、選取 |
| `apps/desktop/src/components/reader/IllustrationCard.tsx` | 「存為角色」表單 |
| `apps/desktop/src/pages/Reader.tsx` | selectedCharacter → 傳參 |
| `apps/desktop/src/stores/reader.ts` | i2iStrength / removeBackground |

---

## 二、問題點（按嚴重度）

### 🔴 P1 — I2I 是錯誤的工具，方向性錯誤

I2I 語義 =「保留輸入圖構圖/色調，重繪細節」，strength 越低越像原圖。
但人物一致性要的是「**同一張臉，出現在全新場景/姿勢/構圖**」。兩者矛盾：

| i2i_strength | 結果 |
|---|---|
| 低 (0.3) | 輸出 ≈ 參考圖本身，場景文字幾乎無效，新場景出不來 |
| 高 (0.8) | 參考圖影響被沖掉，人物特徵也跟著消失 |

**滑桿兩端都達不到目的，中間是兩者都糟的妥協。** 工具誤用，非調參問題。

### 🔴 P2 — 參考圖是「整張場景插圖」而非「角色立繪」

- 存角色時存的是上一張完整插圖（含背景），I2I 會把舊背景構圖帶進新圖。
- RMBG 去背是在補破洞，但去背貼白底當 init image，strength 下仍干擾構圖。
- 每次「存為角色」覆蓋參考圖 → **世代漂移**：A 畫歪 → B 繼承 → 越來越歪。

### 🟠 P3 — 文字錨定鎖不住臉

純文字 prompt（手寫或 Florence2）只能鎖粗特徵（髮色、服裝），**鎖不住面部身份**。
每次生成都是不同的臉。所有純文字方法的物理天花板。

### 🟠 P4 — Florence2 是英文 caption，撞上中文 prompt 流程

prompt 流程已改成「中文 → LLM 濃縮中文 → Z-Image」。Florence2 輸出英文 caption
（`a woman with long hair...`），塞進中文 system prompt，語言混雜，caption 籠統，
抓不到判別性特徵，還多佔一次 VRAM 載入。

### 🟡 P5 — 文檔與代碼不一致

DEVLOG / CLAUDE.md 仍寫 ControlNet、character_loras 目錄、`hentai_quality_studio` LoRA，
代碼裡都沒了，未來會誤導。

---

## 三、正確做法（分層）

| Level | 方法 | 一致性 | 成本 | 污染構圖 |
|---|---|---|---|---|
| **0** | 固定 seed + 結構化文字特徵 | 弱（鎖粗特徵） | 零 | 否 |
| **1** | **IP-Adapter**（圖 → embedding 注入 attention） | 中強 | 免訓練 | **否** ✅ |
| **2** | **角色 LoRA**（多圖訓練進權重） | 最強（鎖臉） | 每角色訓練數分鐘 | 否 |

**關鍵洞察**：IP-Adapter 與 I2I 的根本差別 —— IP-Adapter 把參考圖編碼成「身份條件」
注入 cross-attention，**不當 init image**，所以「這個人 + 全新場景文字 + 全新姿勢」
三者可同時成立。這正是 I2I 做不到、而一致性需要的。

---

## 四、實作規劃（分階段）

### 階段 1 — 短期：修正方向（零新模型成本）

- [ ] I2I 從「人物一致性」降級為單純「變體/重繪」功能（UI 文案與用途分離）
- [ ] 一致性改走**結構化中文特徵**：
      存角色時抽取 `髮色 / 髮型 / 瞳色 / 服裝 / 體型` 成結構化欄位（characters 表加欄位），
      每次生成穩定注入 LLM prompt
- [ ] 可選：綁定該角色固定 seed
- [ ] 移除 / 改造 Florence2 英文 caption（改用中文視覺模型，或讓使用者填結構化欄位）
- 解決：P2（部分）、P3（改善）、P4

### 階段 2 — 中期：IP-Adapter（需先驗證可行性）

- [ ] **先驗證**：Z-Image-Turbo 在 diffusers 是否支援 IP-Adapter（較新 DiT 模型，生態可能未到位）
- [ ] 若支援 → 參考圖改走 IP-Adapter，不再用 I2I 做一致性
- [ ] 「參考圖」概念改成乾淨的**角色立繪**（單人、簡單背景）
- 解決：P1、P2、P3（大幅改善）

### 階段 3 — 長期：角色 LoRA 訓練

- [ ] 角色 LoRA 訓練 pipeline（DEVLOG 原已規劃）
- [ ] 使用者存 3-5 張角色圖 → 後台訓練 → 之後該角色掛此 LoRA
- [ ] 硬體足夠（RTX 5090 / 25GB）
- 解決：P3（徹底，鎖臉）

### 文檔整理（隨時可做）

- [ ] 更新 DEVLOG / CLAUDE.md，移除 ControlNet / character_loras / hentai LoRA 的過時描述

---

## 五、實測結果（2026-05-31）

使用 `test_zimage_compat.py` 對實際 pipeline 做靜態分析 + 實際載入測試。

### IP-Adapter：❌ 不支援

| 檢查項 | 結果 |
|--------|------|
| `load_ip_adapter` 方法 | ❌ 不存在 |
| `IPAdapterMixin` 繼承 | ❌ 無（MRO 只有 `ZImageLoraLoaderMixin`） |
| `attn_processors` 屬性 | ❌ transformer 無此屬性 |
| `set_attn_processor` | ❌ 無 |
| `FluxIPAdapterJointAttnProcessor2_0` | ✅ 存在於 diffusers，但掛不進去 |

根本原因：Z-Image 用自定義 attention 實作（非標準 diffusers `Attention` class），
沒有 `attn_processors` hook，IP-Adapter 無法注入。若要支援需自行 patch attention，
工程量大且脆弱，**排除此路線**。

### LoRA：✅ 確認可用

| 檢查項 | 結果 |
|--------|------|
| `load_lora_weights` | ✅ 存在且可呼叫 |
| dummy safetensors 載入 | ✅ **實測成功**（無 NotImplementedError） |
| PEFT 安裝 | ✅ |
| transformer Linear 模組 | ✅ 30 層，每層有 `to_q / to_k / to_v / to_out.0` |

**LoRA key 格式**（已驗證）：
```
transformer.layers.{N}.attention.to_q.lora_A.weight
transformer.layers.{N}.attention.to_q.lora_B.weight
transformer.layers.{N}.attention.to_k.lora_A.weight
...（noise_refiner / context_refiner 同理）
```

訓練目標：30 主層 × 4 線性投影 = 120 個 LoRA 插入點。
訓練工具：PEFT `LoraConfig` + diffusers `load_lora_into_transformer`。

---

## 六、角色庫完整規劃

### 6.1 設計原則

- 配角、次要角色 → **文字錨定**（零訓練，夠用）
- 主角 → 文字錨定 + **選擇性 LoRA**（使用者主動觸發）
- LoRA 是進階功能，不是預設流程
- 移除 Florence2（英文 caption，對中文流程無益）
- 移除 I2I 作為一致性機制（工具誤用），保留為「場景變體」

---

### 6.2 資料庫 Schema 變更

#### characters 表（現有欄位 + 新增）

```sql
-- 現有
id               INTEGER PRIMARY KEY AUTOINCREMENT
book_id          TEXT NOT NULL
name             TEXT NOT NULL
description      TEXT DEFAULT ''        ← 廢棄，改用結構化欄位
ref_image_base64 TEXT                   ← 廢棄，改用 character_images 表
created_at       INTEGER

-- 新增（全部 nullable，向下相容）
gender           TEXT    -- 女/男/不明
age_hint         TEXT    -- 少女/青年/中年/老年
hair_color       TEXT    -- 黑色/棕色/金色/紅色/銀白/白色
hair_style       TEXT    -- 長直/長波浪/短髮/馬尾/雙馬尾/捲髮
eye_color        TEXT    -- 黑色/棕色/藍色/紅色/金色/綠色
body_type        TEXT    -- 嬌小/苗條/高挑/豐滿高挑/魁梧
height_cm        INTEGER -- 選填
signature_outfit TEXT    -- 標誌性服裝，自由文字
other_features   TEXT    -- 其他特徵（刀疤、翅膀、獸耳…）
character_seed   INTEGER DEFAULT -1   -- -1 = 不固定；否則生圖時優先採用
lora_path        TEXT    -- 已訓練 LoRA 的 safetensors 路徑，NULL=未訓練
lora_trained_at  INTEGER
```

#### character_images 表（新建）

```sql
CREATE TABLE IF NOT EXISTS character_images (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  character_id   INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
  image_base64   TEXT NOT NULL,
  angle          TEXT DEFAULT 'other',   -- 正面/側面/半身/全身/其他
  is_primary     INTEGER DEFAULT 0,      -- 1=主要參考圖（顯示於角色庫縮圖）
  created_at     INTEGER DEFAULT (strftime('%s','now'))
)
```

---

### 6.3 Prompt 組合邏輯

```python
def build_character_fragment(char: dict) -> str:
    """把結構化欄位組成注入 LLM 的中文特徵描述"""
    parts = []
    if char.get("gender"):   parts.append(char["gender"])
    if char.get("age_hint"): parts.append(char["age_hint"])

    hair = ""
    if char.get("hair_color"): hair += char["hair_color"]
    if char.get("hair_style"): hair += char["hair_style"]
    if hair: parts.append(hair)

    if char.get("eye_color"):        parts.append(f'{char["eye_color"]}瞳')
    if char.get("body_type"):        parts.append(char["body_type"])
    if char.get("height_cm"):        parts.append(f'{char["height_cm"]}cm')
    if char.get("signature_outfit"): parts.append(char["signature_outfit"])
    if char.get("other_features"):   parts.append(char["other_features"])

    return "，".join(parts)   # 注入 llm_engine system prompt 的「角色外貌」欄位
```

---

### 6.4 Seed 策略

```python
import hashlib

def character_seed(book_id: str, name: str) -> int:
    """對角色名稱做 hash，得到穩定的生成起點"""
    h = hashlib.md5(f"{book_id}:{name}".encode()).digest()
    return int.from_bytes(h[:4], "big") & 0x7FFFFFFF
```

- `character_seed = -1`（預設）→ 每次隨機，多樣性高
- `character_seed > 0`（使用者鎖定）→ 生圖時優先使用，同角色臉型傾向穩定
- LoRA 已訓練時 seed 影響降低（LoRA 本身已鎖外觀）

---

### 6.5 後端 API 變更

#### 修改
| 端點 | 變更 |
|------|------|
| `POST /illustration/characters/{book_id}` | 接收新結構化欄位；`description` 欄位保留相容 |
| `GET /illustration/characters/{book_id}` | 回傳新欄位 + `images: [{id,angle,is_primary}]` |

#### 新增
| 端點 | 功能 |
|------|------|
| `POST /illustration/characters/{book_id}/{name}/images` | 新增一張參考圖（傳 image_base64, angle） |
| `DELETE /illustration/characters/{book_id}/{name}/images/{img_id}` | 刪除參考圖 |
| `POST /illustration/characters/{book_id}/{name}/portrait` | 用結構化特徵生成一張乾淨立繪，自動存入 images |
| `POST /illustration/characters/{book_id}/{name}/train_lora` | 觸發 LoRA 訓練（≥3 張圖才可用） |
| `GET /illustration/characters/{book_id}/{name}/lora_status` | 回傳訓練進度/完成狀態 |

#### 移除
- `_caption_reference()` / Florence2 整條路徑（不再需要）
- `generate_illustration()` 裡的 I2I 一致性路徑（改為獨立的「場景變體」功能）

---

### 6.6 前端元件規劃

#### CharacterPanel.tsx（大幅改造）

```
┌─ 角色庫 ─────────────────────────────────┐
│  [+ 新增角色]                             │
│                                           │
│  ┌─ 角色卡 ────────────────────────────┐  │
│  │ [縮圖] 秋月                使用中▶  │  │
│  │ 女，青年，黑色長直，棕色瞳           │  │
│  │ 高挑豐滿，172cm，白色教師套裝        │  │
│  │ 參考圖：●●○  [管理] [生成立繪]      │  │
│  │ LoRA：未訓練  [訓練]（需≥3張圖）    │  │
│  └─────────────────────────────────────┘  │
└───────────────────────────────────────────┘
```

#### CharacterEditModal.tsx（新建）

結構化欄位表單：
- 性別（下拉）、年齡感（下拉）
- 髮色（色票/下拉）、髮型（下拉）
- 瞳色（色票/下拉）
- 體型（下拉）、身高（數字，選填）
- 標誌性服裝（文字）
- 其他特徵（文字）
- 預覽：顯示組合後的 prompt fragment
- [生成立繪預覽] → 生一張正面圖確認描述正確

#### IllustrationCard.tsx（精簡）

「存為角色」改為：
1. 輸入角色名稱
2. 選擇這張圖要存為哪種角度（正面/側面/半身/其他）
3. 儲存後提示「前往角色庫補充詳細外貌描述」

#### Reader.tsx（調整）

- 選角色後：注入結構化文字特徵 + 套用 character_seed（若有設定）
- 移除 i2i_strength 作為一致性參數
- i2i_strength 保留在設定面板，作為「場景重繪強度」（與角色一致性解耦）

---

### 6.7 使用者流程（完整）

```
首次看到某角色：
  讀者選取文字 → 生成插圖
  → 點「存為角色」→ 輸入名稱＋選角度
  → 前往角色庫「補充外貌描述」→ 填結構化欄位
  → 系統顯示 prompt fragment 預覽
  → [選填] 點「生成立繪」確認外觀正確

後續生圖：
  角色庫選取角色 → 生圖
  → 結構化特徵自動注入 LLM prompt
  → （若設定了 character_seed）seed 採用角色 seed

累積參考圖（多次生圖後）：
  角色有 ≥ 3 張圖 → 「訓練角色 LoRA」按鈕出現
  → 使用者主動點選（主角才值得）
  → 後台訓練（RTX 5090 約 5-10 分鐘）
  → 完成後後續生圖自動掛載 LoRA
```

---

### 6.8 實作順序（建議）

| 優先 | 項目 | 預計工作量 |
|------|------|-----------|
| P0 | DB migration（新增欄位 + character_images 表） | 小 |
| P0 | `build_character_fragment()` 替換 Florence2 | 小 |
| P0 | 後端 API 更新（結構化欄位 CRUD） | 小 |
| P1 | CharacterEditModal.tsx（結構化欄位表單） | 中 |
| P1 | CharacterPanel.tsx 改造（圖片管理、欄位顯示） | 中 |
| P1 | IllustrationCard.tsx 調整（角度選擇） | 小 |
| P1 | character_seed 邏輯 | 小 |
| P2 | `POST .../portrait`（生成立繪 API） | 小 |
| P3 | LoRA 訓練 pipeline | 大 |

P0 全做完後，文字錨定一致性已到位。
P1 完成後，使用者體驗完整。
P2/P3 是進階功能，可後補。

---

## 七、確定路線（實測後更新）

IP-Adapter 排除，路線收斂為：

```
階段 1（短期）  → 強化文字錨定（結構化中文特徵，零模型成本）
階段 2（中期）  → 角色 LoRA 訓練（PEFT + ZImageLoraLoaderMixin，已確認可用）
```

實作優先順序：
1. 修正「整張插圖當參考圖」問題（改用結構化特徵欄位）
2. I2I 降級為「場景變體」功能，不作為一致性主要機制
3. 建立 LoRA 訓練 pipeline（3-5 圖 → 幾分鐘訓練 → safetensors → 掛載生圖）
