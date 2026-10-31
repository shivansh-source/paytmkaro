import { CheckIcon, StatusPill } from "./msme/ui";
import { FIELD_LABEL, SOURCE_LABEL, documentName, formatDate, formatField, inr, monthLabel } from "../lib/format";
import type { Envelope, Extracted, Transaction } from "../lib/types";

function isExtracted(value: unknown): value is Extracted {
  return typeof value === "object" && value !== null && "confidence" in value && "source" in value;
}

/** Rows the balance-math check flagged, with what the balance should have been. */
function brokenRows(doc: Envelope) {
  const check = doc.checks.find((c) => c.id === "bank.balance_math" && c.status !== "pass");
  if (!check || !doc.data) return [];
  const txns = doc.data.transactions as Transaction[];
  const opening = (doc.data.opening_balance as Extracted<number> | null | undefined)?.value ?? null;
  // Same rule as the backend: a row with no printed balance carries the running total forward.
  const runningBefore = (i: number) => {
    let running: number | null = opening;
    for (let j = 0; j < i; j++) {
      const t = txns[j];
      running = t.balance ?? (running === null ? null : running + t.credit - t.debit);
    }
    return running;
  };
  return check.fields
    .map((f) => Number(f.split(".").pop()))
    .filter((i) => Number.isInteger(i))
    .flatMap((i) => {
      const previous = runningBefore(i);
      return previous === null ? [] : [{ row: txns[i], expected: previous + txns[i].credit - txns[i].debit }];
    });
}

/** One checked document: checks, flagged rows, extracted fields with confidence.
 * Pass `onConfirm` for the MSME (confirm low-confidence fields); omit it for the read-only lender view.
 * Anchors: #doc-{id} on the card, #field-{id}-{name} on each field, for evidence links. */
export function DocumentCard({ doc, onConfirm, busy = false }: { doc: Envelope; onConfirm?: (field: string) => void; busy?: boolean }) {
  const fields = Object.entries(doc.data ?? {}).filter(([, v]) => isExtracted(v)) as [string, Extracted][];
  const txns = (doc.data?.transactions as Transaction[] | undefined) ?? null;
  const months = (doc.data?.months as { period?: string; month?: string }[] | undefined) ?? null;
  const monthNames = months?.map((m) => m.period ?? m.month).filter((m): m is string => Boolean(m)) ?? [];
  const broken = brokenRows(doc);

  return (
    <article className="panel review-card fade-in" id={`doc-${doc.document_id}`}>
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
              statement shows {row.balance === null ? "no balance" : inr(row.balance)}.
            </p>
          ))}
        </div>
      )}

      <table className="field-table">
        <tbody>
          {fields.map(([name, field]) => (
            <tr key={name} id={`field-${doc.document_id}-${name}`} className={field.needs_review ? "needs-review" : undefined}>
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
                  <span className="muted small">Confirmed{onConfirm ? "" : " by applicant"}</span>
                ) : field.needs_review && onConfirm ? (
                  <button type="button" className="btn btn-small" disabled={busy} onClick={() => onConfirm(name)}>
                    Confirm
                  </button>
                ) : field.needs_review ? (
                  <span className="muted small">Unconfirmed</span>
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
      {months && <p className="muted small">{months.length} monthly records: {monthNames.map(monthLabel).join(", ")}</p>}
    </article>
  );
}
