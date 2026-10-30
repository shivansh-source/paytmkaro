"""Image ingest: decoding, EXIF rotation, size limits, OCR + Aadhaar redaction in the pipeline."""

import io
import zlib
from pathlib import Path

import pytest
from PIL import Image

from app.documents.fakes import FakeOcr
from app.documents.ingest import load_document
from app.documents.models import LoadStatus, OcrLine, TextSource
from app.documents.privacy import verhoeff_valid

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "documents"
AADHAAR = next(f"23456789012{d}" for d in "0123456789" if verhoeff_valid(f"23456789012{d}"))
GROUPED = f"{AADHAAR[:4]} {AADHAAR[4:8]} {AADHAAR[8:]}"


def png(image: Image.Image, **options) -> bytes:
    out = io.BytesIO()
    image.save(out, format=options.pop("format", "PNG"), **options)
    return out.getvalue()


def pixels(image_png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(image_png)).convert("L")


@pytest.mark.parametrize(
    "name", ["pan_card.jpg", "pan_card.heic", "aadhaar_front.png", "aadhaar_front.webp", "aadhaar_front.bmp"]
)
def test_single_images_always_ocr(name):
    ocr = FakeOcr([OcrLine(text="INCOME TAX DEPARTMENT", confidence=0.95, bbox=(0, 0, 100, 20))])
    doc = load_document((FIXTURES / name).read_bytes(), name, ocr=ocr)
    assert doc.status is LoadStatus.OK
    [page] = doc.pages
    assert page.text_source is TextSource.OCR and page.text == "INCOME TAX DEPARTMENT"
    assert pixels(page.image_png).mode == "L"  # decodable PNG
    assert ocr.calls == 1


def test_multipage_tiff_gives_one_page_per_frame():
    ocr = FakeOcr([OcrLine(text="some text", confidence=0.9, bbox=(0, 0, 10, 10))])
    doc = load_document((FIXTURES / "kyc_scans_multipage.tiff").read_bytes(), "scan.tif", ocr=ocr)
    assert [p.index for p in doc.pages] == [0, 1]
    assert ocr.calls == 2


def test_image_without_ocr_keeps_image_and_warns():
    doc = load_document((FIXTURES / "pan_card.jpg").read_bytes(), "pan.jpg")
    assert doc.status is LoadStatus.OK
    assert doc.pages[0].text_source is TextSource.NONE and doc.pages[0].image_png
    assert any("Aadhaar" in w for w in doc.warnings)
    assert any("No text" in w for w in doc.warnings)


def test_exif_rotation_is_applied():
    image = Image.new("RGB", (400, 200), "white")
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 CW on display
    doc = load_document(png(image, format="JPEG", exif=exif), "photo.jpg")
    assert (doc.pages[0].width, doc.pages[0].height) == (200, 400)


def test_large_photos_are_downscaled_and_transparency_flattened():
    image = Image.new("RGBA", (4000, 1000), (0, 0, 0, 0))
    doc = load_document(png(image), "big.png")
    page = doc.pages[0]
    assert (page.width, page.height) == (2500, 625)
    assert pixels(page.image_png).getpixel((10, 10)) == 255  # transparent -> white


def test_pixel_limit_is_too_large(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "MAX_IMAGE_PIXELS", 10_000)
    doc = load_document(png(Image.new("RGB", (200, 200))), "a.png")
    assert doc.status is LoadStatus.TOO_LARGE


def test_decompression_bomb_header_is_rejected_before_decoding():
    # A tiny PNG that claims 30000 x 30000 pixels.
    data = bytearray(png(Image.new("1", (1, 1))))
    data[16:24] = (30000).to_bytes(4, "big") * 2
    data[29:33] = zlib.crc32(bytes(data[12:29])).to_bytes(4, "big")
    doc = load_document(bytes(data), "bomb.png")
    assert doc.status is LoadStatus.TOO_LARGE


def test_truncated_image_is_unreadable():
    data = (FIXTURES / "pan_card.jpg").read_bytes()
    doc = load_document(data[:400], "pan.jpg")
    assert doc.status is LoadStatus.UNREADABLE


def test_tiff_frame_limit(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "MAX_PAGES", 1)
    doc = load_document((FIXTURES / "kyc_scans_multipage.tiff").read_bytes(), "scan.tif")
    assert doc.status is LoadStatus.TOO_LARGE


