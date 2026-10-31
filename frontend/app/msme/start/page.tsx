"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { useMsme } from "../../../components/msme/MsmeProvider";
import { ErrorNote } from "../../../components/msme/ui";
import { api } from "../../../lib/api";
import { documentName, inr, inrShort } from "../../../lib/format";
import { readSession } from "../../../lib/session";
import type { Prequalification, QuestionnaireAnswers } from "../../../lib/types";

type Draft = Partial<QuestionnaireAnswers> & { wants_score?: boolean };
type Option = { label: string; set: Draft };

interface Step {
  id: string;
  group: number; // 1..7, for "Question n of 7"
  ask: (d: Draft) => string;
  hint?: string;
  options?: Option[];
  multi?: { label: string; key: "has_gst" | "has_udyam" | "has_itr" | "wants_score" }[];
  number?: { key: keyof QuestionnaireAnswers; prefix?: string; placeholder: string; min: number; max: number; quick?: Option[] };
  when?: (d: Draft) => boolean;
}

const YEAR = new Date().getFullYear();

const STEPS: Step[] = [
  {
    id: "sector", group: 1, ask: () => "What does your business do?",
    options: [
      { label: "Retail shop", set: { sector: "retail" } },
      { label: "Trading / wholesale", set: { sector: "trading" } },
      { label: "Manufacturing", set: { sector: "manufacturing" } },
      { label: "Services", set: { sector: "services" } },
      { label: "Food & restaurants", set: { sector: "food" } },
      { label: "Something else", set: { sector: "other" } }
    ]
  },
  {
    id: "constitution", group: 2, ask: () => "How is the business set up?",
    hint: "Running it alone under your own name? That's a proprietorship.",
    options: [
      { label: "Proprietorship", set: { constitution: "proprietorship" } },
      { label: "Partnership", set: { constitution: "partnership" } },
      { label: "LLP", set: { constitution: "llp" } },
      { label: "Private limited", set: { constitution: "pvt_ltd" } },
      { label: "Not sure", set: { constitution: "not_sure" } }
    ]
  },
  {
    id: "started", group: 2, ask: () => "And when did you start it?",
    options: [
      { label: "This year", set: { started_year: YEAR, started_month: 1 } },
      { label: String(YEAR - 1), set: { started_year: YEAR - 1, started_month: 6 } },
      { label: String(YEAR - 2), set: { started_year: YEAR - 2, started_month: 6 } },
      { label: String(YEAR - 3), set: { started_year: YEAR - 3, started_month: 6 } },
      { label: `${YEAR - 5} or earlier`, set: { started_year: YEAR - 5, started_month: 1 } }
    ]
  },
  {
    id: "annual_sales", group: 3, ask: () => "Roughly how much do you sell in a year?",
    hint: "A rough range is fine. Your GST returns and bank statement will confirm it.",
    options: [
      { label: "Under ₹10 lakh", set: { annual_sales: "under_10l" } },
      { label: "₹10–25 lakh", set: { annual_sales: "10l_25l" } },
      { label: "₹25 lakh – 1 crore", set: { annual_sales: "25l_1cr" } },
      { label: "Over ₹1 crore", set: { annual_sales: "over_1cr" } }
    ]
  },
  {
    id: "loan_amount", group: 4, ask: () => "How much do you need?",
    number: {
      key: "loan_amount", prefix: "₹", placeholder: "500000", min: 10_000, max: 50_000_000,
      quick: [2, 5, 10, 25].map((l) => ({ label: `₹${l} lakh`, set: { loan_amount: l * 100_000 } }))
    }
  },
  {
    id: "tenure", group: 4, ask: (d) => `Over how many months would you like to repay ${inrShort(d.loan_amount ?? 0)}?`,
    options: [12, 18, 24, 36, 48].map((m) => ({ label: `${m} months`, set: { tenure_months: m } }))
  },
  {
    id: "purpose", group: 4, ask: () => "What is it for?",
    options: [
      { label: "Working capital", set: { purpose: "Working capital" } },
      { label: "Buy stock", set: { purpose: "Buy stock" } },
      { label: "Machinery / equipment", set: { purpose: "Machinery or equipment" } },
      { label: "Expand / new outlet", set: { purpose: "Business expansion" } },
      { label: "Something else", set: { purpose: "Other" } }
    ]
  },
  {
    id: "emi", group: 5, ask: () => "Do you pay any loan EMIs today?",
    hint: "Add up all of them: business loans, vehicle loans, personal loans.",
    number: {
      key: "existing_emi_monthly", prefix: "₹", placeholder: "Total EMI per month", min: 0, max: 10_000_000,
      quick: [{ label: "No loans", set: { existing_emi_monthly: 0 } }]
    }
  },
  {
    id: "bounces", group: 6, ask: () => "In the last 6 months, did any EMI or cheque bounce?",
    hint: "Honest answers help: your bank statement shows it either way, and we only use it to find the right lenders.",
    options: [
      { label: "None", set: { bounces_6m: "none" } },
      { label: "1 or 2", set: { bounces_6m: "1_2" } },
      { label: "3 or more", set: { bounces_6m: "3_plus" } },
      { label: "Not sure", set: { bounces_6m: "not_sure" } }
    ]
  },
  {
    id: "have", group: 7, ask: () => "Last one: which of these do you have?",
    hint: "Tap all that apply.",
    multi: [
      { label: "GST registration", key: "has_gst" },
      { label: "Udyam registration", key: "has_udyam" },
      { label: "Filed ITR", key: "has_itr" },
      { label: "I know my credit score", key: "wants_score" }
    ]
  },
  {
    id: "score", group: 7, ask: () => "What's your credit score?", when: (d) => !!d.wants_score,
    hint: "From CIBIL, Experian or your bank app. 300 to 900.",
    number: { key: "credit_score", placeholder: "e.g. 742", min: 300, max: 900 }
  }
];

