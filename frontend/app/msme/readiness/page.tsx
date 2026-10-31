"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useMsme } from "../../../components/msme/MsmeProvider";
import { ScoreDial } from "../../../components/msme/ScoreDial";
import { PageHeader } from "../../../components/msme/ui";
import { documentName, inr, pct } from "../../../lib/format";
import type { DocumentType, Profile, Sourced } from "../../../lib/types";

const BAND = {
  ready: { label: "Lender-ready", text: "Your file is complete and consistent. Lenders can decide on it quickly." },
  almost_ready: { label: "Almost ready", text: "A few fixes will open up more lenders and better terms." },
  not_ready: { label: "Not ready yet", text: "Fix the high-priority items first. Each one is specific and doable." }
};

function evidenceLabel(profile: Profile, sourced: Sourced<unknown> | null | undefined) {
  const id = sourced?.evidence[0]?.document_id;
  const type = profile.documents.find((d) => d.document_id === id)?.document_type;
  return type ? `from your ${documentName(type as DocumentType).toLowerCase()}` : "";
}

export default function ReadinessPage() {
  const router = useRouter();
  const { assessment, ready } = useMsme();

  useEffect(() => {
    if (ready && !assessment) router.replace("/msme/upload");
  }, [ready, assessment, router]);
  if (!assessment?.profile.readiness) return null;

  const { profile } = assessment;
  const readiness = profile.readiness!;
  const band = BAND[readiness.band];
  const cash = profile.cashflow;
  const vintage = profile.identity.business_vintage_months;

  const metrics = [
    { label: "Average monthly balance", value: inr(cash.avg_monthly_balance?.value), source: cash.avg_monthly_balance },
    { label: "Average monthly credits", value: inr(cash.avg_monthly_credits?.value), source: cash.avg_monthly_credits },
    { label: "Existing EMIs / month", value: inr(cash.existing_emi_monthly?.value), source: cash.existing_emi_monthly },
    { label: "FOIR (EMIs ÷ income)", value: pct(cash.foir?.value), source: cash.foir },
    { label: "Bounces, last 6 months", value: String(cash.bounces_6m?.value ?? "–"), source: cash.bounces_6m },
    { label: "GST turnover, 12 months", value: inr(cash.gst_turnover_12m?.value), source: cash.gst_turnover_12m },
    { label: "GST vs bank credits", value: pct(cash.gst_vs_bank_ratio?.value), source: cash.gst_vs_bank_ratio },
    { label: "Business vintage", value: vintage ? `${vintage.value} months` : "–", source: vintage }
  ];

  return (
    <>
      <PageHeader eyebrow="Step 4 of 6" title="Your credit-readiness score" />

      <section className={`panel score-hero band-${readiness.band} fade-in`}>
        <ScoreDial score={readiness.score} />
        <div className="score-copy">
          <p className="eyebrow">{band.label}</p>
          <h2>{band.text}</h2>
          <ul className="components">
            {readiness.components.map((c) => (
              <li key={c.name}>
                <div className="component-row">
                  <span>{c.name}</span>
                  <span className="muted">
                    {+c.points.toFixed(1)} / {c.max_points}
                  </span>
                </div>
                <span className="bar wide">
                  <i style={{ width: `${(c.points / c.max_points) * 100}%` }} />
                </span>
                {c.note && <span className="muted small">{c.note}</span>}
              </li>
            ))}
          </ul>
          <p className="muted small">Computed from your documents by fixed rules, never guessed by AI.</p>
        </div>
      </section>

      <section className="two-col">
        <div className="panel fade-in">
          <h2 className="section-title">Fix-it checklist</h2>
          {profile.fix_it.length === 0 ? (
            <p className="muted">Nothing to fix.</p>
          ) : (
            <ol className="fix-list">
              {profile.fix_it.map((item) => (
                <li key={item.id} className={`priority-${item.priority}`}>
                  <span className={`pill pill-${item.priority === "high" ? "bad" : item.priority === "medium" ? "warn" : "neutral"}`}>
                    {item.priority}
                  </span>
                  <div>
                    <strong>{item.title}</strong>
                    {item.detail && item.detail !== item.title && <p className="muted small">{item.detail}</p>}
                  </div>
                </li>
              ))}
            </ol>
          )}
        </div>
        <div className="panel fade-in">
          <h2 className="section-title">Your cash flow, as lenders see it</h2>
          <dl className="metric-grid">
            {metrics.map((m) => (
              <div key={m.label}>
                <dt>{m.label}</dt>
                <dd>{m.value}</dd>
                <span className="muted small">{evidenceLabel(profile, m.source)}</span>
              </div>
            ))}
          </dl>
        </div>
      </section>

      <footer className="page-actions">
        <Link href="/msme/review" className="link-button">
          ← Checks
        </Link>
        <Link href="/msme/matches" className="btn btn-solid">
          See lender matches <span aria-hidden="true">→</span>
        </Link>
      </footer>
    </>
  );
}
