"use client";

import { useEffect, useState } from "react";

import { useLender } from "../../../components/lender/LenderShell";
import { ErrorNote, PageHeader } from "../../../components/msme/ui";
import { api } from "../../../lib/api";
import { inr, pct } from "../../../lib/format";
import type { LenderProduct } from "../../../lib/types";

const yesNo = (v: boolean | null | undefined) => (v == null ? "Not stated" : v ? "Required" : "Not required");

function rows(p: LenderProduct): [string, string][] {
  return [
    ["Loan amount", p.ticket_size ? `${inr(p.ticket_size.min)} to ${inr(p.ticket_size.max)}` : "Any"],
    ["Tenure", p.tenure_months ? `${p.tenure_months.min} to ${p.tenure_months.max} months` : "Any"],
    ["Minimum business vintage", p.min_business_vintage_months != null ? `${p.min_business_vintage_months} months` : "None"],
    ["Minimum annual turnover", p.min_annual_turnover != null ? inr(p.min_annual_turnover) : "None"],
    [
      "Minimum bureau score",
      p.min_bureau_score != null
        ? `${p.min_bureau_score}${p.bureau_score_is_hard_cutoff === false ? " (soft: can still be considered)" : ""}`
        : "None"
    ],
    ["Maximum FOIR", p.max_foir != null ? pct(p.max_foir) : "None"],
    ["Maximum bounces, 6 months", p.max_bounces_6m != null ? String(p.max_bounces_6m) : "None"],
    ["GST registration", yesNo(p.gst_required)],
    ["ITR", yesNo(p.itr_required)],
    ["Udyam registration", yesNo(p.udyam_required)],
    ["Business types", p.allowed_constitutions?.map((c) => c.replace(/_/g, " ")).join(", ") ?? "Any"],
    ["Excluded sectors", p.excluded_sectors.length ? p.excluded_sectors.map((s) => s.replace(/_/g, " ")).join(", ") : "None"],
    ["Collateral", p.collateral]
  ];
}

export default function CriteriaPage() {
  const lender = useLender();
  const [products, setProducts] = useState<LenderProduct[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .lenders()
      .then((all) => setProducts(all.filter((p) => p.lender === lender.organisation)))
      .catch((e: Error) => setError(e.message));
  }, [lender.organisation]);

  return (
    <>
      <PageHeader eyebrow={lender.organisation} title="Your criteria">
        CreditSetu checks every business against these rules before sending you an application, and tells businesses
        exactly which rule they missed instead of a silent rejection.
      </PageHeader>
      <ErrorNote error={error} />

      {products?.length === 0 && <p className="muted">No products on file for {lender.organisation}.</p>}
      <section className="criteria-list">
        {products?.map((p) => (
          <article key={p.id} className="panel fade-in">
            <header className="lender-head">
              <div>
                <h3>{p.product}</h3>
                <p className="muted small">
                  {p.product_type.replace(/_/g, " ")}
                  {p.scheme && p.scheme !== "none" ? ` · ${p.scheme}` : ""} · {p.id}
                </p>
              </div>
              <span className="pill pill-neutral">{p.record_status}</span>
            </header>
            <div className="lender-numbers">
              <div>
                <span className="big">
                  {p.pricing.apr_range[0]}–{p.pricing.apr_range[1]}%
                </span>
                <span className="muted small">APR range{p.pricing.indicative_only ? ", indicative" : ""}</span>
              </div>
              <div>
                <span>{p.pricing.processing_fee_pct}%</span>
                <span className="muted small">processing fee</span>
              </div>
            </div>
            <table className="field-table criteria-table">
              <tbody>
                {rows(p).map(([label, value]) => (
                  <tr key={label}>
                    <th>{label}</th>
                    <td>{value}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted small">
              Source confidence: {p.source_confidence}. Editing criteria from this screen is coming next; today they live in
              the lender record (schemas/v1/lender).
            </p>
          </article>
        ))}
      </section>
    </>
  );
}
