"""VLM fallback: only for pages the rules can't label, batched, budgeted, strictly validated."""

from __future__ import annotations

import pytest

from app import config
from app.documents.classify import classify
from app.documents.classify.vlm import IMAGES_PER_REQUEST, VLM_ONLY_CONFIDENCE, parse_reply
from app.documents.fakes import FakeVlm
from app.documents.models import DocumentType as T
from app.documents.models import LoadedDocument, LoadStatus, Page, SourceFormat, TextSource
from app.documents.ports import VlmBudgetExceeded, VlmError

PAN_TEXT = """INCOME TAX DEPARTMENT GOVT. OF INDIA
Permanent Account Number Card
ABCPK1234L
Father's Name SURESH KUMAR"""
BANK_TEXT = """Statement of Account   IFSC: DEMO0001234
Date Narration Chq/Ref No Withdrawal Deposit Balance
01/04/2024 UPI/RAJESH/PAYMENT 410112345678 12,500.00 1,37,900.00
02/04/2024 NEFT-ACME SUPPLIES N09234 45,000.00 92,900.00
03/04/2024 IMPS/P2A/SHARMA 409812345111 8,200.00 1,01,100.00"""
PHOTO_NOISE = "SAMPLE ~~ ||| ."  # a blurry phone photo: OCR got almost nothing
WEAK_BANK = "Opening Balance 1,25,400.00"  # one bank signal, below the threshold


def doc(*texts: str, images: bool = True) -> LoadedDocument:
    return LoadedDocument(
        file_name="photos.pdf",
        sha256="0" * 64,
        source_format=SourceFormat.PDF,
        status=LoadStatus.OK,
        pages=[
            Page(index=i, text=t, text_source=TextSource.OCR, image_png=f"png-{i}".encode() if images else None)
            for i, t in enumerate(texts)
        ],
    )


def labels(*types: str) -> dict:
    return {"pages": [{"image": i, "document_type": t, "reason": "layout"} for i, t in enumerate(types, start=1)]}


@pytest.fixture
def budget(monkeypatch):
    def set_budget(n: int) -> None:
        monkeypatch.setattr(config, "VLM_MAX_REQUESTS_PER_DOCUMENT", n)

    set_budget(3)
    return set_budget


def test_confident_pages_never_call_the_vlm(budget):
    vlm = FakeVlm()  # nothing queued: any call would raise
    result = classify(doc(PAN_TEXT, BANK_TEXT), vlm=vlm)
    assert vlm.calls == []
    assert result.method == "rules"


def test_no_vlm_given_leaves_unknown_pages_unknown():
    result = classify(doc(PHOTO_NOISE))
    assert result.pages[0].document_type == T.UNKNOWN
    assert result.method == "rules"


def test_low_confidence_pages_are_batched(budget):
    vlm = FakeVlm([labels("aadhaar", "aadhaar", "pan_card"), labels("gstr_3b")])
    result = classify(doc(PHOTO_NOISE, PHOTO_NOISE, PHOTO_NOISE, PAN_TEXT, PHOTO_NOISE), vlm=vlm)
    assert [n for _, n in vlm.calls] == [IMAGES_PER_REQUEST, 1]
    assert [p.document_type for p in result.pages] == [T.AADHAAR, T.AADHAAR, T.PAN_CARD, T.PAN_CARD, T.GSTR_3B]
    prompt = vlm.calls[0][0]
    assert all(t.value in prompt for t in T)
    assert "SAMPLE" not in prompt  # page text never goes to the model
    # VLM-only labels are capped; the rules page keeps its own (higher) confidence.
    assert result.pages[0].confidence == VLM_ONLY_CONFIDENCE
    assert result.pages[3].confidence > VLM_ONLY_CONFIDENCE
    assert result.method == "rules+vlm"


