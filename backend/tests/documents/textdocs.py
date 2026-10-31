"""Helpers: LoadedDocuments built from text/tables (no files, no OCR engine), and the facts of
app.samples.applicant_b() rendered as document text so extraction can be compared with it."""

from __future__ import annotations

import io

from PIL import Image

from app.documents.extract.common import money
from app.documents.models import LoadedDocument, LoadStatus, OcrLine, Page, SourceFormat, TextSource
from app.samples import applicant_b
from app.schemas.common import DocumentType as EnvType

MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def png(width: int = 100, height: int = 50) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(out, format="PNG")
    return out.getvalue()


def page(text: str, index: int = 0, *, tables=None, source: TextSource = TextSource.NATIVE) -> Page:
    return Page(index=index, text=text, text_source=source, tables=tables or [])


def loaded(*pages: Page, fmt: SourceFormat = SourceFormat.PDF, name: str = "doc.pdf") -> LoadedDocument:
    return LoadedDocument(file_name=name, sha256="a" * 64, source_format=fmt, status=LoadStatus.OK, pages=list(pages))


def text_doc(text: str, **kwargs) -> LoadedDocument:
    return loaded(page(text, **kwargs))


def ocr_page(rows: list[tuple[str, float]], index: int = 0, width: int = 1000, height: int = 1400) -> Page:
    """A scanned page: one OCR box per row (pixel boxes on a width x height image)."""
    lines = [OcrLine(text=t, confidence=c, bbox=(100.0, 100.0 * (i + 1), 100.0 + 12 * len(t), 100.0 * (i + 1) + 40)) for i, (t, c) in enumerate(rows)]
    return Page(index=index, text="\n".join(t for t, _ in rows), text_source=TextSource.OCR, ocr_lines=lines, image_png=png(width, height), width=width, height=height)


# ---------- Applicant B as document text ----------


def _by_type(envelopes):
    return {e.document_type: e.data for e in envelopes}


def applicant_b_texts() -> dict[str, str]:
    """Text of each of Applicant B's documents, rendered from the sample's own values."""
    d = _by_type(applicant_b())
    pan, aad, gst, gstr, bank, udy = (d[EnvType.PAN_CARD], d[EnvType.AADHAAR], d[EnvType.GST_REGISTRATION], d[EnvType.GSTR3B], d[EnvType.BANK_STATEMENT], d[EnvType.UDYAM])
    ddmm = lambda x: x.strftime("%d/%m/%Y")  # noqa: E731
    texts = {
        "pan": f"Permanent Account Number Card\n{pan.pan_number.value}\nName\n{pan.name.value}\nFather's Name\n{pan.father_name.value}\nDate of Birth\n{ddmm(pan.dob.value)}",
        "aadhaar": f"Government of India\nRavi Kumar\nDOB: {ddmm(aad.dob.value)}\nMALE\nXXXX XXXX {aad.aadhaar_last4.value}\nAddress: {aad.address.value.text}",
        "gst": (
            f"Form GST REG-06\nRegistration Number: {gst.gstin.value}\n1. Legal Name {gst.legal_name.value}\n2. Trade Name, if any {gst.trade_name.value}\n"
            f"4. Constitution of Business Proprietorship\n5. Address of Principal Place of Business {gst.principal_address.value.text}\n"
            f"6. Date of Liability {ddmm(gst.registration_date.value)}\n7. Date of Validity From {ddmm(gst.registration_date.value)} To Not Applicable"
        ),
        "udyam": (
            f"UDYAM REGISTRATION CERTIFICATE\nUDYAM REGISTRATION NUMBER: {udy.udyam_number.value}\nName of Enterprise: {udy.enterprise_name.value}\n"
            f"Type of Enterprise: Micro\nMajor Activity: Trading\nOfficial address: {udy.address.value.text}\n"
            f"Date of Incorporation: {ddmm(udy.date_of_incorporation.value)}"
        ),
    }
    blocks = []
    for m in gstr.months:
        y, mo = int(m.period[:4]), int(m.period[5:])
        fy = f"{y}-{(y + 1) % 100:02d}" if mo >= 4 else f"{y - 1}-{y % 100:02d}"
        tax = money(m.outward_taxable_value * 0.09).lstrip("₹")
        blocks.append(
            f"Form GSTR-3B\nYear {fy}  Period {MONTH_NAMES[mo - 1]}\n1. GSTIN {gstr.gstin.value}\n2(a). Legal name of the registered person {gst.legal_name.value}\n"
            f"(a) Outward taxable supplies (other than zero rated, nil rated and exempted)  {money(m.outward_taxable_value).lstrip('₹')}  0.00  {tax}  {tax}  0.00"
        )
    texts["gstr3b"] = "\n\n".join(blocks)
    rows = [
        f"{t.date.strftime('%d/%m/%Y')}  {t.narration:<36}  {money(t.debit).lstrip('₹')}  {money(t.credit).lstrip('₹')}  {money(t.balance).lstrip('₹')}"
        for t in bank.transactions
    ]
    header = (
        f"{bank.bank_name.value}\nAccount Name: {bank.account_holder_name.value}\nAccount Number: XXXXXXXX{bank.account_number_last4.value}\n"
        f"IFSC: {bank.ifsc.value}\nStatement Period: {ddmm(bank.period_from.value)} to {ddmm(bank.period_to.value)}\n"
        f"Opening Balance: {money(bank.opening_balance.value).lstrip('₹')}"
    )
    texts["bank"] = header + "\n" + "\n".join(rows) + f"\nClosing Balance: {money(bank.closing_balance.value).lstrip('₹')}"
    return texts
