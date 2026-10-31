# CreditSetu

AI copilot that makes Indian SMEs lender-ready and matches them to the right lender, with reasons.
Built for the **Paytm Build for India AI Hackathon** (problem statement: *AI Powered Financial Journeys*)
by **Team Cash for Delivery**: Shivansh Sinha, Lakshya Karira, Anansh Srivastava. "CreditSetu" is a
working name ("setu" = bridge).

**One-liner:** weeks of paperwork and lender-hopping become one application and a matched, explained
shortlist in under a day. The lender still makes the credit decision, on a complete, verified file.

## Who owns what

- **Lakshya:** OCR / VLM extraction (`backend/app/documents/`: ingest, classify, extract) **and the
  scoring engine (`backend/app/scoring/`: metrics, readiness score, fix-it list)**. He owns and improves
  the existing scoring code and its tests (`tests/test_scoring.py`); no parallel version. His older
  `app/documents/extract/features.py` duplicates validation + scoring and is superseded.
  Extraction contract: output must become `DocumentEnvelope` (`schemas/v1/msme/`); Aadhaar is masked in
  his layer (Verhoeff on the full number, then only `aadhaar_last4` leaves it); values that fail
  validation must be kept (low confidence) rather than dropped, so checks can show ✗ and the user can
  confirm. Coordinate before changing `SmeProfile` / `CashflowMetrics` / `Readiness` shapes: both
  dashboards, the engine adapter and lender applications read them.
- **Anansh:** lender schema. Owns `schemas/v1/lender/lender_product.schema.json` and lender records.
- **Shivansh (with Claude):** validation (`app/validation/`), recommendation engine, offers/KFS, landing
  page, login, the MSME dashboard **and the lender side** (applications + lender screens).
  Transaction tagging (bounce / EMI / NACH) from narrations happens in validation, not extraction.

## Product in brief

Two-sided platform. The SME journey is the hero of the demo; the lender side is one screen.

1. **Upload** Aadhaar, PAN, GST, ITR, bank statements (photos, PDFs, scans).
2. **AI checks**: hybrid extraction (text-layer parser → OCR for scans/tables → VLM for phone photos),
   then cross-document checks (PAN inside GSTIN chars 3–12, fuzzy name match, DOB, address, GSTR-3B
   turnover vs bank credits, statement balance math per row).
3. **Readiness**: 0–100 credit-readiness score plus a fix-it checklist.
4. **Smart match**: cash-flow profile × lender criteria, ranked, every match with reasons.
5. **Clear offers**: plain-language Key Fact Statement (true APR, EMI, total payback, cooling-off) in
   the user's language (Hindi, Kannada, Tamil, voice).

**USP vs aggregators/DSAs:** fixes the file before submission, explains every offer, gives a "not yet"
path (why + what to change) instead of silent rejection, transparent matching, multilingual.

**Business model:** free for SMEs; lenders pay a success fee, per-qualified-lead fee and/or SaaS fee.
Positioned as a Lending Service Provider under RBI's Digital Lending Directions, 2025.

## Non-negotiable principles

- **Deterministic scoring.** Every score, threshold and match is computed in code. An LLM may narrate
  results or turn policy text into criteria records, but never decides or invents numbers.
- **Honest claims.** We cut document prep, rework and lender-hopping; the lender's own decision time is
  unchanged. Don't write "90% faster"-style claims.
- **Synthetic data only.** All documents are stamped SAMPLE; lenders are "Demo Bank A", "Demo NBFC B"…
  Never use a real Aadhaar/PAN. Aadhaar is masked to the last 4 digits at upload.
- **Bureau score** can't come from documents: it's mocked or self-declared (optional field).

## Repo layout

