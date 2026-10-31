"""PDF loader (pypdfium2): text layer per page, page render, OCR for scanned pages.

The decision "text layer or scan" is made per page: a bundle can mix a born-digital
bank statement page with a scanned PAN card page.
"""

from __future__ import annotations

import ctypes
import math

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from PIL import Image

from app import config
from app.documents.models import LoadStatus, OcrLine, Page, TextSource
from app.documents.ports import OcrEngine
from app.documents.privacy import find_aadhaar_spans, mask_aadhaar_text
from app.documents.ingest.common import (
    MAX_SIDE,
    IngestError,
    check_page_count,
    has_real_text,
    mask_ocr_page,
    mask_tables,
    meaningful_chars,
    ocr_page,
    redact_boxes,
    run_ocr,
    to_png,
    verhoeff_flags,
)

# Below this many meaningful characters, a page mostly covered by an image is a scan.
SCAN_TEXT_CHARS = 200


def _open(data: bytes, password: str | None) -> pdfium.PdfDocument:
    try:
        return pdfium.PdfDocument(data, password=password)
    except pdfium.PdfiumError as exc:
        if "password" in str(exc).lower():
            if password:
                raise IngestError(LoadStatus.PASSWORD_REQUIRED, "The password for this PDF is incorrect. Please try again.")
            raise IngestError(
                LoadStatus.PASSWORD_REQUIRED,
                "This PDF is password protected. Enter its password (for e-Aadhaar it is usually the first 4 letters "
                "of your name in capitals + birth year; bank statements often use your customer ID or date of birth).",
            )
        raise IngestError(LoadStatus.UNREADABLE, "This PDF is damaged or not a valid PDF. Please download it again.")


def _render_scale(page: pdfium.PdfPage) -> float:
    width, height = page.get_size()
    scale = config.RENDER_DPI / 72
    scale = min(scale, MAX_SIDE / max(width, height, 1))
    return min(scale, math.sqrt(config.MAX_IMAGE_PIXELS / max(width * height, 1)))


def _to_device(page: pdfium.PdfPage, size: tuple[int, int], x: float, y: float) -> tuple[int, int]:
    dx, dy = ctypes.c_int(), ctypes.c_int()
    pdfium_c.FPDF_PageToDevice(page.raw, 0, 0, size[0], size[1], 0, x, y, ctypes.byref(dx), ctypes.byref(dy))
    return dx.value, dy.value


def _text_layer_boxes(
    page: pdfium.PdfPage, textpage: pdfium.PdfTextPage, text: str, size: tuple[int, int]
) -> list[tuple[float, float, float, float]]:
    """Pixel boxes covering the hidden part of every Aadhaar number in the text layer."""
    boxes = []
    offset = 0
    for line in text.splitlines(keepends=True):
        for number_start, number_end in find_aadhaar_spans(line.rstrip("\r\n"), text):
            region = (number_start, number_end - 4)  # the last 4 digits stay visible
            xs, ys = [], []
            for text_index in range(offset + region[0], offset + region[1]):
                char_index = pdfium_c.FPDFText_GetCharIndexFromTextIndex(textpage.raw, text_index)
                if char_index < 0:
                    continue
                left, bottom, right, top = textpage.get_charbox(char_index)
                for x, y in ((left, bottom), (right, top)):
                    px, py = _to_device(page, size, x, y)
                    xs.append(px)
                    ys.append(py)
            if xs:
                boxes.append((min(xs), min(ys), max(xs), max(ys)))
        offset += len(line)
    return boxes


Cell = tuple[str, float, float]  # text, left, right (PDF points)


