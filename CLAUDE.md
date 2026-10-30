# CreditSetu

AI copilot that makes Indian SMEs lender-ready and matches them to the right lender, with reasons.
Built for the **Paytm Build for India AI Hackathon** (problem statement: *AI Powered Financial Journeys*)
by **Team Cash for Delivery**: Shivansh Sinha, Lakshya Karira, Anansh Srivastava. "CreditSetu" is a
working name ("setu" = bridge).

**One-liner:** weeks of paperwork and lender-hopping become one application and a matched, explained
shortlist in under a day. The lender still makes the credit decision, on a complete, verified file.

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
    recommendation/      lender matching engine (see below)
  data/
    lenders.json         mock lender products (edit freely; re-read on every request)
    sample_profiles/     applicant_a.json (clean), applicant_b.json (messy)
  schemas/documents/v1/  JSON schemas for document extraction (pan_card, gst_reg06)
  tests/                 pytest
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

The dev machine is Windows; Bash (Git Bash) and PowerShell are both available.

## API

| Method | Path                        | Status                            |
| ------ | --------------------------- | --------------------------------- |
| POST   | `/v1/documents`             | stub                              |
| GET    | `/v1/profile/{sme_id}`      | stub                              |
| POST   | `/v1/match`                 | working: ranked lenders + reasons |
| GET    | `/v1/lenders`               | working: lender products          |
| GET    | `/v1/offers/{id}/explain`   | stub (KFS)                        |

`/v1/match` currently takes the full `SMEProfile` in the body; later it should take an `sme_id` and load
the validated profile.

## Recommendation engine (`backend/app/recommendation/`)

- `models.py`: `SMEProfile` (engine input), `LenderProduct` (criteria + pricing), `CheckResult`,
  `MatchResult`. Pydantic models are the single source of truth for the schema (see `/docs`); there is
  no hand-written lender JSON schema.
- `rules.py`: `RULES` list, one rule per criterion. Numeric min/max criteria are one `Threshold(...)`
  line; others are small functions. A rule returns `None` when the lender doesn't set that criterion.
- `engine.py`: hard filters → fit score → rank.
  - Any `fail` or `missing` check makes a product `not_yet`; check messages become the reasons
    ("Business vintage: needs at least 24 months, you have 14 months").
  - Fit score (matched only) = average headroom (0–1) across passing numeric thresholds × 100.
  - Rank: matched by fit desc then APR asc; not-yet by fewest blockers then APR.
- `lenders.py`: loads `data/lenders.json`.
- `inr()` in `rules.py` formats rupees with Indian grouping (₹15,00,000).

**Schemas are not final.** Every lender criterion is optional (`null` = no requirement). To add one:
add the field to `LenderProduct` (+ matching field on `SMEProfile`), add a rule to `RULES`, set it on
the records that need it. Missing profile data is reported as `missing`, never guessed.

Known open decision: "fit, then APR" ranks lenient expensive lenders above strict cheap ones (Applicant
A sees Demo Bank A, the cheapest, last). Ranking matched products by APR with fit as tie-breaker is a
one-line change in `_rank_key`; not decided yet.

Demo expectations (covered by tests): Applicant A matches all 3 lenders; Applicant B is "not yet" for
Demo Bank A with vintage/turnover/bureau/bounce reasons and matched for the other two.

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
