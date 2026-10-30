"""Raster image loader: JPEG, PNG, WEBP, TIFF (multi-page), BMP, HEIC/HEIF phone photos."""

from __future__ import annotations

import io
import warnings

from PIL import Image, ImageSequence, UnidentifiedImageError

from app.documents.models import LoadStatus, Page
from app.documents.ports import OcrEngine
from app.documents.ingest.common import IngestError, check_page_count, check_pixels, normalize_image, ocr_page, too_large

_heif_registered = False


def _register_heif() -> None:
    global _heif_registered
    if not _heif_registered:
        from pillow_heif import register_heif_opener

        register_heif_opener()
        _heif_registered = True


def open_image(data: bytes) -> Image.Image:
    _register_heif()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(data))
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise too_large("This image is too large to process. Upload a smaller photo or scan.")
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise IngestError(LoadStatus.UNREADABLE, "This image could not be opened; it may be damaged. Please take the photo again.")
    check_pixels(*image.size)
    return image


def image_frames(data: bytes) -> list[Image.Image]:
    """Decoded, normalised frames (one per TIFF page; one for other formats)."""
    image = open_image(data)
    count = getattr(image, "n_frames", 1)
    check_page_count(count)
    frames = []
    try:
        for frame in ImageSequence.Iterator(image) if count > 1 else [image]:
            check_pixels(*frame.size)
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                frame.load()
            frames.append(normalize_image(frame.copy()))
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise too_large("This image is too large to process. Upload a smaller photo or scan.")
    except (OSError, ValueError, SyntaxError, EOFError):
        if not frames:
            raise IngestError(LoadStatus.UNREADABLE, "This image could not be decoded; it may be damaged or cut off.")
    return frames


def load_image(data: bytes, ocr: OcrEngine | None, warnings_out: list[str]) -> list[Page]:
    frames = image_frames(data)
    if ocr is None:
        warnings_out.append("OCR was not run: text was not read and the image was not checked for Aadhaar numbers.")
    return [ocr_page(index, frame, ocr, warnings_out) for index, frame in enumerate(frames)]
