"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useMsme } from "../../../components/msme/MsmeProvider";
import { ErrorNote, PageHeader, StatusPill } from "../../../components/msme/ui";
import { DOCUMENTS } from "../../../lib/format";
import type { DocumentType } from "../../../lib/types";

export default function UploadPage() {
  const router = useRouter();
  const { assessment, loadSample, busy, error, ready, questionnaire } = useMsme();
  // Personalised by the questionnaire, when answered.
  const plan = questionnaire && questionnaire !== "skipped" ? questionnaire.result.checklist : null;
  const planFor = (type: DocumentType) => plan?.find((c) => c.document_type === type);
  const [received, setReceived] = useState<Partial<Record<DocumentType, string>>>({});

  const statusOf = (type: DocumentType) => {
    const doc = assessment?.documents.find((d) => d.document_type === type);
    if (doc) return doc.status;
    return received[type] ? "received" : "missing";
  };

  const load = async (id: "a" | "b") => {
    await loadSample(id);
    router.push("/msme/review");
  };

  if (!ready) return null;
  const requiredDone = DOCUMENTS.filter((d) => !d.optional && statusOf(d.type) !== "missing").length;

  return (
    <>
      <PageHeader eyebrow="Step 2 of 6" title="Upload your documents">
        Photos, PDFs or scans all work. We read each one, check it, and cross-check them against each other before any
        lender sees your file.
        {plan && " Based on your answers, we've marked what you need."}
        {!questionnaire && (
          <>
            {" "}
            <Link href="/msme/start">Answer 7 quick questions first</Link> to see only the documents you need.
          </>
        )}
      </PageHeader>

      <section className="panel demo-banner fade-in">
        <div>
          <strong>Try it with a sample applicant</strong>
          <p className="muted">
            Document reading (OCR / AI vision) is being connected. Load a synthetic applicant to run every check, the
            readiness score and lender matching on real logic.
          </p>
        </div>
        <div className="demo-actions">
          <button type="button" className="btn btn-solid" disabled={busy} onClick={() => load("a")}>
            Applicant A · clean file
          </button>
          <button type="button" className="btn" disabled={busy} onClick={() => load("b")}>
            Applicant B · needs work
          </button>
        </div>
      </section>
      <ErrorNote error={error} />
      {busy && <p className="muted">Checking documents…</p>}

      <section className="doc-grid">
        {DOCUMENTS.map((doc, i) => (
          <article
            key={doc.type}
            className={`doc-card fade-in${planFor(doc.type)?.status === "not_needed" ? " not-needed" : ""}`}
            style={{ animationDelay: `${i * 40}ms` }}
          >
            <div className="doc-card-head">
              <h3>
                {doc.name}
                {!plan && doc.optional && <span className="optional"> · optional</span>}
              </h3>
              <StatusPill status={statusOf(doc.type)} />
            </div>
            {planFor(doc.type) && <span className={`need need-${planFor(doc.type)!.status}`}>{planFor(doc.type)!.status.replace("_", " ")}</span>}
            <p className="muted">{planFor(doc.type)?.why ?? doc.why}</p>
            <p className="doc-how">{doc.how}</p>
            <label className="file-drop">
              <input
                type="file"
                accept="image/*,application/pdf"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) setReceived((r) => ({ ...r, [doc.type]: file.name }));
                }}
              />
              {received[doc.type] ? `Selected: ${received[doc.type]}` : "Choose file"}
            </label>
          </article>
        ))}
      </section>

      <footer className="page-actions">
        <span className="muted">
          {requiredDone} of 6 required documents {assessment ? "checked" : "added"}
        </span>
        {assessment && (
          <Link href="/msme/review" className="btn btn-solid">
            Review checks <span aria-hidden="true">→</span>
          </Link>
        )}
      </footer>
    </>
  );
}
