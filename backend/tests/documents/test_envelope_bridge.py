"""ExtractionResult -> DocumentEnvelope: every conversion rule of the bridge."""

from datetime import date

import pytest
from textdocs import loaded, ocr_page, page, png, text_doc

from app.documents.extract.common import gstin_check_char
from app.documents.extract.envelope import build_envelope, has_envelope, to_envelope
from app.documents.extract.pipeline import extract_detailed
from app.documents.fakes import FakeVlm
from app.documents.models import DocumentType as DT
from app.documents.models import ExtractionResult, LoadedDocument, LoadStatus, Page, SourceFormat, TextSource
from app.schemas.common import DocumentType, Source
from app.schemas.documents import DocumentEnvelope

PAN = "ABCPK1234F"
GSTIN = "29ABCPK1234F1Z" + gstin_check_char("29ABCPK1234F1Z")
PAN_TEXT = f"Permanent Account Number Card\n{PAN}\nName\nRAVI KUMAR\nFather's Name\nSURESH KUMAR\nDate of Birth\n15/08/1985"


def bridge(document, kind, **kwargs):
    out = build_envelope(extract_detailed(document, kind), document, sme_id="sme-1", document_id="doc-1", **kwargs)
    assert out is not None
    assert DocumentEnvelope.model_validate(out.envelope.model_dump()) == out.envelope  # round trip
    return out


def test_pan_values_sources_and_status():
    out = bridge(text_doc(PAN_TEXT), DT.PAN_CARD, size_bytes=4096)
    e, d = out.envelope, out.envelope.data

    assert e.document_type == DocumentType.PAN_CARD and e.status == "needs_review" and e.error is None
    assert d.pan_number.value == PAN and d.pan_number.source == Source.PARSER and d.pan_number.raw_text == PAN
    assert d.dob.value == date(1985, 8, 15) and d.father_name.value == "SURESH KUMAR"
    assert e.file.mime_type == "application/pdf" and e.file.size_bytes == 4096 and e.file.sha256 == "a" * 64
    assert e.triage.input_kind == "digital_pdf" and e.triage.extractor == Source.PARSER and not e.triage.fell_back_to_vlm


def test_repaired_ocr_value_keeps_as_read_text_and_low_confidence_and_box():
    document = loaded(
        ocr_page([("Permanent Account Number", 0.9), ("ABCPKI234F", 0.8), ("Name", 0.9), ("RAVI KUMAR", 0.9), ("Date of Birth", 0.9), ("15/08/1985", 0.9)]),
        name="pan.pdf",
    )
    out = bridge(document, DT.PAN_CARD)
    pan = out.envelope.data.pan_number

    assert pan.value == PAN and pan.raw_text == "ABCPKI234F" and pan.confidence <= 0.6 and pan.needs_review
    assert pan.source == Source.OCR
    # Pixel box (100, 200, 220, 240) on a 1000 x 1400 page -> fractions, page numbers are 1-based.
    assert (pan.bbox.page, pan.bbox.x0, pan.bbox.x1) == (1, 0.1, 0.22)
    assert pan.bbox.y0 == pytest.approx(200 / 1400) and pan.bbox.y1 == pytest.approx(240 / 1400)
    assert out.envelope.triage.input_kind == "scanned_pdf" and out.envelope.triage.extractor == Source.OCR
    assert out.envelope.triage.ocr_mean_confidence == pytest.approx(0.883, abs=0.001)


def test_no_box_when_page_has_no_dimensions_or_ocr_lines():
    out = bridge(text_doc(PAN_TEXT), DT.PAN_CARD)
    assert out.envelope.data.pan_number.bbox is None  # text layer: nothing to point at, nothing invented


def test_missing_fields_become_empty_extracted_not_guesses():
    out = bridge(text_doc("Permanent Account Number Card\nRAVI KUMAR"), DT.PAN_CARD)
    d = out.envelope.data

    assert d.pan_number.value is None and d.pan_number.confidence == 0 and d.pan_number.needs_review
    assert d.dob.value is None and d.father_name is None


