import "../dashboard.css";

import type { ReactNode } from "react";

import { MsmeProvider } from "../../components/msme/MsmeProvider";
import { Shell } from "../../components/msme/Shell";

export const metadata = { title: "Your application · CreditSetu" };

export default function MsmeLayout({ children }: { children: ReactNode }) {
  return (
    <MsmeProvider>
      <Shell>{children}</Shell>
    </MsmeProvider>
  );
}
