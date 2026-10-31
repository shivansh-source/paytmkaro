"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { useMsme } from "../../../components/msme/MsmeProvider";
import { ErrorNote, PageHeader } from "../../../components/msme/ui";
import { api } from "../../../lib/api";
import { APPLICATION_STATUS, formatDateTime, inr } from "../../../lib/format";
import type { ApplicationSummary } from "../../../lib/types";

export default function ApplicationsPage() {
  const { assessBody, ready } = useMsme();
  const [apps, setApps] = useState<ApplicationSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ready || !assessBody) return;
    api
      .applications({ sme_id: assessBody.sme_id })
      .then(setApps)
      .catch((e: Error) => setError(e.message));
  }, [ready, assessBody]);

  return (
    <>
      <PageHeader eyebrow="Your applications" title="Where your file is">
        Every lender you applied to, and what they decided. A &ldquo;not yet&rdquo; always comes with a reason.
      </PageHeader>
      <ErrorNote error={error} />

      {apps?.length === 0 && (
        <p className="muted">
          No applications yet. Pick a lender on the <Link href="/msme/matches">matches</Link> page and apply from its offer.
        </p>
      )}
      <section className="lender-list">
        {apps?.map((a) => {
          const status = APPLICATION_STATUS[a.status];
          return (
            <article key={a.id} className={`panel status-card status-${a.status} fade-in`}>
              <header className="lender-head">
                <div>
                  <h3>{a.lender}</h3>
                  <p className="muted small">
                    {a.product} · {inr(a.amount)} for {a.tenure_months} months · {a.id} · sent {formatDateTime(a.submitted_at)}
                  </p>
                </div>
                <span className={`pill pill-${status.tone}`}>{status.label}</span>
              </header>
              <p className="status-message">
                {a.decision_message ??
                  (a.status === "in_review" ? `${a.lender} is reviewing your file.` : `${a.lender} has received your file.`)}
              </p>
              {a.status === "declined" && (
                <Link href="/msme/matches" className="btn btn-small">
                  See what to change <span aria-hidden="true">→</span>
                </Link>
              )}
            </article>
          );
        })}
      </section>
    </>
  );
}
