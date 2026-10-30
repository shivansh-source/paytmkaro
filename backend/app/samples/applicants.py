"""Synthetic demo applicants as extraction output (DocumentEnvelopes). ALL DATA IS SAMPLE.

Applicant A (clean): every check passes, ready, matches every demo lender.
Applicant B (messy), with three planted problems the demo catches live:
  1. name spelling mismatch on the bank statement ("RAVI KUMAAR")
  2. one missing month: GSTR-3B for July 2026 not uploaded
  3. one edited row: a credit changed from 24,000 to 54,000 without fixing the balance ("possible tampering")
plus a weaker profile: 14 months vintage, 3 EMI bounces, FOIR ~42%.

These are the target shapes for the OCR/VLM extractors to produce.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from app.schemas.common import Address, BBox, Constitution, DocumentType, Extracted, MsmeCategory, RowProvenance, Source
from app.schemas.documents import (
    Aadhaar,
    BankStatement,
    DocumentEnvelope,
    FileInfo,
    GstRegistration,
    Gstr3b,
    Gstr3bMonth,
    PanCard,
    Transaction,
    Triage,
    Udyam,
)
from app.schemas.profile import BureauScore
from app.validation.checksums import gstin_check_digit
from app.validation.months import add_months

AS_OF = date(2026, 10, 31)
UPLOADED = datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc)
STATEMENT_START = date(2025, 10, 1)
STATEMENT_MONTHS = 12
GST_MONTHS = [f"2026-{m:02d}" for m in range(4, 10)]  # April-September 2026

ADDRESS = Address(
    text="SAMPLE, 12 Gandhi Bazaar Main Road, Basavanagudi, Bengaluru, Karnataka 560004",
    city="Bengaluru",
    district="Bengaluru Urban",
    state="Karnataka",
    pincode="560004",
)


def _x(value, confidence: float = 0.97, source: Source = Source.VLM, bbox: BBox | None = None) -> Extracted:
    return Extracted(value=value, confidence=confidence, source=source, bbox=bbox)


def gstin_for(pan: str, state: str = "29", entity: str = "1") -> str:
    body = f"{state}{pan}{entity}Z"
    return body + gstin_check_digit(body)


def _envelope(sme_id: str, doc_id: str, doc_type: DocumentType, data, kind: str, extractor: Source, pages: int = 1) -> DocumentEnvelope:
    mime = "image/jpeg" if kind == "photo" else "application/pdf"
    return DocumentEnvelope(
        document_id=doc_id,
        sme_id=sme_id,
        document_type=doc_type,
        status="needs_review",  # extraction done, validation not yet run
        uploaded_at=UPLOADED,
        file=FileInfo(file_name=f"{doc_type}.{'jpg' if kind == 'photo' else 'pdf'}", mime_type=mime, size_bytes=250_000 * pages,
                      pages=pages, sha256=hashlib.sha256(doc_id.encode()).hexdigest()),
        triage=Triage(input_kind=kind, extractor=extractor),
        data=data,
    )


@dataclass(frozen=True)
class Plan:
    """Monthly cash pattern for a synthetic bank statement."""

    opening: float
    sale: float  # four UPI sales credits per month
    emi: float
    supplier: float
    rent: float
    bounce_months: tuple[int, ...] = ()  # month indexes (0-based) where the EMI bounces


def _transactions(plan: Plan) -> list[Transaction]:
    row = RowProvenance(source=Source.OCR, confidence=0.95)
    rows: list[tuple[date, str, float, float]] = []  # date, narration, debit, credit
    for i in range(STATEMENT_MONTHS):
        m = add_months(STATEMENT_START, i)
        day = lambda d: m.replace(day=d)  # noqa: E731
        rows.append((day(3), "UPI/CR/SAMPLE RETAIL CUSTOMERS", 0, plan.sale))
        rows.append((day(5), "NACH/DR/SAMPLE NBFC LOAN EMI", plan.emi, 0))
        if i in plan.bounce_months:
            rows.append((day(6), "NACH RTN INSUFFICIENT FUNDS SAMPLE NBFC", 0, plan.emi))
            rows.append((day(6), "NACH RTN CHGS INCL GST", 590, 0))
        rows.append((day(10), "UPI/CR/SAMPLE RETAIL CUSTOMERS", 0, plan.sale))
        rows.append((day(12), "NEFT/DR/SAMPLE WHOLESALE SUPPLIES", plan.supplier, 0))
        rows.append((day(18), "UPI/CR/SAMPLE RETAIL CUSTOMERS", 0, plan.sale))
        rows.append((day(22), "IMPS/DR/SHOP RENT SAMPLE LANDLORD", plan.rent, 0))
        rows.append((day(25), "UPI/CR/SAMPLE RETAIL CUSTOMERS", 0, plan.sale))
        rows.append((day(28), "SMS ALERT CHGS", 59, 0))
    balance = plan.opening
    out = []
    for d, narration, debit, credit in rows:
        balance = round(balance + credit - debit, 2)
        out.append(Transaction(date=d, narration=narration, debit=debit, credit=credit, balance=balance, provenance=row))
    return out


@dataclass(frozen=True)
class Person:
    name: str
    pan: str
    dob: date
    trade_name: str
    incorporated: date
    category: MsmeCategory


def _documents(sme_id: str, p: Person, bank_name: str, plan: Plan, gst_value: float, gst_months: list[str],
               transactions: list[Transaction] | None = None) -> list[DocumentEnvelope]:
    gstin = gstin_for(p.pan)
    txns = transactions or _transactions(plan)
    period_to = add_months(STATEMENT_START, STATEMENT_MONTHS) - timedelta(days=1)
    s = sme_id.lower()
    return [
        _envelope(sme_id, f"{s}-pan", DocumentType.PAN_CARD, PanCard(
            pan_number=_x(p.pan, bbox=BBox(page=1, x0=0.12, y0=0.42, x1=0.48, y1=0.49)),
            name=_x(p.name), father_name=_x("SAMPLE FATHER NAME", 0.9), dob=_x(p.dob)), "photo", Source.VLM),
        _envelope(sme_id, f"{s}-aadhaar", DocumentType.AADHAAR, Aadhaar(
            aadhaar_last4=_x("4821"), verhoeff_valid=True, name=_x(p.name), dob=_x(p.dob),
            gender=_x("male", 0.95), address=_x(ADDRESS, 0.9)), "photo", Source.VLM),
        _envelope(sme_id, f"{s}-gst", DocumentType.GST_REGISTRATION, GstRegistration(
            gstin=_x(gstin, 0.99, Source.PARSER), legal_name=_x(p.name, 0.99, Source.PARSER),
            trade_name=_x(p.trade_name, 0.99, Source.PARSER), constitution=_x(Constitution.PROPRIETORSHIP, 0.99, Source.PARSER),
            registration_date=_x(p.incorporated, 0.99, Source.PARSER), principal_address=_x(ADDRESS, 0.99, Source.PARSER)),
            "digital_pdf", Source.PARSER, pages=3),
        _envelope(sme_id, f"{s}-gstr3b", DocumentType.GSTR3B, Gstr3b(
            gstin=_x(gstin, 0.99, Source.PARSER),
            months=[Gstr3bMonth(period=m, outward_taxable_value=gst_value,
                                filing_date=add_months(date.fromisoformat(m + "-18"), 1),
                                due_date=add_months(date.fromisoformat(m + "-20"), 1),
                                provenance=RowProvenance(source=Source.PARSER, confidence=0.99)) for m in gst_months]),
            "digital_pdf", Source.PARSER, pages=len(gst_months)),
        _envelope(sme_id, f"{s}-bank", DocumentType.BANK_STATEMENT, BankStatement(
            account_holder_name=_x(bank_name, 0.96, Source.OCR), account_number_last4=_x("7310", 0.98, Source.OCR),
            ifsc=_x("SMPL0001234", 0.97, Source.OCR), bank_name=_x("SAMPLE BANK", 0.97, Source.OCR),
            period_from=_x(STATEMENT_START, 0.99, Source.OCR), period_to=_x(period_to, 0.99, Source.OCR),
            opening_balance=_x(plan.opening, 0.97, Source.OCR), closing_balance=_x(txns[-1].balance, 0.97, Source.OCR),
            transactions=txns), "scanned_pdf", Source.OCR, pages=14),
        _envelope(sme_id, f"{s}-udyam", DocumentType.UDYAM, Udyam(
            udyam_number=_x("UDYAM-KA-03-0001234", 0.98, Source.PARSER), enterprise_name=_x(p.trade_name, 0.98, Source.PARSER),
            enterprise_type=_x(p.category, 0.98, Source.PARSER), major_activity=_x("trading", 0.98, Source.PARSER),
            date_of_incorporation=_x(p.incorporated, 0.98, Source.PARSER), address=_x(ADDRESS, 0.98, Source.PARSER)),
            "digital_pdf", Source.PARSER),
    ]


def applicant_a() -> list[DocumentEnvelope]:
    person = Person("RAVI KUMAR", "ABCPK1234F", date(1986, 4, 12), "SAMPLE KUMAR STORES", date(2023, 7, 1), MsmeCategory.MICRO)
    plan = Plan(opening=150_000, sale=50_000, emi=50_000, supplier=115_000, rent=20_000)
    return _documents("SAMPLE-A", person, "RAVI KUMAR", plan, gst_value=196_000, gst_months=GST_MONTHS)


TAMPERED_ROW_DATE = date(2026, 2, 10)


def applicant_b() -> list[DocumentEnvelope]:
    person = Person("RAVI KUMAR", "BCDPK5678G", date(1990, 9, 3), "SAMPLE RAVI TRADERS", date(2025, 8, 20), MsmeCategory.MICRO)
    plan = Plan(opening=60_000, sale=24_000, emi=40_000, supplier=45_000, rent=9_000, bounce_months=(6, 7, 8))
    txns = _transactions(plan)
    # Planted problem 3: someone edited one credit; the balance column still shows the original.
    i = next(i for i, t in enumerate(txns) if t.date == TAMPERED_ROW_DATE and t.credit)
    txns[i] = txns[i].model_copy(update={"credit": 54_000.0})
    gst_months = [m for m in GST_MONTHS if m != "2026-07"]  # planted problem 2
    return _documents("SAMPLE-B", person, "RAVI KUMAAR", plan, gst_value=92_000, gst_months=gst_months, transactions=txns)  # problem 1


BUREAU_A = BureauScore(value=760, source="mock")
BUREAU_B = BureauScore(value=705, source="mock")
