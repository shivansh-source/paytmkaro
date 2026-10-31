# CreditSetu

AI copilot that makes Indian SMEs lender-ready and matches them to the right lender, with reasons.
Built for the **Paytm Build for India AI Hackathon** (problem statement: *AI Powered Financial Journeys*)
by **Team Cash for Delivery**: Shivansh Sinha, Lakshya Karira, Anansh Srivastava. "CreditSetu" is a
working name ("setu" = bridge).

**One-liner:** weeks of paperwork and lender-hopping become one application and a matched, explained
shortlist in under a day. The lender still makes the credit decision, on a complete, verified file.

## How the team works

No one owns any part of the code: all three of us work on everything together. Before changing a
shared contract, tell the others, because several parts read it:
- `SmeProfile` / `CashflowMetrics` / `Readiness` are read by both dashboards, the engine adapter, lender
  applications and the assessment engine.
- `DocumentEnvelope` is the extraction contract: extraction output must become it (`schemas/v1/msme/`).
  Aadhaar is masked in the extraction layer (Verhoeff on the full number, then only `aadhaar_last4`
  leaves it). Values that fail validation are kept (low confidence), not dropped, so checks can show ✗
  and the user can confirm.
- The lender schema `schemas/v1/lender/lender_product.schema.json` is the source of truth for lenders.

Placement rules worth keeping: transaction tagging (bounce / EMI / NACH) from narrations happens in
validation, not extraction. Keep one scoring implementation (`app/scoring/`);
`app/documents/extract/features.py` is an older duplicate of validation + scoring and is superseded.

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
    documents/           ingest / classify / extract pipeline (OCR, VLM, privacy masking)
    intake/              upload → pipeline → DocumentEnvelope: bridge.py (field mapping), upload.py
    assessment/          indicative lender ScoreCard (51-parameter registry, DESIGN.md)
  data/
    lenders.json         mock lender products (edit freely; re-read on every request)
    sample_profiles/     MatchInput fixtures: applicant_a.json (clean), applicant_b.json (messy)
  schemas/documents/v1/  extraction output schemas (incl. 5 new types, see "What's left")
  scripts/export_schemas.py   regenerates /schemas from the Pydantic models
  tests/                 pytest, one folder per app package (see "Tests")
schemas/v1/msme/         GENERATED from Pydantic (never edit by hand)
schemas/v1/lender/       HAND-WRITTEN lender JSON Schema: source of truth for the lender side
frontend/                Next.js 14 app router, TypeScript, no Tailwind (plain CSS)
  app/page.tsx           landing page
  app/globals.css        landing styles; app/dashboard.css: login + both dashboards
  app/register/          role choice → details → mock OTP
  app/msme/              MSME dashboard (start, upload, review, readiness, matches, offer, applications)
  app/lender/            lender inbox, application page, criteria
  components/            landing/, auth/, msme/ (MsmeProvider, Shell), lender/, DocumentCard
  components/landing/    BgVideo, AsciiVideo, LandingMotion
  public/media/          compressed background videos + poster jpgs
  movies/                raw stock footage, gitignored, never commit
```

Convention: each pipeline stage gets its own package under `backend/app/` (`documents/`, `validation/`,
`scoring/`, `recommendation/`, `offers/`, …) with tests in the matching `tests/` folder; routes in
`api/v1/` only call into those packages.

## Commands

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload        # http://localhost:8000/docs
pytest                                # pythonpath configured in pyproject.toml
pytest tests/validation               # one area only (folders listed under "Tests")

# frontend
cd frontend
npm install
npm run dev                           # http://localhost:3000
npm run build                         # must pass before committing
```

### Tests (`backend/tests/`, one folder per app package)

```
conftest.py        autouse: no real Sarvam call, fresh SQLite applications store per test
schemas/           test_msme_schemas (exported JSON up to date, privacy types), test_lender_schema (JSON ↔ Pydantic drift)
validation/        test_checksums, test_text_matching, test_tagging, test_document_checks (A clean, B's 3 problems)
scoring/           test_scoring (metrics, readiness, fix-it)
assessment/        ScoreCard tests + test_score_api
recommendation/    test_engine_rules (one rule at a time), test_recommendation (ranking, fixes, demo expectations)
offers/            test_kfs (EMI, fees, true APR)
questionnaire/     test_prequalify (estimates, checklist), test_understand (free text: rules, fake LLM, guardrails)
applications/      test_applications (consent, re-assess, decisions)
api/               test_demo_flow (assess → match → offer through HTTP, samples)
intake/            test_bridge (pipeline → envelope, kept failed reads, boxes, privacy), test_upload_api
documents/         ingest / classify / extract / privacy tests (own conftest with skip guards)
fixtures/          sample .docx/.pdf inputs + make_sample_documents.py
```

New tests go in the folder of the package they test. There are no `__init__.py` files (pytest's default
import mode), so **test file names must be unique across folders**. Baseline: 527 passed, 7 skipped.