def test_aadhaar_is_masked_and_redacted_in_the_pipeline():
    # 22 chars over 440 px: 20 px per character.
    line = OcrLine(text=f"Aadhaar {GROUPED}", confidence=0.9, bbox=(0, 0, 440, 40))
    other = OcrLine(text=f"UPI ref {AADHAAR}", confidence=0.9, bbox=(0, 60, 400, 100))
    image = png(Image.new("RGB", (600, 120), "white"))
    doc = load_document(image, "aadhaar.png", ocr=FakeOcr([line, other]))
    page = doc.pages[0]

    masked = f"XXXX XXXX {AADHAAR[-4:]}"
    assert page.text == f"Aadhaar {masked}\nUPI ref XXXX XXXX {AADHAAR[-4:]}"  # page mentions Aadhaar
    assert [l.text for l in page.ocr_lines] == [f"Aadhaar {masked}", f"UPI ref XXXX XXXX {AADHAAR[-4:]}"]
    assert AADHAAR[:8] not in doc.model_dump_json()

    gray = pixels(page.image_png)
    for char in range(8, 17):  # every hidden digit position
        assert gray.getpixel((char * 20 + 10, 20)) == 0
    assert gray.getpixel((500, 20)) == 255  # outside the line box


def test_upside_down_line_is_redacted_on_both_sides():
    # On a 180-degree line the number sits at the left end in pixels although it is at
    # the right end of the text: the mirrored box must cover it.
    line = OcrLine(text=f"Aadhaar {GROUPED}", confidence=0.9, bbox=(0, 0, 440, 40))
    doc = load_document(png(Image.new("RGB", (600, 60), "white")), "a.png", ocr=FakeOcr([line]))
    gray = pixels(doc.pages[0].image_png)
    for char in range(5, 14):  # mirrored positions of the hidden digits
        assert gray.getpixel((char * 20 + 10, 20)) == 0


def test_numbers_without_aadhaar_context_survive():
    line = OcrLine(text=f"UPI/{AADHAAR}/Payment", confidence=0.9, bbox=(0, 0, 400, 40))
    doc = load_document(png(Image.new("RGB", (500, 60), "white")), "stmt.png", ocr=FakeOcr([line]))
    assert doc.pages[0].text == f"UPI/{AADHAAR}/Payment"
    assert pixels(doc.pages[0].image_png).getpixel((200, 20)) == 255


def test_number_split_into_separate_ocr_boxes_is_masked_and_redacted():
    # Cards print the groups with wide gaps; OCR returns each group as its own box.
    a, b, c = AADHAAR[:4], AADHAAR[4:8], AADHAAR[8:]
    fragments = [
        OcrLine(text="Aadhaar", confidence=0.9, bbox=(0, 0, 140, 40)),
        OcrLine(text=a, confidence=0.9, bbox=(200, 0, 280, 40)),
        OcrLine(text=b, confidence=0.9, bbox=(340, 2, 420, 42)),
        OcrLine(text=c, confidence=0.9, bbox=(480, 0, 560, 40)),
        OcrLine(text="DOB: 15/08/1990", confidence=0.9, bbox=(0, 80, 300, 120)),
    ]
    doc = load_document(png(Image.new("RGB", (600, 140), "white")), "card.png", ocr=FakeOcr(fragments))
    page = doc.pages[0]
    assert [l.text for l in page.ocr_lines] == ["Aadhaar", "XXXX", "XXXX", c, "DOB: 15/08/1990"]
    assert page.text == f"Aadhaar XXXX XXXX {c}\nDOB: 15/08/1990"
    assert a not in doc.model_dump_json() and b not in doc.model_dump_json()
    gray = pixels(page.image_png)
    assert gray.getpixel((240, 20)) == 0 and gray.getpixel((380, 20)) == 0


def test_odd_spacing_in_ocr_text_is_masked():
    a, b, c = AADHAAR[:4], AADHAAR[4:8], AADHAAR[8:]
    lines = [
        OcrLine(text=f"{a} {b} {c}", confidence=0.9, bbox=(0, 0, 280, 40)),
        OcrLine(text=f"{a}   {b}   {c}", confidence=0.9, bbox=(0, 60, 320, 100)),
    ]
    doc = load_document(png(Image.new("RGB", (400, 120), "white")), "card.png", ocr=FakeOcr(lines))
    assert doc.pages[0].text == f"XXXX XXXX {c}\nXXXX XXXX {c}"