def _line_cells(textpage: pdfium.PdfTextPage, line: str, offset: int) -> list[Cell]:
    """Split one text line into cells: a gap wider than ~0.9 of the glyph height, or two or
    more spaces, starts a new cell. Born-digital statements put every column at its own x."""
    glyphs = []  # (char, left, right, height)
    for index, char in enumerate(line):
        char_index = pdfium_c.FPDFText_GetCharIndexFromTextIndex(textpage.raw, offset + index)
        if char_index < 0:
            continue
        left, bottom, right, top = textpage.get_charbox(char_index)
        glyphs.append((char, left, right, top - bottom))
    heights = sorted(h for ch, _, _, h in glyphs if not ch.isspace() and h > 0)
    if not heights:
        return []
    threshold = 0.9 * heights[len(heights) // 2]
    cells: list[list] = []
    spaces, previous_right = 0, None
    for char, left, right, _ in glyphs:
        if char.isspace():
            spaces += 1
            continue
        if cells and previous_right is not None and (spaces >= 2 or left - previous_right > threshold):
            cells.append([char, left, right])
        elif cells:
            cells[-1][0] += (" " if spaces else "") + char
            cells[-1][2] = right
        else:
            cells.append([char, left, right])
        spaces, previous_right = 0, right
    return [(text, left, right) for text, left, right in cells]


def _columns(rows: list[list[Cell]]) -> list[tuple[float, float]]:
    """Column x-ranges: the union of every cell's range, so empty cells keep their column."""
    spans = sorted((left, right) for row in rows for _, left, right in row)
    columns: list[list[float]] = []
    for left, right in spans:
        if columns and left <= columns[-1][1]:
            columns[-1][1] = max(columns[-1][1], right)
        else:
            columns.append([left, right])
    return [(left, right) for left, right in columns]


def _text_layer_tables(textpage: pdfium.PdfTextPage, raw: str) -> list[list[list[str]]]:
    """Rebuild tables from a text layer. A table is a run of lines that split into 2+ cells
    (a lone-cell section label such as "ASSETS" may sit inside the run); it needs 3+ lines and
    either a line with 3+ cells or 4+ lines (key/value tables). Cells go to columns by x
    position. Heuristic: wide-spaced prose can look like a table, and OCR'd pages get none."""
    runs: list[list[list[Cell]]] = []
    current: list[list[Cell]] = []
    pending: list[list[Cell]] = []  # lone-cell lines waiting to see if the table continues

    def close() -> None:
        nonlocal current, pending
        if len(current) >= 3 and (len(current) >= 4 or max(len(r) for r in current) >= 3):
            runs.append(current)
        current, pending = [], []

    offset = 0
    for line in raw.splitlines(keepends=True):
        cells = _line_cells(textpage, line.rstrip("\r\n"), offset)
        offset += len(line)
        if len(cells) >= 2:
            current.extend(pending)
            pending = []
            current.append(cells)
        elif len(cells) == 1 and current and not pending:
            pending.append(cells)
        else:
            close()
    close()

    tables = []
    for run in runs:
        columns = _columns([row for row in run if len(row) >= 2])
        table = []
        for row in run:
            values = [""] * len(columns)
            for text, left, right in row:
                column = next((i for i, (lo, hi) in enumerate(columns) if left <= hi and right >= lo), 0)
                values[column] = f"{values[column]} {text}".strip()
            table.append(values)
        tables.append(table)
    return tables


def _image_coverage(page: pdfium.PdfPage) -> float:
    """Share of the page area covered by image objects (approximate: overlaps add up)."""
    width, height = page.get_size()
    covered = 0.0
    for obj in page.get_objects(filter=(pdfium_c.FPDF_PAGEOBJ_IMAGE,)):
        left, bottom, right, top = obj.get_bounds()
        covered += max(right - left, 0) * max(top - bottom, 0)
    return min(covered / max(width * height, 1), 1.0)


EMBEDDED_IMAGE_SHARE = 0.05  # an image this big (share of the page) may be a pasted ID photo


def _large_image_boxes(page: pdfium.PdfPage, size: tuple[int, int]) -> list[tuple[float, float, float, float]]:
    """Pixel boxes of image objects covering a meaningful share of the page (logos are skipped,
    so ordinary statements never pay for a second OCR pass)."""
    width, height = page.get_size()
    boxes = []
    for obj in page.get_objects(filter=(pdfium_c.FPDF_PAGEOBJ_IMAGE,)):
        left, bottom, right, top = obj.get_bounds()
        if (right - left) * (top - bottom) < EMBEDDED_IMAGE_SHARE * width * height:
            continue
        (x0, y0), (x1, y1) = _to_device(page, size, left, top), _to_device(page, size, right, bottom)
        boxes.append((min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)))
    return boxes


