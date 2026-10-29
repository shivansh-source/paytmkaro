const steps = [
  "1) Upload docs",
  "2) AI verification + cross-checks",
  "3) Credit-readiness score + fix list",
  "4) Smart lender matching",
  "5) Plain-language KFS"
];

export default function HomePage() {
  return (
    <main>
      <h1>CreditSetu</h1>
      <p>Simple hackathon skeleton (frontend + backend + editable schemas).</p>
      <ul>
        {steps.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ul>
      <p>
        API endpoints live in <code>apps/api/app/main.py</code> and schemas in <code>apps/api/schemas</code>.
      </p>
    </main>
  );
}
