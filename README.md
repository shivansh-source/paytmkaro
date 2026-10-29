# CreditSetu Skeleton (Next.js + FastAPI)

Simple, editable project skeleton for the CreditSetu hackathon build.

## Structure

- `apps/web` — Next.js + TypeScript frontend skeleton
- `apps/api` — FastAPI backend skeleton
- `apps/api/schemas/documents/v1` — editable document schemas
- `apps/api/schemas/lenders/v1` — editable lender criteria schema + sample products

## API Sketch Included

- `POST /v1/documents` (upload triage stub)
- `GET /v1/profile/{sme_id}`
- `POST /v1/match`
- `GET /v1/offers/{offer_id}/explain`

## Quick Start (when you want to run)

### API

```bash
cd apps/api
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### Web

```bash
cd apps/web
npm install
npm run dev
```

## Editing Schemas Later

- Document extraction schema files: `apps/api/schemas/documents/v1/*.json`
- Lender rules schema: `apps/api/schemas/lenders/v1/lender_product.schema.json`
- Demo lender records: `apps/api/schemas/lenders/v1/lender_products.sample.json`

The backend loads sample lender records from disk so you can edit them without touching Python code.