def test_failed_extraction_is_a_failed_envelope_with_error():
    bad = LoadedDocument(file_name="x.pdf", sha256="b" * 64, source_format=SourceFormat.PDF, status=LoadStatus.UNREADABLE, message="Damaged file")
    out = build_envelope(extract_detailed(bad, DT.PAN_CARD), bad, sme_id="s", document_id="d")
    assert out.envelope.status == "failed" and out.envelope.error == "Damaged file" and out.envelope.data is None
    assert DocumentEnvelope.model_validate(out.envelope.model_dump())


@pytest.mark.parametrize("kind", [DT.BUREAU_REPORT, DT.FINANCIAL_STATEMENTS, DT.SANCTION_LETTER, DT.SETTLEMENT_REPORT, DT.UNKNOWN])
def test_types_without_an_envelope_slot_return_none(kind):
    assert not has_envelope(kind)
    result = ExtractionResult(document_type=kind, status="ok")
    assert to_envelope(result, text_doc("x"), sme_id="s", document_id="d") is None


def test_aadhaar_last4_verhoeff_flag_and_address():
    text = "Government of India\nRavi Kumar\nDOB: 15/08/1985\nMALE\nXXXX XXXX 4821\nAddress: 12 MG Road, Indiranagar, Bengaluru, Karnataka 560038"

    def doc(flags):
        return loaded(Page(index=0, text=text, text_source=TextSource.NATIVE, aadhaar_verhoeff_valid=flags))

    for flags, expected in (([True], True), ([True, False], False), ([], None)):
        d = bridge(doc(flags), DT.AADHAAR).envelope.data
        assert d.verhoeff_valid is expected
    d = bridge(doc([True]), DT.AADHAAR).envelope.data
    assert d.aadhaar_last4.value == "4821" and d.gender.value == "male"
    assert d.address.value.pincode == "560038" and "Indiranagar" in d.address.value.text


def test_aadhaar_with_only_year_of_birth_fills_the_year_and_leaves_dob_out():
    text = "Government of India\nRavi Kumar\nYear of Birth: 1985\nMALE\nXXXX XXXX 4821"
    d = bridge(text_doc(text), DT.AADHAAR).envelope.data
    assert d.dob is None  # never printed, so nothing to confirm and nothing invented
    assert d.year_of_birth.value == 1985 and d.year_of_birth.source == Source.PARSER


def test_aadhaar_last4_must_be_four_digits_else_empty():
    text = "Government of India\nRavi Kumar\nDOB: 15/08/1985\nMALE"
    d = bridge(text_doc(text), DT.AADHAAR).envelope.data
    assert d.aadhaar_last4.value is None and d.aadhaar_last4.confidence == 0


GST_TEXT = f"""Form GST REG-06
Registration Number: {GSTIN}
1. Legal Name RAVI KUMAR
2. Trade Name, if any KUMAR TRADERS
4. Constitution of Business Proprietorship
5. Address of Principal Place of Business 14, Market Road, Jayanagar, Bengaluru, Karnataka, 560041
6. Date of Liability 01/08/2025
7. Date of Validity From 01/08/2025 To Not Applicable"""


@pytest.mark.parametrize(("printed", "code"), [("Proprietorship", "proprietorship"), ("Private Limited Company", "pvt_ltd"), ("One Person Company", "other"), ("Association of Persons", "other")])
def test_gst_registration_and_constitution_vocabulary(printed, code):
    e = bridge(text_doc(GST_TEXT.replace("Proprietorship", printed)), DT.GST_CERTIFICATE).envelope
    d = e.data
    assert e.document_type == DocumentType.GST_REGISTRATION
    assert d.gstin.value == GSTIN and d.constitution.value.value == code
    assert d.registration_date.value == date(2025, 8, 1) and d.principal_address.value.pincode == "560041"


