"""The fix-it checklist: what the SME should do next, most important first."""

from __future__ import annotations

from app.schemas.common import REQUIRED_DOCUMENTS, Check, CheckStatus, CrossCheck, DocumentType
from app.schemas.documents import DocumentEnvelope
from app.schemas.profile import BureauScore, CashflowMetrics, FixItItem
from app.validation.cross import DocumentSet

DOCUMENT_NAMES = {
    DocumentType.PAN_CARD: "PAN card",
    DocumentType.AADHAAR: "Aadhaar",
    DocumentType.GST_REGISTRATION: "GST registration certificate",
    DocumentType.GSTR3B: "GSTR-3B returns (last 6 months)",
    DocumentType.BANK_STATEMENT: "bank statement (last 6-12 months)",
    DocumentType.UDYAM: "Udyam certificate",
    DocumentType.ITR_V: "ITR-V",
    DocumentType.BUREAU_REPORT: "credit bureau report",
    DocumentType.FINANCIAL_STATEMENTS: "audited or CA-certified financial statements",
    DocumentType.SANCTION_LETTER: "loan sanction letter",
    DocumentType.SETTLEMENT_REPORT: "payment settlement report",
}

# What to tell the SME for a failed / flagged check, by check id. Missing ids fall back to the message.
_ACTIONS: dict[str, tuple[str, str, DocumentType | None]] = {
    CrossCheck.BALANCE_MATH: ("re_upload", "Upload the original bank statement downloaded from net banking", DocumentType.BANK_STATEMENT),
    CrossCheck.STATEMENT_GAPS: ("upload", "Upload the missing months", None),
    CrossCheck.NAME_MATCH: ("confirm_field", "Confirm your name is the same on every document", None),
    CrossCheck.DOB_MATCH: ("confirm_field", "Check the date of birth on PAN and Aadhaar", None),
    CrossCheck.ADDRESS_MATCH: ("confirm_field", "Confirm your business address", None),
    CrossCheck.PAN_IN_GSTIN: ("re_upload", "Check that the PAN card and GST certificate belong to the same business", None),
    CrossCheck.GST_VS_BANK: ("add_info", "Explain the gap between GST turnover and bank credits (e.g. a second account)", None),
}

_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def build_fix_it(
    docs: DocumentSet,
    envelopes: list[DocumentEnvelope],
    cross: list[Check],
    metrics: CashflowMetrics,
    bureau: BureauScore | None,
) -> list[FixItItem]:
    items: list[FixItItem] = []

    for doc_type in REQUIRED_DOCUMENTS:
        if not docs.get(doc_type):
            items.append(FixItItem(id=f"upload.{doc_type}", priority="high", title=f"Upload your {DOCUMENT_NAMES[doc_type]}",
                                   action="upload", document_type=doc_type))

    for check in cross:
        if check.status == CheckStatus.PASS:
            continue
        action, title, doc_type = _ACTIONS.get(check.id, ("confirm_field", check.message, None))
        if check.id == CrossCheck.STATEMENT_GAPS:
            # "Missing GSTR-3B for Jul 2026; No transactions in ..." -> one specific instruction
            title = "Upload " + "; ".join(m.removeprefix("Missing ") for m in check.message.split("; "))
        items.append(FixItItem(
            id=f"fix.{check.id}",
            priority="high" if check.status == CheckStatus.FAIL else "medium",
            title=title,
            detail=check.message,
            action=action,
            check_id=check.id,
            document_type=doc_type,
        ))

    # Document-level problems not already covered by a cross-check (formats, checksums, low confidence).
    covered = {"bank.balance_math", "bank.closing_balance", "bank.missing_months", "gstr3b.missing_months"}
    for env in envelopes:
        for check in env.checks:
            if check.status == CheckStatus.PASS or check.id in covered:
                continue
            items.append(FixItItem(
                id=f"fix.{env.document_id}.{check.id}",
                priority="high" if check.status == CheckStatus.FAIL else "medium" if check.id.endswith("needs_review") else "low",
                title=check.message,
                detail=f"On your {DOCUMENT_NAMES[env.document_type]}",
                action="confirm_field" if check.id.endswith("needs_review") else "re_upload" if check.status == CheckStatus.FAIL else "add_info",
                check_id=check.id,
                document_type=env.document_type,
            ))

    if bureau is None:
        items.append(FixItItem(id="add.bureau", priority="medium", title="Add your credit (bureau) score", action="add_info"))
    if metrics.bounces_6m is not None and metrics.bounces_6m.value > 2:
        items.append(FixItItem(
            id="improve.bounces", priority="low",
            title="Avoid EMI or cheque bounces for the next 6 months",
            detail=f"{metrics.bounces_6m.value} bounces in the last 6 months; most lenders allow 2 or fewer",
            action="add_info",
        ))
    if not docs.get(DocumentType.ITR_V):
        items.append(FixItItem(id="upload.itr_v", priority="low", title="Add your ITR-V to unlock lenders that ask for it",
                               action="upload", document_type=DocumentType.ITR_V))

    return sorted(items, key=lambda i: _PRIORITY_ORDER[i.priority])
