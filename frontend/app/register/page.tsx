import Link from "next/link";

export default function RegisterPage() {
  return (
    <main className="plain-page">
      <p className="eyebrow">Registration</p>
      <h1 className="statement">Coming soon.</h1>
      <p>The SME and lender registration flow and dashboard will live here.</p>
      <p>
        <Link href="/" className="gold">
          ← Back to home
        </Link>
      </p>
    </main>
  );
}
