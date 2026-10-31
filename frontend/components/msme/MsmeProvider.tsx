"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { api } from "../../lib/api";
import { readSession } from "../../lib/session";
import type {
  AssessBody,
  Assessment,
  DocumentType,
  Envelope,
  LoanRequest,
  MatchResult,
  Prequalification,
  QuestionnaireAnswers,
  SkippedPart,
  SortOrder
} from "../../lib/types";

// What happened to the file the SME put in one upload slot.
export interface SlotUpload {
  file_name: string;
  state: "reading" | "done" | "password" | "error";
  message?: string | null;
  skipped: SkippedPart[];
  warnings: string[];
  document_ids: string[];
}

interface MsmeState {
  // Pre-qualification: self-declared answers, or skipped. Verified values replace them after upload.
  questionnaire: { answers: QuestionnaireAnswers; result: Prequalification } | "skipped" | null;
  sampleLabel: string | null;
  uploads: Partial<Record<DocumentType, SlotUpload>>;
  assessBody: AssessBody | null; // what we sent to /assess; re-sent when the SME confirms a field
  assessment: Assessment | null;
  request: Omit<LoanRequest, "sme_id">;
  sort: SortOrder;
  matches: MatchResult[] | null;
}

interface MsmeContext extends MsmeState {
  ready: boolean; // localStorage loaded
  saveQuestionnaire: (answers: QuestionnaireAnswers, result: Prequalification) => void;
  skipQuestionnaire: () => void;
  busy: boolean;
  error: string | null;
  loadSample: (id: "a" | "b") => Promise<void>;
  uploadFile: (slot: DocumentType, file: File, password?: string) => Promise<void>;
  retryWithPassword: (slot: DocumentType, password: string) => Promise<void>;
  confirmField: (documentId: string, field: string) => Promise<void>;
  confirmFields: (items: { documentId: string; field: string }[]) => Promise<void>;
  setRequest: (request: Omit<LoanRequest, "sme_id">) => void;
  setSort: (sort: SortOrder) => void;
  refreshMatches: (override?: Partial<Pick<MsmeState, "request" | "sort">>) => Promise<void>;
  reset: () => void;
}

const KEY = "creditsetu.msme";
const INITIAL: MsmeState = {
  questionnaire: null,
  sampleLabel: null,
  uploads: {},
  assessBody: null,
  assessment: null,
  request: { amount: 500_000, tenure_months: 24, purpose: "Working capital" },
  sort: "cost",
  matches: null
};

const Context = createContext<MsmeContext | null>(null);

// One id per signed-in mobile number, so uploads and applications from the same SME line up.
function smeId(): string {
  const digits = (readSession()?.mobile ?? "").replace(/\D/g, "");
  return digits ? `SME-${digits}` : "SME-DEMO";
}

// New envelopes replace earlier ones of the same type; GSTR-3B uploads add months instead.
function merge(current: Envelope[], incoming: Envelope[]): Envelope[] {
  const ids = new Set(incoming.map((d) => d.document_id));
  const replaced = new Set<DocumentType>(incoming.map((d) => d.document_type).filter((t) => t !== "gstr3b"));
  return [...current.filter((d) => !ids.has(d.document_id) && !replaced.has(d.document_type)), ...incoming];
}

