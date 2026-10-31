"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api } from "../../lib/api";
import { APPLICATION_STATUS } from "../../lib/format";
import type { ApplicationSummary } from "../../lib/types";
import { useMsme } from "./MsmeProvider";

/** Apply to one lender product with explicit consent; shows the status once applied. */
export function ApplyPanel({ productId, lender }: { productId: string; lender: string }) {
  const { assessBody, request } = useMsme();
  const [existing, setExisting] = useState<ApplicationSummary | null>(null);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!assessBody) return;
    api
      .applications({ sme_id: assessBody.sme_id })
      .then((apps) => setExisting(apps.find((a) => a.product_id === productId) ?? null))
      .catch(() => setExisting(null));
  }, [assessBody, productId]);

  if (!assessBody) return null;

  if (existing) {
    const status = APPLICATION_STATUS[existing.status];
    return (
      <section className="panel apply-panel applied fade-in">
        <div>
          <p className="eyebrow">Application {existing.id}</p>
          <h2>
            Sent to {lender} <span className={`pill pill-${status.tone}`}>{status.label}</span>
          </h2>
          {existing.decision_message && <p>{existing.decision_message}</p>}
        </div>
        <Link href="/msme/applications" className="btn">
          Track your applications <span aria-hidden="true">→</span>
        </Link>
      </section>
    );
  }

  const apply = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.apply({
        ...assessBody,
        request: { sme_id: assessBody.sme_id, ...request },
        product_id: productId,
        consent_accepted: true
      });
      const apps = await api.applications({ sme_id: assessBody.sme_id });
      setExisting(apps.find((a) => a.product_id === productId) ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel apply-panel fade-in">
      <div>
        <p className="eyebrow">Apply</p>
        <h2>Send your verified file to {lender}</h2>
        <p className="muted">
          One application: no new paperwork. {lender} gets your checked documents and scores, and makes the final credit
          decision.
        </p>
        <label className="consent">
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
          <span>
            I agree to share my verified business profile, the documents I uploaded, and the checks run on them with{" "}
            {lender} for this loan application. I can withdraw this consent at any time.
          </span>
        </label>
        {error && <p className="form-error">{error}</p>}
      </div>
      <button type="button" className="btn btn-solid" disabled={!consent || busy} onClick={apply}>
        {busy ? "Sending…" : `Apply to ${lender}`} <span aria-hidden="true">→</span>
      </button>
    </section>
  );
}
