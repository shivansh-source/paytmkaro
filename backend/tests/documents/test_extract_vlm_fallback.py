"""Hybrid strategy with FakeVlm: VLM only when needed, validated like OCR, cross-checked, budgeted."""

import io

from PIL import Image

from app import config
from app.documents.extract import extract
from app.documents.extract.common import gstin_check_char
from app.documents.fakes import FakeVlm
from app.documents.models import DocumentType, FieldSource, LoadedDocument, LoadStatus, OcrLine, Page, SourceFormat, TextSource
from app.documents.ports import VlmBudgetExceeded, VlmError
from app.documents.privacy import verhoeff_valid

PAN = "ABCPK1234F"
GSTIN = "29ABCPK1234F1Z" + gstin_check_char("29ABCPK1234F1Z")


def png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 20), "white").save(out, format="PNG")
    return out.getvalue()


def doc(*pages: Page) -> LoadedDocument:
    return LoadedDocument(file_name="scan.jpg", sha256="0" * 64, source_format=SourceFormat.JPEG, status=LoadStatus.OK, pages=list(pages))


def photo(index: int = 0, lines: list[tuple[str, float]] = ()) -> Page:
    ocr = [OcrLine(text=t, confidence=c, bbox=(10, 40.0 * i, 300, 40.0 * i + 20)) for i, (t, c) in enumerate(lines)]
    return Page(index=index, text="\n".join(t for t, _ in lines), text_source=TextSource.OCR, ocr_lines=ocr, image_png=png())


CLEAN_PAN = f"Permanent Account Number Card\n{PAN}\nName\nRAVI KUMAR\nFather's Name\nSURESH KUMAR\nDate of Birth\n15/08/1985"


def test_vlm_not_called_when_text_pass_is_complete():
    vlm = FakeVlm([])
    page = Page(index=0, text=CLEAN_PAN, text_source=TextSource.NATIVE, image_png=png())
    result = extract(doc(page), DocumentType.PAN_CARD, vlm=vlm)

    assert result.status == "ok" and vlm.calls == []


def test_vlm_fills_missing_field_and_agreement_raises_confidence():
    page = photo(lines=[("Permanent Account Number", 0.9), (PAN, 0.82), ("Name", 0.9), ("RAVI KUMAR", 0.8)])  # DOB smudged
    vlm = FakeVlm([{"pan": PAN, "name": "Ravi Kumar", "father_name": None, "dob": "15/08/1985"}])
    result = extract(doc(page), DocumentType.PAN_CARD, vlm=vlm)

    assert len(vlm.calls) == 1 and vlm.calls[0][1] == 1  # one request, one image
    f = result.fields
    assert f["dob"].value == "1985-08-15" and f["dob"].source == FieldSource.VLM and f["dob"].validated
    assert f["pan"].source == FieldSource.OCR and f["pan"].confidence > 0.82 and "agree" in f["pan"].note
    # Free-text name becomes validated only because two independent reads agree.
    assert f["name"].value == "RAVI KUMAR" and f["name"].validated
    assert result.status == "ok"


def test_vlm_value_failing_validation_goes_to_missing():
    page = photo(lines=[(PAN, 0.9), ("Name", 0.9), ("RAVI KUMAR", 0.9)])
    vlm = FakeVlm([{"pan": PAN, "name": "RAVI KUMAR", "dob": "31/02/1985"}])
    result = extract(doc(page), DocumentType.PAN_CARD, vlm=vlm)

    assert "dob" in result.missing and "dob" not in result.fields
    assert any(w.startswith("dob: the VLM read") and "failed validation" in w for w in result.warnings)


def test_disagreement_keeps_text_layer_value_and_warns():
    text = CLEAN_PAN.replace("Date of Birth\n15/08/1985", "")
    page = Page(index=0, text=text, text_source=TextSource.NATIVE, image_png=png())
    vlm = FakeVlm([{"pan": "ABCPK1243F", "name": "RAVI KUMAR", "dob": "15/08/1985"}])
    result = extract(doc(page), DocumentType.PAN_CARD, vlm=vlm)

    pan = result.fields["pan"]
    assert pan.value == PAN and pan.source == FieldSource.TEXT_LAYER and pan.confidence == 0.5
    assert any("pan: text_layer read" in w and "please confirm" in w for w in result.warnings)


