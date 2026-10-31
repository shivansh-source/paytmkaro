"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { DocumentCard } from "../../../../components/DocumentCard";
import { useLender } from "../../../../components/lender/LenderShell";
import { CheckIcon, ErrorNote, PageHeader } from "../../../../components/msme/ui";
import { api } from "../../../../lib/api";
import { APPLICATION_STATUS, DECLINE_REASONS, documentName, formatDateTime, inr, pct } from "../../../../lib/format";
import type { Application, DeclineReason, OfferEstimate, Profile, RuleCheck, Sourced } from "../../../../lib/types";

const OUTCOME: Record<RuleCheck["outcome"], "pass" | "warn" | "fail"> = { pass: "pass", warn: "warn", fail: "fail", missing: "fail" };
const DECIDABLE = new Set(["submitted", "in_review", "info_requested"]);

/** Link a profile value to the document card (and field, when the evidence names one) it came from. */
function Evidence({ profile, value }: { profile: Profile; value: Sourced<unknown> | null | undefined }) {
  const ref = value?.evidence[0];
  if (!ref) return null;
  const doc = profile.documents.find((d) => d.document_id === ref.document_id);
  const field = ref.field.split(".")[1];
  const anchor = field && !["transactions", "months"].includes(field) ? `field-${ref.document_id}-${field}` : `doc-${ref.document_id}`;
  return (
    <a href={`#${anchor}`} className="evidence-link">
      {doc ? documentName(doc.document_type) : "source"} ↗
    </a>
  );
}

