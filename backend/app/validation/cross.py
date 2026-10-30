"""Cross-document checks: the identity chain and the money trail.

Each check returns a single Check with a stable CrossCheck id. A check whose documents aren't uploaded
yet is skipped (the fix-it list asks for the document instead).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from app.schemas.common import Check, CheckStatus, CrossCheck, DocumentType
from app.schemas.documents import DocumentEnvelope
from app.validation.months import month_key
from app.validation.text import compare_addresses, compare_names

# GST turnover / bank credits for the same months. Outside these bands lenders will ask questions.
GST_BANK_PASS = (0.7, 1.3)
GST_BANK_WARN = (0.5, 1.6)


@dataclass
class DocumentSet:
    """The documents an assessment works from: latest upload per type; GSTR-3B may span uploads."""

    by_type: dict[DocumentType, DocumentEnvelope] = field(default_factory=dict)
    gstr3b: list[DocumentEnvelope] = field(default_factory=list)

    @classmethod
    def from_envelopes(cls, envelopes: list[DocumentEnvelope]) -> DocumentSet:
        docs = cls()
        for env in sorted(envelopes, key=lambda e: e.uploaded_at):
            if env.data is None or env.status == "failed":
                continue
            if env.document_type == DocumentType.GSTR3B:
                docs.gstr3b.append(env)
            docs.by_type[env.document_type] = env
        return docs

    def get(self, doc_type: DocumentType) -> DocumentEnvelope | None:
        return self.by_type.get(doc_type)

    def data(self, doc_type: DocumentType):
        env = self.get(doc_type)
        return env.data if env else None

    def gst_months(self) -> dict[str, tuple[float, str]]:
        """period -> (outward taxable value, document_id); later uploads win."""
        months: dict[str, tuple[float, str]] = {}
        for env in self.gstr3b:
            for m in env.data.months:
                months[m.period] = (m.outward_taxable_value, env.document_id)
        return months


def _v(extracted):
    return extracted.value if extracted is not None else None


def _worst(statuses: list[CheckStatus]) -> CheckStatus:
    for status in (CheckStatus.FAIL, CheckStatus.WARN):
        if status in statuses:
            return status
    return CheckStatus.PASS


def pan_in_gstin(docs: DocumentSet) -> Check | None:
    pan_doc, gst_doc = docs.get(DocumentType.PAN_CARD), docs.get(DocumentType.GST_REGISTRATION)
    if not pan_doc or not gst_doc:
        return None
    pan = (_v(pan_doc.data.pan_number) or "").upper()
    gstin = (_v(gst_doc.data.gstin) or "").upper()
    ok = len(gstin) == 15 and gstin[2:12] == pan
    return Check(
        id=CrossCheck.PAN_IN_GSTIN,
        status=CheckStatus.PASS if ok else CheckStatus.FAIL,
        message="PAN inside your GSTIN matches your PAN card" if ok else f"GSTIN contains PAN '{gstin[2:12]}', but your PAN card says '{pan}'",
        document_ids=[pan_doc.document_id, gst_doc.document_id],
        fields=["data.pan_number", "data.gstin"],
        expected=pan,
        actual=gstin[2:12],
    )


def name_match(docs: DocumentSet) -> Check | None:
    pan_doc = docs.get(DocumentType.PAN_CARD)
    if not pan_doc or not _v(pan_doc.data.name):
        return None
    reference = _v(pan_doc.data.name)
    others = [
        ("Aadhaar", DocumentType.AADHAAR, "name"),
        ("GST", DocumentType.GST_REGISTRATION, "legal_name"),
        ("bank account", DocumentType.BANK_STATEMENT, "account_holder_name"),
    ]
    results: list[tuple[str, str, CheckStatus, DocumentEnvelope]] = []
    confirmed: list[str] = []
    for label, doc_type, attr in others:
        env = docs.get(doc_type)
        if env and (name := _v(getattr(env.data, attr))):
            status = compare_names(reference, name)
            # The SME confirmed a near-match ("RAVI KUMAAR") is the same person. A clear mismatch stays failed.
            if status == CheckStatus.WARN and getattr(env.data, attr).user_confirmed:
                status = CheckStatus.PASS
                confirmed.append(label)
            results.append((label, name, status, env))
    if not results:
        return None
    status = _worst([r[2] for r in results])
    off = [f"{label} says '{name}'" for label, name, s, _ in results if s != CheckStatus.PASS]
    labels = ", ".join(r[0] for r in results)
    message = (
        f"Name matches on PAN, {labels}" + (f" ({', '.join(confirmed)} confirmed by you)" if confirmed else "")
        if status == CheckStatus.PASS
        else f"Your PAN says '{reference}', but {'; '.join(off)}"
        + (": please confirm it's the same person" if status == CheckStatus.WARN else "")
    )
    return Check(
        id=CrossCheck.NAME_MATCH,
        status=status,
        message=message,
        document_ids=[pan_doc.document_id, *(r[3].document_id for r in results)],
        expected=reference,
        actual="; ".join(r[1] for r in results if r[2] != CheckStatus.PASS) or None,
    )


def dob_match(docs: DocumentSet) -> Check | None:
    pan_doc, aadhaar_doc = docs.get(DocumentType.PAN_CARD), docs.get(DocumentType.AADHAAR)
    if not pan_doc or not aadhaar_doc:
        return None
    a, b = _v(pan_doc.data.dob), _v(aadhaar_doc.data.dob)
    if a is None or b is None:
        status, message = CheckStatus.WARN, "Couldn't read the date of birth on PAN or Aadhaar"
    elif a == b:
        status, message = CheckStatus.PASS, "Date of birth matches on PAN and Aadhaar"
    else:
        status, message = CheckStatus.FAIL, f"Date of birth differs: PAN {a:%d %b %Y}, Aadhaar {b:%d %b %Y}"
    return Check(
        id=CrossCheck.DOB_MATCH,
        status=status,
        message=message,
        document_ids=[pan_doc.document_id, aadhaar_doc.document_id],
        fields=["data.dob"],
        expected=str(a) if a else None,
        actual=str(b) if b else None,
    )


def address_match(docs: DocumentSet) -> Check | None:
    sources = [
        ("Aadhaar", docs.get(DocumentType.AADHAAR), "address"),
        ("GST", docs.get(DocumentType.GST_REGISTRATION), "principal_address"),
        ("Udyam", docs.get(DocumentType.UDYAM), "address"),
    ]
    found = [(label, env, _v(getattr(env.data, attr))) for label, env, attr in sources if env and _v(getattr(env.data, attr))]
    if len(found) < 2:
        return None
    # Business address (GST) is the anchor when present; home (Aadhaar) may legitimately differ.
    anchor_label, anchor_env, anchor = next((f for f in found if f[0] == "GST"), found[0])
    statuses, notes = [], []
    for label, env, addr in found:
        if env is anchor_env:
            continue
        status = compare_addresses(anchor.text, addr.text, anchor.pincode, addr.pincode)
        if label == "Aadhaar" and status == CheckStatus.FAIL:
            status = CheckStatus.WARN  # proprietor may live elsewhere; ask, don't block
        statuses.append(status)
        if status != CheckStatus.PASS:
            notes.append(f"{label} address differs from {anchor_label}")
    status = _worst(statuses)
    return Check(
        id=CrossCheck.ADDRESS_MATCH,
        status=status,
        message="Address matches on " + ", ".join(f[0] for f in found) if status == CheckStatus.PASS else "; ".join(notes),
        document_ids=[f[1].document_id for f in found],
    )


def bank_credits_by_month(docs: DocumentSet) -> dict[str, float]:
    """Business credits per month. Bounce reversals are refunds of our own debits, not income."""
    bank = docs.data(DocumentType.BANK_STATEMENT)
    totals: dict[str, float] = defaultdict(float)
    if bank:
        for t in bank.transactions:
            if t.credit and "bounce" not in t.tags:
                totals[month_key(t.date)] += t.credit
    return dict(totals)


def gst_vs_bank(docs: DocumentSet) -> Check | None:
    gst, bank_env = docs.gst_months(), docs.get(DocumentType.BANK_STATEMENT)
    if not gst or not bank_env:
        return None
    credits = bank_credits_by_month(docs)
    common = sorted(set(gst) & set(credits))
    if not common:
        return Check(
            id=CrossCheck.GST_VS_BANK,
            status=CheckStatus.WARN,
            message="GST returns and bank statement don't cover the same months",
            document_ids=[bank_env.document_id, *(e.document_id for e in docs.gstr3b)],
        )
    gst_total, bank_total = sum(gst[m][0] for m in common), sum(credits[m] for m in common)
    ratio = gst_total / bank_total if bank_total else float("inf")
    if GST_BANK_PASS[0] <= ratio <= GST_BANK_PASS[1]:
        status = CheckStatus.PASS
    elif GST_BANK_WARN[0] <= ratio <= GST_BANK_WARN[1]:
        status = CheckStatus.WARN
    else:
        status = CheckStatus.FAIL
    pct = round(ratio * 100)
    message = (
        f"GST turnover is {pct}% of bank credits over {len(common)} months: consistent"
        if status == CheckStatus.PASS
        else f"GST turnover is {pct}% of bank credits over {len(common)} months: lenders will ask why"
    )
    return Check(
        id=CrossCheck.GST_VS_BANK,
        status=status,
        message=message,
        document_ids=[bank_env.document_id, *(e.document_id for e in docs.gstr3b)],
        expected=f"{GST_BANK_PASS[0]:.0%}-{GST_BANK_PASS[1]:.0%}",
        actual=f"{ratio:.0%}",
    )


def _from_document_checks(docs: DocumentSet, cross_id: CrossCheck, doc_check_ids: set[str], ok_message: str) -> Check | None:
    envs = [e for e in (docs.get(DocumentType.BANK_STATEMENT), *docs.gstr3b) if e]
    relevant = [c for e in envs for c in e.checks if c.id in doc_check_ids]
    if not relevant:
        return None
    bad = [c for c in relevant if c.status != CheckStatus.PASS]
    return Check(
        id=cross_id,
        status=_worst([c.status for c in relevant]),
        message=ok_message if not bad else "; ".join(dict.fromkeys(c.message for c in bad)),
        document_ids=list(dict.fromkeys(i for c in relevant for i in c.document_ids)),
        fields=[f for c in bad for f in c.fields],
    )


def cross_checks(docs: DocumentSet) -> list[Check]:
    """Run after per-document checks (balance math and gaps are summarised from them)."""
    found = [
        pan_in_gstin(docs),
        name_match(docs),
        dob_match(docs),
        address_match(docs),
        gst_vs_bank(docs),
        _from_document_checks(docs, CrossCheck.BALANCE_MATH, {"bank.balance_math", "bank.closing_balance"},
                              "Every bank statement row adds up"),
        _from_document_checks(docs, CrossCheck.STATEMENT_GAPS, {"bank.missing_months", "gstr3b.missing_months"},
                              "No missing months in bank statement or GST returns"),
    ]
    return [c for c in found if c is not None]
