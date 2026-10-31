"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useMsme } from "../../../components/msme/MsmeProvider";
import { ErrorNote, PageHeader } from "../../../components/msme/ui";
import { inr, inrShort } from "../../../lib/format";
import type { Fix, MatchResult, SortOrder } from "../../../lib/types";

const FIT_LABEL = { strong: "Strong fit", good: "Good fit", just_qualifies: "Just qualifies" };
const FIX_ICON: Record<Fix["kind"], string> = {
  change_request: "↺",
  wait: "◷",
  improve: "↗",
  add_document: "＋",
  add_info: "＋",
  not_eligible: "—"
};
const TENURES = [12, 18, 24, 36, 48, 60];

function LenderCard({ match, onApply, busy }: { match: MatchResult; onApply: (amount: number) => void; busy: boolean }) {
  const matched = match.status === "matched";
  return (
    <article className={`panel lender-card fade-in ${matched ? "is-matched" : "is-not-yet"}`}>
      <header className="lender-head">
        <div>
          <h3>{match.lender}</h3>
          <p className="muted small">
            {match.product}
            {match.scheme && match.scheme !== "none" ? ` · ${match.scheme}` : ""}
          </p>
        </div>
        <span className={`pill ${matched ? "pill-ok" : "pill-wait"}`}>{matched ? "Matched" : match.quick_fix ? "Quick fix" : "Not yet"}</span>
      </header>

      <div className="lender-numbers">
        <div>
          <span className="big">{match.true_apr_pct?.toFixed(1)}%</span>
          <span className="muted small">true APR, fees included</span>
        </div>
        <div>
          <span>
            {match.apr_range[0]}–{match.apr_range[1]}%
          </span>
          <span className="muted small">lender&apos;s APR range</span>
        </div>
        <div>
          <span>{match.processing_fee_pct}%</span>
          <span className="muted small">processing fee</span>
        </div>
        {match.fit_label && (
          <div>
            <span className={`fit fit-${match.fit_label}`}>{FIT_LABEL[match.fit_label]}</span>
            <span className="muted small">how comfortably you qualify</span>
          </div>
        )}
      </div>

      {!matched && (
        <div className="fixes">
          <strong>{match.quick_fix ? "One change and you match:" : "What to change:"}</strong>
          <ul>
            {match.fixes.map((fix) => (
              <li key={fix.rule} className={`fix fix-${fix.kind}`}>
                <span className="fix-icon" aria-hidden="true">
                  {FIX_ICON[fix.kind]}
                </span>
                <span>{fix.message}</span>
                {fix.kind === "change_request" && fix.rule === "ticket_size" && typeof fix.target === "number" && (
                  <button type="button" className="btn btn-small" disabled={busy} onClick={() => onApply(fix.target as number)}>
                    Apply
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      <footer className="lender-foot">
        <details>
          <summary>Why {matched ? "you match" : "not yet"}</summary>
          <ul className="reason-list">
            {match.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </details>
        {matched && (
          <Link href={`/msme/offer/${match.product_id}`} className="btn btn-solid btn-small">
            See the offer <span aria-hidden="true">→</span>
          </Link>
        )}
      </footer>
    </article>
  );
}

export default function MatchesPage() {
  const router = useRouter();
  const { assessment, matches, request, sort, refreshMatches, busy, error, ready } = useMsme();
  const [amount, setAmount] = useState(String(request.amount));
  const [tenure, setTenure] = useState(request.tenure_months);

  useEffect(() => {
    if (ready && !assessment) router.replace("/msme/upload");
  }, [ready, assessment, router]);

  // First visit: match with the saved request.
  useEffect(() => {
    if (ready && assessment && !matches && !busy && !error) refreshMatches();
  }, [ready, assessment, matches, busy, error, refreshMatches]);

  if (!assessment) return null;

  const submit = (nextAmount = Number(amount), nextSort: SortOrder = sort) => {
    if (!nextAmount || nextAmount <= 0) return;
    setAmount(String(nextAmount));
    refreshMatches({ request: { ...request, amount: nextAmount, tenure_months: tenure }, sort: nextSort });
  };

  const matched = matches?.filter((m) => m.status === "matched") ?? [];
  const notYet = matches?.filter((m) => m.status === "not_yet") ?? [];

  return (
    <>
      <PageHeader eyebrow="Step 5 of 6" title="Lenders for your business">
        We checked your verified file against every lender&apos;s rules. You see all of them: the ones you match, and
        exactly what to change for the rest.
      </PageHeader>

      <form
        className="panel request-bar fade-in"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <label>
          Loan amount
          <div className="money-input">
            <span>₹</span>
            <input value={amount} onChange={(e) => setAmount(e.target.value.replace(/\D/g, ""))} inputMode="numeric" />
          </div>
          <span className="muted small">{Number(amount) > 0 ? inrShort(Number(amount)) : ""}</span>
        </label>
        <label>
          Tenure
          <select value={tenure} onChange={(e) => setTenure(Number(e.target.value))}>
            {TENURES.map((t) => (
              <option key={t} value={t}>
                {t} months
              </option>
            ))}
          </select>
        </label>
        <button type="submit" className="btn btn-solid" disabled={busy}>
          Update matches
        </button>
      </form>
      <ErrorNote error={error} />

      {matches && (
        <>
          <div className="sort-bar fade-in">
            <span className="muted">
              {matched.length} matched · {notYet.length} not yet · sorted by{" "}
              {sort === "cost" ? "lowest true APR (fees included)" : "how comfortably you qualify"}
            </span>
            <div className="segmented" role="group" aria-label="Sort lenders">
              {(["cost", "fit"] as SortOrder[]).map((s) => (
                <button key={s} type="button" className={sort === s ? "on" : ""} disabled={busy} onClick={() => submit(Number(amount), s)}>
                  {s === "cost" ? "Lowest cost" : "Best fit"}
                </button>
              ))}
            </div>
          </div>

          <section className="lender-list">
            {matched.map((m) => (
              <LenderCard key={m.product_id} match={m} busy={busy} onApply={(a) => submit(a)} />
            ))}
          </section>

          {notYet.length > 0 && (
            <>
              <h2 className="section-title spaced">Not yet: here&apos;s the path</h2>
              <section className="lender-list">
                {notYet.map((m) => (
                  <LenderCard key={m.product_id} match={m} busy={busy} onApply={(a) => submit(a)} />
                ))}
              </section>
            </>
          )}

          <p className="muted small disclaimer">
            The lender makes the final credit decision. Figures are indicative and computed from published rates; the
            lender&apos;s Key Fact Statement is binding. Requested: {inr(request.amount)} for {request.tenure_months} months.
          </p>
        </>
      )}
      {!matches && busy && <p className="muted">Matching…</p>}
    </>
  );
}
