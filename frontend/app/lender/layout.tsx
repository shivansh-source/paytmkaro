import "../dashboard.css";

import type { ReactNode } from "react";

import { LenderShell } from "../../components/lender/LenderShell";

export const metadata = { title: "Lender workspace · CreditSetu" };

export default function LenderLayout({ children }: { children: ReactNode }) {
  return <LenderShell>{children}</LenderShell>;
}
