"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ApplyPanel } from "../../../../components/msme/ApplyPanel";
import { useMsme } from "../../../../components/msme/MsmeProvider";
import { ErrorNote, PageHeader } from "../../../../components/msme/ui";
import { api } from "../../../../lib/api";
import { inr } from "../../../../lib/format";
import type { OfferEstimate } from "../../../../lib/types";

export default function OfferPage() {
  const router = useRouter();
  const { id } = useParams<{ id: string }>();
  const { assessment, request, ready } = useMsme();
  const [offer, setOffer] = useState<OfferEstimate | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [which, setWhich] = useState(0);

  useEffect(() => {
    if (ready && !assessment) router.replace("/msme/upload");
  }, [ready, assessment, router]);

  useEffect(() => {
    if (!ready) return;
    api
      .offer(id, request.amount, request.tenure_months)
      .then(setOffer)
      .catch((e: Error) => setError(e.message));
  }, [ready, id, request.amount, request.tenure_months]);

  if (!offer) return <ErrorNote error={error} />;
  const s = offer.scenarios[Math.min(which, offer.scenarios.length - 1)];

  const rows: { label: string; value: string; note?: string; strong?: boolean }[] = [
    { label: "Loan amount", value: inr(offer.amount) },
    { label: "You receive in your account", value: inr(s.net_disbursed), note: "after processing fee and GST", strong: true },
    { label: "Monthly EMI", value: inr(s.emi), note: `for ${offer.tenure_months} months`, strong: true },
    { label: "Total you repay", value: inr(s.total_amount_payable), note: "all EMIs added up" },
    { label: "Total cost of the loan", value: inr(s.total_cost_of_credit), note: "interest + fees + GST" },
    { label: "Interest", value: inr(s.total_interest) },
    { label: "Processing fee", value: inr(s.processing_fee) },
    { label: "GST on processing fee", value: inr(s.gst_on_processing_fee) }
  ];

  return (
    <>
      <PageHeader eyebrow="Step 6 of 6 · Key Fact Statement" title={`${offer.lender}: ${offer.product}`}>
        The full cost of this loan in plain numbers, before you apply.
      </PageHeader>

      {offer.scenarios.length > 1 && (
        <div className="segmented fade-in" role="group" aria-label="Rate scenario">
          {offer.scenarios.map((sc, i) => (
            <button key={sc.label} type="button" className={i === which ? "on" : ""} onClick={() => setWhich(i)}>
              {sc.label === "best_case" ? "Best case" : "Worst case"} · {sc.interest_rate_pct_pa}%
            </button>
          ))}
        </div>
      )}

      <section className="kfs-grid">
        <div className="panel apr-card fade-in">
          <p className="eyebrow">True APR</p>
          <p className="apr-big">{s.apr_pct.toFixed(2)}%</p>
          <p className="muted">
            The {offer.rate_basis === "interest_rate" ? "interest rate" : "quoted rate"} is {s.interest_rate_pct_pa}%. Fees
            are taken from the loan upfront, so you actually pay {s.apr_pct.toFixed(2)}% a year on the money you receive.
          </p>
        </div>
        <div className="panel fade-in">
          <dl className="kfs-list">
            {rows.map((r) => (
              <div key={r.label} className={r.strong ? "strong" : undefined}>
                <dt>
                  {r.label}
                  {r.note && <span className="muted small"> · {r.note}</span>}
                </dt>
                <dd>{r.value}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      <ApplyPanel productId={offer.product_id} lender={offer.lender} />

      <section className="panel fade-in">
        <h2 className="section-title">Your right to cancel</h2>
        <p>{offer.cooling_off}</p>
        {offer.notes.length > 0 && (
          <ul className="note-list">
            {offer.notes.map((n) => (
              <li key={n} className="muted small">
                {n}
              </li>
            ))}
          </ul>
        )}
      </section>

      <details className="panel schedule fade-in">
        <summary>Repayment schedule ({s.schedule.length} months)</summary>
        <table>
          <thead>
            <tr>
              <th>Month</th>
              <th>EMI</th>
              <th>Principal</th>
              <th>Interest</th>
              <th>Still owed</th>
            </tr>
          </thead>
          <tbody>
            {s.schedule.map((row) => (
              <tr key={row.month}>
                <td>{row.month}</td>
                <td>{inr(row.emi)}</td>
                <td>{inr(row.principal)}</td>
                <td>{inr(row.interest)}</td>
                <td>{inr(row.balance)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>

      <footer className="page-actions">
        <Link href="/msme/matches" className="link-button">
          ← All lenders
        </Link>
        <span className="muted small">
          {offer.indicative_only ? "Indicative figures from published rates. " : ""}The lender&apos;s own KFS is binding.
        </span>
      </footer>
    </>
  );
}
