"""
vepub 後端端對端驗證腳本

用法：
    uv run python test_e2e.py

會對 http://127.0.0.1:8765 的後端做自動化驗證。
請確保後端已啟動（npm run dev:backend 或直接 uv run uvicorn main:app --port 8765）。
"""
import sys
import os

# 強制 stdout/stderr 使用 UTF-8，避免 PowerShell cp950 編碼問題
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import json
import time
import httpx

BASE = "http://127.0.0.1:8765"
PASS = "[OK]"
FAIL = "[NG]"
INFO = "[--]"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = ""):
    icon = PASS if ok else FAIL
    print(f"  {icon}  {name}" + (f"  →  {detail}" if detail else ""))
    results.append((name, ok, detail))
    return ok


def section(title: str):
    print(f"\n{'─' * 55}")
    print(f"  {title}")
    print(f"{'─' * 55}")


# ─── 工具 ─────────────────────────────────────────────────────────────────────

def get(path: str, **kwargs):
    return httpx.get(f"{BASE}{path}", timeout=10, follow_redirects=True, **kwargs)


def post(path: str, **kwargs):
    return httpx.post(f"{BASE}{path}", timeout=10, follow_redirects=True, **kwargs)


def delete(path: str, **kwargs):
    return httpx.delete(f"{BASE}{path}", timeout=10, follow_redirects=True, **kwargs)


# ─── Phase 1：基礎健康檢查 ────────────────────────────────────────────────────

section("Phase 1：健康檢查")

try:
    r = get("/health/")
    check("後端可連線 /health/", r.status_code == 200, f"HTTP {r.status_code}")
    data = r.json()
    hw = data.get("hardware", {})
    check("有 hardware 欄位", "hardware" in data)
    check(f"GPU 偵測", bool(hw.get("gpu")), hw.get("gpu") or "null")
    check("CUDA 可用", hw.get("cuda_available", False), str(hw.get("cuda_available")))
except Exception as e:
    check("後端可連線", False, str(e))
    print(f"\n  ⚠️  後端無法連線，請先啟動：npm run dev:backend")
    sys.exit(1)


# ─── Phase 2：DB Schema 驗證 ──────────────────────────────────────────────────

section("Phase 2：DB Schema 驗證")

try:
    import sqlite3
    from pathlib import Path

    db_path = Path.home() / ".epub-tts" / "library.db"
    check("library.db 存在", db_path.exists(), str(db_path))

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    check("books 表存在", "books" in tables)
    check("characters 表存在", "characters" in tables)
    check("character_images 表存在", "character_images" in tables, "（新增 Phase 1 表）")
    check("illustrations 表存在", "illustrations" in tables)
    check("reading_progress 表存在", "reading_progress" in tables)
    check("bookmarks 表存在", "bookmarks" in tables)

    # 驗證 characters 新增欄位
    cols = {r[1] for r in conn.execute("PRAGMA table_info(characters)").fetchall()}
    new_cols = ["gender", "age_hint", "hair_color", "hair_style", "eye_color",
                "body_type", "height_cm", "weight_kg", "bwh", "cup_size", "signature_outfit", "other_features",
                "character_seed", "lora_path", "lora_trained_at"]
    for col in new_cols:
        check(f"  characters.{col}", col in cols)

    # 驗證 character_images 欄位
    img_cols = {r[1] for r in conn.execute("PRAGMA table_info(character_images)").fetchall()}
    for col in ["character_id", "image_base64", "angle", "is_primary"]:
        check(f"  character_images.{col}", col in img_cols)

    # 顯示目前書籍
    books = conn.execute("SELECT id, title FROM books").fetchall()
    print(f"\n  {INFO} 書庫中共 {len(books)} 本書：")
    for b in books:
        print(f"       - [{b['id'][:8]}...] {b['title']}")

    conn.close()

except Exception as e:
    check("DB schema 驗證", False, str(e))


# ─── Phase 3：角色庫 API CRUD ─────────────────────────────────────────────────

section("Phase 3：角色庫 API CRUD")

# 取得第一本書 book_id
try:
    books_r = get("/epub/books")
    books = books_r.json()
    check("GET /epub/books 成功", books_r.status_code == 200, f"{len(books)} 本")
    BOOK_ID = books[0]["id"] if books else None
    if BOOK_ID:
        print(f"  {INFO} 使用書籍：{books[0]['title']}")
    else:
        check("有書籍可用", False, "書庫為空，後續測試跳過")
except Exception as e:
    check("GET /epub/books", False, str(e))
    BOOK_ID = None

