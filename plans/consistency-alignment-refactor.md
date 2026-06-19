# 角色一致性架構對齊：primary_char 與 present_chars 統一

> 建立日期：2026-06-16
> 背景：DEVLOG 2026-06-15（插圖四步 Pipeline 重構）「待辦／風險 2」提到此規劃，
> 但檔案當時未實際寫出。本檔案記錄問題分析與**已落地的修正**（非僅規劃）。

## 問題

插圖生成同時存在兩套「誰在場景中」的獨立判定：

1. **`routers/illustration.py::_run_task`** — 對 `req.text` 做 substring 比對
   （最長名優先），決定 `primary_char`，只用來：
   - 載入該角色的參考圖 → IP-Adapter FaceID
   - 解析該角色的 `character_seed`
2. **`services/llm/tasks.py::expand_prompt`**（Step 1+2）— LLM 讀段落語意，
   判定 `present_chars`（誰主動說話/行動/被描寫），再用三層比對找出
   `char_contexts`，據此生成構圖 prompt。

這兩套判定**互不知曉對方結果**。LLM 能分辨「只被提及未在場」，substring
比對不能。後果：`primary_char` 選中 A（A 的名字出現在文字中但只是被提及），
但 `present_chars` 判定真正在場的是 B → prompt 描述 B 的畫面，FaceID 卻把
A 的臉貼上去，人物識別錯亂且難以察覺（圖會生成，只是臉孔張冠李戴）。

## 設計：單一權威來源

`resolve_present_chars()` 中 LLM 的場景判定升級為唯一的「誰在場」來源；
FaceID 參考圖、character seed、構圖 prompt 三者都從同一份結果取值。

### 改動

| 檔案 | 改動 |
|------|------|
| `services/llm/tasks.py` | 把原 `expand_prompt` 的 Step 1+2（場景分析＋三層比對）拆成獨立函式 `resolve_present_chars(raw_text, character_descriptions, style_hint) -> {"scene","char_contexts","is_anime"}`；`expand_prompt` 改為呼叫它後再做 Step 3+4，回傳值由 `(prompt, is_anime)` 擴充為 `(prompt, is_anime, char_contexts)` |
| `services/illustration/generation.py::generate_illustration` | 新增 `book_id` / `character_name` 參數。不再由呼叫端預先決定 FaceID 參考圖或 seed；改為取得 `expand_prompt` 回傳的 `char_contexts`，以 `character_name`（使用者手動選角，優先）→ `char_contexts[0]`（LLM 確認在場）的順序決定 `primary_char`，FaceID 參考圖（`load_char_ref_image`）與 seed（`character_seed_for` / 文字 hash fallback）都從這個唯一結果解析 |
| `services/illustration/generation.py` 新增 `_find_text_primary_char()` | `direct_prompt`（使用者直接給完整 prompt，跳過 LLM 場景分析）情境沒有 `present_chars` 可用，保留簡單 substring fallback；這個情境本身沒有「LLM vs substring 互相矛盾」的風險，因為根本沒有第二套判定存在 |
| `services/illustration/refs.py`（新檔） | 把 `_load_char_ref_image` 的實作從 `routers/illustration_common.py` 搬到 service 層（service 不應反向 import routers），router 端保留同名轉出口 |
| `routers/illustration.py::_run_task` | 移除原本的 substring 掃描 + seed 解析 + ip_ref 載入，直接把 `text` / `character_descriptions` / `book_id` / `character_name`（使用者手動選角時的顯式覆寫）整包傳給 `generate_illustration` |

### 沒有改變的部分

- 使用者在前端手動選角（`req.character_name`，`Reader.tsx` 的 `selectedCharacter`）依然是最高優先權覆寫，行為不變。
- `generate_character_sheet` / `generate_portrait`（角色設定圖、立繪）不受影響——這兩個入口本來就是「使用者明確指定畫這個角色」，沒有「場景中誰在場」的歧義，原本就用顯式 `char_data`/`ip_adapter_image`。
- Step 3+4（構圖融合）邏輯本身（`_build_composition_prompt`）未變動。

## 驗收

- `backend/tests/` 32 個單元測試全綠（純函數測試，不需 GPU）。
- 手動冒煙：對同一段文字，A 被提及但不在場、B 在場時生圖，確認 FaceID 套用的是 B 的參考圖而非 A（待下次啟動 dev 環境時人工確認，本次修改未跑 GPU 驗證）。

## 風險 1（補一道文字層防線；實際生圖穩定度仍待觀察）

`description`（LLM 人設自由敘述）可能與結構化視覺 tags 衝突（如 description
寫「黑髮」蓋掉欄位 remap 的「dark blue hair」）。`_build_char_block_for_composition`
把兩者都丟給構圖 LLM 自行判斷取捨：

- anime 分支 system prompt 原本已有「Use 視覺 tags as the base for appearance;
  use 人設 to infer expression/mood」
- real（中文）分支**原本沒有對應規則**——已於本次補上對稱規則：
  「外觀欄位是畫面基底，若兩者描述的具體外觀不一致，以外觀欄位為準；
  人設只用來推斷表情、姿態與氣質」

這只是 prompt 層的軟約束，不是程式碼層硬性覆蓋；LLM 仍可能不遵守。
是否需要再加程式碼層硬約束（例如生成後比對結構化欄位與 LLM 輸出的關鍵詞），
待累積實際生圖樣本觀察跨場景穩定度後再決定。
