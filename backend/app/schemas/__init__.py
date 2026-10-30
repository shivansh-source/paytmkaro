"""Shared data contracts.

MSME side (common, documents, profile): Pydantic is the source of truth; JSON Schema is generated
into /schemas/v1/msme by `python -m scripts.export_schemas` (run from backend/). Never edit it by hand.

Lender side (lender): the hand-written JSON Schema in /schemas/v1/lender is the source of truth;
lender.py mirrors it and tests/test_lender_schema.py fails if they drift. Edit the JSON first.
"""

from app.schemas.common import (
    REQUIRED_DOCUMENTS,
    REVIEW_CONFIDENCE,
    SCHEMA_VERSION,
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
    Aadhaar,
    BankStatement,
    DocumentEnvelope,
    GstRegistration,
    Gstr3b,
    Gstr3bMonth,
    ItrV,
    PanCard,
    Transaction,
    Triage,
    Udyam,
)
from app.schemas.lender import LenderCatalog, LenderProduct
from app.schemas.profile import (
    BureauScore,
    CashflowMetrics,
    FixItItem,
    Identity,
    LoanRequest,
    Readiness,
    SmeProfile,
)

__all__ = [
    "REQUIRED_DOCUMENTS",
    "REVIEW_CONFIDENCE",
    "SCHEMA_VERSION",
    "Aadhaar",
    "Address",
    "BBox",
    "BankStatement",
    "BureauScore",
    "CashflowMetrics",
    "Check",
    "CheckStatus",
    "Constitution",
    "CrossCheck",
    "DocumentEnvelope",
    "DocumentType",
    "EvidenceRef",
    "Extracted",
    "FixItItem",
    "GstRegistration",
    "Gstr3b",
    "Gstr3bMonth",
    "Identity",
    "ItrV",
    "LenderCatalog",
    "LenderProduct",
    "LoanRequest",
    "MsmeCategory",
    "PanCard",
    "Readiness",
    "RowProvenance",
    "SmeProfile",
    "Source",
    "Sourced",
    "Transaction",
    "Triage",
    "Udyam",
]
