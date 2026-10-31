"""process_upload on the committed fixtures: bytes -> envelopes -> scoring, statuses, shared VLM pool, privacy."""

import os
import re
from pathlib import Path

import pytest
from textdocs import ocr_page

from app import config
from app.assessment import score_sme
from app.assessment.models import ScoreCard
from app.documents import process as process_module
from app.documents.extract import extract
from app.documents.fakes import FakeOcr, FakeVlm
from app.documents.models import DocumentType as DT
from app.documents.models import LoadedDocument, LoadStatus, OcrLine, Page, SourceFormat, TextSource
from app.documents.privacy import verhoeff_valid
from app.documents.process import ProcessResult, process_upload
from app.documents.vlm import VlmBudget
from app.samples import AS_OF
from app.schemas.common import CheckStatus, DocumentType, Source
from app.schemas.documents import DocumentEnvelope
from app.scoring import assess

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "documents"


def run(name: str, **kwargs) -> ProcessResult:
    return process_upload((FIXTURES / name).read_bytes(), name, sme_id="sme-1", **kwargs)


@pytest.mark.parametrize("name", ["bank_statement.pdf", "bank_statement.xlsx", "bank_statement.csv"])
def test_bank_statement_fixture_flows_through_scoring(name):
    result = run(name)

    assert result.status == "ok" and result.message is None
    bank = [e for e in result.envelopes if e.document_type == DocumentType.BANK_STATEMENT]
    assert len(bank) == 1 and bank[0].status == "needs_review" and bank[0].data.transactions
    assessment = assess("sme-1", result.envelopes, as_of=AS_OF)
    checks = {c.id: c.status for d in assessment.documents for c in d.checks}
    assert checks["bank.balance_math"] == CheckStatus.PASS
    card = score_sme(assessment.profile, assessment.documents, as_of=AS_OF)
    assert isinstance(card, ScoreCard)


def test_gst_certificate_fixture():
    result = run("gst_reg06.pdf")
    gst = result.envelopes[0]
    assert gst.document_type == DocumentType.GST_REGISTRATION and gst.data.gstin.value
    assessment = assess("sme-1", result.envelopes, as_of=AS_OF)
    assert {c.id: c.status for c in assessment.documents[0].checks}["gst.checksum"] == CheckStatus.PASS


def test_encrypted_aadhaar_needs_its_password_and_never_raises():
    locked = run("e_aadhaar_encrypted.pdf")
    assert locked.status == "password_required" and locked.message and locked.envelopes == []

    opened = run("e_aadhaar_encrypted.pdf", password="KUMA1990")
    aadhaar = opened.envelopes[0]
    assert opened.status == "ok" and aadhaar.document_type == DocumentType.AADHAAR
    assert aadhaar.triage.password_protected and re.fullmatch(r"\d{4}", aadhaar.data.aadhaar_last4.value)
    assert aadhaar.data.verhoeff_valid is not None  # ingest checked the full number before masking it


def test_mixed_bundle_yields_envelopes_per_recognised_segment():
    result = run("mixed_bundle.pdf", ocr=FakeOcr())
    kinds = [e.document_type for e in result.envelopes]
    assert DocumentType.GST_REGISTRATION in kinds
    assert len({e.document_id for e in result.envelopes}) == len(result.envelopes)
    for envelope in result.envelopes:
        assert ProcessResult.model_validate_json(result.model_dump_json()).envelopes  # serialises


@pytest.mark.parametrize(("name", "status"), [("archive.zip", "unsupported_format"), ("empty.bin", "unreadable")])
def test_unusable_files_come_back_with_a_status_not_an_exception(name, status):
    result = run(name)
    assert result.status == status and result.message and result.envelopes == [] and result.extractions == []


def test_oversized_upload_is_reported(monkeypatch):
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 100)
    result = run("bank_statement.pdf")
    assert result.status == "too_large" and result.message


def test_settlement_report_comes_back_as_an_envelope():
    result = run("settlement_report.csv")
    assert result.status == "ok" and len(result.envelopes) == 1
    assert result.envelopes[0].document_type.value == "settlement_report"
    assert result.extractions == []


def test_unrecognised_file_says_so():
    result = process_upload(b"just some meeting notes about lunch", "notes.txt", sme_id="sme-1")
    assert result.status == "nothing_recognised" and result.message and result.envelopes == []


def test_unexpected_failure_is_contained_and_not_logged_with_content(monkeypatch, caplog):
    def boom(*args, **kwargs):
        raise RuntimeError("secret text 2345 6789 0124")

    monkeypatch.setattr(process_module, "classify", boom)
    with caplog.at_level("DEBUG"):
        result = run("gst_reg06.pdf")
    assert result.status == "error" and result.message
    assert "2345" not in caplog.text and "RuntimeError" in caplog.text


# ---------- one shared VLM pool ----------


