// Mirrors of the backend contracts the dashboard reads (schemas/v1/msme, recommendation, offers).
// Only the fields the UI uses; the JSON Schemas in /schemas are the full reference.

export type DocumentType = "pan_card" | "aadhaar" | "gst_registration" | "gstr3b" | "bank_statement" | "udyam" | "itr_v";
export type CheckStatus = "pass" | "warn" | "fail";
export type DocumentStatus = "queued" | "extracting" | "needs_review" | "verified" | "failed";

export interface Check {
  id: string;
  status: CheckStatus;
  message: string;
  document_ids: string[];
  fields: string[];
  expected?: string | null;
  actual?: string | null;
}

export interface BBox {
  page: number;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export interface Extracted<T = unknown> {
  value: T | null;
  confidence: number;
  source: string;
  bbox?: BBox | null;
  raw_text?: string | null;
  user_confirmed: boolean;
  needs_review?: boolean;
}

export interface Transaction {
  date: string;
  narration: string;
  debit: number;
  credit: number;
  balance: number;
  tags: string[];
}

export interface Envelope {
  document_id: string;
  sme_id: string;
  document_type: DocumentType;
  status: DocumentStatus;
  uploaded_at: string;
  file: { file_name: string; mime_type: string; size_bytes: number; pages?: number | null; sha256: string };
  triage?: { input_kind: "digital_pdf" | "scanned_pdf" | "photo"; extractor: string; fell_back_to_vlm: boolean } | null;
  data: ({ document_type: DocumentType } & Record<string, unknown>) | null;
  checks: Check[];
  error?: string | null;
}

export interface Sourced<T> {
  value: T;
  evidence: { document_id: string; field: string }[];
}

export interface Address {
  text: string;
  city?: string | null;
  state?: string | null;
  pincode?: string | null;
}

export interface Profile {
  sme_id: string;
  identity: {
    legal_name?: Sourced<string> | null;
    trade_name?: Sourced<string> | null;
    constitution?: Sourced<string> | null;
    pan?: Sourced<string> | null;
    gstin?: Sourced<string> | null;
    udyam_number?: Sourced<string> | null;
    msme_category?: Sourced<string> | null;
    business_vintage_months?: Sourced<number> | null;
    address?: Sourced<Address> | null;
    sector?: string | null;
  };
  cashflow: {
    months_analyzed: number;
    avg_monthly_balance?: Sourced<number> | null;
    avg_monthly_credits?: Sourced<number> | null;
    bounces_6m?: Sourced<number> | null;
    existing_emi_monthly?: Sourced<number> | null;
    foir?: Sourced<number> | null;
    gst_turnover_12m?: Sourced<number> | null;
    gst_vs_bank_ratio?: Sourced<number> | null;
  };
  bureau?: { value: number; source: "mock" | "self_declared" | "bureau" } | null;
  documents: { document_id: string; document_type: DocumentType; status: DocumentStatus }[];
  cross_checks: Check[];
  readiness?: {
    score: number;
    band: "not_ready" | "almost_ready" | "ready";
    components: { name: string; points: number; max_points: number; note?: string | null }[];
  } | null;
  fix_it: {
    id: string;
    priority: "high" | "medium" | "low";
    title: string;
    detail?: string | null;
    action: "upload" | "re_upload" | "confirm_field" | "add_info";
    document_type?: DocumentType | null;
  }[];
}

export interface Assessment {
  profile: Profile;
  documents: Envelope[];
}

export interface AssessBody {
  sme_id: string;
  documents: Envelope[];
  bureau?: { value: number; source: string } | null;
  sector?: string | null;
  as_of?: string | null;
}

export interface SampleApplicant extends AssessBody {
  label: string;
}

export interface LoanRequest {
  sme_id: string;
  amount: number;
  tenure_months: number;
  purpose?: string;
}

export type FixKind = "change_request" | "wait" | "improve" | "add_document" | "add_info" | "not_eligible";

export interface Fix {
  rule: string;
  kind: FixKind;
  message: string;
  months?: number | null;
  target?: unknown;
}

export interface MatchResult {
  product_id: string;
  lender: string;
  product: string;
  status: "matched" | "not_yet";
  fit_score: number | null;
  fit_label: "strong" | "good" | "just_qualifies" | null;
  apr_range: [number, number];
  true_apr_pct: number | null;
  processing_fee_pct: number;
  scheme: string | null;
  reasons: string[];
  fixes: Fix[];
  quick_fix: boolean;
}

export type SortOrder = "cost" | "fit";

export interface Installment {
  month: number;
  emi: number;
  principal: number;
  interest: number;
  balance: number;
}

export interface OfferScenario {
  label: "best_case" | "worst_case";
  interest_rate_pct_pa: number;
  emi: number;
  total_interest: number;
  processing_fee: number;
  gst_on_processing_fee: number;
  net_disbursed: number;
  total_amount_payable: number;
  total_cost_of_credit: number;
  apr_pct: number;
  schedule: Installment[];
}

export interface OfferEstimate {
  product_id: string;
  lender: string;
  product: string;
  amount: number;
  tenure_months: number;
  tenure_adjusted: boolean;
  within_ticket_size: boolean;
  rate_basis: "interest_rate" | "apr_proxy";
  indicative_only: boolean;
  scenarios: OfferScenario[];
  cooling_off: string;
  notes: string[];
}
