"""Shared helpers for the format loaders: errors, image normalisation, and the
per-page finish step that applies OCR and the Aadhaar privacy invariant."""

from __future__ import annotations

import io
import logging
import re
import warnings
import zipfile

from PIL import Image, ImageDraw, ImageOps

from app import config
from app.documents.models import LoadStatus, OcrLine, Page, TextSource
from app.documents.ports import OcrEngine
from app.documents.privacy import find_aadhaar_spans, mask_aadhaar_text, redact_aadhaar_image

log = logging.getLogger(__name__)

MAX_SIDE = 2500  # long side of page images handed to OCR / VLM
MIN_NATIVE_CHARS = 20
# Words that put a text layer on a scan without making it born-digital: watermarks and
# the footers scanner apps stamp on every page.
_STAMP_WORDS = re.compile(
    r"\b(sample|specimen|watermark|draft|copy|confidential|void)\b"
    r"|scanned (with|by|using)[^\n]*|camscanner|adobe scan|microsoft lens|office lens|genius scan|tapscanner",
    re.IGNORECASE,
)


class IngestError(Exception):
    """A user-facing load failure; becomes LoadedDocument.status/message."""

    def __init__(self, status: LoadStatus, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def too_large(what: str) -> IngestError:
    return IngestError(LoadStatus.TOO_LARGE, what)


def check_page_count(count: int) -> None:
    if count > config.MAX_PAGES:
        raise too_large(f"This file has {count} pages; the limit is {config.MAX_PAGES}. Upload only the pages needed.")


def meaningful_chars(text: str) -> int:
    """Alphanumeric characters left after removing watermarks and scanner-app footers."""
    return sum(ch.isalnum() for ch in _STAMP_WORDS.sub("", text))


def has_real_text(text: str) -> bool:
    return meaningful_chars(text) >= MIN_NATIVE_CHARS


def to_png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=False)
    return out.getvalue()


def check_pixels(width: int, height: int) -> None:
    if width * height > config.MAX_IMAGE_PIXELS:
        raise too_large(f"Image is {width}x{height} pixels, too large to process. Upload a smaller photo or scan.")