def test_gstr3b_months_in_rupees_with_row_provenance():
    text = "\n\n".join(
        f"Form GSTR-3B\nYear 2026-27  Period {name}\n1. GSTIN {GSTIN}\n(a) Outward taxable supplies (other than zero rated, nil rated and exempted)  {value}  0.00  8,280.00  8,280.00  0.00"
        for name, value in (("April", "92,000.00"), ("May", "1,00,000.50"))
    )
    e = bridge(text_doc(text), DT.GSTR_3B).envelope
    assert e.document_type == DocumentType.GSTR3B and e.data.gstin.value == GSTIN
    assert [(m.period, m.outward_taxable_value) for m in e.data.months] == [("2026-04", 92000.0), ("2026-05", 100000.5)]
    assert all(m.provenance.source == Source.PARSER for m in e.data.months)


BANK_HEAD = "DEMO BANK\nAccount Name: RAVI KUMAR\nAccount Number: XXXXXX5521\nIFSC: DEMO0001234\nStatement Period: 01/04/2026 to 30/04/2026\nOpening Balance: 10,000.00\n"


def test_bank_statement_rows_have_no_tags_and_keep_ref_in_its_own_field():
    rows = "02/04/2026  UPI/CR/SALES 123456789  5,000.00  15,000.00\n05/04/2026  NACH RTN INSUFFICIENT FUNDS  2,000.00  13,000.00"
    d = bridge(text_doc(BANK_HEAD + rows + "\nClosing Balance: 13,000.00"), DT.BANK_STATEMENT).envelope.data

    assert d.account_number_last4.value == "5521" and d.opening_balance.value == 10000.0 and d.closing_balance.value == 13000.0
    first, second = d.transactions
    assert (first.credit, first.debit, first.balance) == (5000.0, 0.0, 15000.0)
    assert first.ref == "123456789" and "123456789" not in first.narration
    assert (second.debit, second.credit) == (2000.0, 0.0)
    assert all(t.tags == [] for t in d.transactions)
    assert first.provenance.source == Source.PARSER and first.provenance.confidence == pytest.approx(0.95)


def test_direction_inferred_row_lowers_confidence_and_metadata_is_not_passed_on():
    # Edited balance: neither debit nor credit explains it, so the direction comes from the narration.
    rows = "02/04/2026  UPI/CR/SALES  5,000.00  99,000.00"
    d = bridge(text_doc(BANK_HEAD + rows), DT.BANK_STATEMENT).envelope.data
    assert d.transactions[0].credit == 5000.0 and d.transactions[0].provenance.confidence == pytest.approx(0.8)
    assert "balance_ok" not in d.transactions[0].model_dump()


def test_bank_row_without_a_balance_is_kept_and_reported():
    table = [["Date", "Narration", "Debit", "Credit", "Balance"], ["02/04/2026", "UPI/CR/SALES", "", "5,000.00", "15,000.00"], ["03/04/2026", "CASH DEPOSIT", "", "1,000.00", ""]]
    out = bridge(text_doc(BANK_HEAD, tables=[table]), DT.BANK_STATEMENT)
    rows = out.envelope.data.transactions
    # Dropping it would silently remove real money from turnover; keep it, without an invented balance.
    assert [(t.credit, t.balance) for t in rows] == [(5000.0, 15000.0), (1000.0, None)]
    assert any("no printed balance" in n for n in out.notes)


def test_row_box_is_found_when_the_ocr_line_is_unique():
    document = loaded(ocr_page([("Account Name: RAVI KUMAR", 0.9), ("Opening Balance: 10,000.00", 0.9), ("02/04/2026 UPI/CR/KUMAR SALES 5,000.00 15,000.00", 0.9)]))
    t = bridge(document, DT.BANK_STATEMENT).envelope.data.transactions[0]
    assert t.provenance.bbox is not None and t.provenance.bbox.page == 1 and t.provenance.source == Source.OCR


