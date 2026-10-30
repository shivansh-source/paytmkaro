"""Document classifier: LoadedDocument -> per-page DocumentType + segments.

Deterministic rules first (signals.py tables, scored in rules.py); a VLM is only a
fallback for pages the rules could not label (vlm.py). Every page result lists the
human-readable signals behind it.

    from app.documents.classify import classify
    result = classify(loaded_document, vlm=optional_vlm_client)
"""

from __future__ import annotations

from app.documents.classify.pipeline import classify

__all__ = ["classify"]