def test_request_budget_is_respected(budget):
    budget(2)
    vlm = FakeVlm([labels("aadhaar", "aadhaar", "aadhaar")] * 5)
    result = classify(doc(*[PHOTO_NOISE] * 7), vlm=vlm)
    assert len(vlm.calls) == 2
    last = result.pages[6]
    assert last.document_type == T.UNKNOWN
    assert any("request limit" in s for s in last.signals)


def test_bad_labels_are_rejected(budget):
    reply = {
        "pages": [
            {"image": 1, "document_type": "passport", "reason": "looks like a passport"},
            {"image": 2, "document_type": "bank_statement"},
            {"image": 2, "document_type": "itr"},  # contradictory duplicate
            {"image": 9, "document_type": "itr"},  # out of range
        ]
    }
    vlm = FakeVlm([reply])
    result = classify(doc(PHOTO_NOISE, PHOTO_NOISE, PHOTO_NOISE), vlm=vlm)
    assert [p.document_type for p in result.pages] == [T.UNKNOWN] * 3
    assert result.method == "rules"
    assert all(any("no valid label" in s for s in p.signals) for p in result.pages)


@pytest.mark.parametrize(
    "reply",
    [
        "not a dict",
        {"pages": "nope"},
        {"pages": [None, 3, {"image": True, "document_type": "pan_card"}]},
        {"pages": [{"image": "1", "document_type": "pan_card"}]},
        {"pages": [{"image": 1, "document_type": ["pan_card"]}]},
    ],
)
def test_malformed_replies_parse_to_nothing(reply):
    assert parse_reply(reply, 2) == {}


def test_single_image_top_level_reply_and_reason_is_scrubbed():
    parsed = parse_reply({"document_type": " PAN_CARD ", "reason": "number ABCPK1234L 98765 visible"}, 1)
    label, reason = parsed[1]
    assert label == T.PAN_CARD
    assert "1234" not in reason and "98765" not in reason


def test_vlm_error_keeps_rules_result_and_continues(budget):
    vlm = FakeVlm([VlmError("HTTP 500"), labels("bank_statement")])
    result = classify(doc(*[PHOTO_NOISE] * 4), vlm=vlm)
    assert len(vlm.calls) == 2
    assert [p.document_type for p in result.pages] == [T.UNKNOWN] * 3 + [T.BANK_STATEMENT]
    assert any("request failed" in s for s in result.pages[0].signals)
    assert result.method == "vlm"


def test_budget_exceeded_stops_all_further_requests(budget):
    vlm = FakeVlm([VlmBudgetExceeded("429"), labels("aadhaar")])
    result = classify(doc(*[PHOTO_NOISE] * 6), vlm=vlm)
    assert len(vlm.calls) == 1
    assert all(p.document_type == T.UNKNOWN for p in result.pages)
    assert result.method == "rules"


def test_vlm_label_corroborated_by_rules_gets_higher_confidence(budget):
    vlm = FakeVlm([labels("bank_statement", "bank_statement")])
    result = classify(doc(WEAK_BANK, PHOTO_NOISE), vlm=vlm)
    corroborated, alone = result.pages
    assert corroborated.document_type == alone.document_type == T.BANK_STATEMENT
    assert 0.7 <= corroborated.confidence <= 0.85
    assert "text: 'Opening Balance'" in corroborated.signals
    assert alone.confidence == VLM_ONLY_CONFIDENCE <= 0.7


def test_text_only_and_context_filled_pages_are_not_sent(budget):
    vlm = FakeVlm()
    classify(doc(PHOTO_NOISE, images=False), vlm=vlm)  # spreadsheet-like: no image
    classify(doc(BANK_TEXT, "", BANK_TEXT), vlm=vlm)  # blank page between statement pages
    assert vlm.calls == []


def test_non_ok_document_never_calls_vlm():
    vlm = FakeVlm()
    loaded = LoadedDocument(
        file_name="x.doc", sha256="0" * 64, source_format=SourceFormat.DOC, status=LoadStatus.UNSUPPORTED_FORMAT
    )
    result = classify(loaded, vlm=vlm)
    assert vlm.calls == [] and result.method == "none"
