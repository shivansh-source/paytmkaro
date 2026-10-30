"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { BridgeMark } from "../BridgeMark";
import { DEMO_OTP, homeFor, readSession, writeSession, type Role } from "../../lib/session";

const ROLES: { role: Role; title: string; body: string }[] = [
  { role: "msme", title: "I run a business", body: "Get lender-ready, see every lender you qualify for, and what to fix for the rest." },
  { role: "lender", title: "I'm a lender", body: "Receive verified, scored applications with every number linked to its document." }
];

export function RegisterForm({ initialRole }: { initialRole: Role | null }) {
  const router = useRouter();
  const [role, setRole] = useState<Role | null>(initialRole);
  const [step, setStep] = useState<"details" | "otp">("details");
  const [name, setName] = useState("");
  const [organisation, setOrganisation] = useState("");
  const [mobile, setMobile] = useState("");
  const [otp, setOtp] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Already signed in with this role? Go straight to the workspace.
  useEffect(() => {
    const session = readSession();
    if (session && (!initialRole || session.role === initialRole)) router.replace(homeFor(session.role));
  }, [initialRole, router]);

  const sendOtp = (e: FormEvent) => {
    e.preventDefault();
    if (!/^[6-9][0-9]{9}$/.test(mobile)) return setError("Enter a 10-digit Indian mobile number");
    if (!name.trim() || !organisation.trim()) return setError("Fill in your name and organisation");
    setError(null);
    setStep("otp");
  };

  const verify = (e: FormEvent) => {
    e.preventDefault();
    if (otp !== DEMO_OTP || !role) return setError("That code doesn't match. For the demo, use 123456.");
    writeSession({ role, name: name.trim(), organisation: organisation.trim(), mobile, signedInAt: new Date().toISOString() });
    router.push(homeFor(role));
  };

  return (
    <main className="auth">
      <Link href="/" className="brand auth-brand">
        <BridgeMark />
        CreditSetu
      </Link>

      <div className="auth-card fade-in">
        <p className="eyebrow">Sign in or create an account</p>

        {!role ? (
          <>
            <h1 className="auth-title">Who are you?</h1>
            <div className="role-grid">
              {ROLES.map((r) => (
                <button key={r.role} type="button" className="role-card" onClick={() => setRole(r.role)}>
                  <strong>{r.title}</strong>
                  <span>{r.body}</span>
                  <i aria-hidden="true">→</i>
                </button>
              ))}
            </div>
          </>
        ) : step === "details" ? (
          <form onSubmit={sendOtp} className="auth-form">
            <h1 className="auth-title">{role === "msme" ? "Your business" : "Your institution"}</h1>
            <label>
              Your name
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Ravi Kumar" autoFocus />
            </label>
            <label>
              {role === "msme" ? "Business name" : "Bank / NBFC name"}
              <input
                value={organisation}
                onChange={(e) => setOrganisation(e.target.value)}
                placeholder={role === "msme" ? "Kumar Stores" : "Demo NBFC B"}
              />
            </label>
            <label>
              Mobile number
              <div className="mobile-input">
                <span>+91</span>
                <input
                  value={mobile}
                  onChange={(e) => setMobile(e.target.value.replace(/\D/g, "").slice(0, 10))}
                  inputMode="numeric"
                  placeholder="98765 43210"
                />
              </div>
            </label>
            {error && <p className="form-error">{error}</p>}
            <button type="submit" className="btn btn-solid">
              Send OTP <span aria-hidden="true">→</span>
            </button>
            <button type="button" className="link-button" onClick={() => setRole(null)}>
              ← Change role
            </button>
          </form>
        ) : (
          <form onSubmit={verify} className="auth-form">
            <h1 className="auth-title">Enter the code</h1>
            <p className="muted">
              Sent to +91 {mobile.slice(0, 5)} {mobile.slice(5)}. <span className="demo-note">Demo code: {DEMO_OTP}</span>
            </p>
            <input
              className="otp-input"
              value={otp}
              onChange={(e) => setOtp(e.target.value.replace(/\D/g, "").slice(0, 6))}
              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder="••••••"
              autoFocus
            />
            {error && <p className="form-error">{error}</p>}
            <button type="submit" className="btn btn-solid">
              Verify and continue <span aria-hidden="true">→</span>
            </button>
            <button type="button" className="link-button" onClick={() => setStep("details")}>
              ← Edit details
            </button>
          </form>
        )}
      </div>
      <p className="auth-foot">Demo only: no real OTP is sent and nothing leaves this browser.</p>
    </main>
  );
}
