"""Field extraction with provenance: deterministic text/OCR readers first, VLM fallback, code validates.

    result = extract(document, DocumentType.PAN_CARD, vlm=get_default_vlm())
    features = profile_features([result, ...], as_of=date.today())
    SMEProfile(sme_id=..., requested_amount=..., **features.profile_fields())
"""

from __future__ import annotations

from app.documents.extract.features import DocumentCheck, FeatureValue, ProfileFeatures, cross_checks, name_match, profile_features
from app.documents.extract.pipeline import extract
from app.documents.extract.schemas import json_schema, validate_field

__all__ = [
    "DocumentCheck",
    "FeatureValue",
    "ProfileFeatures",
    "cross_checks",
    "extract",
    "json_schema",
    "name_match",
    "profile_features",
    "validate_field",
]
