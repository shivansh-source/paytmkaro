"""Real PaddleOCR tests. Slow (seconds per image on CPU), so skipped unless RUN_OCR_TESTS=1:

    RUN_OCR_TESTS=1 python -m pytest tests/documents/test_ocr_paddle.py -s
"""

import io
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from PIL import Image

from app.documents.ingest import load_document
from app.documents.models import LoadStatus, TextSource
from app.documents.privacy import verhoeff_valid

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "documents"
AADHAAR = next(f"23456789012{d}" for d in "0123456789" if verhoeff_valid(f"23456789012{d}"))

real_ocr = pytest.mark.skipif(os.getenv("RUN_OCR_TESTS") != "1", reason="set RUN_OCR_TESTS=1 to run real PaddleOCR")


def test_importing_the_ocr_package_does_not_load_paddle():
    code = "import sys, app.documents.ocr as o; o.get_default_ocr(); print('paddleocr' in sys.modules)"
    backend = Path(__file__).resolve().parents[2]
    out = subprocess.run([sys.executable, "-c", code], cwd=backend, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


@pytest.fixture(scope="module")
def engine():
    from app.documents.ocr import get_default_ocr

    ocr = get_default_ocr()
    started = time.perf_counter()
    ocr._load()
    print(f"\n[ocr] model load {time.perf_counter() - started:.1f}s")
    return ocr


def timed_load(data: bytes, name: str, engine, **kwargs):
    started = time.perf_counter()
    doc = load_document(data, name, ocr=engine, **kwargs)
    pages = max(len(doc.pages), 1)
    print(f"[ocr] {name}: {time.perf_counter() - started:.1f}s for {pages} page(s)")
    return doc


@real_ocr
def test_pan_card_photo(engine):
    doc = timed_load((FIXTURES / "pan_card.jpg").read_bytes(), "pan_card.jpg", engine)
    page = doc.pages[0]
    assert page.text_source is TextSource.OCR
    assert "ABCDE1234F" in page.text
    assert "INCOME TAX" in page.text.upper()
    assert all(0 <= line.confidence <= 1 for line in page.ocr_lines)
    x0, y0, x1, y1 = page.ocr_lines[0].bbox
    assert 0 <= x0 < x1 <= page.width and 0 <= y0 < y1 <= page.height


@real_ocr
def test_aadhaar_card_is_masked_and_redacted(engine):
    doc = timed_load((FIXTURES / "aadhaar_front.png").read_bytes(), "aadhaar_front.png", engine)
    page = doc.pages[0]
    assert f"XXXX XXXX {AADHAAR[-4:]}" in page.text
    assert AADHAAR[:4] + " " + AADHAAR[4:8] not in doc.model_dump_json()
    # Read the redacted image again: the hidden digits must be gone from the pixels too.
    reread = " ".join(line.text for line in engine.recognize(page.image_png)).replace(" ", "")
    assert AADHAAR[:8] not in reread
    assert "Kumar" in page.text


@real_ocr
def test_upside_down_photo(engine):
    image = Image.open(FIXTURES / "pan_card.jpg").rotate(180)
    out = io.BytesIO()
    image.save(out, format="JPEG")
    doc = timed_load(out.getvalue(), "pan_upside_down.jpg", engine)
    assert "ABCDE1234F" in doc.pages[0].text


@real_ocr
def test_scanned_pdf_page(engine):
    doc = timed_load((FIXTURES / "gst_reg06_scanned.pdf").read_bytes(), "gst_reg06_scanned.pdf", engine)
    assert doc.status is LoadStatus.OK
    assert doc.pages[0].text_source is TextSource.OCR
    assert "REG-06" in doc.pages[0].text.replace(" ", "")


@real_ocr
def test_aadhaar_photo_pasted_into_a_text_pdf(engine):
    doc = timed_load((FIXTURES / "letter_with_aadhaar_photo.pdf").read_bytes(), "letter_with_aadhaar_photo.pdf", engine)
    page = doc.pages[0]
    assert page.text_source is TextSource.NATIVE and "term loan" in page.text
    assert f"XXXX XXXX {AADHAAR[-4:]}" in page.text
    assert page.aadhaar_verhoeff_valid == [True]
    assert AADHAAR[:8] not in doc.model_dump_json()
    reread = " ".join(line.text for line in engine.recognize(page.image_png)).replace(" ", "")
    assert AADHAAR[:8] not in reread  # the pixels no longer show the number either
