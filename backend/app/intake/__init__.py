"""Upload intake: file bytes -> the document pipeline (ingest, classify, extract) -> DocumentEnvelopes.

`bridge.py` maps the pipeline's ExtractionResult onto our envelope contract; `upload.py` runs one file
through the pipeline. Routes call `process_upload` with `default_engines()`.
"""

from __future__ import annotations

import importlib.util
import logging

from app import config
from app.documents.ports import OcrEngine, VlmClient
from app.documents.vlm import get_default_vlm
from app.intake.bridge import TYPE_MAP, to_envelope
from app.intake.upload import SkippedPart, UploadResult, process_upload

log = logging.getLogger(__name__)


def default_ocr() -> OcrEngine | None:
    """Local PaddleOCR when it is installed (it is heavy, ~1 GB); else None and photos need the VLM."""
    if importlib.util.find_spec("paddleocr") is None:
        return None
    from app.documents.ocr import get_default_ocr

    return get_default_ocr()


def default_engines() -> tuple[OcrEngine | None, VlmClient | None]:
    """OCR when installed; the VLM only alongside it, because OCR is what finds Aadhaar numbers to black out
    before a page image leaves the server (see config.VLM_WITHOUT_OCR)."""
    ocr, vlm = default_ocr(), get_default_vlm()
    if ocr is None and vlm is not None and not config.VLM_WITHOUT_OCR:
        log.warning("PaddleOCR is not installed: the VLM is off for uploads so unredacted images never leave the server")
        vlm = None
    return ocr, vlm


__all__ = ["SkippedPart", "TYPE_MAP", "UploadResult", "default_engines", "default_ocr", "process_upload", "to_envelope"]
