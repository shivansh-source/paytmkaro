"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { BridgeMark } from "../BridgeMark";
import { clearSession, readSession, type Session } from "../../lib/session";
import { useMsme } from "./MsmeProvider";

export function Shell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { assessment, matches, sampleLabel, reset } = useMsme();
  const [session, setSession] = useState<Session | null>(null);

  useEffect(() => {
    const s = readSession();
    if (!s || s.role !== "msme") router.replace("/register?role=msme");
    else setSession(s);
  }, [router]);

  const steps = [
    { href: "/msme/upload", label: "Upload documents", done: !!assessment },
    { href: "/msme/review", label: "Review checks", done: !!assessment, locked: !assessment },
    { href: "/msme/readiness", label: "Readiness score", done: !!assessment?.profile.readiness, locked: !assessment },
    { href: "/msme/matches", label: "Lender matches", done: !!matches, locked: !assessment },
    { href: "/msme/offer", label: "Offer & KFS", done: false, locked: !matches },
    { href: "/msme/applications", label: "Applications", done: false, locked: !assessment }
  ];

  const signOut = () => {
    clearSession();
    reset();
    router.push("/");
  };

  if (!session) return null;

  return (
    <div className="shell">
      <aside className="sidebar">
        <Link href="/" className="brand">
          <BridgeMark />
          CreditSetu
        </Link>
        <nav className="steps-nav" aria-label="Application steps">
          {steps.map((step, i) => {
            const active = pathname.startsWith(step.href);
            const className = `step-link${active ? " active" : ""}${step.done ? " done" : ""}${step.locked ? " locked" : ""}`;
            const content = (
              <>
                <span className="step-index">{step.done && !active ? "✓" : i + 1}</span>
                {step.label}
              </>
            );
            return step.locked || step.href === "/msme/offer" ? (
              <span key={step.href} className={className} aria-disabled={step.locked}>
                {content}
              </span>
            ) : (
              <Link key={step.href} href={step.href} className={className}>
                {content}
              </Link>
            );
          })}
        </nav>
        <div className="sidebar-foot">
          {sampleLabel && <p className="sample-tag">SAMPLE · {sampleLabel}</p>}
          <p className="who">
            <strong>{session.organisation}</strong>
            <span>{session.name}</span>
          </p>
          <button type="button" className="link-button" onClick={signOut}>
            Sign out
          </button>
        </div>
      </aside>
      <main className="workspace">{children}</main>
    </div>
  );
}