The dashboard calls `/api/v1/*`, which `next.config.mjs` rewrites to FastAPI (`BACKEND_URL`, default
`http://localhost:8000`), so run the backend alongside the frontend. No CORS setup needed.

**AI keys** live in `backend/.env` (git-ignored, loaded by `app/config.py`): `SARVAM_API_KEY` (free-text
questionnaire), `GROQ_API_KEY` (VLM fallback for photos). Never paste keys in chat or commit them. Tests never call a
real model: `tests/conftest.py` blanks `SARVAM_API_KEY`, `tests/questionnaire/test_understand.py` injects a fake,
and `tests/intake/conftest.py` gives the upload route no OCR / VLM (tests pass `FakeOcr`). Real-engine tests are
opt-in: `RUN_OCR_TESTS=1`, `RUN_VLM_TESTS=1`.

**OCR / VLM for uploads.** Digital PDFs, spreadsheets, Word and CSV need neither. Photos and scans need
**PaddleOCR** (in `requirements.txt`, about 1 GB; models download on first use, then ~8 s per photo on CPU).
The Groq VLM only fills what text/OCR missed. **Without PaddleOCR the VLM is off for uploads** (images would
leave the server before any Aadhaar number was blacked out); `VLM_WITHOUT_OCR=1` overrides that knowingly.
Free-tier Groq can take 40-80 s on a photo (rate limits), so the Next proxy timeout is raised to 180 s.
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
   not needed from the questionnaire (link to the questionnaire if it was never opened). Choosing a file
   **uploads it** (`POST /v1/documents`, "Reading…" while it runs; GSTR-3B takes several files), then the
   provider re-assesses every uploaded envelope (`/v1/assess`, latest result wins if uploads overlap). A new
   upload replaces the same document type; GSTR-3B months add up. Locked PDFs show a password box; parts we
   can't use show the reason ("looks like a photo and OCR isn't on", "bureau report: not scored yet"). The
   `sme_id` is `SME-<mobile>`. **"Load sample applicant A / B"** still loads the synthetic applicants
   (`GET /v1/samples/{a|b}`) and clears uploads.
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
Applications use their own server-side profile: `submit()` re-runs `assess()` on the documents it is
sent, so lenders see our checks' results, not a profile the browser computed (documents are still
browser-supplied until uploads are stored server-side). Demo seed: 3 applications under `SEED-A` / `SEED-B` (so live demos
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
| POST   | `/v1/documents`             | multipart `file`, `sme_id`, optional `document_type` (slot hint) + `password` → `UploadResult`: envelopes, skipped parts with reasons, warnings. Always 200; `status` says `password_required` / `unsupported_format` / … Nothing stored |
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

Demo flow: `/v1/documents` (per file) → `/v1/assess` → `/v1/match/profile` → `/v1/offers/{id}/explain`. Nothing is persisted yet;
the client passes the profile back. Storage + `sme_id`-based lookups come later.

## Pipeline: validation → scoring → engine → offers

All deterministic, all run on synthetic data today (`app/samples/`), and on extracted envelopes later.

- **`app/validation/`**: `checksums.py` (Verhoeff, GSTIN check digit, state codes), `text.py` (fuzzy
  name / address match: exact = pass, initials or near-spelling = warn; a bracketed business name as in
  "R. KUMAR (KUMAR TRADERS)" is tried with and without the brackets), `tagging.py` (bounce / EMI /
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
  `python -m scripts.export_schemas` from `backend/`; `tests/schemas/test_msme_schemas.py` fails if
  `/schemas/v1/msme` is stale. Bump `SCHEMA_VERSION` on breaking changes.
- **Lender side: JSON is the source of truth.** `schemas/v1/lender/lender_product.schema.json`
  (hand-written, JSON Schema draft 2020-12, 87 fields) is authoritative. `lender.py` mirrors
  it as Pydantic (`LenderProduct`, `LenderCatalog`) for the engine. Change the JSON first, then mirror
  it; `tests/schemas/test_lender_schema.py` fails on any drift (fields, required, enum values, all 16
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

**Schema 1.1** (readers still accept 1.0 payloads, so profiles saved in the browser keep working):
`Transaction.balance` and `Aadhaar.dob` can be null (read code must cope), `opening_balance` is optional,
and `Aadhaar.year_of_birth`, `Transaction.ref` and the `input_kind` values `spreadsheet` / `word` / `text`
were added. A row with no printed balance is kept, never dropped; validation chains a running total through
it, and `bank.balance_math` is a warning (never a pass) when fewer than half the rows can be checked.
Not in the envelope yet: bureau report, financial statements, sanction letter, settlement report (their
extraction is returned raw).

**Extraction entry point:** `app/documents/process.py::process_upload(bytes, file_name, sme_id=...)` runs
ingest → classify → extract → `DocumentEnvelope` with one shared VLM budget and never raises (it returns a
status). It also offers `bureau` from an uploaded report as `self_declared` (unverified); nothing passes it to
`assess()` yet. `/v1/documents` is still a stub.

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

## Assessment engine (`backend/app/assessment/`, PR #6)

Lender-facing **indicative** `ScoreCard`: `score_sme(profile, validated_documents, as_of=...)`, exposed as
`POST /v1/score` (same body as `/v1/assess`). Full design, registry table, math and fairness policy in
`app/assessment/DESIGN.md` (drift-tested against `registry.py` + `config.json`).

- 51 parameters, each shown as computed / pending / not_applicable with value, band, points, weight,
  reason and evidence refs. Index 0-100 = weighted mean over *available* weight, with coverage % beside
  it; bands strong / moderate / cautious / weak / insufficient_data (< 25% coverage). Failed balance math
  or a PAN/GSTIN mismatch caps the grade at "cautious".
- **Not** readiness (readiness = is the file complete and consistent, for the SME), **not** a probability
  of default, and **not used for lender matching** (matching stays on documented lender criteria).
- Only 11 weights come from the reference scorecard; the other 40 are **uncalibrated placeholders**. Say
  "indicative" in any UI or pitch.
- Field lock keeps personal identifiers out of the feature table; age, state and pincode are never scored.
- Not shown in the lender UI yet. Many pending parameters need schema additions proposed in
  DESIGN.md §7 (bureau report details, financial statements, sanction letter, settlement report,
  hashed counterparty key): these touch `SmeProfile` / `DocumentEnvelope`, so agree as a team first.

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

## Status and what's left (as of 31 Oct 2026, main @ PR #6)

**Built (on main):**
- **MSME side:** questionnaire with Sarvam free text → upload → review → readiness → matches → KFS offer
  → apply → application status.
- **Lender side:** inbox, application page, decisions, criteria.
- **Recommendation engine** (matching, ranking, "not yet" fixes) and KFS / true APR.
- **Scoring engine:** validation, metrics, readiness, fix-it, plus the indicative assessment engine and
  `/v1/score` (PR #6).
- Landing page, login, extractor + classifier (PR #3).

- **Uploads connected to extraction** (`app/intake/`, `POST /v1/documents`, upload page): real files go
  ingest → classify → extract → envelope → assess. Verified on Lakshya's fixtures: digital PDFs, XLSX, a
  bundled PDF (split per document), a password-protected e-Aadhaar, phone photos via PaddleOCR (with boxes).

The demo runs end to end on uploaded files **and** on the built-in sample applicants.

**Next (the demo needs these):**
1. **Real sample documents** for Applicant A (clean) and B (3 planted problems), stamped SAMPLE: PAN and
   Aadhaar as phone photos, GST REG-06 + 6 GSTR-3B as PDFs, a scanned bank statement, Udyam. They should
   reproduce `app/samples/applicants.py` so the same checks fire on uploads. Lakshya's
   `tests/fixtures/make_sample_documents.py` already writes PDFs/images; extend it rather than start over.
2. **Highlight boxes on the review page:** envelopes now carry `bbox` for OCR'd fields, but the review page
   doesn't show the document image yet (needs the page image served or returned with the upload).
3. **Store uploads server-side** (encrypted): today envelopes live in the browser and are sent back to
   `/v1/assess` and `/v1/applications`. Applications should reference stored document ids so a browser can't
   alter what lenders see. Pairs with the encryption item.
4. WIP commit `1e8640c` (five new document types in classify / extract) was flagged "unreviewed": review it
   before relying on it. Those types are read but skipped at upload ("not used in your score yet").
5. Aadhaar address is often not read (seen on the e-Aadhaar fixture): check the extractor.
6. Discussed, not built: mock **Account Aggregator** (bank data by consent, no OCR) and mock **DigiLocker**
   (PAN / Aadhaar / GST pulled verified), both feeding `/v1/assess` directly; **encryption at rest** for stored
   uploads and the applications DB; **Docker** compose for backend + frontend.

**Later, as polish (AI layer, deliberately postponed):**
- Sarvam explaining offers and fixes in Hindi and English (narrates engine output, never changes it), plus
  voice for the offer summary.
- An AI credit summary on the lender application page.
- Lender policy PDF → criteria record (a human confirms it).
- Possibly the assessment ScoreCard on the lender page, labelled "indicative".

**Smaller items:**
- Mock lenders: 3 of 5 exist. Missing: Mudra-style micro loan and CGTMSE collateral-free loan;
  check official scheme limits before adding.
- Schema additions from `app/assessment/DESIGN.md` §7 (decide which, if any, before the demo).
- "Declared vs verified": compare questionnaire answers with document-derived numbers.
- `next@14.2.5` has a published security advisory; bump to a patched 14.2.x.
- Native-speaker check of Hindi / Kannada / Tamil copy; favicon; mobile pass; demo script.
- Open decisions: final product name; hosted vs self-hosted VLM and the privacy answer; fee numbers
  (suggested: success fee 1–2%, lead fee ~₹300–500, SaaS ~₹25–50k/mo).

## Working agreements

- Commit only when asked; branch off `main` for work.
- Run `pytest` (backend) and `npm run build` (frontend) before declaring work done.
- Keep raw media out of git; commit `package-lock.json`.
