"""Synthetic examples (Applicant A, clean). Used by tests and exported next to the JSON Schemas so
dashboard and extraction work can start before the pipeline exists. All values are SAMPLE data."""

from __future__ import annotations

from datetime import date, datetime, timezone

from app.schemas.common import (
    Address,
    BBox,
    Check,
    CheckStatus,
    Constitution,
    CrossCheck,
    DocumentType,
    EvidenceRef,
    Extracted,
    MsmeCategory,
    RowProvenance,
    Source,
    Sourced,
)
from app.schemas.documents import (
    BankStatement,
    DocumentEnvelope,
    FileInfo,
    PanCard,
    Transaction,
    Triage,
)
from app.schemas.profile import (
    BureauScore,
    CashflowMetrics,
    DocumentSummary,
    FixItItem,
    Identity,
    LoanRequest,
    Readiness,
    ReadinessComponent,
    SmeProfile,
)

SME_ID = "SAMPLE-A"
UPLOADED = datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc)
ADDRESS = Address(
    text="SAMPLE, 12 Gandhi Bazaar Main Road, Basavanagudi, Bengaluru, Karnataka 560004",
    city="Bengaluru",
    district="Bengaluru Urban",
    state="Karnataka",
    pincode="560004",
)


def example_pan_envelope() -> DocumentEnvelope:
    return DocumentEnvelope(
        document_id="doc-pan-a",
        sme_id=SME_ID,
        document_type=DocumentType.PAN_CARD,
        status="verified",
        uploaded_at=UPLOADED,
        file=FileInfo(file_name="pan.jpg", mime_type="image/jpeg", size_bytes=412_000, pages=1, sha256="0" * 64),
        triage=Triage(input_kind="photo", extractor=Source.VLM),
        data=PanCard(
            pan_number=Extracted[str](
                value="ABCPK1234F",
                confidence=0.97,
                source=Source.VLM,
                bbox=BBox(page=1, x0=0.12, y0=0.42, x1=0.48, y1=0.49),
            ),
            name=Extracted[str](value="RAVI KUMAR", confidence=0.95, source=Source.VLM),
            father_name=Extracted[str](value="SURESH KUMAR", confidence=0.91, source=Source.VLM),
            dob=Extracted[date](value=date(1986, 4, 12), confidence=0.93, source=Source.VLM),
        ),
        checks=[
            Check(id="pan.format", status=CheckStatus.PASS, message="PAN format is valid", fields=["data.pan_number"]),
            Check(
                id="pan.holder_type",
                status=CheckStatus.PASS,
                message="4th letter P: PAN belongs to an individual, as expected for a proprietorship",
                fields=["data.pan_number"],
            ),
        ],
    )


def example_bank_statement_envelope() -> DocumentEnvelope:
    row = RowProvenance(source=Source.OCR, confidence=0.94)
    return DocumentEnvelope(
        document_id="doc-bank-a",
        sme_id=SME_ID,
        document_type=DocumentType.BANK_STATEMENT,
        status="verified",
        uploaded_at=UPLOADED,
        file=FileInfo(file_name="statement.pdf", mime_type="application/pdf", size_bytes=1_830_000, pages=14, sha256="1" * 64),
        triage=Triage(input_kind="scanned_pdf", extractor=Source.OCR, ocr_mean_confidence=0.93),
        data=BankStatement(
            account_holder_name=Extracted[str](value="RAVI KUMAR", confidence=0.96, source=Source.OCR),
            account_number_last4=Extracted[str](value="4821", confidence=0.98, source=Source.OCR),
            ifsc=Extracted[str](value="SMPL0001234", confidence=0.97, source=Source.OCR),
            period_from=Extracted[date](value=date(2025, 10, 1), confidence=0.99, source=Source.OCR),
            period_to=Extracted[date](value=date(2026, 9, 30), confidence=0.99, source=Source.OCR),
            opening_balance=Extracted[float](value=152_400.0, confidence=0.97, source=Source.OCR),
            closing_balance=Extracted[float](value=171_900.0, confidence=0.97, source=Source.OCR),
            transactions=[
                Transaction(date=date(2025, 10, 3), narration="UPI/CR/SAMPLE TRADERS", credit=42_000, balance=194_400, tags=["upi"], provenance=row),
                Transaction(date=date(2025, 10, 5), narration="NACH/DR/SAMPLE NBFC EMI", debit=18_500, balance=175_900, tags=["nach", "emi"], provenance=row),
            ],
        ),
        checks=[
            Check(id="bank.ifsc_format", status=CheckStatus.PASS, message="IFSC format is valid", fields=["data.ifsc"]),
            Check(id=CrossCheck.BALANCE_MATH, status=CheckStatus.PASS, message="Every row adds up"),
        ],
    )


