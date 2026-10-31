import type { DocumentType } from "./types";

const rupees = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });

/** ₹15,00,000: Indian digit grouping, no paise. */
export const inr = (amount: number | null | undefined) => (amount == null ? "–" : rupees.format(amount));

/** 1500000 -> "₹15 lakh", 25000000 -> "₹2.5 crore": for headline numbers. */
export function inrShort(amount: number): string {
  if (amount >= 1e7) return `₹${+(amount / 1e7).toFixed(2)} crore`;
  if (amount >= 1e5) return `₹${+(amount / 1e5).toFixed(2)} lakh`;
  return inr(amount);
}

export const pct = (ratio: number | null | undefined, digits = 0) => (ratio == null ? "–" : `${(ratio * 100).toFixed(digits)}%`);

/** "2026-07" -> "Jul 2026" */
export function monthLabel(month: string): string {
  const [y, m] = month.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString("en-IN", { month: "short", year: "numeric" });
}

export function formatDate(iso: string): string {
  const d = new Date(iso + (iso.length === 10 ? "T00:00:00" : ""));
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

export const DOCUMENTS: { type: DocumentType; name: string; why: string; how: string; optional?: boolean }[] = [
  { type: "pan_card", name: "PAN card", why: "Identity, and the anchor for every cross-check", how: "Phone photo" },
  { type: "aadhaar", name: "Aadhaar", why: "Name, date of birth, address. Only the last 4 digits are kept", how: "Phone photo" },
  { type: "gst_registration", name: "GST registration (REG-06)", why: "Business identity: GSTIN, legal name, address", how: "PDF" },
  { type: "gstr3b", name: "GSTR-3B returns", why: "Declared turnover, last 6 months", how: "PDF" },
  { type: "bank_statement", name: "Bank statement", why: "Real cash flow: balances, bounces, EMIs", how: "PDF, last 6-12 months" },
  { type: "udyam", name: "Udyam certificate", why: "Confirms MSME status and category", how: "PDF or photo" },
  { type: "itr_v", name: "ITR-V", why: "Declared income, for lenders that ask for it", how: "PDF", optional: true },
  { type: "bureau_report", name: "Credit bureau report", why: "Uploaded score and credit history; lender verifies independently", how: "PDF", optional: true },
  { type: "financial_statements", name: "Financial statements", why: "Revenue, profit and balance sheet", how: "PDF, XLSX or DOCX", optional: true },
  { type: "sanction_letter", name: "Loan sanction letter", why: "Existing facilities and repayment terms", how: "PDF or DOCX", optional: true },
  { type: "settlement_report", name: "Payment settlement report", why: "Payment aggregator collections and fees", how: "CSV, XLSX or PDF", optional: true }
];

export const documentName = (type: DocumentType) => DOCUMENTS.find((d) => d.type === type)?.name ?? type;

export const SOURCE_LABEL: Record<string, string> = {
  parser: "read from the PDF text",
  ocr: "read by OCR",
  vlm: "read by AI vision",
  user: "confirmed by you",
  system: "computed"
};

export const FIELD_LABEL: Record<string, string> = {
  pan_number: "PAN",
  name: "Name",
  father_name: "Father's name",
  dob: "Date of birth",
  year_of_birth: "Year of birth",
  aadhaar_last4: "Aadhaar (last 4)",
  gender: "Gender",
  address: "Address",
  gstin: "GSTIN",
  legal_name: "Legal name",
  trade_name: "Trade name",
  constitution: "Business type",
  registration_date: "Registered on",
  principal_address: "Business address",
  account_holder_name: "Account holder",
  account_number_last4: "Account (last 4)",
  ifsc: "IFSC",
  bank_name: "Bank",
  period_from: "From",
  period_to: "To",
  opening_balance: "Opening balance",
  closing_balance: "Closing balance",
  udyam_number: "Udyam number",
  enterprise_name: "Enterprise",
  enterprise_type: "MSME category",
  major_activity: "Activity",
  date_of_incorporation: "Incorporated on",
  date_of_registration: "Udyam registered on",
  assessment_year: "Assessment year",
  itr_form: "ITR form",
  gross_total_income: "Gross total income",
  acknowledgement_number: "Acknowledgement no.",
  filing_date: "Filed on",
  bureau_name: "Credit bureau",
  report_date: "Report date",
  score: "Consumer credit score",
  cmr_rank: "Commercial CMR rank",
  active_accounts: "Active credit accounts",
  total_outstanding: "Total outstanding",
  overdue_amount: "Overdue amount",
  max_dpd_24m: "Maximum DPD (24 months)",
  written_off_or_settled: "Written off or settled",
  suit_filed_or_wilful_default: "Suit filed or wilful default",
  enquiries_90d: "Credit enquiries (90 days)",
  financial_year: "Financial year",
  prior_financial_year: "Previous financial year",
  audit_status: "Statement status",
  revenue: "Revenue",
  prior_revenue: "Previous year revenue",
  profit_after_tax: "Profit after tax",
  net_margin: "Net margin",
  total_assets: "Total assets",
  total_liabilities: "Total liabilities",
  total_equity_and_liabilities: "Equity and liabilities",
  net_worth: "Net worth",
  long_term_borrowings: "Long-term borrowings",
  short_term_borrowings: "Short-term borrowings",
  debt_to_equity: "Debt-to-equity ratio",
  ebitda: "EBITDA",
  depreciation: "Depreciation",
  interest_expense: "Interest expense",
  principal_repayments: "Principal repayments",
  dscr: "Debt service coverage ratio",
  facility_type: "Facility type",
  sanctioned_amount: "Sanctioned amount",
  sanction_date: "Sanction date",
  interest_rate_pct: "Interest rate",
  rate_type: "Rate type",
  tenure_months: "Tenure",
  emi_amount: "Monthly EMI",
  fd_lien_or_margin: "Fixed deposit lien or margin",
  security: "Security / collateral",
  provider: "Payment provider",
  merchant_id_last4: "Merchant ID (last 4)",
  total_gross: "Total gross settlements",
  total_fees: "Total fees",
  total_net: "Total net settlements"
};

const MONEY_FIELDS = new Set([
  "opening_balance", "closing_balance", "gross_total_income", "total_outstanding", "overdue_amount",
  "revenue", "prior_revenue", "profit_after_tax", "total_assets", "total_liabilities",
  "total_equity_and_liabilities", "net_worth", "long_term_borrowings", "short_term_borrowings", "ebitda",
  "depreciation", "interest_expense", "principal_repayments", "sanctioned_amount", "emi_amount",
  "total_gross", "total_fees", "total_net"
]);
const DATE_FIELDS = new Set([
  "dob", "registration_date", "period_from", "period_to", "date_of_incorporation", "date_of_registration",
  "filing_date", "report_date", "sanction_date"
]);
const PERCENT_FIELDS = new Set(["net_margin", "interest_rate_pct"]);
const RATIO_FIELDS = new Set(["debt_to_equity", "dscr"]);

export function formatField(name: string, value: unknown): string {
  if (value == null) return "Not read";
  if (typeof value === "object" && value !== null && "text" in value) return String((value as { text: string }).text);
  if (MONEY_FIELDS.has(name) && typeof value === "number") return inr(value);
  if (DATE_FIELDS.has(name) && typeof value === "string") return formatDate(value);
  if (PERCENT_FIELDS.has(name) && typeof value === "number") return `${new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(value)}%`;
  if (RATIO_FIELDS.has(name) && typeof value === "number") return `${new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(value)}×`;
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (name === "aadhaar_last4" || name === "account_number_last4") return `XXXX XXXX ${value}`;
  return String(value).replace(/_/g, " ");
}

export const APPLICATION_STATUS: Record<string, { label: string; tone: "ok" | "warn" | "bad" | "neutral" }> = {
  submitted: { label: "New", tone: "warn" },
  in_review: { label: "In review", tone: "neutral" },
  approved_in_principle: { label: "Approved in principle", tone: "ok" },
  info_requested: { label: "Info requested", tone: "warn" },
  declined: { label: "Not yet", tone: "bad" },
  withdrawn: { label: "Withdrawn", tone: "neutral" }
};

export const DECLINE_REASONS: { value: string; label: string }[] = [
  { value: "vintage", label: "Business too new" },
  { value: "turnover", label: "Turnover too low" },
  { value: "cash_flow", label: "EMIs or bounces too high" },
  { value: "credit_history", label: "Credit history" },
  { value: "documents", label: "Documents need fixing" },
  { value: "policy", label: "Outside current policy" },
  { value: "other", label: "Other (explain in note)" }
];

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
}