def test_itr_and_udyam_map_to_envelope_types():
    itr = "Assessment Year 2025-26\nPAN ABCPK1234F\nName RAVI KUMAR\nForm Number ITR-4\ne-Filing Acknowledgement Number 123456789012345\nGross Total Income 4,80,000\nTotal Income 4,50,000"
    e = bridge(text_doc(itr), DT.ITR).envelope
    assert e.document_type == DocumentType.ITR_V
    assert (e.data.assessment_year.value, e.data.itr_form.value, e.data.gross_total_income.value) == ("2025-26", "ITR-4", 480000.0)

    udyam = "UDYAM REGISTRATION NUMBER: UDYAM-MH-00-1234567\nName of Enterprise: KUMAR TRADERS\nType of Enterprise: Small\nMajor Activity: Trading\nOfficial address: 12, Market Road, Pune, Maharashtra 411001\nDate of Incorporation: 01/04/2022\nDate of Udyam Registration: 10/05/2022"
    e = bridge(text_doc(udyam), DT.UDYAM_CERTIFICATE).envelope
    assert e.document_type == DocumentType.UDYAM
    assert e.data.enterprise_type.value.value == "small" and e.data.date_of_registration.value == date(2022, 5, 10)
    assert e.data.address.value.pincode == "411001"


def test_triage_records_vlm_fallback_and_photo_input():
    photo = Page(index=0, text="", text_source=TextSource.NONE, image_png=png(), width=100, height=50)
    document = loaded(photo, fmt=SourceFormat.JPEG, name="pan.jpg")
    vlm = FakeVlm([{"pan": PAN, "name": "RAVI KUMAR", "dob": "15/08/1985"}])
    extraction = extract_detailed(document, DT.PAN_CARD, vlm=vlm)
    e = build_envelope(extraction, document, sme_id="s", document_id="d", password_protected=True).envelope

    assert e.triage.input_kind == "photo" and e.triage.extractor == Source.VLM and e.triage.fell_back_to_vlm
    assert "pan" in e.triage.fallback_reason and e.triage.password_protected and e.file.mime_type == "image/jpeg"
    assert e.data.pan_number.source == Source.VLM and e.data.pan_number.raw_text == PAN


def test_repaired_gstin_keeps_exactly_the_printed_text_as_raw():
    printed = GSTIN.replace("1234", "I234")  # OCR read the digit 1 as the letter I
    document = loaded(ocr_page([("Form GST REG-06", 0.9), (f"Registration Number: {printed}", 0.8), ("1. Legal Name RAVI KUMAR", 0.9)]))
    gstin = bridge(document, DT.GST_CERTIFICATE).envelope.data.gstin

    assert gstin.value == GSTIN and gstin.raw_text == printed and gstin.confidence <= 0.75 and gstin.needs_review


def test_assess_survives_fields_the_extractor_could_not_read():
    """A statement with no opening balance and a PAN card with no date of birth still go through scoring."""
    from app.samples import AS_OF
    from app.scoring import assess

    bank_text = BANK_HEAD.replace("Opening Balance: 10,000.00\n", "") + "02/04/2026  UPI/CR/SALES  5,000.00  15,000.00"
    envelopes = [
        bridge(text_doc(bank_text), DT.BANK_STATEMENT).envelope,
        bridge(text_doc(PAN_TEXT.replace("Date of Birth\n15/08/1985", "")), DT.PAN_CARD).envelope,
    ]
    assert envelopes[0].data.opening_balance is None and envelopes[1].data.dob.value is None
    assessment = assess("sme-1", envelopes, as_of=AS_OF)
    assert assessment.profile.readiness is not None
    # A number the bank never printed is not something to ask the SME to confirm.
    reviews = [c for d in assessment.documents for c in d.checks if c.id.endswith("needs_review")]
    assert not any("opening" in c.message.lower() for c in reviews)
