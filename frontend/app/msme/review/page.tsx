"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useMsme } from "../../../components/msme/MsmeProvider";
import { DocumentCard } from "../../../components/DocumentCard";
import { CheckIcon, ErrorNote, PageHeader } from "../../../components/msme/ui";
import type { Assessment, Check, Envelope, Extracted } from "../../../lib/types";

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
      <PageHeader eyebrow="Step 3 of 6" title="What we checked">
        {problems === 0
          ? "Every document is consistent with the others. Nothing for you to fix here."
          : `${problems} thing${problems > 1 ? "s" : ""} need${problems > 1 ? "" : "s"} your attention before lenders see your file.`}
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
