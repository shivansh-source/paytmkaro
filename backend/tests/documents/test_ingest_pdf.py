"""PDF ingest: per-page text layer vs scan, passwords, limits, Aadhaar redaction."""

import io
import re
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image

from app.documents.fakes import FakeOcr
from app.documents.ingest import load_document
from app.documents.models import LoadStatus, OcrLine, TextSource

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "documents"
PASSWORD = "KUMA1990"


def read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def fake_ocr(text: str = "PERMANENT ACCOUNT NUMBER ABCDE1234F R. KUMAR") -> FakeOcr:
    return FakeOcr([OcrLine(text=text, confidence=0.9, bbox=(10, 10, 500, 40))])


def test_text_layer_pdf_is_native_and_not_ocrd():
    ocr = fake_ocr()
    doc = load_document(read("gst_reg06.pdf"), "gst.pdf", ocr=ocr)
    assert doc.status is LoadStatus.OK
    [page] = doc.pages
    assert page.text_source is TextSource.NATIVE
    assert "Form GST REG-06" in page.text and "27ABCDE1234F" in page.text
    assert page.image_png and page.width and page.height
    assert ocr.calls == 0


def test_scanned_pdf_is_ocrd():
    ocr = fake_ocr()
    doc = load_document(read("gst_reg06_scanned.pdf"), "scan.pdf", ocr=ocr)
    [page] = doc.pages
    assert page.text_source is TextSource.OCR
    assert "ABCDE1234F" in page.text
    assert ocr.calls == 1


def test_scanned_pdf_without_ocr_keeps_image_and_warns():
    doc = load_document(read("gst_reg06_scanned.pdf"), "scan.pdf")
    assert doc.status is LoadStatus.OK
    [page] = doc.pages
    assert page.text_source is TextSource.NONE and page.text == ""
    assert page.image_png
    assert any("scanned" in w for w in doc.warnings)
    assert any("No text" in w for w in doc.warnings)


def test_scan_decision_is_per_page():
    ocr = fake_ocr()
    doc = load_document(read("mixed_bundle.pdf"), "bundle.pdf", ocr=ocr)
    # Page 1 born-digital, page 2 a bare scan, page 3 a scan with only a SAMPLE text stamp.
    assert [p.text_source for p in doc.pages] == [TextSource.NATIVE, TextSource.OCR, TextSource.OCR]
    assert ocr.calls == 2


def test_scanner_app_footer_does_not_make_a_scan_native():
    ocr = fake_ocr()
    doc = load_document(read("pan_camscanner.pdf"), "pan.pdf", ocr=ocr)
    assert doc.pages[0].text_source is TextSource.OCR
    assert ocr.calls == 1


def test_password_protected_pdf():
    data = read("e_aadhaar_encrypted.pdf")
    missing = load_document(data, "eaadhaar.pdf")
    assert missing.status is LoadStatus.PASSWORD_REQUIRED
    assert "password" in missing.message.lower()
    wrong = load_document(data, "eaadhaar.pdf", password="WRONG123")
    assert wrong.status is LoadStatus.PASSWORD_REQUIRED
    assert "incorrect" in wrong.message.lower()
    ok = load_document(data, "eaadhaar.pdf", password=PASSWORD)
    assert ok.status is LoadStatus.OK
    assert "e-Aadhaar" in ok.text


def test_aadhaar_in_text_layer_is_masked_in_text_and_blacked_out_in_image():
    doc = load_document(read("e_aadhaar_encrypted.pdf"), "eaadhaar.pdf", password=PASSWORD)
    page = doc.pages[0]
    assert "XXXX XXXX " in page.text
    digits = "".join(ch for ch in page.text if ch.isdigit())
    assert len(digits) < 12 + 8  # DOB digits + last 4 only; never the full number

    # Locate the number in the rendered page through pdfium itself, independent of ingest.
    pdf = pdfium.PdfDocument(read("e_aadhaar_encrypted.pdf"), password=PASSWORD)
    textpage = pdf[0].get_textpage()
    # The fixture prints the groups with wide gaps, like the card does.
    match = re.search(r"(\d{4}) +(\d{4}) +(\d{4})", textpage.get_text_range())
    width_pt, height_pt = pdf[0].get_size()
    image = Image.open(io.BytesIO(page.image_png)).convert("L")
    scale = image.width / width_pt

    def shade(char_index: int) -> int:
        left, bottom, right, top = textpage.get_charbox(char_index)
        return image.getpixel((int((left + right) / 2 * scale), int((height_pt - (top + bottom) / 2) * scale)))

    assert shade(match.start(1) + 1) < 40 and shade(match.start(2) + 1) < 40  # hidden digits blacked out
    pdf.close()


def test_page_limit(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "MAX_PAGES", 2)
    doc = load_document(read("mixed_bundle.pdf"), "bundle.pdf")
    assert doc.status is LoadStatus.TOO_LARGE
    assert "3 pages" in doc.message


def test_ocr_failure_is_a_warning_not_a_crash():
    class Broken:
        def recognize(self, image_png):
            raise RuntimeError("paddle exploded")

    doc = load_document(read("gst_reg06_scanned.pdf"), "scan.pdf", ocr=Broken())
    assert doc.status is LoadStatus.OK
    assert doc.pages[0].text_source is TextSource.NONE
    assert any("OCR error" in w for w in doc.warnings)


def test_stamps_and_scanner_footers_are_not_a_text_layer():
    from app.documents.ingest.common import has_real_text

    assert not has_real_text("SAMPLE")
    assert not has_real_text("Scanned with CamScanner\nSAMPLE SPECIMEN")
    assert not has_real_text("Scanned by TapScanner on 12/04/2025 10:31")
    assert has_real_text("Form GST REG-06 Registration Certificate")
