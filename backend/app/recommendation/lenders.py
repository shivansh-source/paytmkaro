"""Lender product records, loaded from backend/data/lenders.json.

The file is re-read on every call so edits to lender records show up without
restarting the server. Swap this module for a database query later; the engine
only needs an iterable of LenderProduct.
"""

from __future__ import annotations

from pathlib import Path

from app.config import LENDERS_FILE
from app.schemas.lender import LenderCatalog, LenderProduct


def load_lender_products(path: Path = LENDERS_FILE) -> list[LenderProduct]:
    return LenderCatalog.model_validate_json(path.read_text(encoding="utf-8")).products
