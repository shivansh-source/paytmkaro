"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useMsme } from "../../../components/msme/MsmeProvider";
import { CheckIcon, ErrorNote, PageHeader, StatusPill } from "../../../components/msme/ui";
import { FIELD_LABEL, SOURCE_LABEL, documentName, formatDate, formatField, inr, monthLabel } from "../../../lib/format";
import type { Assessment, Check, Envelope, Extracted, Transaction } from "../../../lib/types";

// Which field holds the person's name on each document, for confirming a near-match.
const NAME_FIELD: Partial<Record<Envelope["document_type"], string>> = {
  aadhaar: "name",
  gst_registration: "legal_name",
  bank_statement: "account_holder_name"
};

/** Name fields that differ from the PAN name: what "Yes, same person" confirms. */
function differingNames(check: Check, assessment: Assessment) {
  const pan = assessment.documents.find((d) => d.document_type === "pan_card");
  const reference = (pan?.data?.name as Extracted<string> | undefined)?.value?.toUpperCase().trim();
  return assessment.documents.flatMap((doc) => {
    const field = NAME_FIELD[doc.document_type];
    const value = field ? (doc.data?.[field] as Extracted<string> | undefined)?.value : null;
    return field && check.document_ids.includes(doc.document_id) && value && value.toUpperCase().trim() !== reference
      ? [{ documentId: doc.document_id, field }]
      : [];
  });
}

function isExtracted(value: unknown): value is Extracted {
  return typeof value === "object" && value !== null && "confidence" in value && "source" in value;
}

/** Rows the balance-math check flagged, with what the balance should have been. */
function brokenRows(doc: Envelope) {
  const check = doc.checks.find((c) => c.id === "bank.balance_math" && c.status !== "pass");
  if (!check || !doc.data) return [];
  const txns = doc.data.transactions as Transaction[];
  const opening = (doc.data.opening_balance as Extracted<number>).value ?? 0;
  return check.fields
    .map((f) => Number(f.split(".").pop()))
    .filter((i) => Number.isInteger(i))
    .map((i) => {
      const previous = i === 0 ? opening : txns[i - 1].balance;
      return { row: txns[i], expected: previous + txns[i].credit - txns[i].debit };
    });
}

function DocumentCard({ doc, onConfirm, busy }: { doc: Envelope; onConfirm: (field: string) => void; busy: boolean }) {
  const fields = Object.entries(doc.data ?? {}).filter(([, v]) => isExtracted(v)) as [string, Extracted][];
  const txns = (doc.data?.transactions as Transaction[] | undefined) ?? null;
  const months = (doc.data?.months as { period: string }[] | undefined) ?? null;
  const broken = brokenRows(doc);

  return (
    <article className="panel review-card fade-in">
      <header className="review-head">
        <div>
          <h3>{documentName(doc.document_type)}</h3>
          <p className="muted small">
            {doc.file.file_name}
            {doc.triage && ` · ${SOURCE_LABEL[doc.triage.extractor] ?? doc.triage.extractor}`}
            {doc.triage?.fell_back_to_vlm && " (fell back to AI vision)"}
          </p>
        </div>
        <StatusPill status={doc.status} />
      </header>

      <ul className="check-list">
        {doc.checks.map((c) => (
          <li key={c.id}>
            <CheckIcon status={c.status} />
            {c.message}
          </li>
        ))}
      </ul>

      {broken.length > 0 && (
        <div className="tamper-box">
          <strong>Rows that don&apos;t add up</strong>
          {broken.map(({ row, expected }) => (
            <p key={row.date + row.narration}>
              {formatDate(row.date)} · {row.narration}: credit {inr(row.credit)}. The balance should be {inr(expected)}, the
              statement shows {inr(row.balance)}.
            </p>
          ))}
        </div>
      )}

      <table className="field-table">
        <tbody>
          {fields.map(([name, field]) => (
            <tr key={name} className={field.needs_review ? "needs-review" : undefined}>
              <th>{FIELD_LABEL[name] ?? name}</th>
              <td>{formatField(name, field.value)}</td>
              <td className="confidence">
                <span className="bar">
                  <i style={{ width: `${Math.round(field.confidence * 100)}%` }} />
                </span>
                {Math.round(field.confidence * 100)}%
              </td>
              <td className="confirm-cell">
                {field.user_confirmed ? (
                  <span className="muted small">Confirmed</span>
                ) : field.needs_review ? (
                  <button type="button" className="btn btn-small" disabled={busy} onClick={() => onConfirm(name)}>
                    Confirm
                  </button>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {txns && (
        <p className="muted small">
          {txns.length} transactions read · {txns.filter((t) => t.tags.includes("bounce")).length} bounces ·{" "}
          {txns.filter((t) => t.tags.includes("emi")).length} EMI debits
        </p>
      )}
      {months && <p className="muted small">{months.length} monthly returns: {months.map((m) => monthLabel(m.period)).join(", ")}</p>}
    </article>
  );
}

export default function ReviewPage() {
  const router = useRouter();
  const { assessment, confirmField, confirmFields, busy, error, ready } = useMsme();

  useEffect(() => {
    if (ready && !assessment) router.replace("/msme/upload");
  }, [ready, assessment, router]);
  if (!assessment) return null;

  const cross = assessment.profile.cross_checks;
  const problems = cross.filter((c) => c.status !== "pass").length;

  return (
    <>
      <PageHeader eyebrow="Step 2 of 5" title="What we checked">
        {problems === 0
          ? "Every document is consistent with the others. Nothing for you to fix here."
          : `${problems} thing${problems > 1 ? "s" : ""} need your attention before lenders see your file.`}
      </PageHeader>
      <ErrorNote error={error} />

      <section className="panel fade-in">
        <h2 className="section-title">Across your documents</h2>
        <ul className="check-list large">
          {cross.map((c) => (
            <li key={c.id}>
              <CheckIcon status={c.status} />
              <span className="grow">{c.message}</span>
              {c.id === "cross.name_match" && c.status === "warn" && (
                <button type="button" className="btn btn-small" disabled={busy} onClick={() => confirmFields(differingNames(c, assessment))}>
                  Yes, same person
                </button>
              )}
            </li>
          ))}
        </ul>
      </section>

      <section className="review-grid">
        {assessment.documents.map((doc) => (
          <DocumentCard key={doc.document_id} doc={doc} busy={busy} onConfirm={(field) => confirmField(doc.document_id, field)} />
        ))}
      </section>

      <footer className="page-actions">
        <Link href="/msme/upload" className="link-button">
          ← Documents
        </Link>
        <Link href="/msme/readiness" className="btn btn-solid">
          See your readiness score <span aria-hidden="true">→</span>
        </Link>
      </footer>
    </>
  );
}
