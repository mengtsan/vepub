"""
InsightFace ArcFace 包裝器。
Lazy-load buffalo_l：首次呼叫時才初始化，後續直接使用快取實例。
GPU 優先，失敗則退回 CPU。
"""
import logging
import threading
from typing import Optional, Tuple

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

_app = None
_app_lock = threading.Lock()


def _get_app():
    global _app
    if _app is not None:
        return _app
    with _app_lock:
        if _app is not None:
            return _app
        try:
            from insightface.app import FaceAnalysis
            import torch

            ctx_id = 0 if torch.cuda.is_available() else -1
            providers = ["CUDAExecutionProvider"] if ctx_id == 0 else ["CPUExecutionProvider"]
            app = FaceAnalysis(name="buffalo_l", providers=providers)
            app.prepare(ctx_id=ctx_id, det_size=(640, 640))
            _app = app
            device_str = "GPU" if ctx_id == 0 else "CPU"
            logger.info("InsightFace buffalo_l 已載入 (%s)", device_str)
        except Exception as e:
            raise RuntimeError(f"InsightFace 載入失敗（請確認 insightface 已安裝）: {e}") from e
    return _app


def extract_face(
    image: Image.Image,
) -> Tuple[Optional["torch.Tensor"], Optional[Image.Image]]:
    """
    偵測人臉並回傳 ArcFace embedding 與對齊人臉圖。

    Returns:
        (embedding, aligned_face)
        - embedding: torch.Tensor shape (1, 512), float32；未偵測到時為 None
        - aligned_face: PIL.Image 224×224；無法對齊時為 None
    """
    import torch

    try:
        app = _get_app()
    except Exception as e:
        logger.warning("InsightFace 不可用: %s", e)
        return None, None

    img_bgr = np.array(image.convert("RGB"))[:, :, ::-1].copy()

    try:
        faces = app.get(img_bgr)
    except Exception as e:
        logger.warning("InsightFace 偵測失敗: %s", e)
        return None, None

    # 動漫臉部特徵不明顯，降低閾值重試
    if not faces:
        try:
            app.det_model.det_thresh = 0.3
            faces = app.get(img_bgr)
        except Exception:
            pass
        finally:
            try:
                app.det_model.det_thresh = 0.5
            except Exception:
                pass

    if not faces:
        logger.info("InsightFace: 未偵測到人臉（動漫角色可能觸發此情況）")
        return None, None

    face = max(faces, key=lambda f: f.det_score)
    embedding = torch.from_numpy(
        np.array(face.normed_embedding, dtype=np.float32)
    ).unsqueeze(0)  # (1, 512)

    aligned_face: Optional[Image.Image] = None
    try:
        from insightface.utils import face_align
        aimg = face_align.norm_crop(img_bgr, landmark=face.kps, image_size=224)
        aligned_face = Image.fromarray(aimg[:, :, ::-1])
    except Exception:
        pass

    return embedding, aligned_face