export function MsmeProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<MsmeState>(INITIAL);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Uploaded envelopes, updated synchronously so uploads that finish together don't overwrite each other.
  const uploaded = useRef<Envelope[]>([]);
  const assessSeq = useRef(0);
  const files = useRef<Partial<Record<DocumentType, File>>>({}); // kept in memory for a password retry

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(KEY);
      if (saved) {
        const restored: MsmeState = { ...INITIAL, ...JSON.parse(saved) };
        // A refresh mid-read loses the request: show those slots as needing the file again.
        for (const slot of Object.values(restored.uploads)) {
          if (slot && (slot.state === "reading" || slot.state === "password")) {
            slot.state = "error";
            slot.message = "The page was reloaded before this finished. Please choose the file again.";
          }
        }
        if (!restored.sampleLabel) uploaded.current = restored.assessBody?.documents ?? [];
        setState(restored);
      }
    } catch {
      /* corrupt storage: start fresh */
    }
    setReady(true);
  }, []);

  useEffect(() => {
    if (ready) window.localStorage.setItem(KEY, JSON.stringify(state));
  }, [state, ready]);

  const run = useCallback(async (task: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await task();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, []);

  const loadSample = useCallback(
    (id: "a" | "b") =>
      run(async () => {
        const sample = await api.sample(id);
        const { label, ...rest } = sample;
        const told = state.questionnaire && state.questionnaire !== "skipped" ? state.questionnaire.answers : null;
        const body = {
          ...rest,
          sector: told?.sector ?? rest.sector,
          bureau: told?.credit_score ? { value: told.credit_score, source: "self_declared" } : rest.bureau
        };
        const assessment = await api.assess(body);
        uploaded.current = [];
        assessSeq.current += 1; // a slow upload finishing later must not replace the sample
        setState((s) => ({ ...s, sampleLabel: label, uploads: {}, assessBody: body, assessment, matches: null }));
      }),
    [run, state.questionnaire]
  );

  const setSlot = (slot: DocumentType, upload: SlotUpload) =>
    setState((s) => ({ ...s, uploads: { ...s.uploads, [slot]: upload } }));

  const uploadFile = useCallback(
    async (slot: DocumentType, file: File, password?: string) => {
      files.current[slot] = file;
      const blank = { file_name: file.name, skipped: [], warnings: [], document_ids: [] };
      setSlot(slot, { ...blank, state: "reading" });
      setError(null);
      try {
        const result = await api.upload(file, smeId(), slot, password);
        if (result.status === "password_required") {
          setSlot(slot, { ...blank, state: "password", message: result.message });
          return;
        }
        if (result.status !== "ok" || result.documents.length === 0) {
          const message = result.message ?? result.skipped[0]?.reason ?? "We couldn't read anything from this file.";
          setSlot(slot, { ...blank, state: "error", message, skipped: result.skipped, warnings: result.warnings });
          return;
        }
        delete files.current[slot];
        uploaded.current = merge(uploaded.current, result.documents);
        setSlot(slot, {
          ...blank,
          state: "done",
          skipped: result.skipped,
          warnings: result.warnings,
          document_ids: result.documents.map((d) => d.document_id)
        });

        // Re-assess the whole file. Only the latest assessment is kept if several uploads overlap.
        const seq = ++assessSeq.current;
        const told = state.questionnaire && state.questionnaire !== "skipped" ? state.questionnaire.answers : null;
        const body: AssessBody = {
          sme_id: smeId(),
          documents: uploaded.current,
          sector: told?.sector ?? null,
          bureau: told?.credit_score ? { value: told.credit_score, source: "self_declared" } : null
        };
        const assessment = await api.assess(body);
        if (seq === assessSeq.current) {
          setState((s) => ({ ...s, sampleLabel: null, assessBody: body, assessment, matches: null }));
        }
      } catch (e) {
        setSlot(slot, { ...blank, state: "error", message: e instanceof Error ? e.message : String(e) });
      }
    },
    [state.questionnaire]
  );

  const retryWithPassword = useCallback(
    async (slot: DocumentType, password: string) => {
      const file = files.current[slot];
      if (file) await uploadFile(slot, file, password);
    },
    [uploadFile]
  );

  const confirmFields = useCallback(
    (items: { documentId: string; field: string }[]) =>
      run(async () => {
        if (!state.assessBody || items.length === 0) return;
        const documents = state.assessBody.documents.map((doc) => {
          const fields = items.filter((i) => i.documentId === doc.document_id).map((i) => i.field);
          if (!fields.length || !doc.data) return doc;
          const data = { ...doc.data };
          for (const field of fields) {
            const current = data[field] as Record<string, unknown> | undefined;
            if (current) data[field] = { ...current, user_confirmed: true };
          }
          return { ...doc, data };
        });
        const body = { ...state.assessBody, documents };
        const assessment = await api.assess(body);
        if (!state.sampleLabel) uploaded.current = documents;
        setState((s) => ({ ...s, assessBody: body, assessment, matches: null }));
      }),
    [run, state.assessBody, state.sampleLabel]
  );

  const confirmField = useCallback(
    (documentId: string, field: string) => confirmFields([{ documentId, field }]),
    [confirmFields]
  );

  const refreshMatches = useCallback(
    (override?: Partial<Pick<MsmeState, "request" | "sort">>) =>
      run(async () => {
        const profile = state.assessment?.profile;
        if (!profile) return;
        const request = override?.request ?? state.request;
        const sort = override?.sort ?? state.sort;
        const matches = await api.match(profile, { sme_id: profile.sme_id, ...request }, sort);
        setState((s) => ({ ...s, request, sort, matches }));
      }),
    [run, state.assessment, state.request, state.sort]
  );

  const value = useMemo<MsmeContext>(
    () => ({
      ...state,
      ready,
      busy,
      error,
      loadSample,
      uploadFile,
      retryWithPassword,
      confirmField,
      confirmFields,
      refreshMatches,
      setRequest: (request) => setState((s) => ({ ...s, request })),
      saveQuestionnaire: (answers, result) =>
        setState((s) => ({
          ...s,
          questionnaire: { answers, result },
          request: { amount: answers.loan_amount, tenure_months: answers.tenure_months, purpose: answers.purpose },
          matches: null
        })),
      skipQuestionnaire: () => setState((s) => ({ ...s, questionnaire: "skipped" })),
      setSort: (sort) => setState((s) => ({ ...s, sort })),
      reset: () => {
        uploaded.current = [];
        files.current = {};
        setState(INITIAL);
      }
    }),
    [state, ready, busy, error, loadSample, uploadFile, retryWithPassword, confirmField, confirmFields, refreshMatches]
  );

  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useMsme(): MsmeContext {
  const ctx = useContext(Context);
  if (!ctx) throw new Error("useMsme must be used inside <MsmeProvider>");
  return ctx;
}
