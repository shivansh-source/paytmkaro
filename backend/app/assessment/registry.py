"""The parameter registry: one declarative entry per assessment parameter, 51 in all.

To add a parameter: add ONE `Parameter(...)` line here (with a small pure function from features.py when it
can be computed today) and its weight and bands to config.json under the same id. tests/assessment fails
if the registry and the config disagree, so a parameter can never be half-added.

A parameter with `feature=None` is PENDING BY SCHEMA: no field in SmeProfile / DocumentEnvelope carries what
it needs. It still appears in every ScoreCard, with `waits_for` naming the exact field or document, and its
column stays null in the feature table. `applies` may return a reason to mark it NOT APPLICABLE for a given
business (excluded from the weight base).

Categories follow the structure of an internal lender reference scorecard (51 parameters, 11 of which could
not be computed from documents there either); sources, thresholds and names are adapted to India.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.assessment import features as f
from app.assessment.features import Context, FeatureFn
from app.schemas.common import DocumentType

CP, SP, BC, FN, RB, DI = (
    "Company profile",
    "Promoter profile",
    "Banking conduct and exposure",
    "Financial strength",
    "Risk, bureau and disclosure",
    "Data integrity",
)
CATEGORIES = (CP, SP, BC, FN, RB, DI)

EQUITY_REVIEW = (
    "Structural attribute: may disadvantage small or informal businesses. Lender must document why it is "
    "a risk factor, and review its effect on outcomes across business sizes."
)


@dataclass(frozen=True)
class Parameter:
    id: str
    name: str
    category: str
    documents: str  # India source documents, for the design table
    field_path: str  # where the input lives; "(proposed)" marks a field that does not exist yet
    formula: str  # one line: how the value is derived
    feature: FeatureFn | None = None  # None: pending by schema
    waits_for: str | None = None  # pending by schema: the exact missing field or document
    pending_reason: str | None = None
    applies: Callable[[Context], str | None] | None = None  # returns a reason when NOT applicable
    critical: bool = False  # a zero here caps the grade (explicit rule, shown on the card)
    in_total: bool = True  # False: outside the weight base (see DESIGN.md)
    uses_bank: bool = False  # derived from the bank statement (flagged if it fails reconciliation)
    review_flag: str | None = None  # fairness note: needs human review

    @property
    def computable(self) -> bool:
        return self.feature is not None


def _trading_only(ctx: Context) -> str | None:
    udyam = ctx.docs.get(DocumentType.UDYAM)
    if udyam is not None and udyam.data.major_activity.value not in (None, "trading"):
        return f"Warehouse proof is only needed for trading businesses; this one is {udyam.data.major_activity.value}."
    return None


def _pending(id, name, category, documents, field_path, formula, waits_for, why, **kw) -> Parameter:
    return Parameter(id, name, category, documents, field_path, formula, None, waits_for, why, **kw)


REGISTRY: tuple[Parameter, ...] = (
    # ---- Company profile ----
    Parameter("cp.vintage", "Business vintage", CP, "Udyam certificate, GST registration", "SmeProfile.identity.business_vintage_months",
              "months from Udyam incorporation (else GST registration) to as_of", f.vintage_months),
    Parameter("cp.constitution", "Constitution", CP, "GST registration, PAN, Certificate of Incorporation", "SmeProfile.identity.constitution",
              "category lookup", f.constitution, review_flag=EQUITY_REVIEW),
    Parameter("cp.msme_category", "Udyam category", CP, "Udyam certificate", "SmeProfile.identity.msme_category",
              "category lookup", f.msme_category, review_flag=EQUITY_REVIEW),
    Parameter("cp.udyam_registration", "Udyam registration", CP, "Udyam certificate", "DocumentEnvelope[udyam].data.udyam_number",
              "present and matches UDYAM-XX-00-0000000", f.udyam_registration),
    Parameter("cp.gst_registration_tenure", "GST registration tenure", CP, "GST REG-06 certificate", "DocumentEnvelope[gst_registration].data.registration_date",
              "months from registration date to as_of", f.gst_registration_tenure),
    _pending("cp.premises_proof", "Registered premises proof", CP, "Registered rent or lease agreement, utility bill", "(proposed) DocumentType rent_agreement: lease_end_date, is_registered",
             "months of lease remaining and registration status", "document rent_agreement (lease_end_date, is_registered) or utility_bill",
             "No rent or utility document type exists in the schema yet."),
    _pending("cp.operating_licence", "Operating licence", CP, "Shop and Establishment licence, Certificate of Incorporation", "(proposed) DocumentType operating_licence: valid_to",
             "licence present and unexpired at as_of", "document operating_licence (licence_type, valid_to)",
             "No licence document type exists in the schema yet."),
    _pending("cp.employee_base", "Employee base and statutory dues", CP, "EPFO ECR and ESIC returns, payroll register", "(proposed) DocumentType epfo_esic_return: employee_count, months_filed_12m",
             "employee count and share of the last 12 months with dues filed", "document epfo_esic_return (employee_count, months_filed_12m)",
             "No EPFO / ESIC document type exists in the schema yet."),
    _pending("cp.warehouse_status", "Warehouse status (owned / rented / third party)", CP, "Warehouse rent agreement or 3PL contract (trading firms only)", "(proposed) DocumentType rent_agreement with premises_type = warehouse",
             "owned = best, rented, third party; applies only when Udyam major_activity is trading", "document rent_agreement (premises_type = warehouse)",
             "No warehouse or 3PL document type exists in the schema yet.", applies=_trading_only),
    _pending("cp.sector_view", "Industry risk view", CP, "External sector view (CRISIL, ICRA, CARE research)", "(proposed) external sector rating by NIC code",
             "published sector outlook mapped to a band", "external sector-outlook feed keyed by Udyam NIC code (not borrower documents)",
             "Needs an external sector rating; no borrower document can supply it. Any sector or geography scoring needs human fairness review."),
    # ---- Promoter profile ----
    Parameter("sp.itr_filed", "Income-tax return recency", SP, "ITR-V (acknowledgement), Form 26AS / AIS", "DocumentEnvelope[itr_v].data.assessment_year",
              "years between the latest return's assessment year and the current one", f.itr_filed),
    Parameter("sp.itr_income_margin", "Income reported against turnover", SP, "ITR-V, GSTR-3B", "DocumentEnvelope[itr_v].data.gross_total_income; SmeProfile.cashflow.gst_turnover_12m",
              "gross total income / annualised GST turnover", f.itr_income_margin),
    _pending("sp.promoter_net_worth", "Promoter personal net worth", SP, "Personal net worth statement, property papers", "(proposed) DocumentType net_worth_statement: net_worth",
             "declared net worth against the facility size (good to have; depends on facility size)", "document net_worth_statement (net_worth)",
             "No net-worth statement document type exists in the schema yet."),
    # ---- Banking conduct and exposure ----
    Parameter("bc.bounces_6m", "Bounced debits (6 months)", BC, "Bank statement (Account Aggregator or PDF)", "SmeProfile.cashflow.bounces_6m",
              "count of bounce-tagged debits in the last 6 statement months", f.bounces_6m, uses_bank=True),
    Parameter("bc.foir", "Existing EMI burden (FOIR)", BC, "Bank statement", "SmeProfile.cashflow.foir",
              "average EMI of last 3 months / average monthly credits", f.foir, uses_bank=True),
    Parameter("bc.liquidity_cushion", "Balance cushion", BC, "Bank statement", "SmeProfile.cashflow.avg_monthly_balance / avg_monthly_credits",
              "average monthly balance / average monthly credits", f.liquidity_cushion, uses_bank=True),
    Parameter("bc.revenue_trend", "Bank inflow trend", BC, "Bank statement", "DocumentEnvelope[bank_statement].data.transactions[].credit",
              "mean credits of last 3 months / mean of earlier months (>= 6 months needed)", f.revenue_trend, uses_bank=True),
    Parameter("bc.credit_stability", "Inflow stability", BC, "Bank statement", "DocumentEnvelope[bank_statement].data.transactions[].credit",
              "stdev / mean of monthly credits", f.credit_stability, uses_bank=True),
    Parameter("bc.low_balance_days", "Low-balance days", BC, "Bank statement", "DocumentEnvelope[bank_statement].data.transactions[].balance",
              "share of days with end-of-day balance below one month of existing EMI", f.low_balance_days, uses_bank=True),
    Parameter("bc.cash_credit_share", "Cash share of inflow", BC, "Bank statement", "DocumentEnvelope[bank_statement].data.transactions[].tags",
              "value of cash-tagged credits / value of business credits", f.cash_credit_share, uses_bank=True,
              review_flag="High cash inflow is common in legitimate trades (mandi, kirana). Lender must confirm it is a risk signal for its book, not a penalty on informal sectors."),
    Parameter("bc.statement_depth", "Bank statement depth", BC, "Bank statement", "SmeProfile.cashflow.months_analyzed",
              "months covered by the statement", f.statement_months, uses_bank=True),
    Parameter("bc.gst_bank_consistency", "GST turnover vs bank inflow", BC, "GSTR-3B, bank statement", "SmeProfile.cashflow.gst_vs_bank_ratio",
              "GST outward value / bank credits over the months both cover", f.gst_bank_consistency, uses_bank=True),
    Parameter("bc.gst_filing_timeliness", "GST filing timeliness", BC, "GSTR-3B", "DocumentEnvelope[gstr3b].data.months[].filing_date, due_date",
              "GSTR-3B months filed on or before due date / months with both dates (>= 3)", f.gst_filing_timeliness),
    Parameter("bc.gst_turnover_trend", "GST turnover trend", BC, "GSTR-3B", "DocumentEnvelope[gstr3b].data.months[].outward_taxable_value",
              "mean of last 3 months / mean of earlier months (>= 4 months needed)", f.gst_turnover_trend),
    Parameter("bc.turnover_scale", "Annual turnover scale", BC, "GSTR-3B", "SmeProfile.cashflow.gst_turnover_12m",
              "GST outward value of the last 12 months, annualised", f.turnover_scale, review_flag=EQUITY_REVIEW),
    _pending("bc.customer_concentration", "Customer concentration", BC, "Bank statement, sales invoices", "(proposed) Transaction.counterparty_key (pseudonymous key, never a name)",
             "share of credits from the top 3 counterparties", "Transaction.counterparty_key on bank_statement.data.transactions[]",
             "Transactions carry no counterparty field; parsing names out of narrations is not done (privacy)."),
    Parameter("bc.od_utilisation", "Overdraft / cash-credit utilisation", BC, "Sanction letter, bank statement", "DocumentEnvelope[sanction_letter].data.facility_type, sanctioned_amount; DocumentEnvelope[bank_statement].data.transactions[].balance",
              "average overdrawn amount (negative end-of-day balance) / sanctioned limit; only when the statement goes negative", f.od_utilisation, uses_bank=True),
    Parameter("bc.pg_settlements", "Payment-aggregator settlements vs bank inflow", BC, "Payment aggregator / UPI merchant settlement report", "DocumentEnvelope[settlement_report].data.months[].net; SmeProfile bank credits",
              "settlement net / bank business credits over the months both cover (>= 2); a consistency check, not a digital-share score", f.pg_settlements, uses_bank=True),
    _pending("bc.macro_shock", "Macro or sector shock on pay-ins", BC, "News and sector events (analytical)", "(proposed) external shock calendar",
             "last-3-year vs last-year revenue shock check, plus a sector event list", "external shock calendar plus 3 years of revenue (financial_statements.prior_revenue)",
             "Analytical; no standalone document source."),
    Parameter("bc.margin_facility", "Overdraft secured by FD lien (margin) taken", BC, "Sanction letter (security, FD lien)", "DocumentEnvelope[sanction_letter].data.fd_lien_or_margin",
              "flag when any facility is fully cash-margined (limit sized above what the business needs)", f.margin_facility,
              review_flag="An overdraft secured by a fixed deposit is common for small firms with no other collateral. Lender must confirm it is a risk signal for its book, not a penalty on firms without property."),
    Parameter("bc.facility_trend", "Facility trend at last renewal", BC, "Sanction letters across renewals", "DocumentEnvelope[sanction_letter].data.sanctioned_amount, sanction_date",
              "increased / same / decreased between the two newest sanctions of the same facility type", f.facility_trend),
    # ---- Financial strength ----
    Parameter("fn.revenue_growth_yoy", "Revenue growth (year on year)", FN, "Audited or CA-certified financials, Form 3CD above thresholds", "DocumentEnvelope[financial_statements].data.revenue, prior_revenue",
              "revenue / prior-year revenue - 1, latest financial year (3-year version needs one more year of data)", f.revenue_growth),
    Parameter("fn.net_margin", "Net profit margin", FN, "Audited or CA-certified financials", "DocumentEnvelope[financial_statements].data.profit_after_tax, revenue",
              "profit after tax / revenue, recomputed from the components", f.net_margin,
              review_flag="Margins differ widely by trade and traders are legitimately thin. Lender should compare within sector, not across sectors."),
    Parameter("fn.leverage", "Leverage (debt to equity)", FN, "Audited or CA-certified financials", "DocumentEnvelope[financial_statements].data.long_term_borrowings, short_term_borrowings, net_worth",
              "(long + short term borrowings) / net worth; zero or negative net worth is the worst band", f.leverage),
    Parameter("fn.dscr", "Debt service coverage (DSCR)", FN, "Audited or CA-certified financials", "DocumentEnvelope[financial_statements].data.profit_after_tax, depreciation, interest_expense, principal_repayments",
              "(profit after tax + depreciation + interest) / (principal repayments + interest)", f.dscr),
    _pending("fn.unit_economics", "Unit economics (gross profit based, CLV:CAC)", FN, "P&L, bank statement, internal CRM data", "(proposed) CRM export: marketing_spend, new_customers; financial_statements gross profit",
             "gross profit x customer lifetime value : customer acquisition cost, target 3:1 or better", "internal CRM data (marketing spend, customer count) plus document financial_statements",
             "Needs CRM data the SME holds; no extractor covers it."),
    # ---- Risk, bureau and disclosure ----
    Parameter("rb.consumer_score", "Promoter bureau score", RB, "CIBIL / Experian / Equifax / CRIF consumer score (300-900)", "SmeProfile.bureau.value",
              "bureau score, 300-900", f.consumer_score),
    Parameter("rb.cmr", "CIBIL MSME Rank (CMR 1-10, 1 is best)", RB, "CIBIL commercial report (CMR)", "SmeProfile.bureau.cmr_rank, else DocumentEnvelope[bureau_report].data.cmr_rank",
              "rank 1-10; lower is better (direction opposite to the consumer score)", f.cmr_rank),
    Parameter("rb.worst_dpd_24m", "Worst days past due (24 months)", RB, "Bureau report", "SmeProfile.bureau.max_dpd_24m, else DocumentEnvelope[bureau_report].data.max_dpd_24m",
              "worst DPD across accounts in the last 24 months", f.worst_dpd_24m),
    Parameter("rb.enquiries_90d", "Credit enquiries (90 days)", RB, "Bureau report", "SmeProfile.bureau.enquiries_90d, else DocumentEnvelope[bureau_report].data.enquiries_90d",
              "count of enquiries in the last 90 days", f.enquiries_90d),
    Parameter("rb.adverse_flags", "Written-off / suit-filed / wilful-default flags", RB, "Bureau report (RBI CRILC is not accessible to us)", "SmeProfile.bureau.written_off_or_settled, suit_filed_or_wilful_default, else DocumentEnvelope[bureau_report]",
              "any flag set = worst band; both flags must be stated false for the best band", f.adverse_flags),
    _pending("rb.voluntary_disclosure", "Voluntary disclosure of concerns", RB, "Interview with the relationship manager", "(proposed) RM interview record",
             "RM view of how openly the promoter shares concerns", "RM interview record (not a document)",
             "Interview-only; no document can supply it."),
    _pending("rb.company_assets", "Business assets (value and type)", RB, "Fixed-asset register, Vahan registration for vehicles, property ownership records", "(proposed) DocumentType asset_register: total_value, registrable_share",
             "value and type of registrable and non-registrable assets", "document asset_register (total_value, registrable_share)",
             "No asset document type exists in the schema yet."),
    Parameter("rb.responsiveness", "Documentation responsiveness (turnaround)", RB, "Relationship manager timestamps", "(proposed) RM turnaround log",
              "average hours to supply a requested document", None, "RM turnaround log (not a document)",
              "Analytical, from RM timestamps. The reference scorecard leaves it out of the calculation for now, so it is outside our weight base too.", in_total=False),
    # ---- Data integrity ----
    Parameter("di.balance_math", "Bank statement reconciliation", DI, "Bank statement", "SmeProfile.cross_checks[cross.balance_math].status",
              "status of the row-by-row balance check", f.balance_math, critical=True),
    Parameter("di.statement_gaps", "Statement continuity", DI, "Bank statement, GSTR-3B", "SmeProfile.cross_checks[cross.statement_gaps].status",
              "status of the missing-months check", f.statement_gaps),
    Parameter("di.tax_registration_link", "PAN-GSTIN link", DI, "PAN card, GST registration", "SmeProfile.cross_checks[cross.pan_in_gstin].status",
              "status of the PAN-inside-GSTIN check", f.tax_registration_link, critical=True),
    Parameter("di.name_match", "Name consistency", DI, "PAN, Aadhaar, GST, bank statement", "SmeProfile.cross_checks[cross.name_match].status",
              "status of the fuzzy name check; only the status is used, never the names", f.name_agreement),
    Parameter("di.premises_agreement", "Address consistency", DI, "Aadhaar, GST, Udyam", "SmeProfile.cross_checks[cross.address_match].status",
              "status of the address check; only the status is used, never the address", f.premises_agreement),
    Parameter("di.kyc_record_match", "PAN-Aadhaar record consistency", DI, "PAN, Aadhaar", "SmeProfile.cross_checks[cross.dob_match].status",
              "status of the PAN-vs-Aadhaar record check; only the status is used, never the dates", f.kyc_record_match),
    Parameter("di.low_confidence_fields", "Extraction confidence", DI, "All uploaded documents", "DocumentEnvelope[*].data.*.needs_review",
              "extracted fields needing review / all extracted fields", f.low_confidence_fields),
)

BY_ID: dict[str, Parameter] = {p.id: p for p in REGISTRY}
assert len(BY_ID) == len(REGISTRY), "duplicate parameter id"
