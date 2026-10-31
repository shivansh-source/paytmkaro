from pathlib import Path
from datetime import date

import pytest

from app.documents.process import process_upload
from app.schemas.common import DocumentType
from app.scoring import assess
from app.validation import validate_all

FIXTURES = Path(__file__).parent / "fixtures" / "documents"


@pytest.mark.parametrize(
    ("file_name", "expected"),
    [
        ("bureau_report.pdf", DocumentType.BUREAU_REPORT),
        ("financial_statements.pdf", DocumentType.FINANCIAL_STATEMENTS),
        ("sanction_letter.pdf", DocumentType.SANCTION_LETTER),
        ("settlement_report.csv", DocumentType.SETTLEMENT_REPORT),
    ],
)
def test_new_document_fixtures_become_validatable_envelopes(file_name, expected):
    result = process_upload((FIXTURES / file_name).read_bytes(), file_name, sme_id="sample")

    assert result.status == "ok"
    assert result.extractions == []
    assert len(result.envelopes) == 1
    envelope = result.envelopes[0]
    assert envelope.document_type == expected
    assert envelope.data.document_type == expected.value

    checked, _, _ = validate_all(result.envelopes, as_of=date(2026, 10, 31))
    assert checked[0].checks
    # A valid envelope must be safe to pass through the same profile builder as core documents.
    profile = assess("sample", checked, as_of=date(2026, 10, 31)).profile
    assert any(doc.document_type == expected for doc in profile.documents)


def test_assessment_uses_uploaded_consumer_score_as_self_declared_and_preserves_bureau_detail():
    file_name = "bureau_report.pdf"
    result = process_upload((FIXTURES / file_name).read_bytes(), file_name, sme_id="sample")
    profile = assess("sample", result.envelopes, as_of=date(2026, 10, 31)).profile

    assert profile.bureau is not None
    assert profile.bureau.source == "self_declared"
    assert profile.bureau.value == 705
    assert profile.bureau.max_dpd_24m == 30


def test_commercial_cmr_only_report_never_becomes_a_consumer_score():
    file_name = "bureau_report_commercial.pdf"
    result = process_upload((FIXTURES / file_name).read_bytes(), file_name, sme_id="sample")
    profile = assess("sample", result.envelopes, as_of=date(2026, 10, 31)).profile

    assert result.envelopes[0].data.cmr_rank.value == 4
    assert profile.bureau is None