if BOOK_ID:
    TEST_CHAR = "__test_e2e_char__"

    # 新增角色（含結構化欄位）
    r = post(f"/illustration/characters/{BOOK_ID}", json={
        "name": TEST_CHAR,
        "gender": "女",
        "age_hint": "少女",
        "hair_color": "黑色",
        "hair_style": "長直",
        "eye_color": "棕色",
        "body_type": "苗條",
        "height_cm": 162,
        "weight_kg": 48,
        "bwh": "85-60-86",
        "cup_size": "C",
        "signature_outfit": "白色制服",
        "other_features": "左臉有小痣",
        "character_seed": -1,
    })
    check("POST /illustration/characters（新增角色）", r.status_code == 200)

    # 取得角色列表
    r = get(f"/illustration/characters/{BOOK_ID}")
    check("GET /illustration/characters（取得列表）", r.status_code == 200)
    chars = r.json()
    test_char = next((c for c in chars if c["name"] == TEST_CHAR), None)
    check("新角色出現在列表中", test_char is not None)

    if test_char:
        check("  gender 欄位正確", test_char.get("gender") == "女", test_char.get("gender"))
        check("  hair_color 欄位正確", test_char.get("hair_color") == "黑色")
        check("  height_cm 欄位正確", test_char.get("height_cm") == 162, str(test_char.get("height_cm")))
        check("  weight_kg 欄位正確", test_char.get("weight_kg") == 48, str(test_char.get("weight_kg")))
        check("  bwh 欄位正確", test_char.get("bwh") == "85-60-86", test_char.get("bwh"))
        check("  cup_size 欄位正確", test_char.get("cup_size") == "C", test_char.get("cup_size"))
        check("  images 為空 list", isinstance(test_char.get("images"), list) and len(test_char["images"]) == 0)

        # 新增角色圖片（1x1 白色 PNG base64）
        tiny_png = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI6QAAAABJRU5ErkJggg=="
        )
        r = post(f"/illustration/characters/{BOOK_ID}/{TEST_CHAR}/images", json={
            "image_base64": tiny_png,
            "angle": "正面",
            "is_primary": True,
        })
        check("POST .../images（新增角色圖片）", r.status_code == 200)
        img_id = r.json().get("id") if r.status_code == 200 else None
        check("  回傳 img id", img_id is not None, str(img_id))

        if img_id:
            # 取得圖片
            r = get(f"/illustration/characters/{BOOK_ID}/{TEST_CHAR}/images/{img_id}")
            check("GET .../images/{id}（取得單張圖）", r.status_code == 200)
            check("  image_base64 不為空", bool(r.json().get("image_base64")))

            # 設為主要
            r = post(f"/illustration/characters/{BOOK_ID}/{TEST_CHAR}/set_primary/{img_id}")
            check("POST .../set_primary（設主要圖）", r.status_code == 200)

            # 刪除圖片
            r = delete(f"/illustration/characters/{BOOK_ID}/{TEST_CHAR}/images/{img_id}")
            check("DELETE .../images/{id}（刪除圖片）", r.status_code == 200)

    # 驗證 build_character_fragment 組合邏輯
    print(f"\n  {INFO} 驗證 build_character_fragment 邏輯：")
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from services.illustration_engine import build_character_fragment, character_seed_for

    frag = build_character_fragment({
        "gender": "女", "age_hint": "少女",
        "hair_color": "黑色", "hair_style": "長直",
        "eye_color": "棕色", "body_type": "苗條",
        "height_cm": 162, "weight_kg": 48,
        "bwh": "85-60-86", "cup_size": "C",
        "signature_outfit": "白色制服",
        "other_features": "左臉有小痣",
    })
    check("build_character_fragment 有輸出", bool(frag), frag[:80])
    check("  包含性別", "女" in frag)
    check("  包含髮型描述", "黑色長直" in frag)
    check("  包含瞳色", "棕色瞳" in frag)
    check("  包含身高", "162cm" in frag)
    check("  包含體重", "48kg" in frag)
    check("  包含三圍", "三圍85-60-86" in frag)
    check("  包含罩杯", "C罩杯" in frag)

    seed = character_seed_for(BOOK_ID, "test_char")
    check("character_seed_for 穩定（兩次相同）",
          seed == character_seed_for(BOOK_ID, "test_char"),
          f"seed={seed}")
    check("  seed 在合法範圍", 0 <= seed <= 0x7FFF_FFFF)

    # fallback 測試：無結構化欄位時用 description
    frag_fallback = build_character_fragment({"description": "高挑的紅髮女子", "gender": None})
    check("build_character_fragment fallback（用 description）",
          frag_fallback == "高挑的紅髮女子", frag_fallback)

    # 清理測試角色
    r = delete(f"/illustration/characters/{BOOK_ID}/{TEST_CHAR}")
    check("DELETE /illustration/characters（清理）", r.status_code == 200)