def test_low_confidence_ocr_loses_to_vlm_on_disagreement():
    page = photo(lines=[("29ABCPK1234F1Z" + "Q", 0.5)])  # malformed, rejected, so GSTIN missing
    vlm = FakeVlm([{"gstin": GSTIN, "legal_name": "RAVI KUMAR", "constitution_of_business": "Proprietorship", "validity_from": "01/08/2025"}])
    result = extract(doc(page), DocumentType.GST_CERTIFICATE, vlm=vlm)

    assert result.fields["gstin"].source == FieldSource.VLM and result.fields["gstin"].validated
    assert result.fields["registration_date"].value == "2025-08-01" and result.fields["registration_date"].source == FieldSource.COMPUTED
    assert result.status == "ok"


def test_vlm_gstin_with_bad_check_character_is_rejected():
    page = photo(lines=[("Form GST REG-06", 0.9)])
    vlm = FakeVlm([{"gstin": GSTIN[:-1] + ("A" if GSTIN[-1] != "A" else "B"), "legal_name": "RAVI KUMAR"}])
    result = extract(doc(page), DocumentType.GST_CERTIFICATE, vlm=vlm)

    assert "gstin" in result.missing and "pan_from_gstin" not in result.fields


def test_per_document_budget_caps_requests(monkeypatch):
    monkeypatch.setattr(config, "VLM_MAX_REQUESTS_PER_DOCUMENT", 1)
    pages = [photo(i, [("blurred", 0.2)]) for i in range(5)]
    vlm = FakeVlm([{"pan": None}] * 5)
    result = extract(doc(*pages), DocumentType.PAN_CARD, vlm=vlm)

    assert len(vlm.calls) == 1 and vlm.calls[0][1] == 2  # 2 images per request by default
    assert any("budget" in w for w in result.warnings)
    assert set(result.missing) == {"pan", "name", "dob"} and result.status == "failed"


def test_rate_limit_stops_vlm_for_the_document():
    pages = [photo(i, [("blurred", 0.2)]) for i in range(4)]
    vlm = FakeVlm([VlmBudgetExceeded("429 after retries"), {"pan": PAN}])
    result = extract(doc(*pages), DocumentType.PAN_CARD, vlm=vlm)

    assert len(vlm.calls) == 1
    assert any("rate limit" in w for w in result.warnings) and "pan" in result.missing


def test_vlm_error_moves_on_to_next_chunk():
    pages = [photo(i, [("blurred", 0.2)]) for i in range(4)]
    vlm = FakeVlm([VlmError("not JSON"), {"pan": PAN, "name": "RAVI KUMAR", "dob": "15/08/1985"}])
    result = extract(doc(*pages), DocumentType.PAN_CARD, vlm=vlm)

    assert len(vlm.calls) == 2 and result.fields["pan"].page_index is None and result.status == "ok"


def test_text_only_page_sends_text_not_images():
    page = Page(index=0, text="Some spreadsheet export with no labels", text_source=TextSource.NATIVE)
    vlm = FakeVlm([{"pan": PAN, "name": "RAVI KUMAR", "dob": "1985-08-15"}])
    extract(doc(page), DocumentType.PAN_CARD, vlm=vlm)

    prompt, n_images = vlm.calls[0]
    assert n_images == 0 and "Some spreadsheet export" in prompt and "Never guess" in prompt


def test_aadhaar_number_from_vlm_is_masked_everywhere():
    full = next("23456789012" + d for d in "0123456789" if verhoeff_valid("23456789012" + d))
    grouped = f"{full[:4]} {full[4:8]} {full[8:]}"
    page = photo(lines=[("Government of India", 0.9)])
    vlm = FakeVlm([{"name": "Ravi Kumar", "dob": "15/08/1985", "gender": "MALE", "aadhaar_last4": full, "address": f"Ref {grouped}, 12 MG Road, Bengaluru 560038"}])
    result = extract(doc(page), DocumentType.AADHAAR, vlm=vlm)

    dumped = result.model_dump_json()
    assert result.fields["aadhaar_last4"].value == full[-4:]
    assert full not in dumped and full[:8] not in dumped and grouped not in dumped
    assert "XXXX XXXX" in result.fields["address"].value
    assert "aadhaar_last4" in vlm.calls[0][0] and "never return more than its last 4 digits" in vlm.calls[0][0]


