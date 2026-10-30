from datetime import date

import pytest
from pydantic import ValidationError

from app.recommendation import load_lender_products, match_input, recommend
from app.schemas import Aadhaar, DocumentEnvelope, Extracted, SmeProfile, Source
from app.schemas.examples import (
    example_bank_statement_envelope,
    example_loan_request,
    example_pan_envelope,
    example_sme_profile,
)
from scripts.export_schemas import render


def test_exported_json_schemas_are_up_to_date():
    stale = [path.name for path, text in render().items() if not path.exists() or path.read_text(encoding="utf-8") != text]
    assert not stale, f"Run `python -m scripts.export_schemas` from backend/. Stale: {stale}"


@pytest.mark.parametrize("build", [example_pan_envelope, example_bank_statement_envelope, example_sme_profile])
def test_examples_round_trip_through_json(build):
    model = build()
    again = type(model).model_validate_json(model.model_dump_json())
    assert again == model


def test_envelope_discriminates_document_type():
    envelope = DocumentEnvelope.model_validate_json(example_pan_envelope().model_dump_json())
    assert envelope.data is not None and envelope.data.document_type == "pan_card"


def test_envelope_rejects_mismatched_data():
    raw = example_pan_envelope().model_dump(mode="json")
    raw["document_type"] = "aadhaar"
    with pytest.raises(ValidationError, match="envelope says"):
        DocumentEnvelope.model_validate(raw)


def aadhaar_with(**overrides):
    fields = {
        "aadhaar_last4": {"value": "4821", "confidence": 0.98, "source": "vlm"},
        "name": {"value": "RAVI KUMAR", "confidence": 0.95, "source": "vlm"},
        "dob": {"value": "1986-04-12", "confidence": 0.93, "source": "vlm"},
        "address": {"value": {"text": "SAMPLE, Bengaluru 560004"}, "confidence": 0.9, "source": "vlm"},
        **overrides,
    }
    return Aadhaar.model_validate(fields)


def test_full_aadhaar_number_cannot_be_stored():
    with pytest.raises(ValidationError):
        aadhaar_with(aadhaar_last4={"value": "123412344821", "confidence": 0.98, "source": "vlm"})
    with pytest.raises(ValidationError):
        aadhaar_with(aadhaar_number="123412344821")


def test_low_confidence_field_needs_review_until_confirmed():
    field = Extracted[date](value=date(1986, 4, 12), confidence=0.6, source=Source.OCR)
    assert field.needs_review
    assert not field.model_copy(update={"user_confirmed": True}).needs_review
    assert Extracted[str](value=None, confidence=0.99, source=Source.VLM).needs_review


def test_profile_feeds_the_recommendation_engine():
    results = recommend(match_input(example_sme_profile(), example_loan_request()), load_lender_products())
    assert [r.status for r in results] == ["matched"] * len(results)


def test_profile_rejects_unknown_fields():
    raw = example_sme_profile().model_dump(mode="json")
    raw["identity"]["aadhaar_number"] = "123412344821"
    with pytest.raises(ValidationError):
        SmeProfile.model_validate(raw)
