"""Lender product records, loaded from backend/data/lenders.json.

The file is re-read on every call so edits to lender records show up without
restarting the server. Swap this module for a database query later; the engine
only needs an iterable of LenderProduct.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.config import LENDERS_FILE
from app.recommendation.models import LenderProduct


def load_lender_products(path: Path = LENDERS_FILE) -> list[LenderProduct]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [LenderProduct.model_validate(item) for item in payload["products"]]
