import type { CheckStatus, DocumentStatus } from "../../lib/types";

const ICON: Record<CheckStatus, string> = { pass: "✓", warn: "⚠", fail: "✗" };

export function CheckIcon({ status }: { status: CheckStatus }) {
  return (
    <span className={`check-icon ${status}`} aria-label={status}>
      {ICON[status]}
    </span>
  );
}

const DOC_STATUS: Record<DocumentStatus | "missing", { label: string; tone: string }> = {
  verified: { label: "Verified", tone: "ok" },
  needs_review: { label: "Needs review", tone: "warn" },
  failed: { label: "Couldn't read", tone: "bad" },
  queued: { label: "Queued", tone: "neutral" },
  extracting: { label: "Reading…", tone: "neutral" },
  missing: { label: "Not uploaded", tone: "neutral" }
};

export function StatusPill({ status }: { status: keyof typeof DOC_STATUS }) {
  const { label, tone } = DOC_STATUS[status];
  return <span className={`pill pill-${tone}`}>{label}</span>;
}

export function PageHeader({ eyebrow, title, children }: { eyebrow: string; title: string; children?: React.ReactNode }) {
  return (
    <header className="page-header fade-in">
      <p className="eyebrow">{eyebrow}</p>
      <h1>{title}</h1>
      {children && <div className="page-lede">{children}</div>}
    </header>
  );
}

export function ErrorNote({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      Something went wrong talking to the server: {error}. Is the backend running on port 8000?
    </p>
  );
}
