import "../dashboard.css";

import Link from "next/link";

import { BridgeMark } from "../../components/BridgeMark";

export const metadata = { title: "Lender workspace · CreditSetu" };

// Placeholder: the lender screen (incoming verified profiles with evidence links) is built next.
export default function LenderPage() {
  return (
    <main className="auth">
      <Link href="/" className="brand auth-brand">
        <BridgeMark />
        CreditSetu
      </Link>
      <div className="auth-card fade-in">
        <p className="eyebrow">Lender workspace</p>
        <h1 className="auth-title">Coming next.</h1>
        <p className="muted">
          Incoming applications arrive here as verified, scored profiles: KYC status, GST turnover, average balance,
          bounces and FOIR, each linked to the document it came from.
        </p>
      </div>
    </main>
  );
}