def test_bank_statement_rows_from_vlm_are_balance_checked():
    page = photo(lines=[("Account Name RAVI KUMAR", 0.9), ("Account Number XXXX5521", 0.9)])
    vlm = FakeVlm([{
        "account_holder_name": "RAVI KUMAR", "account_number_last4": "5521",
        "transactions": [
            {"date": "01/04/2026", "narration": "OPENING", "debit": None, "credit": None, "balance": "10,000.00"},
            {"date": "02/04/2026", "narration": "UPI/CR/SALES", "debit": None, "credit": "5,000.00", "balance": "15,000.00"},
            {"date": "03/04/2026", "narration": "NACH/EMI", "debit": "2,000.00", "credit": None, "balance": "14,000.00"},
            {"date": "04/04/2026", "narration": "UPI/CR/SALES", "debit": None, "credit": "1,000.00", "balance": "15,000.00"},
        ],
    }])
    result = extract(doc(page), DocumentType.BANK_STATEMENT, vlm=vlm)

    assert "transactions" in vlm.calls[0][0]
    rows = result.tables["transactions"]
    assert [r["source"] for r in rows] == ["vlm"] * 4
    assert result.fields["balance_breaks"].value == 1
    assert result.fields["total_credits"].value == 6000.0  # computed by code, not read


def test_header_page_with_rows_is_still_sent_for_missing_fields():
    page0 = photo(0, [("Account Number XXXX5521", 0.9), ("01/04/2026  UPI/CR/SALES  1,000.00  1,000.00", 0.9)])
    page1 = photo(1, [("smudge", 0.3)])
    vlm = FakeVlm([_rows_reply(10, 1000), {"account_holder_name": "RAVI KUMAR", "account_number_last4": "5521"}])
    result = extract(doc(page0, page1), DocumentType.BANK_STATEMENT, vlm=vlm)

    assert len(vlm.calls) == 2 and "transactions" in vlm.calls[0][0] and "transactions" not in vlm.calls[1][0]
    assert result.fields["account_holder_name"].value == "RAVI KUMAR" and result.fields["account_holder_name"].page_index == 0
    assert [r["page_index"] for r in result.tables["transactions"]] == [0, 1, 1]


def _rows_reply(day: int, opening: float) -> dict:
    return {"transactions": [
        {"date": f"{day:02d}/04/2026", "narration": "UPI/CR/SALES", "debit": None, "credit": "1,000.00", "balance": f"{opening + 1000:,.2f}"},
        {"date": f"{day + 1:02d}/04/2026", "narration": "UPI/CR/SALES", "debit": None, "credit": "1,000.00", "balance": f"{opening + 2000:,.2f}"},
    ]}


def test_every_photo_page_of_a_statement_is_read_for_rows():
    pages = [photo(i, [("Account Name RAVI KUMAR", 0.9), ("Account Number XXXX5521", 0.9)] if i == 0 else [("smudge", 0.3)]) for i in range(3)]
    vlm = FakeVlm([_rows_reply(1, 0), _rows_reply(10, 2000), _rows_reply(20, 4000)])
    result = extract(doc(*pages), DocumentType.BANK_STATEMENT, vlm=vlm)

    assert len(vlm.calls) == 3 and all(n == 1 for _, n in vlm.calls)
    rows = result.tables["transactions"]
    assert len(rows) == 6 and [r["page_index"] for r in rows] == [0, 0, 1, 1, 2, 2]
    assert result.fields["balance_breaks"].value == 0 and result.fields["total_credits"].value == 6000.0


def test_budget_warning_names_pages_not_read(monkeypatch):
    monkeypatch.setattr(config, "VLM_MAX_REQUESTS_PER_DOCUMENT", 2)
    pages = [photo(i, [("Account Name RAVI KUMAR", 0.9)] if i == 0 else [("smudge", 0.3)]) for i in range(3)]
    vlm = FakeVlm([_rows_reply(1, 0), _rows_reply(10, 2000), _rows_reply(20, 4000)])
    result = extract(doc(*pages), DocumentType.BANK_STATEMENT, vlm=vlm)

    assert len(vlm.calls) == 2 and len(result.tables["transactions"]) == 4
    assert any("budget" in w and "page(s) 3 not read" in w for w in result.warnings)
