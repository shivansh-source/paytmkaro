import { Fragment } from "react";
import Link from "next/link";

import { BridgeMark } from "../components/BridgeMark";
import { AsciiVideo } from "../components/landing/AsciiVideo";
import { BgVideo } from "../components/landing/BgVideo";
import { LandingMotion } from "../components/landing/LandingMotion";

const problems = [
  <>
    10–15 <span className="gold">documents.</span>
  </>,
  <>
    Weeks of <span className="gold">waiting.</span>
  </>,
  <>
    The same paperwork, <span className="gold">every lender.</span>
  </>,
  <>
    Rejected. <span className="gold">No reason given.</span>
  </>
];

// [plain part, highlighted part]
const notYet = [
  ["“Not yet” is", "not “no”."],
  ["Not yet means:", "here’s why."],
  ["Not yet means:", "here’s what to fix."],
  ["Not yet means:", "you’ll get there."]
];

const steps = [
  ["Upload", "Aadhaar, PAN, GST, ITR and bank statements, as photos, PDFs or scans."],
  ["AI checks", "Fields are read and cross-checked: PAN inside GSTIN, names, balance math."],
  ["Readiness", "A 0–100 credit-readiness score and a fix-it checklist."],
  ["Smart match", "Your cash-flow profile against every lender’s rules, ranked, with reasons."],
  ["Clear offers", "True APR, EMI, total payback and your cooling-off right, in your language."]
];

const compare = [
  ["Forwards documents as-is", "Checks and fixes them before submission"],
  ["Shows a list of offers", "Explains each offer: true APR, EMI, fees"],
  ["Silent rejection", "“Not yet”, with why and what to change"],
  ["Black-box matching", "Every match shows its reasons"],
  ["English-only fine print", "Your language, and voice"]
];

const languages = [
  ["English", "Credit you can understand."],
  ["हिन्दी", "ऐसा लोन, जो आप समझ सकें।"],
  ["ಕನ್ನಡ", "ನಿಮಗೆ ಅರ್ಥವಾಗುವ ಸಾಲ."],
  ["தமிழ்", "உங்களுக்குப் புரியும் கடன்."]
];

const profile = [
  ["KYC status", "Verified", "PAN ↔ Aadhaar ↔ GSTIN"],
  ["GST turnover (12 mo)", "₹24,00,000", "GSTR-3B, 12 of 12 months filed"],
  ["Average monthly balance", "₹1,86,400", "Bank statement, 12 months"],
  ["Bounces (6 mo)", "0", "No RTN or NACH returns found"],
  ["FOIR", "25%", "Existing EMIs ÷ average monthly credits"]
];

function SplitChars({ text }: { text: string }) {
  const words = text.split(" ");
  return (
    <>
      {words.map((word, w) => (
        <Fragment key={w}>
          <span className="word">
            {[...word].map((ch, i) => (
              <span key={i} className="char">
                {ch}
              </span>
            ))}
          </span>
          {w < words.length - 1 ? " " : null}
        </Fragment>
      ))}
    </>
  );
}