def _unreadable_pan(index: int = 0) -> LoadedDocument:
    photo = Page(index=index, text="", text_source=TextSource.NONE, image_png=ocr_page([("x", 0.1)]).image_png, width=100, height=50)
    return LoadedDocument(file_name="p.jpg", sha256="c" * 64, source_format=SourceFormat.JPEG, status=LoadStatus.OK, pages=[photo])


def test_two_extractions_sharing_a_budget_stop_at_the_pool_limit():
    budget = VlmBudget(1)
    vlm = FakeVlm([{"pan": "ABCPK1234F"}, {"pan": "ABCPK1234F"}])

    first = extract(_unreadable_pan(), DT.PAN_CARD, vlm=vlm, budget=budget)
    second = extract(_unreadable_pan(), DT.PAN_CARD, vlm=vlm, budget=budget)

    assert len(vlm.calls) == 1 and budget.exhausted and budget.used == 1
    assert "pan" in first.fields and "pan" not in second.fields
    assert any("budget" in w for w in second.warnings)


def test_extract_without_a_budget_gets_its_own_pool(monkeypatch):
    monkeypatch.setattr(config, "VLM_MAX_REQUESTS_PER_DOCUMENT", 1)
    vlm = FakeVlm([{"pan": None}, {"pan": None}])
    for _ in range(2):
        extract(_unreadable_pan(), DT.PAN_CARD, vlm=vlm)
    assert len(vlm.calls) == 2  # one per call: separate pools


def test_process_upload_reports_vlm_use_and_honours_the_shared_budget():
    budget = VlmBudget(0)
    vlm = FakeVlm([])
    result = run("gst_reg06.pdf", vlm=vlm, budget=budget)
    assert vlm.calls == [] and result.vlm_requests_used == 0 and result.status == "ok"


# ---------- privacy ----------


def _aadhaar_number() -> str:
    return next("23456789012" + d for d in "0123456789" if verhoeff_valid("23456789012" + d))


def test_no_full_aadhaar_number_in_any_output():
    number = _aadhaar_number()
    spaced = f"{number[:4]} {number[4:8]} {number[8:]}"
    for rendering in (spaced, number):
        text = f"Government of India\nAadhaar\nRavi Kumar\nDOB: 15/08/1985\nMALE\n{rendering}\nAddress: 12 MG Road, Bengaluru 560038"
        result = process_upload(text.encode(), "aadhaar.txt", sme_id="sme-1")
        dumped = result.model_dump_json()
        assert number not in dumped and spaced not in dumped
        assert not re.search(r"(?<!\d)\d{4}\s?\d{4}\s?\d{4}(?!\d)", re.sub(r"[0-9a-f]{64}", "", dumped))
        aadhaar = next(e for e in result.envelopes if e.document_type == DocumentType.AADHAAR)
        assert aadhaar.data.aadhaar_last4.value == number[-4:]


def test_classifier_and_extractor_spend_one_pool_inside_process_upload():
    """pan_card.jpg has no text without OCR: the classifier uses the only request, so the extractor has none left."""
    labels = {"pages": [{"image": 1, "document_type": "pan_card", "reason": "layout"}]}
    vlm = FakeVlm([labels, {"pan": "ABCPK1234F", "name": "RAVI KUMAR", "dob": "15/08/1985"}])
    budget = VlmBudget(1)
    result = run("pan_card.jpg", vlm=vlm, budget=budget)

    assert len(vlm.calls) == 1 and budget.exhausted and result.vlm_requests_used == 1
    assert result.classification.document_type == DT.PAN_CARD
    assert any(w.startswith("pan_card:") and "budget" in w for w in result.warnings)
    pan = result.envelopes[0]
    assert pan.document_type == DocumentType.PAN_CARD and pan.status == "failed" and pan.data is None  # nothing read, nothing guessed
    assert pan.error


def test_with_a_pool_of_two_the_extractor_gets_the_second_request():
    labels = {"pages": [{"image": 1, "document_type": "pan_card", "reason": "layout"}]}
    vlm = FakeVlm([labels, {"pan": "ABCPK1234F", "name": "RAVI KUMAR", "dob": "15/08/1985"}])
    result = run("pan_card.jpg", vlm=vlm, budget=VlmBudget(2))

    assert len(vlm.calls) == 2 and result.vlm_requests_used == 2
    pan = result.envelopes[0]
    assert pan.data.pan_number.value == "ABCPK1234F" and pan.triage.fell_back_to_vlm and pan.triage.extractor == Source.VLM


@pytest.mark.skipif(os.getenv("RUN_OCR_TESTS") != "1", reason="real PaddleOCR: set RUN_OCR_TESTS=1")
def test_scanned_gst_certificate_with_real_paddle_round_trips():
    from app.documents.ocr import PaddleOcrEngine  # noqa: PLC0415

    result = run("gst_reg06_scanned.pdf", ocr=PaddleOcrEngine())
    gst = next(e for e in result.envelopes if e.document_type == DocumentType.GST_REGISTRATION)
    assert DocumentEnvelope.model_validate(gst.model_dump()) == gst and gst.triage.input_kind == "scanned_pdf"
