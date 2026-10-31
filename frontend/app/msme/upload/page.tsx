"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useMsme, type SlotUpload } from "../../../components/msme/MsmeProvider";
import { ErrorNote, PageHeader, StatusPill } from "../../../components/msme/ui";
import { DOCUMENTS } from "../../../lib/format";
import type { DocumentType } from "../../../lib/types";

export default function UploadPage() {
  const router = useRouter();
  const { assessment, loadSample, uploadFile, retryWithPassword, uploads, busy, error, ready, questionnaire } = useMsme();
  // Personalised by the questionnaire, when answered.
  const plan = questionnaire && questionnaire !== "skipped" ? questionnaire.result.checklist : null;
  const planFor = (type: DocumentType) => plan?.find((c) => c.document_type === type);
  const [passwords, setPasswords] = useState<Partial<Record<DocumentType, string>>>({});

  const statusOf = (type: DocumentType) => {
    const slot = uploads[type];
    if (slot?.state === "reading") return "extracting";
    const doc = assessment?.documents.find((d) => d.document_type === type);
    if (doc) return doc.status;
    return slot?.state === "error" || slot?.state === "password" ? "failed" : "missing";
  };
  const reading = Object.values(uploads).some((u) => u?.state === "reading");

  const load = async (id: "a" | "b") => {
    await loadSample(id);
    router.push("/msme/review");
  };

  if (!ready) return null;
  const requiredDone = DOCUMENTS.filter((d) => !d.optional && ["verified", "needs_review"].includes(statusOf(d.type))).length;

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
          <strong>No documents to hand? Try a sample applicant</strong>
          <p className="muted">
            Upload your own files below, or load a synthetic applicant (stamped SAMPLE) to see every check, the
            readiness score and lender matching at once.
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
      {reading && <p className="muted">Reading your documents… a phone photo can take up to a minute.</p>}

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
            <label className={`file-drop${uploads[doc.type]?.state === "reading" ? " is-reading" : ""}`}>
              <input
                type="file"
                accept="image/*,application/pdf,.heic,.docx,.xlsx,.xls,.csv"
                multiple={doc.type === "gstr3b"}
                disabled={uploads[doc.type]?.state === "reading"}
                onChange={async (e) => {
                  const chosen = Array.from(e.target.files ?? []);
                  e.target.value = ""; // choosing the same file again still triggers a read
                  for (const file of chosen) await uploadFile(doc.type, file);
                }}
              />
              {uploads[doc.type] ? `${uploads[doc.type]!.state === "reading" ? "Reading" : "File"}: ${uploads[doc.type]!.file_name}` : "Choose file"}
            </label>
            <UploadNotes
              upload={uploads[doc.type]}
              password={passwords[doc.type] ?? ""}
              onPassword={(value) => setPasswords((p) => ({ ...p, [doc.type]: value }))}
              onRetry={() => retryWithPassword(doc.type, passwords[doc.type] ?? "")}
            />
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

function UploadNotes({
  upload,
  password,
  onPassword,
  onRetry
}: {
  upload?: SlotUpload;
  password: string;
  onPassword: (value: string) => void;
  onRetry: () => void;
}) {
  if (!upload || upload.state === "reading") return null;
  if (upload.state === "password") {
    return (
      <form
        className="upload-password"
        onSubmit={(e) => {
          e.preventDefault();
          if (password) onRetry();
        }}
      >
        <p className="muted">{upload.message}</p>
        <input type="password" value={password} onChange={(e) => onPassword(e.target.value)} placeholder="PDF password" />
        <button type="submit" className="btn" disabled={!password}>
          Open
        </button>
      </form>
    );
  }
  const notes = [
    ...(upload.state === "error" && upload.message ? [upload.message] : []),
    ...upload.skipped
      .filter((s) => s.reason !== upload.message)
      .map((s) => `Page${s.pages.length > 1 ? "s" : ""} ${s.pages.join(", ")}: ${s.reason}`),
    ...upload.warnings.filter((w) => !w.startsWith("OCR was not run") && !w.startsWith("No text could be read")).slice(0, 2)
  ];
  if (!notes.length) return null;
  return (
    <ul className={`upload-notes${upload.state === "error" ? " is-error" : ""}`}>
      {notes.map((note) => (
        <li key={note}>{note}</li>
      ))}
    </ul>
  );
}