export default function HomePage() {
  return (
    <>
      <LandingMotion />
      <div className="progress" data-progress />
      <div className="cursor" data-cursor />

      <header className="nav" data-nav>
        <Link href="/" className="brand">
          <BridgeMark />
          CreditSetu
        </Link>
        <nav className="nav-links">
          <a href="#how">How it works</a>
          <a href="#lenders">For lenders</a>
          <Link href="/register" className="btn" data-magnetic>
            Get started <span aria-hidden="true">→</span>
          </Link>
        </nav>
      </header>

      <main>
        {/* ---------- Hero ---------- */}
        <section className="section hero" data-hero>
          <div className="media" data-hero-media>
            <div className="media" data-hero-zoom>
              <BgVideo name="hero-lines" />
            </div>
          </div>
          <div className="shade" />
          <div className="content">
            <h1 className="display" data-hero-title>
              <span className="mask">
                <span>
                  <SplitChars text="Lender-ready." />
                </span>
              </span>
              <span className="mask indent">
                <span className="gold">
                  <SplitChars text="In a day." />
                </span>
              </span>
            </h1>
            <p className="lede" data-hero-fade>
              One application. Verified documents. A matched, explained shortlist of lenders, built for India’s small
              businesses.
            </p>
            <div className="stats" data-hero-fade>
              <div className="stat">
                <b data-scramble>1</b>
                <span>application, every lender</span>
              </div>
              <div className="stat">
                <b data-scramble>₹0</b>
                <span>for businesses</span>
              </div>
              <div className="stat">
                <b data-scramble>100%</b>
                <span>of matches explained</span>
              </div>
              <Link href="/register" className="btn btn-solid" data-magnetic>
                Check your readiness <span aria-hidden="true">→</span>
              </Link>
            </div>
          </div>
          <div className="scroll-cue" data-hero-fade>
            <span>Scroll</span>
            <i />
          </div>
        </section>

        {/* ---------- Problem (pinned, ASCII) ---------- */}
        <section className="problem" data-problem>
          <AsciiVideo name="problem-knot" />
          <div className="shade" />
          <div className="problem-inner">
            <p className="eyebrow">
              The problem <span className="swap-count" data-swap-count>01 / 0{problems.length}</span>
            </p>
            <div className="swap" data-swap>
              {problems.map((line, i) => (
                <h2 key={i} className="statement mask">
                  <span>{line}</span>
                </h2>
              ))}
            </div>
            <p className="problem-foot">
              Digital lenders can decide in 24–72 hours, but only when the file is complete. Most SME files aren’t.
            </p>
          </div>
        </section>

        {/* ---------- Not yet (wave) ---------- */}
        <section className="section wave" data-wave>
          <p className="eyebrow" data-scramble>
            The not-yet path
          </p>
          <div className="fill-lines" data-fill>
            {notYet.map(([plain, hl]) => (
              <h2 key={hl} className="statement">
                {plain.split(" ").map((word, i) => (
                  <span key={`p${i}`} className="fill-word">
                    {word}{" "}
                  </span>
                ))}
                {hl.split(" ").map((word, i) => (
                  <span key={`h${i}`} className="fill-word gold">
                    {word}{" "}
                  </span>
                ))}
              </h2>
            ))}
          </div>

          <div className="example">
            <div data-lines>
              <h3 className="statement small">
                <span className="mask">
                  <span>Every lender,</span>
                </span>
                <span className="mask">
                  <span className="gold">every reason.</span>
                </span>
              </h3>
              <p className="lede" data-reveal>
                Instead of a silent rejection, you see exactly which rule you missed and by how much. Fix it, and the
                lender moves to your shortlist.
              </p>
            </div>
            <div className="panel" data-panel>
              <div className="panel-row" data-panel-row>
                <div className="panel-head">
                  <strong>Demo Finance C</strong>
                  <span className="pill pill-ok">Matched</span>
                </div>
                <small className="panel-sub">GST turnover loan · 19–25% APR</small>
              </div>
              <div className="panel-row" data-panel-row>
                <div className="panel-head">
                  <strong>Demo NBFC B</strong>
                  <span className="pill pill-ok">Matched</span>
                </div>
                <small className="panel-sub">Flexi MSME loan · 20–26% APR</small>
              </div>
              <div className="panel-row" data-panel-row>
                <div className="panel-head">
                  <strong>Demo Bank A</strong>
                  <span className="pill pill-wait">Not yet</span>
                </div>
                <ul>
                  <li>Business vintage: needs at least 24 months, you have 14 months</li>
                  <li>Annual turnover: needs at least ₹15,00,000, you have ₹11,00,000</li>
                  <li>Bureau score: needs at least 730, you have 705</li>
                  <li>Bounces in the last 6 months: needs at most 2, you have 3</li>
                </ul>
              </div>
            </div>
          </div>
        </section>

        {/* ---------- Process (pinned ring reveal) ---------- */}
        <section className="process" id="how" data-process>
          <div className="ring-stage">
            <div className="ring-clip">
              <BgVideo name="process-rings" />
            </div>
            <div className="shade" />
            <div className="content">
              <p className="eyebrow">Credit-readiness score</p>
              <div className="score-wrap">
                <svg className="score-ring" viewBox="0 0 100 100" aria-hidden="true">
                  <circle cx="50" cy="50" r="46" className="score-ring-track" />
                  <circle cx="50" cy="50" r="46" className="score-ring-fill" data-score-ring data-value="82" />
                </svg>
                <div className="score" aria-label="82">
                  {[..."82"].map((digit, i) => (
                    <span key={i} className="digit" aria-hidden="true">
                      <span className="reel" data-reel={digit}>
                        {Array.from({ length: 20 }, (_, n) => (
                          <span key={n}>{n % 10}</span>
                        ))}
                        <span>{digit}</span>
                      </span>
                    </span>
                  ))}
                </div>
              </div>
              <div className="score-label">out of 100 · sample applicant</div>
            </div>
            <div className="checks">
              <span className="check" data-check>
                ✓ PAN matches GSTIN
              </span>
              <span className="check" data-check>
                ✓ Every statement row adds up
              </span>
              <span className="check" data-check>
                ✓ 12 of 12 GST returns filed
              </span>
              <span className="check warn" data-check>
                ⚠ “R. Kumar” vs “Ravi Kumar”: please confirm
              </span>
            </div>
          </div>
        </section>

        <section className="steps" data-steps>
          {steps.map(([title, body], i) => (
            <div key={title} className="step" data-step>
              <span>0{i + 1}</span>
              <h3>{title}</h3>
              <p>{body}</p>
            </div>
          ))}
        </section>

        {/* ---------- Compare ---------- */}
        <section className="section">
          <p className="eyebrow" data-scramble>
            Why not an aggregator
          </p>
          <h2 className="statement" data-lines>
            <span className="mask">
              <span>Lender-ready first.</span>
            </span>
            <span className="mask">
              <span className="gold">Matched second.</span>
            </span>
          </h2>
          <div className="compare">
            <div className="compare-row compare-head">
              <span className="them">Typical aggregator</span>
              <span className="us">CreditSetu</span>
            </div>
            {compare.map(([them, us]) => (
              <div key={them} className="compare-row" data-compare-row>
                <span className="them">{them}</span>
                <span className="us">{us}</span>
                <i className="rule" />
              </div>
            ))}
          </div>
        </section>

        {/* ---------- Languages (pinned) ---------- */}
        <section className="langs" data-langs>
          <p className="eyebrow">Plain language, your language</p>
          <div className="lang-stack">
            {languages.map(([name, line]) => (
              <div key={name} className="lang-item" data-lang>
                <span className="lang-name">{name}</span>
                <p className="lang-line">{line}</p>
              </div>
            ))}
          </div>
          <p className="lang-foot">Every offer comes with a Key Fact Statement: true APR, EMI, total payback, cooling-off.</p>
        </section>

        {/* ---------- Lenders ---------- */}
        <section className="section" id="lenders">
          <div className="band" data-band aria-hidden="true">
            <div className="band-inner" data-band-inner>
              <BgVideo name="hero-lines" />
            </div>
          </div>
          <div className="lender-grid">
            <div data-lines>
              <p className="eyebrow">For lenders</p>
              <h2 className="statement">
                <span className="mask">
                  <span>A file,</span>
                </span>
                <span className="mask">
                  <span className="gold">not a pile.</span>
                </span>
              </h2>
              <p className="lede" data-reveal>
                Receive a structured, verified, scored profile with every number linked to the document it came from.
                Set your own criteria; we only send files that fit.
              </p>
              <div className="lender-actions" data-reveal>
                <Link href="/register?role=lender" className="btn" data-magnetic>
                  Partner with us <span aria-hidden="true">→</span>
                </Link>
              </div>
            </div>
            <div className="panel" data-panel>
              {profile.map(([label, value, source]) => (
                <div key={label} className="profile-row" data-panel-row>
                  <span>{label}</span>
                  <b data-scramble>{value}</b>
                  <em>{source}</em>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ---------- CTA ---------- */}
        <section className="section cta" data-cta>
          <BgVideo name="cta-tunnel" />
          <div className="shade" />
          <div className="content">
            <h2 className="display" data-cta-title>
              Get <span className="gold">lender-ready.</span>
            </h2>
            <div className="cta-actions">
              <Link href="/register" className="btn btn-solid" data-magnetic>
                Start your application <span aria-hidden="true">→</span>
              </Link>
              <Link href="/register?role=lender" className="btn" data-magnetic>
                I’m a lender <span aria-hidden="true">→</span>
              </Link>
            </div>
          </div>
        </section>
      </main>

      <footer className="footer">
        <span className="brand">
          <BridgeMark />
          CreditSetu
        </span>
        <span>Team Cash for Delivery · Paytm Build for India AI Hackathon</span>
        <span>All names, documents and lenders shown are samples.</span>
      </footer>
    </>
  );
}
