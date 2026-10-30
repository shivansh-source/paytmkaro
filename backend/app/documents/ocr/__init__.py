"""Local OCR: PaddleOCR 3.x (PP-OCRv6 detection, PP-OCRv5 recognition) behind the OcrEngine port.

The stages (detect -> crop -> textline orientation -> recognize) are wired here
instead of using the PaddleOCR pipeline class because, on Paddle 3.3 CPU, the
detection model crashes with oneDNN on ("ConvertPirAttribute2RuntimeAttribute not
support") while recognition runs ~5x faster with it. The pipeline class only has
one switch for both. paddleocr is imported lazily: importing this package is cheap,
and models load once per process via get_default_ocr().
"""

from __future__ import annotations

import io
import logging
import os
import threading
from typing import Any

import numpy as np
from PIL import Image

from app import config
from app.documents.models import OcrLine

__all__ = ["PaddleOcrEngine", "get_default_ocr"]

log = logging.getLogger(__name__)

REC_MODELS = {
    "hi": "devanagari_PP-OCRv5_mobile_rec",  # Devanagari + Latin: reads Hindi and English
    "en": "en_PP-OCRv5_mobile_rec",
}
# Measured on this CPU (no oneDNN for detection), synthetic 1654x2339 statement page with 40 rows:
#   v5 server det, full resolution (pipeline default): ~640 s
#   v5 server det, long side capped at 1280:            ~58 s
#   v6 medium det, long side capped at 1280:            ~26-33 s <- chosen
#   v6 medium det, long side capped at 960:             ~22-24 s
# Both read all 40 refs and 40 balances; 1280 keeps more detail for small print. Timings are
# noisy (shared CPU). PP-OCRv6_medium_det was already in this machine's model cache.
DET_MODEL = "PP-OCRv6_medium_det"
TEXTLINE_ORIENTATION_MODEL = "PP-LCNet_x1_0_textline_ori"
DET_OPTIONS = {"limit_side_len": 1280, "limit_type": "max", "thresh": 0.3, "box_thresh": 0.6, "unclip_ratio": 1.5}


def _crop(image: np.ndarray, poly: np.ndarray) -> np.ndarray:
    """Perspective-crop one detected text quad to an upright strip."""
    import cv2

    pts = poly.astype(np.float32)
    width = int(max(np.linalg.norm(pts[0] - pts[1]), np.linalg.norm(pts[2] - pts[3])))
    height = int(max(np.linalg.norm(pts[0] - pts[3]), np.linalg.norm(pts[1] - pts[2])))
    width, height = max(width, 1), max(height, 1)
    target = np.float32([[0, 0], [width, 0], [width, height], [0, height]])
    matrix = cv2.getPerspectiveTransform(pts, target)
    crop = cv2.warpPerspective(image, matrix, (width, height), borderMode=cv2.BORDER_REPLICATE, flags=cv2.INTER_CUBIC)
    if height / width >= 1.5:  # vertical strip: text runs top-to-bottom
        crop = np.rot90(crop)
    return np.ascontiguousarray(crop)


def _reading_order(polys: list[np.ndarray]) -> list[int]:
    """Top-to-bottom, then left-to-right for boxes on the same line (10 px tolerance)."""
    order = sorted(range(len(polys)), key=lambda i: (polys[i][:, 1].min(), polys[i][:, 0].min()))
    for _ in range(len(order)):
        changed = False
        for j in range(len(order) - 1):
            a, b = polys[order[j]], polys[order[j + 1]]
            if abs(b[:, 1].min() - a[:, 1].min()) < 10 and b[:, 0].min() < a[:, 0].min():
                order[j], order[j + 1] = order[j + 1], order[j]
                changed = True
        if not changed:
            break
    return order


class PaddleOcrEngine:
    """Text detection + recognition. `lang="hi"` (Devanagari) also reads English."""

    def __init__(self, lang: str | None = None, *, textline_orientation: bool = True, min_score: float = 0.3):
        self.lang = lang or config.OCR_LANG
        if self.lang not in REC_MODELS:
            raise ValueError(f"No recognition model configured for OCR_LANG={self.lang!r}; use one of {sorted(REC_MODELS)}")
        # Textline orientation reads upside-down phone photos; it costs little next to recognition.
        self.textline_orientation = textline_orientation
        self.min_score = min_score
        self._models: tuple[Any, Any, Any] | None = None
        self._lock = threading.Lock()  # Paddle predictors are not thread-safe

    def _load(self) -> tuple[Any, Any, Any]:
        if self._models is None:
            # Skip PaddleX's online model-host check; models are already in the local cache.
            os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
            from paddleocr import TextDetection, TextLineOrientationClassification, TextRecognition

            det = TextDetection(model_name=DET_MODEL, enable_mkldnn=False, **DET_OPTIONS)
            rec = TextRecognition(model_name=REC_MODELS[self.lang], enable_mkldnn=True)
            ori = (
                TextLineOrientationClassification(model_name=TEXTLINE_ORIENTATION_MODEL, enable_mkldnn=True)
                if self.textline_orientation
                else None
            )
            self._models = (det, rec, ori)
        return self._models

    def recognize(self, image_png: bytes) -> list[OcrLine]:
        image = Image.open(io.BytesIO(image_png)).convert("RGB")
        bgr = np.ascontiguousarray(np.asarray(image)[:, :, ::-1])  # Paddle expects OpenCV channel order
        with self._lock:
            det, rec, ori = self._load()
            polys = [np.asarray(p) for p in next(iter(det.predict(bgr)))["dt_polys"]]
            if not polys:
                return []
            order = _reading_order(polys)
            polys = [polys[i] for i in order]
            crops = [_crop(bgr, poly) for poly in polys]
            if ori is not None:
                for i, result in enumerate(ori.predict(crops)):
                    if result["label_names"][0] == "180_degree":
                        crops[i] = np.ascontiguousarray(crops[i][::-1, ::-1])
            texts = list(rec.predict(crops))
        lines = []
        for poly, result in zip(polys, texts):
            text, score = result["rec_text"], float(result["rec_score"])
            if not text.strip() or score < self.min_score:
                continue
            x0, y0 = (float(v) for v in poly.min(axis=0))
            x1, y1 = (float(v) for v in poly.max(axis=0))
            lines.append(OcrLine(text=text, confidence=min(max(score, 0.0), 1.0), bbox=(x0, y0, x1, y1)))
        return lines


_default: PaddleOcrEngine | None = None
_default_lock = threading.Lock()


def get_default_ocr() -> PaddleOcrEngine:
    """Process-wide engine; the models load on the first recognize() call."""
    global _default
    with _default_lock:
        if _default is None:
            _default = PaddleOcrEngine()
        return _default