/** Whether the draft already holds the answer for a question (e.g. from an earlier typed sentence). */
function answered(id: string, d: Draft): boolean {
  switch (id) {
    case "sector": return d.sector != null;
    case "constitution": return d.constitution != null;
    case "started": return d.started_year != null;
    case "annual_sales": return d.annual_sales != null;
    case "loan_amount": return d.loan_amount != null;
    case "tenure": return d.tenure_months != null;
    case "purpose": return d.purpose != null;
    case "emi": return d.existing_emi_monthly != null;
    case "bounces": return d.bounces_6m != null;
    case "have": return d.has_gst != null || d.has_udyam != null || d.has_itr != null;
    case "score": return d.credit_score != null;
    default: return false;
  }
}

function TextAnswer({ onSend, disabled }: { onSend: (text: string) => void; disabled: boolean }) {
  const [text, setText] = useState("");
  return (
    <form
      className="chat-text"
      onSubmit={(e) => {
        e.preventDefault();
        if (text.trim()) {
          onSend(text.trim());
          setText("");
        }
      }}
    >
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Or type your answer in English, Hindi or Hinglish…"
        maxLength={500}
        disabled={disabled}
        aria-label="Type your answer"
      />
      <button type="submit" className="btn btn-small" disabled={disabled || !text.trim()}>
        Send
      </button>
    </form>
  );
}

interface Message {
  from: "bot" | "you";
  text: string;
  hint?: string;
}

function NumberAnswer({ step, onAnswer }: { step: Step; onAnswer: (value: number, label: string) => void }) {
  const spec = step.number!;
  const [value, setValue] = useState("");
  const n = Number(value);
  const valid = value !== "" && n >= spec.min && n <= spec.max;
  return (
    <form
      className="chat-number"
      onSubmit={(e) => {
        e.preventDefault();
        if (valid) onAnswer(n, spec.prefix ? inr(n) : String(n));
      }}
    >
      <div className="money-input">
        {spec.prefix && <span>{spec.prefix}</span>}
        <input value={value} onChange={(e) => setValue(e.target.value.replace(/\D/g, ""))} inputMode="numeric" placeholder={spec.placeholder} autoFocus />
      </div>
      <button type="submit" className="btn btn-solid btn-small" disabled={!valid}>
        Send
      </button>
      {value && !valid && (
        <span className="muted small">
          Between {spec.prefix ? inr(spec.min) : spec.min} and {spec.prefix ? inr(spec.max) : spec.max}
        </span>
      )}
    </form>
  );
}

