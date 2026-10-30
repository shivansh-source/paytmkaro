import io

from PIL import Image

from app.documents.models import OcrLine
from app.documents.privacy import mask_aadhaar_text, redact_aadhaar_image, verhoeff_valid


def with_check_digit(base11: str) -> str:
    return next(base11 + d for d in "0123456789" if verhoeff_valid(base11 + d))


VALID = with_check_digit("23456789012")


def test_grouped_number_is_always_masked():
    assert mask_aadhaar_text("No. 2345 6789 0123 issued") == "No. XXXX XXXX 0123 issued"
    assert mask_aadhaar_text("2345-6789-0123") == "XXXX XXXX 0123"


def test_contiguous_number_needs_checksum_and_aadhaar_context():
    assert mask_aadhaar_text(f"Aadhaar {VALID}") == f"Aadhaar XXXX XXXX {VALID[-4:]}"
    # Same number in a bank statement with no Aadhaar mention: a UPI reference, keep it.
    assert mask_aadhaar_text(f"UPI/{VALID}/Payment") == f"UPI/{VALID}/Payment"
    # Aadhaar context but failing Verhoeff: not an Aadhaar number.
    bad = VALID[:-1] + str((int(VALID[-1]) + 1) % 10)
    assert mask_aadhaar_text(f"आधार {bad}") == f"आधार {bad}"


def test_numbers_starting_with_0_or_1_are_not_aadhaar():
    assert mask_aadhaar_text("1234 5678 9012") == "1234 5678 9012"


def test_image_redaction_blacks_out_digits():
    image = Image.new("RGB", (400, 40), "white")
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    line = OcrLine(text="2345 6789 0123", confidence=0.99, bbox=(0, 0, 280, 40))

    out = Image.open(io.BytesIO(redact_aadhaar_image(buf.getvalue(), [line], line.text))).convert("RGB")

    assert out.getpixel((40, 20)) == (0, 0, 0)  # inside the first 8 digits
    assert out.getpixel((390, 20)) == (255, 255, 255)  # outside the line


def test_image_without_aadhaar_is_returned_unchanged():
    data = b"not even decoded"
    assert redact_aadhaar_image(data, [OcrLine(text="ABCDE1234F", confidence=1, bbox=(0, 0, 1, 1))], "") is data