```
backend/                 FastAPI (Python 3.13)
  app/
    main.py              creates the app, mounts /v1 router + /health
    config.py            paths (DATA_DIR, LENDERS_FILE)
    api/v1/              thin routes, one file per resource
    schemas/             shared data contracts (see "Schemas" below)
    validation/          per-document + cross-document checks, transaction tagging
    scoring/             metrics, identity, readiness, fix-it; assess() builds the SmeProfile
    recommendation/      lender matching engine + "not yet" fixes
    offers/              KFS math: EMI, schedule, fees, true APR
    samples/             synthetic Applicants A and B as DocumentEnvelopes
    questionnaire/       pre-qualification: self-declared answers → estimates, preview, checklist;
                         understand.py reads free-typed answers (rules, then Sarvam)
    llm/                 LLM clients (Sarvam). Human-facing only: understanding / explaining, never deciding
    applications/        MSME → lender applications (SQLite), consent, decisions, demo seed
    documents/           Lakshya's ingest / classify / extract pipeline (OCR, VLM)
  data/
    lenders.json         mock lender products (edit freely; re-read on every request)
    sample_profiles/     MatchInput fixtures: applicant_a.json (clean), applicant_b.json (messy)
  scripts/export_schemas.py   regenerates /schemas from the Pydantic models
  tests/                 pytest
schemas/v1/msme/         GENERATED from Pydantic (never edit by hand)
schemas/v1/lender/       HAND-WRITTEN lender JSON Schema: source of truth for the lender side
frontend/                Next.js 14 app router, TypeScript, no Tailwind (plain CSS)
  app/page.tsx           landing page
  app/globals.css        all styles
  app/register/          placeholder for registration (dashboard to be built separately)
  app/sme/               placeholder SME journey page
  components/landing/    BgVideo, AsciiVideo, LandingMotion
  public/media/          compressed background videos + poster jpgs
  movies/                raw stock footage, gitignored, never commit
```

Convention: each pipeline stage gets its own package under `backend/app/` (`documents/`, `scoring/`,
`offers/` next); routes in `api/v1/` only call into those packages.

## Commands

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload        # http://localhost:8000/docs
pytest                                # pythonpath configured in pyproject.toml

