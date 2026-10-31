"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { BridgeMark } from "../BridgeMark";
import { signOut } from "../../lib/api";
import { readSession, type Session } from "../../lib/session";

const SessionContext = createContext<Session | null>(null);

/** The signed-in lender. Only rendered inside LenderShell, which waits for a lender session. */
export function useLender(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useLender must be used inside <LenderShell>");
  return session;
}

const NAV = [
  { href: "/lender", label: "Applications", match: (p: string) => p === "/lender" || p.startsWith("/lender/applications") },
  { href: "/lender/criteria", label: "Your criteria", match: (p: string) => p.startsWith("/lender/criteria") }
];

export function LenderShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [session, setSession] = useState<Session | null>(null);

  useEffect(() => {
    const s = readSession();
    if (!s || s.role !== "lender") router.replace("/register?role=lender");
    else setSession(s);
  }, [router]);

  if (!session) return null;

  return (
    <SessionContext.Provider value={session}>
      <div className="shell lender">
        <aside className="sidebar">
          <Link href="/" className="brand">
            <BridgeMark />
            CreditSetu
          </Link>
          <p className="eyebrow sidebar-label">Lender workspace</p>
          <nav className="steps-nav" aria-label="Lender workspace">
            {NAV.map((item) => (
              <Link key={item.href} href={item.href} className={`step-link${item.match(pathname) ? " active" : ""}`}>
                {item.label}
              </Link>
            ))}
          </nav>
          <div className="sidebar-foot">
            <p className="who">
              <strong>{session.organisation}</strong>
              <span>{session.name}</span>
            </p>
            <button
              type="button"
              className="link-button"
              onClick={signOut}
            >
              Sign out
            </button>
          </div>
        </aside>
        <main className="workspace">{children}</main>
      </div>
    </SessionContext.Provider>
  );
}