def example_sme_profile() -> SmeProfile:
    def ev(doc: str, field: str) -> list[EvidenceRef]:
        return [EvidenceRef(document_id=doc, field=field)]

    return SmeProfile(
        sme_id=SME_ID,
        updated_at=UPLOADED,
        identity=Identity(
            legal_name=Sourced[str](value="RAVI KUMAR", evidence=ev("doc-gst-a", "data.legal_name")),
            trade_name=Sourced[str](value="SAMPLE KUMAR STORES", evidence=ev("doc-gst-a", "data.trade_name")),
            constitution=Sourced[Constitution](value=Constitution.PROPRIETORSHIP, evidence=ev("doc-gst-a", "data.constitution")),
            pan=Sourced[str](value="ABCPK1234F", evidence=ev("doc-pan-a", "data.pan_number")),
            gstin=Sourced[str](value="29ABCPK1234F1Z5", evidence=ev("doc-gst-a", "data.gstin")),
            udyam_number=Sourced[str](value="UDYAM-KA-03-0001234", evidence=ev("doc-udyam-a", "data.udyam_number")),
            msme_category=Sourced[MsmeCategory](value=MsmeCategory.MICRO, evidence=ev("doc-udyam-a", "data.enterprise_type")),
            date_of_incorporation=Sourced[date](value=date(2023, 8, 1), evidence=ev("doc-udyam-a", "data.date_of_incorporation")),
            business_vintage_months=Sourced[int](value=38, evidence=ev("doc-udyam-a", "data.date_of_incorporation")),
            address=Sourced[Address](value=ADDRESS, evidence=ev("doc-gst-a", "data.principal_address")),
            sector="retail",
        ),
        cashflow=CashflowMetrics(
            months_analyzed=12,
            avg_monthly_balance=Sourced[float](value=186_400.0, evidence=ev("doc-bank-a", "data.transactions")),
            avg_monthly_credits=Sourced[float](value=205_000.0, evidence=ev("doc-bank-a", "data.transactions")),
            bounces_6m=Sourced[int](value=0, evidence=ev("doc-bank-a", "data.transactions")),
            existing_emi_monthly=Sourced[float](value=51_250.0, evidence=ev("doc-bank-a", "data.transactions")),
            foir=Sourced[float](value=0.25, evidence=ev("doc-bank-a", "data.transactions")),
            gst_turnover_12m=Sourced[float](value=2_400_000.0, evidence=ev("doc-gstr3b-a", "data.months")),
            gst_vs_bank_ratio=Sourced[float](value=0.98, evidence=ev("doc-gstr3b-a", "data.months") + ev("doc-bank-a", "data.transactions")),
        ),
        bureau=BureauScore(value=760, source="mock"),
        documents=[
            DocumentSummary(document_id="doc-pan-a", document_type=DocumentType.PAN_CARD, status="verified"),
            DocumentSummary(document_id="doc-bank-a", document_type=DocumentType.BANK_STATEMENT, status="verified"),
        ],
        cross_checks=[
            Check(id=CrossCheck.PAN_IN_GSTIN, status=CheckStatus.PASS, message="PAN inside GSTIN matches your PAN card", document_ids=["doc-pan-a", "doc-gst-a"]),
            Check(id=CrossCheck.NAME_MATCH, status=CheckStatus.PASS, message="Name matches on PAN, Aadhaar, GST and bank account"),
            Check(id=CrossCheck.DOB_MATCH, status=CheckStatus.PASS, message="Date of birth matches on PAN and Aadhaar"),
            Check(id=CrossCheck.ADDRESS_MATCH, status=CheckStatus.PASS, message="Address matches on Aadhaar, GST and Udyam"),
            Check(id=CrossCheck.GST_VS_BANK, status=CheckStatus.PASS, message="GST turnover is within 2% of bank credits"),
            Check(id=CrossCheck.BALANCE_MATH, status=CheckStatus.PASS, message="Every bank statement row adds up"),
        ],
        readiness=Readiness(
            score=82,
            band="ready",
            components=[
                ReadinessComponent(name="Documents complete", points=25, max_points=25),
                ReadinessComponent(name="Identity verified", points=25, max_points=25),
                ReadinessComponent(name="Cash flow", points=20, max_points=30),
                ReadinessComponent(name="Credit history", points=12, max_points=20, note="Bureau score is mocked"),
            ],
        ),
        fix_it=[
            FixItItem(
                id="fix-itr",
                priority="low",
                title="Add your ITR-V to unlock lenders that ask for it",
                action="upload",
                document_type=DocumentType.ITR_V,
            )
        ],
    )


def example_loan_request() -> LoanRequest:
    return LoanRequest(sme_id=SME_ID, amount=500_000, tenure_months=24, purpose="Working capital")
