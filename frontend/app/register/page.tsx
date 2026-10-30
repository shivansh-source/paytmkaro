import "../dashboard.css";

import { RegisterForm } from "../../components/auth/RegisterForm";
import type { Role } from "../../lib/session";

export const metadata = { title: "Sign in · CreditSetu" };

export default function RegisterPage({ searchParams }: { searchParams: { role?: string } }) {
  const role: Role | null = searchParams.role === "lender" ? "lender" : searchParams.role === "msme" ? "msme" : null;
  return <RegisterForm initialRole={role} />;
}