# ─── Phase 4：插圖生成 API ────────────────────────────────────────────────────

section("Phase 4：插圖生成 API 狀態")

r = get("/illustration/status")
check("GET /illustration/status", r.status_code == 200)
if r.status_code == 200:
    status = r.json()
    check("  llm_available", status.get("llm_available", False),
          f"model={status.get('llm_model', 'null')}")
    check("  llm_model 有值", bool(status.get("llm_model")), status.get("llm_model") or "null")
    print(f"  {INFO} Z-Image 已載入：{status.get('model_loaded', False)}")

# 列出 transformers
r = get("/illustration/transformers")
check("GET /illustration/transformers", r.status_code == 200)
if r.status_code == 200:
    tfs = r.json()
    check("  至少有一個 transformer", len(tfs) > 0, f"共 {len(tfs)} 個")
    for t in tfs:
        active_mark = "★" if t["active"] else " "
        print(f"  {INFO}  [{active_mark}] {t['filename']}")


# ─── Phase 5：角色分析 API ────────────────────────────────────────────────────

section("Phase 5：角色分析 API（結構驗證，不實際執行 LLM）")

if BOOK_ID:
    # 測試：先查分析狀態（可能是 404 或之前任務的 200，都正常）
    r = get(f"/illustration/analyze_characters/{BOOK_ID}/status")
    check("GET analyze_characters/status 可查詢",
          r.status_code in (200, 404), f"HTTP {r.status_code}")
    if r.status_code == 200:
        prev = r.json()
        print(f"  {INFO} 存在上次分析任務（{prev.get('status')}），_analysis_jobs 無 TTL 清理屬已知 Bug")

    # 測試角色分析 API 端點回傳（不等待完成，只確認啟動成功）
    r = post(f"/illustration/analyze_characters/{BOOK_ID}?max_chapters=0")
    check("POST analyze_characters（max_chapters=0 全書）已啟動",
          r.status_code == 200 and r.json().get("status") in ("started", "already_running"),
          r.json().get("status", "error"))

    if r.status_code == 200 and r.json().get("status") == "started":
        time.sleep(1)
        # 確認任務狀態
        r2 = get(f"/illustration/analyze_characters/{BOOK_ID}/status")
        check("GET analyze_characters/status（啟動後可查詢）", r2.status_code == 200)
        if r2.status_code == 200:
            job = r2.json()
            check("  status 為 pending/running",
                  job.get("status") in ("pending", "running"), job.get("status"))
            print(f"  {INFO} 分析任務已啟動，狀態：{job.get('status')}，進度：{job.get('progress')}%")
            print(f"  {INFO} （分析任務在後台執行，不等待完成）")


# ─── Phase 6：多視角 API ──────────────────────────────────────────────────────

section("Phase 6：多視角 API（結構驗證）")

if BOOK_ID:
    # 嘗試對不存在的角色觸發多視角（應回 404）
    r = post(f"/illustration/characters/{BOOK_ID}/__nonexistent__/generate_angles",
             json={"angles": ["正面"]})
    check("generate_angles 對不存在角色回 404", r.status_code == 404, f"HTTP {r.status_code}")

    # 查詢不存在的 job（應回 404）
    r = get("/illustration/angle_jobs/nonexistent-job-id")
    check("GET angle_jobs/{id}（不存在）回 404", r.status_code == 404, f"HTTP {r.status_code}")


# ─── 結果摘要 ─────────────────────────────────────────────────────────────────

section("驗證結果摘要")

total  = len(results)
passed = sum(1 for _, ok, _ in results if ok)
failed = total - passed

print(f"\n  通過：{passed} / {total}")
if failed:
    print(f"\n  失敗項目：")
    for name, ok, detail in results:
        if not ok:
            print(f"    {FAIL}  {name}" + (f"  →  {detail}" if detail else ""))

print(f"\n{'═' * 55}")
if failed == 0:
    print("  🎉  全部通過！後端 API 狀態良好。")
else:
    print(f"  ⚠️   有 {failed} 項未通過，請檢查上方詳情。")
print(f"{'═' * 55}\n")

sys.exit(0 if failed == 0 else 1)