export default function StartPage() {
  const router = useRouter();
  const { ready, questionnaire, saveQuestionnaire, skipQuestionnaire } = useMsme();
  const [draft, setDraft] = useState<Draft>({});
  const [index, setIndex] = useState(-1); // -1: intro
  const [messages, setMessages] = useState<Message[]>([]);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [typing, setTyping] = useState(false);
  const [result, setResult] = useState<Prequalification | null>(null);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const firstName = (readSession()?.name ?? "").split(" ")[0];

  // Coming back after finishing: show the saved summary.
  useEffect(() => {
    if (ready && questionnaire && questionnaire !== "skipped" && !result && index === -1) setResult(questionnaire.result);
  }, [ready, questionnaire, result, index]);

  // Braces matter: newer Chrome returns a Promise from scrollIntoView, which React would treat as a cleanup.
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, typing, result]);

  const ask = (i: number, d: Draft) => {
    let next = i;
    // Skip questions that don't apply, or that a typed answer already covered.
    while (next < STEPS.length && ((STEPS[next].when && !STEPS[next].when!(d)) || answered(STEPS[next].id, d))) next++;
    if (next >= STEPS.length) return finish(d);
    setTyping(true);
    setTimeout(() => {
      setTyping(false);
      setMessages((m) => [...m, { from: "bot", text: STEPS[next].ask(d), hint: STEPS[next].hint }]);
      setIndex(next);
    }, 450);
  };

  const answer = (label: string, set: Draft) => {
    const d = { ...draft, ...set };
    setDraft(d);
    setMessages((m) => [...m, { from: "you", text: label }]);
    setPicked(new Set());
    ask(index + 1, d);
  };

  /** A typed answer: the server reads it (rules first, then Sarvam) and returns validated fields only. */
  const sendText = async (text: string) => {
    if (!step) return;
    setMessages((m) => [...m, { from: "you", text }]);
    setTyping(true);
    try {
      const r = await api.interpret(step.id, text);
      const d: Draft = { ...draft, ...r.updates, ...(r.updates.credit_score ? { wants_score: true } : {}) };
      setDraft(d);
      setTyping(false);
      if (r.understood) setMessages((m) => [...m, { from: "bot", text: r.understood! }]);
      if (r.answered_step) {
        setPicked(new Set());
        ask(index + 1, d);
      } else if (r.message) {
        setMessages((m) => [...m, { from: "bot", text: r.message! }]);
      }
    } catch (e) {
      setTyping(false);
      setMessages((m) => [...m, { from: "bot", text: "Sorry, that didn't go through. Please tap an option instead." }]);
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const finish = async (d: Draft) => {
    setIndex(STEPS.length);
    setTyping(true);
    const answers: QuestionnaireAnswers = {
      sector: d.sector!, constitution: d.constitution!, started_year: d.started_year!, started_month: d.started_month ?? 1,
      annual_sales: d.annual_sales!, loan_amount: d.loan_amount!, tenure_months: d.tenure_months!, purpose: d.purpose ?? "Working capital",
      existing_emi_monthly: d.existing_emi_monthly ?? 0, bounces_6m: d.bounces_6m ?? "not_sure",
      has_gst: !!d.has_gst, has_udyam: !!d.has_udyam, has_itr: !!d.has_itr, credit_score: d.wants_score ? d.credit_score ?? null : null
    };
    try {
      const prequal = await api.prequalify(answers);
      saveQuestionnaire(answers, prequal);
      setResult(prequal);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setTyping(false);
    }
  };

  const start = () => {
    setMessages([]);
    setDraft({});
    setResult(null);
    setPicked(new Set());
    ask(0, {});
  };

  const skip = () => {
    skipQuestionnaire();
    router.push("/msme/upload");
  };

  if (!ready) return null;
  const step = index >= 0 && index < STEPS.length ? STEPS[index] : null;
  const matched = result?.matches.filter((m) => m.status === "matched") ?? [];
  const quick = result?.matches.filter((m) => m.status === "not_yet" && m.quick_fix) ?? [];

  return (
    <div className="chat-page">
      <header className="chat-top fade-in">
        <div>
          <p className="eyebrow">Step 1 of 6 · About your business</p>
          <h1>{result ? "Here's where you stand" : "A few quick questions"}</h1>
        </div>
        <button type="button" className="link-button" onClick={skip}>
          Skip to documents →
        </button>
      </header>

      <section className="chat" aria-live="polite">
        <div className="bubble bot fade-in">
          Hi{firstName ? ` ${firstName}` : ""}! Answer 7 quick questions (about 2 minutes) and we&apos;ll show you the lenders
          you&apos;re likely to match and ask only for the documents you need. Or skip and upload documents directly.
        </div>

        {index === -1 && !result && (
          <div className="chips fade-in">
            <button type="button" className="chip primary" onClick={start}>
              Let&apos;s start
            </button>
            <button type="button" className="chip" onClick={skip}>
              Skip, upload documents
            </button>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={`bubble ${m.from} fade-in`}>
            {m.text}
            {m.hint && <span className="bubble-hint">{m.hint}</span>}
          </div>
        ))}

        {typing && (
          <div className="bubble bot typing" aria-label="typing">
            <i />
            <i />
            <i />
          </div>
        )}

        {step && !typing && (
          <div className="answer fade-in">
            <span className="progress-note muted small">Question {step.group} of 7</span>
            {step.options && (
              <div className="chips">
                {step.options.map((o) => (
                  <button key={o.label} type="button" className="chip" onClick={() => answer(o.label, o.set)}>
                    {o.label}
                  </button>
                ))}
              </div>
            )}
            {step.multi && (
              <>
                <div className="chips">
                  {step.multi.map((o) => (
                    <button
                      key={o.key}
                      type="button"
                      className={`chip${picked.has(o.key) ? " on" : ""}`}
                      aria-pressed={picked.has(o.key)}
                      onClick={() => setPicked((p) => new Set(p.has(o.key) ? [...p].filter((k) => k !== o.key) : [...p, o.key]))}
                    >
                      {picked.has(o.key) ? "✓ " : ""}
                      {o.label}
                    </button>
                  ))}
                </div>
                <button
                  type="button"
                  className="btn btn-solid btn-small"
                  onClick={() => {
                    const set: Draft = { has_gst: false, has_udyam: false, has_itr: false, wants_score: false };
                    picked.forEach((k) => ((set as Record<string, boolean>)[k] = true));
                    const labels = step.multi!.filter((o) => picked.has(o.key)).map((o) => o.label);
                    answer(labels.length ? labels.join(", ") : "None of these", set);
                  }}
                >
                  {picked.size ? "Done" : "None of these"}
                </button>
              </>
            )}
            {step.number && (
              <>
                {step.number.quick && (
                  <div className="chips">
                    {step.number.quick.map((o) => (
                      <button key={o.label} type="button" className="chip" onClick={() => answer(o.label, o.set)}>
                        {o.label}
                      </button>
                    ))}
                  </div>
                )}
                <NumberAnswer step={step} onAnswer={(value, label) => answer(label, { [step.number!.key]: value } as Draft)} />
              </>
            )}
            <TextAnswer onSend={sendText} disabled={typing} />
          </div>
        )}

        <ErrorNote error={error} />

        {result && (
          <div className="bubble bot result fade-in">
            <strong>
              {matched.length > 0
                ? `You're likely to match ${matched.length} lender${matched.length > 1 ? "s" : ""}.`
                : "No lender matches yet, but here's the path."}
            </strong>
            {matched.length > 0 && (
              <ul className="prequal-list">
                {matched.map((m) => (
                  <li key={m.product_id}>
                    <span>
                      {m.lender} · {m.product}
                    </span>
                    <span className="gold">~{m.true_apr_pct?.toFixed(1)}% true APR</span>
                  </li>
                ))}
              </ul>
            )}
            {quick.length > 0 && <p className="muted small">{quick.length} more with one small change to your request.</p>}
            <p className="muted small">{result.notes[0]}</p>
          </div>
        )}

        {result && (
          <div className="bubble bot result fade-in">
            <strong>Documents to upload</strong>
            <ul className="checklist">
              {result.checklist.map((c) => (
                <li key={c.document_type} className={`ck-${c.status}`}>
                  <span className={`pill pill-${c.status === "required" ? "ok" : c.status === "recommended" ? "warn" : "neutral"}`}>
                    {c.status.replace("_", " ")}
                  </span>
                  <span>
                    <strong>{documentName(c.document_type)}</strong>
                    <span className="muted small"> · {c.why}</span>
                  </span>
                </li>
              ))}
            </ul>
            <div className="chips">
              <Link href="/msme/upload" className="btn btn-solid">
                Upload my documents <span aria-hidden="true">→</span>
              </Link>
              <button type="button" className="chip" onClick={start}>
                Change my answers
              </button>
            </div>
          </div>
        )}
        <div ref={endRef} />
      </section>
    </div>
  );
}
