# CreditSetu

AI copilot that makes Indian SMEs lender-ready and matches them to the right lender, with reasons.
Built for the Paytm Build for India AI Hackathon by Team Cash for Delivery.

## Layout

```
backend/                      FastAPI service
  app/
    main.py                   creates the app, mounts routers
    config.py                 paths
    api/v1/                   thin HTTP routes, one file per resource
    recommendation/           lender matching engine
      models.py               SMEProfile, LenderProduct, MatchResult
      rules.py                one rule per lender criterion
      engine.py               hard filters -> fit score -> rank
      lenders.py              loads lender records
  data/
    lenders.json              mock lender products (edit freely)
    sample_profiles/          demo applicants: A (clean), B (messy)
  schemas/documents/v1/       JSON schemas for document extraction
  tests/
frontend/                     Next.js app
```

Each pipeline stage gets its own package under `backend/app/` (e.g. `documents/`, `scoring/`,
`offers/`), and the routes in `api/v1/` only call into those packages.

## API

| Method | Path                         | Status                              |
| ------ | ---------------------------- | ----------------------------------- |
| POST   | `/v1/documents`              | stub                                |
| GET    | `/v1/profile/{sme_id}`       | stub                                |
| POST   | `/v1/match`                  | working: ranked lenders + reasons   |
| GET    | `/v1/lenders`                | working: lender products            |
| GET    | `/v1/offers/{id}/explain`    | stub                                |

Interactive docs and request/response schemas: http://localhost:8000/docs

## Recommendation engine

1. **Hard filters.** Every rule in `rules.py` checks one lender criterion. A failed check, or
   missing SME data for a criterion the lender sets, makes the product "not yet"; the failed
   check's message becomes the fix-it reason ("Business vintage: needs at least 24 months, you
   have 14 months").
2. **Fit score.** For matched products, the average headroom across numeric thresholds (how far
   past each bar the SME is), 0 to 100.
3. **Rank.** Matched by fit, then APR; not-yet by fewest blockers, then APR.

Scores are computed in code; an LLM may later narrate them but never decides them.

### Changing the schema

Lender criteria and profile fields are not final. Every lender criterion is optional (`null` means
"no requirement"), so to add one:

1. Add the field to `LenderProduct` (and the matching field to `SMEProfile`) in `models.py`.
2. Add a rule to `RULES` in `rules.py`. Numeric min/max criteria are one `Threshold(...)` line.
3. Set the field on whichever records in `data/lenders.json` need it.

## Running locally

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
pytest
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

## Demo data

All documents, applicants and lenders are synthetic and marked SAMPLE / Demo. Never use a real
Aadhaar or PAN.