def normalize_image(image: Image.Image) -> Image.Image:
    """EXIF-rotate, convert to RGB (flattening transparency on white), cap the long side."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        image = ImageOps.exif_transpose(image)
    if image.mode in ("RGBA", "LA", "P", "PA"):
        image = image.convert("RGBA")
        background = Image.new("RGB", image.size, "white")
        background.paste(image, mask=image.getchannel("A"))
        image = background
    elif image.mode != "RGB":
        image = image.convert("RGB")
    if max(image.size) > MAX_SIDE:
        scale = MAX_SIDE / max(image.size)
        image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.LANCZOS)
    return image


def mask_tables(tables: list[list[list[str]]], context: str) -> list[list[list[str]]]:
    return [[[mask_aadhaar_text(cell, context) for cell in row] for row in table] for table in tables]


def native_page(index: int, text: str, tables: list[list[list[str]]] | None = None) -> Page:
    """A page whose text came from the file itself (cells, docx runs, plain text)."""
    tables = tables or []
    context = text + "\n" + "\n".join("\t".join(row) for table in tables for row in table)
    return Page(
        index=index,
        text=mask_aadhaar_text(text, context),
        text_source=TextSource.NATIVE if text.strip() else TextSource.NONE,
        tables=mask_tables(tables, context),
    )


def ocr_page(
    index: int, image: Image.Image, ocr: OcrEngine | None, warnings_out: list[str], image_png: bytes | None = None
) -> Page:
    """Image page: OCR (when an engine is given), then redact the image and mask the text.
    `image_png` overrides the encoding of `image` (e.g. already redacted from a text layer)."""
    image_png = image_png or to_png(image)
    page = Page(index=index, image_png=image_png, width=image.width, height=image.height)
    if ocr is None:
        return page
    try:
        raw_lines = [line for line in ocr.recognize(image_png) if line.text.strip()]
    except Exception as exc:  # an OCR crash must not fail the whole upload
        log.warning("OCR failed on page %d: %s", index, type(exc).__name__)
        warnings_out.append(f"Page {index + 1}: text could not be read (OCR error).")
        return page
    rows = _rows(raw_lines)
    context = "\n".join(text for text, _ in rows)
    masked_texts = [line.text for line in raw_lines]
    boxes = []
    for row_text, spans in rows:
        for number_start, number_end in find_aadhaar_spans(row_text, context):
            region = (number_start, number_end - 4)  # the last 4 digits stay visible
            hit = [(i, start, max(region[0], start), min(region[1], end)) for i, (start, end) in spans]
            hit = [h for h in hit if h[2] < h[3]]
            for i, start, lo, hi in hit:
                if len(hit) > 1:
                    # Number split across boxes: X out this fragment's share of the hidden digits.
                    chars = list(masked_texts[i])
                    for k in range(lo - start, hi - start):
                        if chars[k].isdigit():
                            chars[k] = "X"
                    masked_texts[i] = "".join(chars)
                boxes.extend(_fragment_boxes(raw_lines[i], lo - start, hi - start))

    page.image_png = redact_boxes(redact_aadhaar_image(image_png, raw_lines, context=context), boxes)
    page.ocr_lines = [
        line.model_copy(update={"text": mask_aadhaar_text(text, context)}) for line, text in zip(raw_lines, masked_texts)
    ]
    page.text = mask_aadhaar_text("\n".join(" ".join(page.ocr_lines[i].text for i, _ in spans) for _, spans in rows))
    page.text_source = TextSource.OCR if page.text.strip() else TextSource.NONE
    return page


def _rows(lines: list[OcrLine]) -> list[tuple[str, list[tuple[int, tuple[int, int]]]]]:
    """Group OCR fragments that sit on the same visual row, left to right. Aadhaar cards print
    the number with wide gaps, so OCR often returns '2345', '6789', '0124' as separate boxes;
    masking must see them joined. Returns (row text, [(line index, (start, end) in row text)])."""
    order = sorted(range(len(lines)), key=lambda i: (lines[i].bbox[1] + lines[i].bbox[3]) / 2)
    groups: list[list[int]] = []
    for i in order:
        _, y0, _, y1 = lines[i].bbox
        if groups:
            last = groups[-1]
            top = min(lines[j].bbox[1] for j in last)
            bottom = max(lines[j].bbox[3] for j in last)
            overlap = min(y1, bottom) - max(y0, top)
            if overlap >= 0.5 * min(y1 - y0, bottom - top):
                last.append(i)
                continue
        groups.append([i])
    rows = []
    for group in groups:
        group.sort(key=lambda j: lines[j].bbox[0])
        text, spans = "", []
        for j in group:
            if text:
                text += " "
            spans.append((j, (len(text), len(text) + len(lines[j].text))))
            text += lines[j].text
        rows.append((text, spans))
    return rows


def _fragment_boxes(line: OcrLine, start: int, end: int) -> list[tuple[float, float, float, float]]:
    """Box for characters [start, end) of one OCR fragment, estimated from character offsets,
    plus its mirror image: on an upside-down line (read via textline orientation) the text runs
    right-to-left in pixels. On upright lines the mirror can also hide the visible last 4
    digits in the image, which is the safe direction to err."""
    x0, y0, x1, y1 = line.bbox
    per_char = (x1 - x0) / max(len(line.text), 1)
    return [
        (x0 + per_char * (start - 0.5), y0, x0 + per_char * (end + 0.5), y1),
        (x1 - per_char * (end + 0.5), y0, x1 - per_char * (start - 0.5), y1),
    ]


def redact_boxes(image_png: bytes, boxes: list[tuple[float, float, float, float]]) -> bytes:
    if not boxes:
        return image_png
    image = Image.open(io.BytesIO(image_png)).convert("RGB")
    draw = ImageDraw.Draw(image)
    for x0, y0, x1, y1 in boxes:
        draw.rectangle((x0 - 2, y0 - 2, x1 + 2, y1 + 2), fill="black")
    return to_png(image)


MAX_UNZIPPED_BYTES = 200 * 1024 * 1024


def check_zip(data: bytes) -> None:
    """Zip-bomb guard for DOCX/XLSX before a parser inflates them."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            total = sum(info.file_size for info in archive.infolist())
    except zipfile.BadZipFile:
        raise IngestError(LoadStatus.UNREADABLE, "This file is damaged and could not be opened.")
    if total > MAX_UNZIPPED_BYTES:
        raise too_large("This file expands to too much data to process safely.")
