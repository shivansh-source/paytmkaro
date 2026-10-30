"""Aadhaar masking: only the last 4 digits ever leave ingest.

Ingest applies both functions to every page right after text/OCR is read, so
the classifier, the extractor and the hosted VLM never see a full number.

What counts as an Aadhaar number:
- 4-4-4 digit groups separated by a space or hyphen (how Aadhaar is printed):
  always masked.
- 12 contiguous digits: masked only when they pass the Verhoeff check AND the
  text mentions Aadhaar. Bank statements are full of 12-digit UPI references
  that must survive.
"""

from __future__ import annotations

import io
import re

from PIL import Image, ImageDraw

from app.documents.models import OcrLine

# Horizontal whitespace only: OCR lines are joined with "\n", and a year at the end of one
# line must not join digits on the next. Aadhaar cards print wide or non-breaking gaps.
_SEP = r"(?:[ \t  -​]+|[ \t]*-[ \t]*)"
_GROUPED = re.compile(rf"(?<!\d)([2-9]\d{{3}}){_SEP}(\d{{4}}){_SEP}(\d{{4}})(?!\d)")
_CONTIGUOUS = re.compile(r"(?<!\d)([2-9]\d{11})(?!\d)")
_KEYWORDS = re.compile(r"aadhaar|aadhar|uidai|unique identification|आधार", re.IGNORECASE)

# Verhoeff tables.
_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]


def verhoeff_valid(digits: str) -> bool:
    """Aadhaar's check digit scheme. `digits` must be digits only."""
    check = 0
    for i, ch in enumerate(reversed(digits)):
        check = _D[check][_P[i % 8][int(ch)]]
    return check == 0


def find_aadhaar_spans(text: str, context: str | None = None) -> list[tuple[int, int]]:
    """(start, end) of each Aadhaar number in `text`, for callers that redact by position."""
    return _spans(text, text if context is None else context)


def _spans(text: str, context: str) -> list[tuple[int, int]]:
    """(start, end) of each Aadhaar number in `text`; `context` decides whether contiguous runs count."""
    spans = [m.span() for m in _GROUPED.finditer(text)]
    if _KEYWORDS.search(context):
        spans += [m.span() for m in _CONTIGUOUS.finditer(text) if verhoeff_valid(m.group(1))]
    return spans


def _mask(number: str) -> str:
    return "XXXX XXXX " + re.sub(r"\D", "", number)[-4:]


def mask_aadhaar_text(text: str, context: str | None = None) -> str:
    """Replace each Aadhaar number with 'XXXX XXXX 1234'. `context` defaults to `text` itself;
    pass the whole page text when masking a single OCR line."""
    context = text if context is None else context
    for start, end in sorted(_spans(text, context), reverse=True):
        text = text[:start] + _mask(text[start:end]) + text[end:]
    return text


def mask_ocr_lines(lines: list[OcrLine], context: str) -> list[OcrLine]:
    return [line.model_copy(update={"text": mask_aadhaar_text(line.text, context)}) for line in lines]


def redact_aadhaar_image(image_png: bytes, lines: list[OcrLine], context: str) -> bytes:
    """Black out the first 8 digits of every Aadhaar number found by OCR. Lines are the
    unmasked OCR output for this image. Position inside a line is estimated from character
    offsets, so the box is padded. A number OCR missed is not redacted: callers must treat
    the result as best-effort."""
    boxes = []
    for line in lines:
        for start, end in _spans(line.text, context):
            # Cover from the number's start to just before its last 4 digits.
            x0, y0, x1, y1 = line.bbox
            per_char = (x1 - x0) / max(len(line.text), 1)
            cover_end = end - 4
            boxes.append((x0 + per_char * (start - 0.5), y0 - 2, x0 + per_char * (cover_end + 0.5), y1 + 2))
    if not boxes:
        return image_png

    image = Image.open(io.BytesIO(image_png)).convert("RGB")
    draw = ImageDraw.Draw(image)
    for box in boxes:
        draw.rectangle(box, fill="black")
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()
