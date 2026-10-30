"""VLM prompts. The VLM only reads what is printed; every number it returns is re-validated
in code, and totals/counts are never asked for."""

from __future__ import annotations

from app.documents.models import DocumentType

_RULES = (
    "Rules: copy each value exactly as printed on the document. Use null when a value is not printed "
    "or you cannot read it clearly. Never guess, infer, compute, add up or total anything. "
    "Reply with one JSON object only, no commentary."
)

FIELDS: dict[DocumentType, dict[str, str]] = {
    DocumentType.PAN_CARD: {
        "pan": "10-character Permanent Account Number",
        "name": "card holder's name",
        "father_name": "father's name, or null",
        "dob": "date of birth as printed",
    },
    DocumentType.AADHAAR: {
        "name": "holder's name in English",
        "dob": "date of birth as printed, or null",
        "year_of_birth": "year of birth if only the year is printed, else null",
        "gender": "male, female or transgender",
        "aadhaar_last4": "ONLY the last 4 digits of the masked Aadhaar number",
        "address": "full address from the back side, or null",
        "pincode": "6-digit PIN code, or null",
    },
    DocumentType.GST_CERTIFICATE: {
        "gstin": "15-character GSTIN / registration number",
        "legal_name": "legal name",
        "trade_name": "trade name, or null",
        "constitution_of_business": "constitution of business, as printed",
        "address": "address of principal place of business",
        "date_of_liability": "date of liability as printed",
        "validity_from": "date of validity 'from' as printed",
        "type_of_registration": "type of registration",
    },
    DocumentType.GSTR_3B: {
        "gstin": "GSTIN",
        "legal_name": "legal name of the registered person",
        "financial_year": "financial year, e.g. 2025-26",
        "periods": (
            "list, one object per return period shown: {\"period\": \"YYYY-MM\", \"taxable_outward_value\": "
            "total taxable value in table 3.1 row (a), \"igst\", \"cgst\", \"sgst\", \"cess\": the tax amounts "
            "printed on that same row}"
        ),
    },
    DocumentType.ITR: {
        "pan": "PAN",
        "name": "name of the assessee",
        "assessment_year": "assessment year, e.g. 2025-26",
        "form_type": "ITR form, e.g. ITR-4",
        "acknowledgement_number": "15-digit acknowledgement number",
        "filing_date": "date of filing as printed",
        "gross_total_income": "gross total income as printed",
        "total_income": "total income as printed",
        "tax_payable": "tax payable as printed",
        "business_turnover": "gross turnover / gross receipts if printed, else null",
    },
    DocumentType.BANK_STATEMENT: {
        "account_holder_name": "account holder name",
        "bank_name": "bank name",
        "ifsc": "IFSC code",
        "account_number_last4": "ONLY the last 4 digits of the account number",
        "period_from": "statement period start date as printed",
        "period_to": "statement period end date as printed",
        "opening_balance": "opening balance as printed",
        "closing_balance": "closing balance as printed",
    },
}

TRANSACTIONS = (
    "list of every transaction row in the order shown: {\"date\", \"narration\", \"ref\", \"debit\", "
    "\"credit\", \"balance\"} copied as printed (null for an empty cell). Do not add opening, closing "
    "or total rows"
)

_EXTRA = {
    DocumentType.AADHAAR: "The Aadhaar number is masked; never return more than its last 4 digits.",
    DocumentType.BANK_STATEMENT: "Never return a full account number.",
}

_TITLE = {
    DocumentType.PAN_CARD: "Indian PAN card",
    DocumentType.AADHAAR: "Indian Aadhaar card (number masked)",
    DocumentType.GST_CERTIFICATE: "GST registration certificate (Form GST REG-06)",
    DocumentType.GSTR_3B: "GSTR-3B monthly GST return",
    DocumentType.ITR: "Indian income tax return / ITR-V acknowledgement",
    DocumentType.BANK_STATEMENT: "Indian bank account statement",
}

MAX_TEXT_CHARS = 6000  # keeps a text-only request well under the free tier's 8K tokens/minute


def build_prompt(document_type: DocumentType, *, with_transactions: bool = False, text: str | None = None) -> str:
    fields = dict(FIELDS[document_type])
    if with_transactions:
        fields["transactions"] = TRANSACTIONS
    keys = "\n".join(f'- "{k}": {v}' for k, v in fields.items())
    source = "the attached page image(s)" if text is None else "the document text below"
    prompt = f"Read {source} of a synthetic sample {_TITLE[document_type]}. Return a JSON object with exactly these keys:\n{keys}\n{_RULES}"
    if extra := _EXTRA.get(document_type):
        prompt += f" {extra}"
    if text is not None:
        prompt += f"\n\nDocument text:\n<<<\n{text[:MAX_TEXT_CHARS]}\n>>>"
    return prompt
