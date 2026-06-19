"""角色參考圖讀取（供 IP-Adapter FaceID 使用）。
原本內嵌於 routers/illustration_common.py，搬到 service 層以便
generation.py 可以直接呼叫（service 不應反向 import routers）。
routers/illustration_common.py 的 _load_char_ref_image 改為轉出口。
"""
import base64 as _b64
import io as _io

from services.db import get_db_connection, DB_DIR

_IMAGES_DIR = DB_DIR / "images"


def load_char_ref_image(book_id: str, char_name: str):
    """讀取角色參考圖，優先取 primary；無 primary 時 fallback 到最新一張。"""
    try:
        from PIL import Image as _Image
        conn = get_db_connection()
        # ORDER BY is_primary DESC 讓 primary=1 排最前；沒有 primary 時取最新
        row = conn.execute(
            """SELECT ci.image_path, ci.image_base64
               FROM character_images ci
               JOIN characters c ON c.id = ci.character_id
               WHERE c.book_id=? AND c.name=?
               ORDER BY ci.is_primary DESC, ci.created_at DESC
               LIMIT 1""",
            (book_id, char_name),
        ).fetchone()
        conn.close()
        if not row:
            return None
        if row["image_path"]:
            path = _IMAGES_DIR / row["image_path"]
            if path.exists():
                return _Image.open(path).convert("RGB")
        if row["image_base64"]:
            data = _b64.b64decode(row["image_base64"])
            return _Image.open(_io.BytesIO(data)).convert("RGB")
    except Exception:
        pass
    return None
