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
    DocumentType.BUREAU_REPORT: {
        "bureau_name": "CIBIL, Experian, Equifax or CRIF",
        "report_date": "report date as printed",
        "pan_masked": "PAN with all but the last 4 characters replaced by X",
        "score": "credit score exactly as printed; write NH if the report says no history (never 0)",
        "score_type": "name of the score, e.g. CIBIL Score 3.0",
        "cmr_rank": "Commercial Credit Risk rank 1-10 (1 is best), only on commercial reports, else null",
        "active_accounts": "number of active accounts",
        "total_outstanding": "total outstanding as printed",
        "overdue_amount": "total overdue as printed",
        "max_dpd_24m": "maximum days past due in the last 24 months",
        "written_off_or_settled": "yes or no: any written-off or settled account",
        "suit_filed_or_wilful_default": "yes or no",
        "enquiries_90d": "enquiries in the last 90 days",
        "accounts": (
            "list, one object per account: {\"lender\", \"account_type\", \"status\", \"account_last4\": last 4 digits only, "
            "\"sanctioned\", \"outstanding\", \"emi\", \"dpd_summary\"}. Never include phone numbers, street addresses or full account numbers"
        ),
    },
    DocumentType.UDYAM_CERTIFICATE: {
        "udyam_number": "Udyam registration number, UDYAM-XX-00-0000000",
        "enterprise_name": "name of the enterprise",
        "pan": "PAN if printed, else null",
        "enterprise_type": "micro, small or medium",
        "organisation_type": "type of organisation as printed",
        "date_of_incorporation": "date of incorporation as printed",
        "date_of_commencement": "date of commencement as printed",
        "registration_date": "date of Udyam registration as printed",
        "nic_codes": "list of {\"code\": NIC code digits, \"description\"}",
        "major_activity": "manufacturing, services or trading",
        "address": "official address of the enterprise",
        "state": "state",
        "pincode": "6-digit PIN code",
    },
    DocumentType.FINANCIAL_STATEMENTS: {
        "unit": "the unit the amounts are stated in, as printed (e.g. 'Rs. in lakhs', 'in Crores'); do NOT convert any amount",
        "audit_status": "audited, ca_certified or provisional",
        "financial_year": "latest year, e.g. 2025-26",
        "prior_financial_year": "previous year, e.g. 2024-25",
        "auditor_name": "signing auditor, or null",
        "auditor_firm": "audit firm, or null",
        "udin": "UDIN as printed, or null",
        "<amount>": (
            "for each of revenue (revenue from operations), other_income, total_expenses, depreciation, interest_expense, "
            "profit_before_tax, profit_after_tax, total_assets, current_assets, current_liabilities, total_liabilities, "
            "total_equity_and_liabilities, net_worth, long_term_borrowings, short_term_borrowings, trade_receivables, "
            "trade_payables, inventory, cash: the latest-year amount exactly as printed under the key, and the previous-year "
            "amount under the key prefixed 'prior_' (e.g. revenue and prior_revenue); null if not printed"
        ),
    },
    DocumentType.SANCTION_LETTER: {
        "lender_name": "name of the lender",
        "facility_type": "term loan, overdraft, cash credit, working capital or other",
        "sanctioned_amount": "sanctioned amount as printed",
        "interest_rate_pct": "interest rate per annum as printed, number only",
        "rate_type": "fixed or floating",
        "apr_pct": "APR if printed, else null",
        "tenure_months": "tenure in months",
        "emi_amount": "EMI as printed, else null",
        "processing_fee": "processing fee amount if printed in rupees, else null",
        "processing_fee_pct": "processing fee percentage if printed, else null",
        "security": "security / collateral as printed",
        "fd_lien_or_margin": "yes if secured by a fixed-deposit lien or 100% margin, else no",
        "sanction_date": "date of sanction as printed",
        "validity_date": "validity date as printed",
        "cooling_off_days": "cooling-off period in days",
    },
    DocumentType.SETTLEMENT_REPORT: {
        "provider": "payment provider or aggregator name",
        "merchant_id_last4": "ONLY the last 4 digits of the merchant id",
        "period_from": "report period start as printed",
        "period_to": "report period end as printed",
        "settlements": (
            "list, one object per settlement: {\"date\", \"gross_amount\", \"fees\" (total fees/MDR/tax deducted), "
            "\"net_settled\", \"txn_count\", \"mode\"}. Never include customer names, UPI IDs, phone numbers or card numbers"
        ),
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
    DocumentType.BUREAU_REPORT: "Never return a phone number, a street address or a full account number.",
    DocumentType.SETTLEMENT_REPORT: "Never return personal data of the merchant's customers.",
}

_TITLE = {
    DocumentType.PAN_CARD: "Indian PAN card",
    DocumentType.AADHAAR: "Indian Aadhaar card (number masked)",
    DocumentType.GST_CERTIFICATE: "GST registration certificate (Form GST REG-06)",
    DocumentType.GSTR_3B: "GSTR-3B monthly GST return",
    DocumentType.ITR: "Indian income tax return / ITR-V acknowledgement",
    DocumentType.BANK_STATEMENT: "Indian bank account statement",
    DocumentType.BUREAU_REPORT: "credit bureau report (consumer or commercial)",
    DocumentType.UDYAM_CERTIFICATE: "Udyam registration certificate",
    DocumentType.FINANCIAL_STATEMENTS: "set of financial statements (profit and loss, balance sheet)",
    DocumentType.SANCTION_LETTER: "loan sanction letter",
    DocumentType.SETTLEMENT_REPORT: "merchant payment settlement report",
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