def _read_embedded_images(
    page: Page, ocr: OcrEngine, boxes: list[tuple[float, float, float, float]], warnings: list[str]
) -> None:
    """A text-layer page with a big picture (an Aadhaar photo pasted into a PDF): OCR the render,
    redact any Aadhaar number anywhere on it, and add the text found inside the picture."""
    lines = run_ocr(page.index, page.image_png, ocr, warnings)
    if lines is None:
        return

    def inside(line: OcrLine) -> bool:
        x0, y0, x1, y1 = line.bbox
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        return any(bx0 <= cx <= bx1 and by0 <= cy <= by1 for bx0, by0, bx1, by1 in boxes)

    result = mask_ocr_page(lines, page.image_png, include=inside)
    page.image_png = result.image_png
    page.ocr_lines = [line for line in result.lines if inside(line)]
    page.aadhaar_verhoeff_valid += result.verhoeff
    if result.text:
        page.text = f"{page.text}\n{result.text}" if page.text else result.text


def _is_born_digital(page: pdfium.PdfPage, text: str) -> bool:
    """Real text layer, and not a scan with a short stamp/footer on top. A searchable scan
    (scanner app with an invisible OCR layer) has plenty of text and counts as born-digital."""
    if not has_real_text(text):
        return False
    return meaningful_chars(text) >= SCAN_TEXT_CHARS or _image_coverage(page) < 0.5


def load_pdf(data: bytes, password: str | None, ocr: OcrEngine | None, warnings: list[str]) -> list[Page]:
    pdf = _open(data, password)
    try:
        check_page_count(len(pdf))
        pages = []
        scanned_without_ocr = images_unchecked = 0
        for index in range(len(pdf)):
            page = pdf[index]
            textpage = page.get_textpage()
            raw = textpage.get_text_range()  # unnormalised, so offsets match pdfium's text indexes
            text = "\n".join(raw.splitlines())
            image: Image.Image = page.render(scale=_render_scale(page)).to_pil().convert("RGB")
            # Any Aadhaar number in the text layer is also visible in the render: black it out
            # using the exact character boxes, whatever happens to the page next.
            image_png = redact_boxes(to_png(image), _text_layer_boxes(page, textpage, raw, image.size))

            if _is_born_digital(page, text):
                native = Page(
                    index=index,
                    text=mask_aadhaar_text(text),
                    text_source=TextSource.NATIVE,
                    tables=mask_tables(_text_layer_tables(textpage, raw), text),
                    aadhaar_verhoeff_valid=verhoeff_flags(text),
                    image_png=image_png,
                    width=image.width,
                    height=image.height,
                )
                boxes = _large_image_boxes(page, image.size)
                if boxes and ocr is None:
                    images_unchecked += 1
                elif boxes:
                    _read_embedded_images(native, ocr, boxes, warnings)
                pages.append(native)
            elif ocr is not None:
                pages.append(ocr_page(index, image, ocr, warnings, image_png=image_png))
            else:
                scanned_without_ocr += 1
                pages.append(Page(index=index, image_png=image_png, width=image.width, height=image.height))
            textpage.close()
            page.close()
        if scanned_without_ocr:
            warnings.append(f"{scanned_without_ocr} page(s) look scanned; OCR was not run on them.")
        if images_unchecked:
            warnings.append(
                f"{images_unchecked} page(s) contain large images that were not OCR'd or checked for Aadhaar numbers."
            )
        return pages
    finally:
        pdf.close()