function DecisionPanel({ app, onDone }: { app: Application; onDone: (a: Application) => void }) {
  const [mode, setMode] = useState<"approve" | "info" | "decline" | null>(null);
  const [reason, setReason] = useState<DeclineReason | "">("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (app.decision && !DECIDABLE.has(app.status)) {
    return (
      <div className="panel decision-panel decided">
        <p className="eyebrow">Your decision</p>
        <h3>{APPLICATION_STATUS[app.status].label}</h3>
        {app.decision.note && <p className="muted">Note: {app.decision.note}</p>}
        <p className="muted small">The business sees:</p>
        <blockquote>{app.decision.message_for_msme}</blockquote>
      </div>
    );
  }

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const body =
        mode === "approve"
          ? { action: "approve_in_principle" as const, note: note || undefined }
          : mode === "info"
            ? { action: "request_info" as const, note }
            : { action: "decline" as const, reason: reason as DeclineReason, note: note || undefined };
      onDone(await api.decide(app.id, body));
      setMode(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel decision-panel">
      <p className="eyebrow">Your decision</p>
      {app.status === "info_requested" && app.decision && <p className="muted small">You asked: {app.decision.note}</p>}
      <div className="decision-buttons">
        <button type="button" className={`btn btn-solid${mode === "approve" ? " active" : ""}`} onClick={() => setMode("approve")}>
          Approve in principle
        </button>
        <button type="button" className={`btn${mode === "info" ? " active" : ""}`} onClick={() => setMode("info")}>
          Ask for more information
        </button>
        <button type="button" className={`btn btn-decline${mode === "decline" ? " active" : ""}`} onClick={() => setMode("decline")}>
          Decline
        </button>
      </div>

      {mode && (
        <div className="decision-form fade-in">
          {mode === "decline" && (
            <label>
              Reason (required: the business sees it)
              <select value={reason} onChange={(e) => setReason(e.target.value as DeclineReason)}>
                <option value="">Choose a reason</option>
                {DECLINE_REASONS.map((r) => (
                  <option key={r.value} value={r.value}>
                    {r.label}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label>
            {mode === "info" ? "What do you need? (required)" : "Note to the business (optional)"}
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={3}
              placeholder={mode === "info" ? "e.g. Original bank statement downloaded from net banking" : ""}
            />
          </label>
          {error && <p className="form-error">{error}</p>}
          <div className="decision-actions">
            <button
              type="button"
              className="btn btn-solid"
              disabled={busy || (mode === "decline" && !reason) || (mode === "info" && !note.trim())}
              onClick={submit}
            >
              {mode === "approve" ? "Confirm approval" : mode === "info" ? "Send request" : "Confirm decline"}
            </button>
            <button type="button" className="link-button" onClick={() => setMode(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default function ApplicationPage() {
  const { id } = useParams<{ id: string }>();
  const lender = useLender();
  const [app, setApp] = useState<Application | null>(null);
  const [offer, setOffer] = useState<OfferEstimate | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .application(id)
      .then(async (loaded) => {
        // Opening a new application moves it to "in review".
        const current = loaded.status === "submitted" ? await api.decide(loaded.id, { action: "start_review" }) : loaded;
        setApp(current);
        const offerEstimate = await api.offer(current.product_id, current.request.amount, current.request.tenure_months ?? 24);
        setOffer(offerEstimate);
      })
      .catch((e: Error) => setError(e.message));
  }, [id]);

  if (!app) return <ErrorNote error={error} />;
  if (app.lender !== lender.organisation) {
    return <p className="form-error">This application was sent to {app.lender}, not {lender.organisation}.</p>;
  }

  const { profile } = app;
  const identity = profile.identity;
  const cash = profile.cashflow;
  const readiness = profile.readiness;
  const status = APPLICATION_STATUS[app.status];
  const flagged = profile.cross_checks.filter((c) => c.status !== "pass");
  const best = offer?.scenarios[0];
  // What this loan would do to the applicant's repayment burden.
  const foirAfter =
    best && cash.existing_emi_monthly && cash.avg_monthly_credits?.value
      ? (cash.existing_emi_monthly.value + best.emi) / cash.avg_monthly_credits.value
      : null;
  const name = identity.trade_name?.value ?? identity.legal_name?.value ?? profile.sme_id;

  const metrics: { label: string; value: string; source: Sourced<unknown> | null | undefined }[] = [
    { label: "GST turnover, 12 months", value: inr(cash.gst_turnover_12m?.value), source: cash.gst_turnover_12m },
    { label: "Average monthly balance", value: inr(cash.avg_monthly_balance?.value), source: cash.avg_monthly_balance },
    { label: "Average monthly credits", value: inr(cash.avg_monthly_credits?.value), source: cash.avg_monthly_credits },
    { label: "Existing EMIs / month", value: inr(cash.existing_emi_monthly?.value), source: cash.existing_emi_monthly },
    { label: "FOIR", value: pct(cash.foir?.value), source: cash.foir },
    { label: "Bounces, last 6 months", value: String(cash.bounces_6m?.value ?? "–"), source: cash.bounces_6m },
    { label: "GST vs bank credits", value: pct(cash.gst_vs_bank_ratio?.value), source: cash.gst_vs_bank_ratio },
    {
      label: "Business vintage",
      value: identity.business_vintage_months ? `${identity.business_vintage_months.value} months` : "–",
      source: identity.business_vintage_months
    }
  ];

  const identityRows: [string, Sourced<unknown> | null | undefined, string?][] = [
    ["Legal name", identity.legal_name],
    ["Trade name", identity.trade_name],
    ["Business type", identity.constitution],
    ["PAN", identity.pan],
    ["GSTIN", identity.gstin],
    ["Udyam", identity.udyam_number],
    ["MSME category", identity.msme_category],
    ["Address", identity.address, identity.address?.value ? (identity.address.value as { text: string }).text : undefined]
  ];

  return (
    <>
      <Link href="/lender" className="link-button back-link">
        ← All applications
      </Link>
      <PageHeader eyebrow={`${app.id} · ${app.product}`} title={name}>
        Asking for <strong>{inr(app.request.amount)}</strong> over {app.request.tenure_months} months
        {app.request.purpose ? ` for ${app.request.purpose.toLowerCase()}` : ""}. Submitted {formatDateTime(app.submitted_at)}.{" "}
        <span className={`pill pill-${status.tone}`}>{status.label}</span>
      </PageHeader>
      <ErrorNote error={error} />

      <section className="lender-top">
        <div className="panel verdict fade-in">
          <div className="verdict-score">
            <span className={`score-chip big band-${readiness?.band}`}>{readiness?.score ?? "–"}</span>
            <div>
              <strong>Readiness {readiness?.score}/100</strong>
              <p className="muted small">Computed by CreditSetu from the documents below, by fixed rules.</p>
            </div>
          </div>
          {flagged.length === 0 ? (
            <p className="flag ok">✓ Every cross-document check passed</p>
          ) : (
            <ul className="check-list">
              {flagged.map((c) => (
                <li key={c.id}>
                  <CheckIcon status={c.status} />
                  {c.message}
                </li>
              ))}
            </ul>
          )}
        </div>
        <DecisionPanel app={app} onDone={setApp} />
      </section>

      <section className="two-col">
        <div className="panel fade-in">
          <h2 className="section-title">Cash flow, with sources</h2>
          <dl className="metric-grid">
            {metrics.map((m) => (
              <div key={m.label}>
                <dt>{m.label}</dt>
                <dd>{m.value}</dd>
                <Evidence profile={profile} value={m.source} />
              </div>
            ))}
          </dl>
          <p className="muted small">Bureau score: {profile.bureau ? `${profile.bureau.value} (${profile.bureau.source.replace("_", " ")})` : "not provided"}</p>
        </div>
        <div className="panel fade-in">
          <h2 className="section-title">Against your criteria</h2>
          <ul className="check-list">
            {app.match.checks.map((c) => (
              <li key={c.rule}>
                <CheckIcon status={OUTCOME[c.outcome]} />
                {c.message}
              </li>
            ))}
          </ul>
          {best && (
            <div className="offer-strip">
              <div>
                <span className="big">{inr(best.emi)}</span>
                <span className="muted small">EMI at {best.interest_rate_pct_pa}%</span>
              </div>
              <div>
                <span className="big">{best.apr_pct.toFixed(2)}%</span>
                <span className="muted small">true APR incl. fees</span>
              </div>
              <div>
                <span className="big">{pct(foirAfter)}</span>
                <span className="muted small">FOIR after this loan</span>
              </div>
            </div>
          )}
        </div>
      </section>

      <section className="panel fade-in">
        <h2 className="section-title">Identity</h2>
        <dl className="identity-grid">
          {identityRows.map(([label, value, text]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{text ?? (value ? String(value.value).replace(/_/g, " ") : "–")}</dd>
              <Evidence profile={profile} value={value} />
            </div>
          ))}
        </dl>
      </section>

      <h2 className="section-title spaced">Documents and evidence</h2>
      <section className="review-grid">
        {app.documents.map((doc) => (
          <DocumentCard key={doc.document_id} doc={doc} />
        ))}
      </section>

      <section className="two-col spaced-top">
        <div className="panel">
          <h2 className="section-title">Consent</h2>
          <p className="small">{app.consent.text}</p>
          <p className="muted small">Given {formatDateTime(app.consent.accepted_at)}</p>
        </div>
        <div className="panel">
          <h2 className="section-title">History</h2>
          <ol className="timeline">
            {app.history.map((e, i) => (
              <li key={i}>
                <span className="muted small">{formatDateTime(e.at)}</span>
                <span>
                  {e.actor === "msme" ? "Business" : e.actor === "lender" ? "You" : "System"}: {e.action.replace(/_/g, " ")}
                  {e.note ? ` (${e.note})` : ""}
                </span>
              </li>
            ))}
          </ol>
        </div>
      </section>
    </>
  );
}
