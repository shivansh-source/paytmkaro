import type { ReactNode } from "react";
import { Noto_Sans_Devanagari, Noto_Sans_Kannada, Noto_Sans_Tamil, Outfit } from "next/font/google";

import "./globals.css";

const outfit = Outfit({ subsets: ["latin"], weight: ["300", "400", "500", "600"], variable: "--font-outfit" });
const devanagari = Noto_Sans_Devanagari({ subsets: ["devanagari"], weight: ["400", "500"], variable: "--font-deva" });
const kannada = Noto_Sans_Kannada({ subsets: ["kannada"], weight: ["400", "500"], variable: "--font-kannada" });
const tamil = Noto_Sans_Tamil({ subsets: ["tamil"], weight: ["400", "500"], variable: "--font-tamil" });

export const metadata = {
  title: "CreditSetu: lender-ready in a day",
  description: "One application, verified documents and an explained shortlist of lenders for India's small businesses."
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html
      lang="en"
      className={`${outfit.variable} ${devanagari.variable} ${kannada.variable} ${tamil.variable}`}
      suppressHydrationWarning
    >
      <head>
        {/* Lets CSS hide elements that GSAP animates in, without hiding them when JS is off. */}
        <script dangerouslySetInnerHTML={{ __html: "document.documentElement.classList.add('js')" }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
