"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api } from "../../lib/api";
import type { AssessBody, Assessment, LoanRequest, MatchResult, SortOrder } from "../../lib/types";

interface MsmeState {
  sampleLabel: string | null;
  assessBody: AssessBody | null; // what we sent to /assess; re-sent when the SME confirms a field
  assessment: Assessment | null;
  request: Omit<LoanRequest, "sme_id">;
  sort: SortOrder;
  matches: MatchResult[] | null;
}

interface MsmeContext extends MsmeState {
  ready: boolean; // localStorage loaded
  busy: boolean;
  error: string | null;
  loadSample: (id: "a" | "b") => Promise<void>;
  confirmField: (documentId: string, field: string) => Promise<void>;
  confirmFields: (items: { documentId: string; field: string }[]) => Promise<void>;
  setRequest: (request: Omit<LoanRequest, "sme_id">) => void;
  setSort: (sort: SortOrder) => void;
  refreshMatches: (override?: Partial<Pick<MsmeState, "request" | "sort">>) => Promise<void>;
  reset: () => void;
}

const KEY = "creditsetu.msme";
const INITIAL: MsmeState = {
  sampleLabel: null,
  assessBody: null,
  assessment: null,
  request: { amount: 500_000, tenure_months: 24, purpose: "Working capital" },
  sort: "cost",
  matches: null
};

const Context = createContext<MsmeContext | null>(null);

export function MsmeProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<MsmeState>(INITIAL);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(KEY);
      if (saved) setState({ ...INITIAL, ...JSON.parse(saved) });
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
        const { label, ...body } = sample;
        const assessment = await api.assess(body);
        setState((s) => ({ ...s, sampleLabel: label, assessBody: body, assessment, matches: null }));
      }),
    [run]
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
        setState((s) => ({ ...s, assessBody: body, assessment, matches: null }));
      }),
    [run, state.assessBody]
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
      confirmField,
      confirmFields,
      refreshMatches,
      setRequest: (request) => setState((s) => ({ ...s, request })),
      setSort: (sort) => setState((s) => ({ ...s, sort })),
      reset: () => setState(INITIAL)
    }),
    [state, ready, busy, error, loadSample, confirmField, confirmFields, refreshMatches]
  );

  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useMsme(): MsmeContext {
  const ctx = useContext(Context);
  if (!ctx) throw new Error("useMsme must be used inside <MsmeProvider>");
  return ctx;
}
