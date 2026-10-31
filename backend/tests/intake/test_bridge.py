"""Pipeline output -> DocumentEnvelope: field mapping, failed reads kept for review, boxes, privacy."""
import re
from pathlib import Path

import pytest

from app.documents.fakes import FakeOcr
from app.documents.models import OcrLine
from app.intake import process_upload
from app.schemas import CheckStatus, DocumentType, Source
from app.validation import validate_all

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "documents"


def upload(name: str, **kw):
    return process_upload((FIXTURES / name).read_bytes(), name, sme_id="T-1", **kw)


def gst_text(gstin: str = "27ABCDE1234F1Z0") -> bytes:
    return (
        "Government of India\nForm GST REG-06\nRegistration Certificate\n"
        f"Registration Number: {gstin}\n1. Legal Name: R. KUMAR\n2. Trade Name, if any: KUMAR TRADERS\n"
        "3. Constitution of Business: Proprietorship\n"
        "4. Address of Principal Place of Business: 12, Market Road, Pune, Maharashtra, 411001\n"
        "5. Date of Liability: 01/04/2022\n7. Type of Registration: Regular\nSAMPLE"
    ).encode()


def test_gst_certificate_maps_onto_the_envelope():
    result = upload("gst_reg06.pdf")
    [env] = result.documents
    assert env.document_type == DocumentType.GST_REGISTRATION
    assert env.triage.input_kind == "digital_pdf" and env.triage.extractor == Source.PARSER
    d = env.data
    assert d.gstin.value == "27ABCDE1234F1Z0" and d.gstin.source == Source.PARSER
    assert d.constitution.value == "proprietorship"
    assert d.registration_date.value.isoformat() == "2022-04-01"
    assert d.principal_address.value.pincode == "411001"
    [checked], _, _ = validate_all([env], env.uploaded_at.date())
    assert checked.status == "verified"


def test_bank_statement_rows_and_computed_closing_balance():
    [env] = upload("bank_statement.pdf").documents
    d = env.data
    assert len(d.transactions) == 7
    assert d.transactions[0].provenance.source == Source.PARSER
    # The header has no closing balance: it comes from the last row's running balance, marked as computed.
    assert d.closing_balance.source == Source.SYSTEM
    assert d.closing_balance.value == d.transactions[-1].balance
    assert d.account_number_last4.value == "4321"


def test_a_read_that_fails_validation_is_kept_for_review_not_dropped():
    [env] = process_upload(gst_text("27ABCDE1234F1Z9"), "gst.txt", sme_id="T-1").documents
    gstin = env.data.gstin
    assert gstin.value == "27ABCDE1234F1Z9" and gstin.raw_text == "27ABCDE1234F1Z9"
    assert gstin.confidence < 0.5 and gstin.needs_review
    [checked], _, _ = validate_all([env], env.uploaded_at.date())
    assert {c.id: c.status for c in checked.checks}["gst.checksum"] == CheckStatus.FAIL


def test_bundle_is_split_and_unreadable_pages_are_explained():
    result = upload("mixed_bundle.pdf")
    assert [d.document_type for d in result.documents] == [DocumentType.GST_REGISTRATION]
    [skipped] = result.skipped
    assert skipped.pages == [2, 3] and "OCR" in skipped.reason


def test_document_types_without_an_envelope_slot_are_skipped_with_a_reason():
    result = upload("bureau_report.pdf")
    assert result.documents == []
    assert "isn't used in your score yet" in result.skipped[0].reason


def test_password_protected_e_aadhaar_keeps_only_the_last_four_digits():
    assert upload("e_aadhaar_encrypted.pdf").status == "password_required"
    [env] = upload("e_aadhaar_encrypted.pdf", password="KUMA1990").documents
    assert env.document_type == DocumentType.AADHAAR and env.triage.password_protected
    assert len(env.data.aadhaar_last4.value) == 4
    assert env.data.verhoeff_valid is True  # checked on the full number before it was masked
    assert not re.search(r"\d{5,}", env.data.model_dump_json())  # no long digit run anywhere in the extracted data


def test_photo_with_ocr_gets_highlight_boxes():
    lines = [
        ("INCOME TAX DEPARTMENT", (40, 20, 600, 60)),
        ("Permanent Account Number Card", (40, 80, 600, 120)),
        ("ABCDE1234F", (40, 140, 300, 180)),
        ("Name", (40, 200, 140, 230)),
        ("RAVI KUMAR", (40, 235, 300, 270)),
        ("Date of Birth", (40, 280, 240, 310)),
        ("15/08/1990", (40, 315, 240, 350)),
    ]
    ocr = FakeOcr([OcrLine(text=t, confidence=0.93, bbox=b) for t, b in lines])
    [env] = upload("pan_card.jpg", ocr=ocr, expected_type=DocumentType.PAN_CARD).documents
    pan = env.data.pan_number
    assert pan.value == "ABCDE1234F" and pan.source == Source.OCR
    assert env.triage.input_kind == "photo" and env.triage.ocr_mean_confidence == pytest.approx(0.93)
    assert pan.bbox is not None and pan.bbox.page == 1 and 0 <= pan.bbox.x0 < pan.bbox.x1 <= 1


def test_photo_without_ocr_or_vlm_says_so():
    result = upload("pan_card.jpg", expected_type=DocumentType.PAN_CARD)
    assert result.documents == [] and "OCR" in result.skipped[0].reason


def test_wrong_slot_warns_but_uses_what_the_document_is():
    result = upload("gst_reg06.pdf", expected_type=DocumentType.BANK_STATEMENT)
    assert result.documents[0].document_type == DocumentType.GST_REGISTRATION
    assert any("looks like" in w for w in result.warnings)


def test_document_ids_are_stable_for_the_same_file():
    a = upload("gst_reg06.pdf").documents[0].document_id
    assert a == upload("gst_reg06.pdf").documents[0].document_id


def test_no_ocr_means_no_vlm_so_unredacted_images_never_leave(monkeypatch):
    from app import intake

    monkeypatch.setattr(intake, "default_ocr", lambda: None)
    monkeypatch.setattr(intake, "get_default_vlm", lambda: object())
    assert intake.default_engines() == (None, None)
    monkeypatch.setattr("app.config.VLM_WITHOUT_OCR", True)
    assert intake.default_engines()[1] is not None
