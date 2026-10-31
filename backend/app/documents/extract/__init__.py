"""Field extraction with provenance: deterministic text/OCR readers first, VLM fallback, code validates.

    result = extract(document, DocumentType.PAN_CARD, vlm=get_default_vlm())
    features = profile_features([result, ...], as_of=date.today())
    MatchInput(sme_id=..., requested_amount=..., **features.profile_fields())
"""

from __future__ import annotations

from app.documents.extract.features import DocumentCheck, FeatureValue, ProfileFeatures, cross_checks, name_match, profile_features
from app.documents.extract.envelope import BridgeOutput, build_envelope, has_envelope, to_envelope
from app.documents.extract.pipeline import Extraction, extract, extract_detailed
from app.documents.extract.schemas import json_schema, validate_field

__all__ = [
    "BridgeOutput",
    "Extraction",
    "build_envelope",
    "extract_detailed",
    "has_envelope",
    "to_envelope",
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
