"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { useLender } from "../../components/lender/LenderShell";
import { ErrorNote, PageHeader } from "../../components/msme/ui";
import { api } from "../../lib/api";
import { APPLICATION_STATUS, formatDateTime, inr, inrShort } from "../../lib/format";
import type { ApplicationSummary } from "../../lib/types";

const FILTERS = [
  { key: "all", label: "All", test: () => true },
  { key: "new", label: "New", test: (a: ApplicationSummary) => a.status === "submitted" },
  { key: "review", label: "In review", test: (a: ApplicationSummary) => a.status === "in_review" || a.status === "info_requested" },
  { key: "decided", label: "Decided", test: (a: ApplicationSummary) => a.status === "approved_in_principle" || a.status === "declined" }
] as const;

const FIT = { strong: "Strong fit", good: "Good fit", just_qualifies: "Just qualifies" };

function Flags({ app }: { app: ApplicationSummary }) {
  if (!app.red_flags && !app.warnings) return <span className="flag ok">✓ All checks passed</span>;
  return (
    <span className="flags">
      {app.red_flags > 0 && <span className="flag bad">✗ {app.red_flags} red flag{app.red_flags > 1 ? "s" : ""}</span>}
      {app.warnings > 0 && <span className="flag warn">⚠ {app.warnings} to check</span>}
    </span>
  );
}

export default function InboxPage() {
  const lender = useLender();
  const [apps, setApps] = useState<ApplicationSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["key"]>("all");

  useEffect(() => {
    api
      .applications({ lender: lender.organisation })
      .then(setApps)
      .catch((e: Error) => setError(e.message));
  }, [lender.organisation]);

  const shown = apps?.filter(FILTERS.find((f) => f.key === filter)!.test) ?? [];
  const count = (key: (typeof FILTERS)[number]["key"]) => apps?.filter(FILTERS.find((f) => f.key === key)!.test).length ?? 0;

  return (
    <>
      <PageHeader eyebrow={lender.organisation} title="Applications">
        Every file here was verified by CreditSetu before it reached you: documents read, cross-checked and scored, with
        each number linked to the document it came from.
      </PageHeader>
      <ErrorNote error={error} />

      {apps && (
        <>
          <section className="stat-row fade-in">
            <div>
              <span className="stat-big">{count("new")}</span>
              <span className="muted small">new</span>
            </div>
            <div>
              <span className="stat-big">{count("review")}</span>
              <span className="muted small">in review</span>
            </div>
            <div>
              <span className="stat-big">{count("decided")}</span>
              <span className="muted small">decided</span>
            </div>
            <div>
              <span className="stat-big">{inrShort(apps.reduce((sum, a) => sum + a.amount, 0))}</span>
              <span className="muted small">requested in total</span>
            </div>
          </section>

          <div className="segmented fade-in" role="tablist" aria-label="Filter applications">
            {FILTERS.map((f) => (
              <button key={f.key} type="button" role="tab" aria-selected={filter === f.key} className={filter === f.key ? "on" : ""} onClick={() => setFilter(f.key)}>
                {f.label} · {count(f.key)}
              </button>
            ))}
          </div>

          {shown.length === 0 ? (
            <p className="muted empty">No applications here yet.</p>
          ) : (
            <section className="inbox">
              {shown.map((a, i) => {
                const status = APPLICATION_STATUS[a.status];
                return (
                  <Link key={a.id} href={`/lender/applications/${a.id}`} className="panel inbox-row fade-in" style={{ animationDelay: `${i * 40}ms` }}>
                    <div className="inbox-main">
                      <strong>{a.business_name}</strong>
                      <span className="muted small">
                        {a.id} · {a.product} · {formatDateTime(a.submitted_at)}
                      </span>
                      <Flags app={a} />
                    </div>
                    <div className="inbox-cell">
                      <span>{inr(a.amount)}</span>
                      <span className="muted small">{a.tenure_months} months</span>
                    </div>
                    <div className="inbox-cell">
                      <span className={`score-chip band-${a.readiness_band}`}>{a.readiness_score ?? "–"}</span>
                      <span className="muted small">readiness</span>
                    </div>
                    <div className="inbox-cell">
                      <span>{a.fit_label ? FIT[a.fit_label] : "–"}</span>
                      <span className="muted small">{a.true_apr_pct?.toFixed(1)}% true APR</span>
                    </div>
                    <div className="inbox-cell end">
                      <span className={`pill pill-${status.tone}`}>{status.label}</span>
                      <span className="open">Open →</span>
                    </div>
                  </Link>
                );
              })}
            </section>
          )}
        </>
      )}
      {!apps && !error && <p className="muted">Loading applications…</p>}
    </>
  );
}
