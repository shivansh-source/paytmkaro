"""What process_upload adds for the upload page: kept failed reads, slot hints, reasons, the VLM/OCR rule."""
from pathlib import Path

from app.documents import process
from app.documents.process import process_upload
from app.schemas import CheckStatus, DocumentType
from app.validation import validate_all

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "documents"


def upload(name: str, **kw):
    return process_upload((FIXTURES / name).read_bytes(), name, sme_id="T-1", **kw)


def gst_text(gstin: str) -> bytes:
    return (
        "Government of India\nForm GST REG-06\nRegistration Certificate\n"
        f"Registration Number: {gstin}\n1. Legal Name: R. KUMAR\n2. Trade Name, if any: KUMAR TRADERS\n"
        "3. Constitution of Business: Proprietorship\n"
        "4. Address of Principal Place of Business: 12, Market Road, Pune, Maharashtra, 411001\n"
        "5. Date of Liability: 01/04/2022\n7. Type of Registration: Regular\nSAMPLE"
    ).encode()


def test_a_read_that_fails_validation_is_kept_for_review_not_dropped():
    [env] = process_upload(gst_text("27ABCDE1234F1Z9"), "gst.txt", sme_id="T-1").envelopes
    gstin = env.data.gstin
    assert gstin.value == "27ABCDE1234F1Z9" and gstin.raw_text == "27ABCDE1234F1Z9"
    assert gstin.confidence < 0.5 and gstin.needs_review
    [checked], _, _ = validate_all([env], env.uploaded_at.date())
    assert {c.id: c.status for c in checked.checks}["gst.checksum"] == CheckStatus.FAIL


def test_photo_without_ocr_or_vlm_says_so_in_the_slot_it_was_uploaded_to():
    result = upload("pan_card.jpg", expected_type=DocumentType.PAN_CARD)
    assert all(e.status == "failed" for e in result.envelopes)
    assert "OCR" in result.skipped[0].reason and result.skipped[0].pages == [1]


def test_bundle_parts_that_cannot_be_read_are_explained():
    result = upload("mixed_bundle.pdf")
    assert [e.document_type for e in result.envelopes] == [DocumentType.GST_REGISTRATION]
    assert [s.pages for s in result.skipped] == [[2, 3]] and "OCR" in result.skipped[0].reason


def test_financial_statements_are_returned_as_typed_envelopes():
    result = upload("financial_statements.pdf")
    assert [env.document_type for env in result.envelopes] == [DocumentType.FINANCIAL_STATEMENTS]
    assert result.extractions == []
    assert result.skipped == []


def test_bureau_report_score_is_offered_as_self_declared():
    result = upload("bureau_report.pdf")
    assert result.bureau is not None and result.bureau.source == "self_declared"
    assert [env.document_type for env in result.envelopes] == [DocumentType.BUREAU_REPORT]
    assert any("unverified" in warning for warning in result.warnings)
    assert result.skipped == []


def test_wrong_slot_warns_but_uses_what_the_document_is():
    result = upload("gst_reg06.pdf", expected_type=DocumentType.BANK_STATEMENT)
    assert result.envelopes[0].document_type == DocumentType.GST_REGISTRATION
    assert any("looks like" in w for w in result.warnings)


def test_no_ocr_means_no_vlm_so_unredacted_images_never_leave(monkeypatch):
    monkeypatch.setattr("app.config.OCR_ENABLED", True)
    monkeypatch.setattr(process, "default_ocr", lambda: None)
    monkeypatch.setattr(process, "get_default_vlm", lambda: object())
    assert process.default_engines() == (None, None)
    monkeypatch.setattr("app.config.VLM_WITHOUT_OCR", True)
    assert process.default_engines()[1] is not None