# frontend
cd frontend
npm install
npm run dev                           # http://localhost:3000
npm run build                         # must pass before committing
```

The dashboard calls `/api/v1/*`, which `next.config.mjs` rewrites to FastAPI (`BACKEND_URL`, default
`http://localhost:8000`), so run the backend alongside the frontend. No CORS setup needed.

**AI keys** live in `backend/.env` (git-ignored, loaded by `app/config.py`): `SARVAM_API_KEY` (free-text
questionnaire), `GROQ_API_KEY` (Lakshya's VLM). Never paste keys in chat or commit them. Tests never call a
real model: `tests/conftest.py` blanks `SARVAM_API_KEY`, and `tests/test_understand.py` injects a fake.
Principle for any new AI feature: **AI reads and explains; code computes and decides.**

Gotchas seen so far: `uvicorn --reload` on Windows sometimes misses **new** files (new routes 404 until a
restart); React effects must not return values (`useEffect(() => el.scrollIntoView())` crashes in newer
Chrome, which returns a Promise there: wrap the body in braces).

The dev machine is Windows; Bash (Git Bash) and PowerShell are both available. Port 3000 is often taken
by the user's own dev server: use another port (e.g. 3100) for test runs, and kill only processes you
started (stopping a background `npx next start` can leave an orphaned `node` holding the port).

## Login + MSME dashboard (`frontend/app/register`, `frontend/app/msme`)

Flow: landing → `/register` (role choice; `?role=lender|msme` pre-selects) → details → mock OTP
(`123456`, shown on screen) → MSMEs land on `/msme/start` (questionnaire), lenders on `/lender` (lenders
pick their institution from `/v1/lenders`, so the inbox knows whose applications to show). Session in
`localStorage` (`lib/session.ts`); no real auth for the hackathon. Sign-out does a full page load
(`window.location.assign("/")`), because clearing data makes page guards redirect and race `router.push`.

MSME screens (all client components inside `MsmeProvider`, which persists assessment, request, sort and
matches to `localStorage` so a refresh mid-demo is safe):
0. `/msme/start` (sidebar step 1): **questionnaire as a scripted chat**, skippable ("Skip to documents").
   7 questions: sector; business type; start year; yearly sales band; loan amount + tenure + purpose;
   existing EMIs; EMI/cheque bounces in 6 months; which of GST / Udyam / ITR / credit score they have
   (score asked only if they know it). `POST /v1/prequalify` (`backend/app/questionnaire/`) turns answers
   into **conservative** estimates (lower bound of the sales band; "not sure" stays unknown), a "likely
   lenders" preview from the same engine (labelled as an estimate), and a personalised checklist
   (no GST → GST documents "not needed"; no Udyam → "recommended, free online"). Answers set the loan
   request, the sector, and a **self-declared** bureau score for the assessment.
   **Free text:** under every question users can type in English, Hindi or Hinglish
   ("main kirana dukaan chalata hoon, teen saal se, 5 lakh chahiye"). `POST /v1/questionnaire/interpret`
   (`app/questionnaire/understand.py`): mask PAN / long digit runs → deterministic rules for short answers
   ("5 lakh", "2022", "koi loan nahi") → otherwise **Sarvam** (`sarvam-105b-conversations`, json_schema
   structured output). Guardrails, all tested: the model only *copies* facts (each EMI separately, sales +
   period, years in business) and **code does all arithmetic**; every rupee amount must appear in the
   user's own digits (grounding: a "20k"→2000 slip is dropped); answers for *other* questions are kept only
   if the text mentions that topic, and a "none/zero/no" for them needs an explicit "no" (models invent
   "no loans, no bounces"); values are range-checked; nothing is guessed. The chat echoes "Got it: …" and
   skips questions already answered. No key / Sarvam down → rules + chips still work.
1. `/msme/upload`: 6 required documents + optional ITR-V, marked required / recommended / optional /
   not needed from the questionnaire (link to the questionnaire if it was never opened). Extraction isn't wired yet, so a chosen file
   shows "received, waiting for extraction"; **"Load sample applicant A / B"** runs the real pipeline
   via `GET /v1/samples/{a|b}` → `POST /v1/assess`.
2. `/msme/review`: cross-checks (name warning has "Yes, same person", which sets `user_confirmed` and
   re-assesses; the backend then passes a near-match but never a different person), per-document
   checks, fields with confidence, "Confirm" for low-confidence fields, and the exact rows that break
   the balance math with the expected balance.
3. `/msme/readiness`: odometer dial + ring (`ScoreDial`), components, fix-it list, metrics with source.
4. `/msme/matches`: amount + tenure, **sort toggle "Lowest cost" (true APR incl. fees, default) /
   "Best fit"**, caption states the active order, fit shown as a label (strong / good / just qualifies,
   never a probability), fixes on "not yet" cards, **Apply** on amount quick fixes.
5. `/msme/offer/[id]`: KFS: amount received, EMI, total payable, cost of credit, true APR vs quoted rate,
   fees + GST, cooling-off, best/worst case, schedule.
6. `/msme/offer/[id]` also has **Apply** (consent checkbox → `POST /v1/applications`); `/msme/applications`
   shows each lender's status and decision message ("Not yet" always carries a reason).

Lender screens (`frontend/app/lender`, `LenderShell` guards the lender role): **inbox** (counts, filters,
readiness ring, red flags / warnings, fit, true APR, status), **application page** (flagged checks,
cash flow with evidence links that jump to `#field-{doc}-{field}`, fit against the lender's own rules,
EMI / true APR / FOIR after this loan, identity, read-only `DocumentCard`s, consent, history, decision
panel; opening a new application marks it in review), **Your criteria** (read-only lender products).
Applications use their own server-side profile: `submit()` re-runs `assess()` on the documents, so a
browser can't edit what lenders see. Demo seed: 3 applications under `SEED-A` / `SEED-B` (so live demos
with SAMPLE-A / SAMPLE-B start clean); DB file `backend/data/creditsetu.sqlite3` (git-ignored;
`CREDITSETU_DB`, `CREDITSETU_SEED=0` in tests via `tests/conftest.py`).

Styles: `app/dashboard.css` reuses the landing palette and fonts; calmer motion (one fade-in, the
dial). Anything that could collide with landing classes is scoped under `.shell` / `.auth`, and the
landing's lender-card list styles are scoped to `.example`, because Next keeps CSS loaded across
client-side navigation. `lib/types.ts` mirrors the backend contracts the UI reads; `lib/format.ts` has
`inr()` (Indian grouping), field labels and document metadata.

## API

| Method | Path                        | Status                            |
| ------ | --------------------------- | --------------------------------- |
| POST   | `/v1/documents`             | stub                                                     |
| GET    | `/v1/profile/{sme_id}`      | stub (no storage yet)                                    |
| POST   | `/v1/assess`                | envelopes → checked documents + `SmeProfile`             |
| POST   | `/v1/score`                 | same body as `/v1/assess` → indicative `ScoreCard` (`app/assessment`; weights uncalibrated, not used for matching) |
| POST   | `/v1/match/profile`         | `SmeProfile` + `LoanRequest` (+ `?sort=cost|fit`) → ranked lenders + fixes |
| POST   | `/v1/match`                 | flat `MatchInput` → ranked lenders (for testing rules)   |
| GET    | `/v1/lenders`               | lender products                                          |
| GET    | `/v1/offers/{id}/explain`   | `?amount=&tenure_months=` → KFS numbers                  |
| GET    | `/v1/samples/{a|b}`         | sample applicant as a ready `/v1/assess` body            |
| POST   | `/v1/prequalify`            | questionnaire answers → estimates, likely lenders, document checklist |
| POST   | `/v1/questionnaire/interpret` | `{step, text}` free-typed answer → validated answer fields (rules, then Sarvam) |
| POST   | `/v1/applications`          | MSME applies (consent required); server re-runs assess + eligibility |
| GET    | `/v1/applications`          | `?lender=` inbox or `?sme_id=` an MSME's applications    |
| GET    | `/v1/applications/{id}`     | full application: profile, documents, match, history   |
| POST   | `/v1/applications/{id}/decision` | lender: start_review / approve_in_principle / request_info (note) / decline (reason) |

Demo flow: `/v1/assess` → `/v1/match/profile` → `/v1/offers/{id}/explain`. Nothing is persisted yet;
the client passes the profile back. Storage + `sme_id`-based lookups come later.

## Pipeline: validation → scoring → engine → offers

All deterministic, all run on synthetic data today (`app/samples/`), and on Lakshya's envelopes later.

- **`app/validation/`**: `checksums.py` (Verhoeff, GSTIN check digit, state codes), `text.py` (fuzzy
  name / address match: exact = pass, initials or near-spelling = warn), `tagging.py` (bounce / EMI /
  NACH / charges / UPI / cash / GST from narrations; a bounce charge line is `charges`, not a second
  bounce, and "CHGS INCL GST" is not a GST payment), `documents.py` (per-document checks, check ids like
  `pan.format`, `bank.balance_math`, plus a `*.needs_review` warning listing low-confidence fields),
  `cross.py` (`DocumentSet` = latest envelope per type, GSTR-3B merged across uploads; the 7
  `CrossCheck`s; GST/bank ratio pass 0.7-1.3, warn 0.5-1.6).
- **`app/scoring/`**: `metrics.py` (definitions in its docstring: AMB = mean daily end-of-day balance,
  credits exclude bounce reversals, bounces in last 6 statement months, EMI = avg of last 3 months,
  FOIR = EMI / avg credits, GST turnover annualised; identity from GST > PAN, vintage from Udyam
  incorporation, else GST registration), `readiness.py` (components 25/25/15/25/10, bands ready ≥75,
  almost ≥50; **failed balance math caps the score at 49**), `fixit.py`, and `assess()` in
  `__init__.py`, the single entry point.
- **`app/offers/kfs.py`**: EMI (reducing balance, rounded to the rupee, last EMI clears the balance),
  processing fee + 18% GST, net disbursed, total payable, total cost of credit, **true APR = IRR of net
  disbursed vs EMIs, × 12**. Best and worst case from the lender's range. Uses
  `interest_rate_range_pct_pa` when published, else the APR range as a proxy (flagged in `notes`).
- **`app/samples/applicants.py`**: Applicant A (clean: readiness 100, all lenders) and B (3 planted
  problems: "RAVI KUMAAR" on bank statement → name warn; no GSTR-3B for Jul 2026 → gap fail; credit on
  10 Feb 2026 edited 24k→54k → balance-math fail → readiness capped at 49). Target output shape for
  extraction. `AS_OF = 2026-10-31` keeps tests stable.

## Schemas (`backend/app/schemas/`)

Shared contracts for extraction (OCR/VLM), validation, the MSME dashboard, the lender side and the
engine. **The two sides have different sources of truth, on purpose:**

- **MSME side: Pydantic is the source of truth.** After changing a model run
  `python -m scripts.export_schemas` from `backend/`; `tests/test_schemas.py` fails if
  `/schemas/v1/msme` is stale. Bump `SCHEMA_VERSION` on breaking changes.
- **Lender side: JSON is the source of truth.** `schemas/v1/lender/lender_product.schema.json`
  (hand-written by Anansh, JSON Schema draft 2020-12, 87 fields) is authoritative. `lender.py` mirrors
  it as Pydantic (`LenderProduct`, `LenderCatalog`) for the engine. Change the JSON first, then mirror
  it; `tests/test_lender_schema.py` fails on any drift (fields, required, enum values, all 16
  sub-objects) and validates `backend/data/lenders.json` + the example against both. Never generate the
  lender JSON from Python. `allowed_constitutions` uses the same values as MSME `Constitution`.
- `common.py`: `Extracted[T]` (value + confidence + source + bbox + raw_text + user_confirmed, with a
  computed `needs_review` when confidence < `REVIEW_CONFIDENCE` 0.85 or value missing),
  `RowProvenance` (one per table row, not per cell), `Sourced[T]` (profile value + `EvidenceRef`s back
  to document fields), `Check` (pass / warn / fail + plain-language message), enums (`DocumentType`,
  `Source`, `Constitution`, `MsmeCategory`, `CrossCheck` ids), format regexes (PAN, GSTIN, IFSC, Udyam,
  pincode).
- `documents.py`: one model per document (`PanCard`, `Aadhaar`, `GstRegistration`, `Gstr3b`,
  `BankStatement`, `Udyam`, `ItrV`) and `DocumentEnvelope` (file info, `Triage` = which extractor and
  whether it fell back to VLM, status, checks, `data` discriminated by `document_type`).
- `profile.py`: `SmeProfile` (identity, `CashflowMetrics`, `BureauScore` with source
  mock/self_declared/bureau, document summaries, cross-checks, `Readiness` 0-100 with components,
  `fix_it` list) and `LoanRequest` (kept separate: one profile, many requests).
- `examples.py`: synthetic Applicant A objects used by tests and exported as example JSON.

Conventions: money in rupees (float, compare with ₹0.01 tolerance); bbox coordinates are page
fractions 0-1; extracted values are NOT pattern-constrained (a misread must be storable so validation
can flag it); all models forbid unknown fields. **Privacy is enforced by types**: Aadhaar and bank
account numbers are `Last4` (exactly 4 digits), so a full number cannot be stored.

Demo documents: PAN (photo→VLM), Aadhaar (photo→VLM), GST REG-06 (PDF→parser), GSTR-3B 6 months
(PDF→parser), bank statement 6-12 months (scanned PDF→OCR tables), Udyam (PDF or photo), ITR-V
optional (PDF→parser).

## Recommendation engine (`backend/app/recommendation/`)

- `models.py`: `MatchInput` (flat engine input), `CheckResult` (outcome pass / warn / fail / missing),
  `Fix`, `MatchResult` (with `fixes` and `quick_fix`); re-exports the shared `LenderProduct`.
- Rules cover ticket size, tenure, vintage (per-constitution override wins), turnover, bureau
  (`bureau_score_is_hard_cutoff: false` → **warn**, not fail), FOIR, bounces, statement months, age,
  GST / ITR / Udyam required, constitution, excluded + eligible sectors, negative geographies,
  collateral-free limit (above it → warn). `warn` never blocks; it counts as zero headroom in fit.
  Not ruled on yet: `ticket_size_tiers`, `udyam_preferred`, charges, internal score thresholds.
- `fixes.py`: the "not yet" path. Each blocking check becomes one `Fix` computed from the gap:
  change_request ("Ask for ₹12,00,000 or less"), wait ("Eligible in 10 months"), improve ("Raise your
  bureau score by 25 points", "Reduce existing EMIs by about 20%"), add_document, add_info,
  not_eligible. A product whose fixes are all change_request is a `quick_fix`.
- `adapter.py`: `match_input(SmeProfile, LoanRequest) -> MatchInput`. The only place that knows both
  shapes; if `SmeProfile` changes, change this.
- `rules.py`: `RULES` list, one rule per criterion. Numeric min/max criteria are one `Threshold(...)`
  line; others are small functions. A rule returns `None` when the lender doesn't set that criterion.
- `engine.py`: hard filters → fit score → rank.
  - Any `fail` or `missing` check makes a product `not_yet`; check messages become the reasons
    ("Business vintage: needs at least 24 months, you have 14 months").
  - Fit score (matched only) = average headroom (0–1) across passing numeric thresholds × 100.
  - Rank: the SME chooses. `sort=cost` (default): matched by true APR incl. fees, then fit; `sort=fit`:
    by fit, then true APR. Not-yet always after matched: quick fixes first, then fewest fixes, then APR.
  - Each result carries `true_apr_pct` (best case, for the requested amount + tenure) and `fit_label`.
- `lenders.py`: loads `data/lenders.json`.
- `inr()` in `rules.py` formats rupees with Indian grouping (₹15,00,000).

**Schemas are not final.** Every lender criterion is optional (`null` = no requirement). To add one:
add the field to `LenderProduct` (+ matching field on `MatchInput`, filled in `adapter.py`), add a rule to `RULES`, set it on
the records that need it. Missing profile data is reported as `missing`, never guessed.

Ranking decision (settled): the borrower picks the order, defaulting to lowest true APR, and the UI says
which order is active. Reason: "fit" alone ranks lenient expensive lenders above strict cheap ones, and
an LSP should present matching offers in an unbiased, comparable way (check the exact RBI Digital Lending
Directions wording before quoting it).

Demo expectations (covered by tests, full pipeline from documents): Applicant A matches all 3 lenders;
Applicant B is "not yet" for Demo Bank A with vintage / turnover / bureau / bounce fixes and matched for
Demo NBFC B. At ₹14 lakh, B's Demo Finance C becomes a quick fix ("Ask for ₹12,00,000 or less").

## Landing page (`frontend/`)

Inspired by the *feel* of worldquant.com (dark, huge type, scroll-driven motion). Never copy their
assets, copy, fonts or logo.

**Design system** (CSS variables in `globals.css`):
- Background `--bg #050507`, text `--ink #f4efe6`, muted `--muted #9d978b`, accent `--gold #f2b544`,
  secondary `--navy #333d6f`. Gold-on-black is the look; avoid green/purple/pink.
- Fonts via `next/font/google`: Outfit (Latin) + Noto Sans Devanagari / Kannada / Tamil.
- Logo: inline SVG bridge arc (`BridgeMark` in `page.tsx`).

**Sections (top to bottom):** hero (gold-lines video, letter-by-letter title) → problem (pinned,
statements swap over live ASCII render of the knot video) → "not yet" (words light up on scroll +
sample lender cards using real engine messages) → readiness score (rings video, odometer digits roll
to 82 + gauge ring draws, plays once, not scroll-scrubbed) → 5 steps → aggregator comparison (lines
draw) → languages (pinned, blur crossfade) → for lenders (video band with parallax + profile panel) →
CTA (tunnel video) → footer.

**Motion** lives entirely in `components/landing/LandingMotion.tsx` (GSAP 3 + ScrollTrigger, Lenis
smooth scroll). Elements opt in with `data-*` attributes (`data-reveal`, `data-lines`,
`data-scramble`, `data-magnetic`, `data-fill`, …). Respect `prefers-reduced-motion` (every effect must
leave content visible). The `js` class on `<html>` (set in `layout.tsx`) is used to hide elements
GSAP animates in, so nothing is hidden when JS is off.

**User feedback so far, keep honoring it:**
- No "plain video playing site": every section needs real transitions.
- Effects must complete while their content is on screen (the old warped-text effect never finished
  and was removed).
- No circular clip-path reveals; no scroll-scrubbed number counters.
- No sliced static-image strips; use live video instead of stills.
- Video quality matters: don't upscale low-res encodes.

**Videos** (Pexels, free licence; all gold-on-black): `hero-lines`, `problem-knot` (ping-ponged so it
loops), `process-rings`, `cta-tunnel` in `public/media/` with `.jpg` posters. `BgVideo` lazy-loads and
plays only on screen; data-saver / reduced-motion users get the poster. Re-encode from `movies/` with
ffmpeg (H.264, `-an -movflags +faststart`); keep each ≤ ~4 MB except `process-rings` (11 MB at 1920px,
particles compress badly and lower settings looked blurry).

Translations on the languages section (Hindi, Kannada, Tamil) were machine-drafted: get a native
speaker to check before demoing. Score 82, ₹ figures and "R. Kumar" are sample data.

## Open items (from the team's notes)

- Final product name; VLM choice (hosted vs self-hosted) and the privacy answer.
- Business-model fee numbers (suggested: success fee 1–2%, lead fee ~₹300–500, SaaS ~₹25–50k/mo).
- Confirm MVP scope (currently 3 document types, 5 mock lenders, Hindi + English).
- Generate synthetic documents for Applicant A (clean) and B (3 planted errors: name mismatch on bank
  statement, one missing month, one edited row breaking balance math).
- Mock lenders: 3 of 5 exist. Missing: Mudra-style micro loan and CGTMSE collateral-free loan; check
  official scheme limits before adding.
- Registration flow and dashboard (separate from the landing page).
- `next@14.2.5` has a published security advisory; bump to a patched 14.2.x.

## Working agreements

- Commit only when asked; branch off `main` for work.
- Run `pytest` (backend) and `npm run build` (frontend) before declaring work done.
- Keep raw media out of git; commit `package-lock.json`.
