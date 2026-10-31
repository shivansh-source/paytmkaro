# SME assessment engine (`app/assessment`): design

Status: first slice. Deterministic code, synthetic data, **uncalibrated placeholder weights**.
Owner: Lakshya (with Claude). Read-only dependencies: `app/scoring`, `app/validation`, `app/schemas`, `app/samples`.

## 1. Purpose and non-goals

**Purpose.** Give a lender a transparent, weighted, parameter-by-parameter view of an SME's credit-relevant
signals, computed in code from the documents the SME already provided. Every parameter shows its value, band,
points, weight, the document fields it came from and a plain-language reason. Parameters we cannot compute yet
stay in the output as empty ("null") columns that say exactly what they are waiting for.

**It is an indicative assessment.** The lender still makes the credit decision.

Non-goals, stated so nobody builds on a wrong assumption:

- **Not a probability of default, not approval odds, not a credit or bureau score.** The output is an index of
  0-100 plus a band (`strong`, `moderate`, `cautious`, `weak`, `insufficient_data`). It never says "approved"
  or "rejected".
- **Not the readiness score.** Readiness (`app/scoring/readiness.py`) measures how complete and consistent the
  SME's *file* is, to help the SME fix it. This engine looks at the *business signals* inside that file for the
  lender. They share inputs (`SmeProfile`) and nothing else; this package does not edit or duplicate readiness
  or metric definitions.
- **Not an input to lender matching.** `app/recommendation` ranks on documented, impartial criteria (RBI's Digital
  Lending Directions expect an LSP to document its matching logic). Feeding an uncalibrated index into ranking
  would change that logic, so it is deliberately not wired. Any future use needs a separate decision.
- **Not a place for age or geography.** Age is a lender *eligibility* rule in the recommendation engine. State and
  pincode are not scored (redlining risk). See section 6.
- **No LLM decides or invents a number.** An LLM may later *narrate* a ScoreCard; it never sets one.

## 2. How it fits the pipeline

```
documents -> extraction (OCR/VLM) -> DocumentEnvelopes
          -> validation (tags, per-document and cross-document checks)
          -> scoring.assess()  -> SmeProfile (identity, cash-flow metrics, bureau, cross-checks, readiness)
          -> assessment.score_sme(profile, validated_documents, as_of=...)  -> ScoreCard   (this package)
          -> lender view (explains every parameter, with evidence links back to document fields)
```

Entry point: `score_sme(profile, documents, *, as_of=None, config=None) -> ScoreCard`. `documents` must be the
**validated** envelopes (`assess(...).documents`), because bounce / cash / UPI tags are applied by validation.
`as_of` defaults to `profile.updated_at.date()`; the system clock is never read. No API route exists yet; the
coordinator wires it.

Module map: `config.json` + `config.py` (weights, bands, policy), `registry.py` (one entry per parameter),
`features.py` (pure feature functions with evidence), `confidence.py` (input-quality tiers), `fieldlock.py`,
`models.py` (ScoreCard and friends), `scorer.py` (`score_sme`).

Adding a parameter is one `Parameter(...)` entry in `registry.py` plus its weight and bands under the same id in
`config.json` (and a small function in `features.py` if it can be computed). `tests/assessment` fails if the two
files disagree.

## 3. Parameter registry

The structure is adapted from an internal lender reference scorecard of 51 parameters (40 computable from its
documents, 11 pending, each pending one kept as a null column rather than dropped). Our registry also has 51
entries. The documents differ (India), so a different 39 are computable today and 12 are pending; 8 of the 12 are
the reference's own pending parameters, with the reference's weights.

<!-- registry-summary total=51 computable=39 pending=12 total_weight=85 computable_weight=70 pending_weight_in_base=15 reference_total=11 reference_total_weight=18 reference_computable=3 outside_weight_base=1 -->

- **51** parameters; **39 computable today** (weight 70 of 85), **12 pending** (weight 15 inside the base;
  one more of them, `rb.responsiveness`, weight 1, is outside the base, see below).
- The reference scorecard documents exactly **11 weights** (3,2,1,1,1,3,1,3,1,1,1 = 18) and they are kept as they
  are. Three of those 11 parameters (`bc.margin_facility`, `bc.facility_trend`, `rb.adverse_flags`) can be computed
  in India now that the sanction letter and bureau report have envelopes; the other 8 stay pending. The remaining
  **40 weights are our placeholders.** Weight source is shown per row: `reference` means "documented in the
  reference, not validated for India"; `placeholder` means "our guess". **No weight in this package is calibrated.**
- Two of the 39 computable parameters (`sp.itr_filed`, `sp.itr_income_margin`, weight 3 together) need the optional
  ITR-V. Twelve more read documents the sample applicants do not upload (bureau report, financial statements,
  sanction letter, settlement report), so for the samples all of these show as pending at run time. Registry-level
  "computable" means a schema field exists; run-time status says whether the document was provided.
- Maximum coverage today with every supported document, a real bureau pull and an ITR-V: 70/85 = 82.4%.
  Applicants A and B (six core documents, mock bureau score counted at half weight): 38.5/85 = 45.3%, unchanged,
  because they carry none of the four newer document types.
- **Decision: `rb.responsiveness` is outside the weight base** (`in_total: false`). The reference scorecard leaves it
  out of its calculation "for now" (it is derived from relationship-manager timestamps, not documents). It still
  appears in every ScoreCard as pending. Its equivalent bureau-adverse-flags parameter (`rb.adverse_flags`) is kept
  inside the base, because written-off / suit-filed / wilful-default flags matter in India.
- Considered and left out on purpose: promoter years of experience or residence (correlates with age; not a signal
  in India), current ratio (covered by `fn.leverage` and `fn.dscr` for now), UPI share of inflow (would penalise
  cash-heavy sectors; see the cash share flag).

Direction matters: for the consumer bureau score higher is better; CIBIL MSME Rank (CMR 1-10) runs the other way
(1 is best), so its bands will be written lowest-first when the field exists.

Band points are 0-100; bands are evaluated in order and the first match wins. Thresholds are INR-sensible
placeholders. Table (generated by `python -m app.assessment.design_table` from `registry.py` and `config.json`; a test fails if it drifts):

<!-- registry-table:start -->
| id | category | India source documents | input field | formula | bands (value=points) | weight | status today | waits for |
|---|---|---|---|---|---|---|---|---|
| `cp.vintage` | Company profile | Udyam certificate, GST registration | `SmeProfile.identity.business_vintage_months` | months from Udyam incorporation (else GST registration) to as_of | >=60=100; >=36=80; >=24=60; >=12=40; else=15 | 2 (placeholder) | computable |  |
| `cp.constitution` | Company profile | GST registration, PAN, Certificate of Incorporation | `SmeProfile.identity.constitution` | category lookup | pvt_ltd=100; public_ltd=100; llp=90; partnership=70; proprietorship=55; huf=55; trust=50; society=50; other=40 | 1 (placeholder) | computable |  |
| `cp.msme_category` | Company profile | Udyam certificate | `SmeProfile.identity.msme_category` | category lookup | micro=60; small=75; medium=90 | 1 (placeholder) | computable |  |
| `cp.udyam_registration` | Company profile | Udyam certificate | `DocumentEnvelope[udyam].data.udyam_number` | present and matches UDYAM-XX-00-0000000 | registered=100; invalid_format=20 | 1 (placeholder) | computable |  |
| `cp.gst_registration_tenure` | Company profile | GST REG-06 certificate | `DocumentEnvelope[gst_registration].data.registration_date` | months from registration date to as_of | >=36=100; >=24=80; >=12=55; >=6=35; else=15 | 1 (placeholder) | computable |  |
| `cp.premises_proof` | Company profile | Registered rent or lease agreement, utility bill | `(proposed) DocumentType rent_agreement: lease_end_date, is_registered` | months of lease remaining and registration status | not defined until computable | 1 (placeholder) | pending (schema) | document rent_agreement (lease_end_date, is_registered) or utility_bill |
| `cp.operating_licence` | Company profile | Shop and Establishment licence, Certificate of Incorporation | `(proposed) DocumentType operating_licence: valid_to` | licence present and unexpired at as_of | not defined until computable | 1 (placeholder) | pending (schema) | document operating_licence (licence_type, valid_to) |
| `cp.employee_base` | Company profile | EPFO ECR and ESIC returns, payroll register | `(proposed) DocumentType epfo_esic_return: employee_count, months_filed_12m` | employee count and share of the last 12 months with dues filed | not defined until computable | 1 (placeholder) | pending (schema) | document epfo_esic_return (employee_count, months_filed_12m) |
| `cp.warehouse_status` | Company profile | Warehouse rent agreement or 3PL contract (trading firms only) | `(proposed) DocumentType rent_agreement with premises_type = warehouse` | owned = best, rented, third party; applies only when Udyam major_activity is trading | not defined until computable | 2 (reference) | pending (schema); not applicable if not a trading business | document rent_agreement (premises_type = warehouse) |
| `cp.sector_view` | Company profile | External sector view (CRISIL, ICRA, CARE research) | `(proposed) external sector rating by NIC code` | published sector outlook mapped to a band | not defined until computable | 1 (reference) | pending (schema) | external sector-outlook feed keyed by Udyam NIC code (not borrower documents) |
| `sp.itr_filed` | Promoter profile | ITR-V (acknowledgement), Form 26AS / AIS | `DocumentEnvelope[itr_v].data.assessment_year` | years between the latest return's assessment year and the current one | <=1=100; <=2=55; else=20 | 2 (placeholder) | computable when ITR-V uploaded |  |
| `sp.itr_income_margin` | Promoter profile | ITR-V, GSTR-3B | `DocumentEnvelope[itr_v].data.gross_total_income; SmeProfile.cashflow.gst_turnover_12m` | gross total income / annualised GST turnover | >=0.08=100; >=0.04=75; >=0.02=50; >=0.01=30; else=10 | 1 (placeholder) | computable when ITR-V uploaded |  |
| `sp.promoter_net_worth` | Promoter profile | Personal net worth statement, property papers | `(proposed) DocumentType net_worth_statement: net_worth` | declared net worth against the facility size (good to have; depends on facility size) | not defined until computable | 1 (reference) | pending (schema) | document net_worth_statement (net_worth) |
| `bc.bounces_6m` | Banking conduct and exposure | Bank statement (Account Aggregator or PDF) | `SmeProfile.cashflow.bounces_6m` | count of bounce-tagged debits in the last 6 statement months | <=0=100; <=1=60; <=2=40; <=4=15; else=0 | 3 (placeholder) | computable |  |
| `bc.foir` | Banking conduct and exposure | Bank statement | `SmeProfile.cashflow.foir` | average EMI of last 3 months / average monthly credits | <=0.2=100; <=0.35=80; <=0.5=45; <=0.65=15; else=0 | 3 (placeholder) | computable |  |
| `bc.liquidity_cushion` | Banking conduct and exposure | Bank statement | `SmeProfile.cashflow.avg_monthly_balance / avg_monthly_credits` | average monthly balance / average monthly credits | >=1=100; >=0.6=80; >=0.3=55; >=0.15=30; else=5 | 2 (placeholder) | computable |  |
| `bc.revenue_trend` | Banking conduct and exposure | Bank statement | `DocumentEnvelope[bank_statement].data.transactions[].credit` | mean credits of last 3 months / mean of earlier months (>= 6 months needed) | >=1.1=100; >=0.95=85; >=0.85=60; >=0.7=30; else=5 | 2 (placeholder) | computable |  |
| `bc.credit_stability` | Banking conduct and exposure | Bank statement | `DocumentEnvelope[bank_statement].data.transactions[].credit` | stdev / mean of monthly credits | <=0.15=100; <=0.3=75; <=0.5=45; <=0.75=20; else=0 | 1 (placeholder) | computable |  |
| `bc.low_balance_days` | Banking conduct and exposure | Bank statement | `DocumentEnvelope[bank_statement].data.transactions[].balance` | share of days with end-of-day balance below one month of existing EMI | <=0.02=100; <=0.1=75; <=0.25=45; <=0.5=20; else=0 | 1 (placeholder) | computable |  |
| `bc.cash_credit_share` | Banking conduct and exposure | Bank statement | `DocumentEnvelope[bank_statement].data.transactions[].tags` | value of cash-tagged credits / value of business credits | <=0.1=100; <=0.25=80; <=0.5=55; <=0.75=30; else=10 | 1 (placeholder) | computable |  |
| `bc.statement_depth` | Banking conduct and exposure | Bank statement | `SmeProfile.cashflow.months_analyzed` | months covered by the statement | >=12=100; >=9=80; >=6=60; >=3=30; else=10 | 1 (placeholder) | computable |  |
| `bc.gst_bank_consistency` | Banking conduct and exposure | GSTR-3B, bank statement | `SmeProfile.cashflow.gst_vs_bank_ratio` | GST outward value / bank credits over the months both cover | 0.85-1.15=100; 0.7-1.3=75; 0.5-1.6=40; else=10 | 2 (placeholder) | computable |  |
| `bc.gst_filing_timeliness` | Banking conduct and exposure | GSTR-3B | `DocumentEnvelope[gstr3b].data.months[].filing_date, due_date` | GSTR-3B months filed on or before due date / months with both dates (>= 3) | >=0.95=100; >=0.8=75; >=0.6=45; else=15 | 2 (placeholder) | computable |  |
| `bc.gst_turnover_trend` | Banking conduct and exposure | GSTR-3B | `DocumentEnvelope[gstr3b].data.months[].outward_taxable_value` | mean of last 3 months / mean of earlier months (>= 4 months needed) | >=1.1=100; >=0.95=85; >=0.85=60; >=0.7=30; else=5 | 1 (placeholder) | computable |  |
| `bc.turnover_scale` | Banking conduct and exposure | GSTR-3B | `SmeProfile.cashflow.gst_turnover_12m` | GST outward value of the last 12 months, annualised | >=5e+07=100; >=1e+07=85; >=2e+06=65; >=500000=40; else=15 | 1 (placeholder) | computable |  |
| `bc.customer_concentration` | Banking conduct and exposure | Bank statement, sales invoices | `(proposed) Transaction.counterparty_key (pseudonymous key, never a name)` | share of credits from the top 3 counterparties | not defined until computable | 2 (placeholder) | pending (schema) | Transaction.counterparty_key on bank_statement.data.transactions[] |
| `bc.od_utilisation` | Banking conduct and exposure | Sanction letter, bank statement | `DocumentEnvelope[sanction_letter].data.facility_type, sanctioned_amount; DocumentEnvelope[bank_statement].data.transactions[].balance` | average overdrawn amount (negative end-of-day balance) / sanctioned limit; only when the statement goes negative | <=0.5=100; <=0.75=75; <=0.9=45; <=1=20; else=5 | 2 (placeholder) | computable |  |
| `bc.pg_settlements` | Banking conduct and exposure | Payment aggregator / UPI merchant settlement report | `DocumentEnvelope[settlement_report].data.months[].net; SmeProfile bank credits` | settlement net / bank business credits over the months both cover (>= 2); a consistency check, not a digital-share score | <=1.1=100; <=1.3=40; else=10 | 2 (placeholder) | computable |  |
| `bc.macro_shock` | Banking conduct and exposure | News and sector events (analytical) | `(proposed) external shock calendar` | last-3-year vs last-year revenue shock check, plus a sector event list | not defined until computable | 1 (reference) | pending (schema) | external shock calendar plus 3 years of revenue (financial_statements.prior_revenue) |
| `bc.margin_facility` | Banking conduct and exposure | Sanction letter (security, FD lien) | `DocumentEnvelope[sanction_letter].data.fd_lien_or_margin` | flag when any facility is fully cash-margined (limit sized above what the business needs) | not_margined=100; cash_margined=40 | 3 (reference) | computable |  |
| `bc.facility_trend` | Banking conduct and exposure | Sanction letters across renewals | `DocumentEnvelope[sanction_letter].data.sanctioned_amount, sanction_date` | increased / same / decreased between the two newest sanctions of the same facility type | increased=100; same=75; decreased=30 | 1 (reference) | computable |  |
| `fn.revenue_growth_yoy` | Financial strength | Audited or CA-certified financials, Form 3CD above thresholds | `DocumentEnvelope[financial_statements].data.revenue, prior_revenue` | revenue / prior-year revenue - 1, latest financial year (3-year version needs one more year of data) | >=0.15=100; >=0.05=80; >=0=60; >=-0.1=35; else=10 | 2 (placeholder) | computable |  |
| `fn.net_margin` | Financial strength | Audited or CA-certified financials | `DocumentEnvelope[financial_statements].data.profit_after_tax, revenue` | profit after tax / revenue, recomputed from the components | >=0.1=100; >=0.05=80; >=0.02=55; >=0=30; else=5 | 2 (placeholder) | computable |  |
| `fn.leverage` | Financial strength | Audited or CA-certified financials | `DocumentEnvelope[financial_statements].data.long_term_borrowings, short_term_borrowings, net_worth` | (long + short term borrowings) / net worth; zero or negative net worth is the worst band | <=0.5=100; <=1=80; <=2=55; <=3=30; else=10 | 2 (placeholder) | computable |  |
| `fn.dscr` | Financial strength | Audited or CA-certified financials | `DocumentEnvelope[financial_statements].data.profit_after_tax, depreciation, interest_expense, principal_repayments` | (profit after tax + depreciation + interest) / (principal repayments + interest) | >=2=100; >=1.5=85; >=1.25=65; >=1=35; else=5 | 3 (placeholder) | computable |  |
| `fn.unit_economics` | Financial strength | P&L, bank statement, internal CRM data | `(proposed) CRM export: marketing_spend, new_customers; financial_statements gross profit` | gross profit x customer lifetime value : customer acquisition cost, target 3:1 or better | not defined until computable | 3 (reference) | pending (schema) | internal CRM data (marketing spend, customer count) plus document financial_statements |
| `rb.consumer_score` | Risk, bureau and disclosure | CIBIL / Experian / Equifax / CRIF consumer score (300-900) | `SmeProfile.bureau.value` | bureau score, 300-900 | >=750=100; >=700=80; >=650=55; >=600=30; else=10 | 3 (placeholder) | computable |  |
| `rb.cmr` | Risk, bureau and disclosure | CIBIL commercial report (CMR) | `SmeProfile.bureau.cmr_rank, else DocumentEnvelope[bureau_report].data.cmr_rank` | rank 1-10; lower is better (direction opposite to the consumer score) | <=2=100; <=3=85; <=5=60; <=6=40; <=8=20; else=5 | 3 (placeholder) | computable |  |
| `rb.worst_dpd_24m` | Risk, bureau and disclosure | Bureau report | `SmeProfile.bureau.max_dpd_24m, else DocumentEnvelope[bureau_report].data.max_dpd_24m` | worst DPD across accounts in the last 24 months | <=0=100; <=30=70; <=60=40; <=90=15; else=0 | 3 (placeholder) | computable |  |
| `rb.enquiries_90d` | Risk, bureau and disclosure | Bureau report | `SmeProfile.bureau.enquiries_90d, else DocumentEnvelope[bureau_report].data.enquiries_90d` | count of enquiries in the last 90 days | <=2=100; <=4=70; <=6=40; else=15 | 1 (placeholder) | computable |  |
| `rb.adverse_flags` | Risk, bureau and disclosure | Bureau report (RBI CRILC is not accessible to us) | `SmeProfile.bureau.written_off_or_settled, suit_filed_or_wilful_default, else DocumentEnvelope[bureau_report]` | any flag set = worst band; both flags must be stated false for the best band | <=0=100; else=0 | 3 (reference) | computable |  |
| `rb.voluntary_disclosure` | Risk, bureau and disclosure | Interview with the relationship manager | `(proposed) RM interview record` | RM view of how openly the promoter shares concerns | not defined until computable | 1 (reference) | pending (schema) | RM interview record (not a document) |
| `rb.company_assets` | Risk, bureau and disclosure | Fixed-asset register, Vahan registration for vehicles, property ownership records | `(proposed) DocumentType asset_register: total_value, registrable_share` | value and type of registrable and non-registrable assets | not defined until computable | 1 (reference) | pending (schema) | document asset_register (total_value, registrable_share) |
| `rb.responsiveness` | Risk, bureau and disclosure | Relationship manager timestamps | `(proposed) RM turnaround log` | average hours to supply a requested document | not defined until computable | 1 (reference; outside weight base) | pending (schema) | RM turnaround log (not a document) |
| `di.balance_math` | Data integrity | Bank statement | `SmeProfile.cross_checks[cross.balance_math].status` | status of the row-by-row balance check | pass=100; warn=50; fail=0 | 3 (placeholder) | computable |  |
| `di.statement_gaps` | Data integrity | Bank statement, GSTR-3B | `SmeProfile.cross_checks[cross.statement_gaps].status` | status of the missing-months check | pass=100; warn=50; fail=0 | 2 (placeholder) | computable |  |
| `di.tax_registration_link` | Data integrity | PAN card, GST registration | `SmeProfile.cross_checks[cross.pan_in_gstin].status` | status of the PAN-inside-GSTIN check | pass=100; fail=0 | 2 (placeholder) | computable |  |
| `di.name_match` | Data integrity | PAN, Aadhaar, GST, bank statement | `SmeProfile.cross_checks[cross.name_match].status` | status of the fuzzy name check; only the status is used, never the names | pass=100; warn=50; fail=0 | 1 (placeholder) | computable |  |
| `di.premises_agreement` | Data integrity | Aadhaar, GST, Udyam | `SmeProfile.cross_checks[cross.address_match].status` | status of the address check; only the status is used, never the address | pass=100; warn=50; fail=0 | 1 (placeholder) | computable |  |
| `di.kyc_record_match` | Data integrity | PAN, Aadhaar | `SmeProfile.cross_checks[cross.dob_match].status` | status of the PAN-vs-Aadhaar record check; only the status is used, never the dates | pass=100; warn=50; fail=0 | 1 (placeholder) | computable |  |
| `di.low_confidence_fields` | Data integrity | All uploaded documents | `DocumentEnvelope[*].data.*.needs_review` | extracted fields needing review / all extracted fields | <=0=100; <=0.05=80; <=0.15=50; else=20 | 1 (placeholder) | computable |  |
<!-- registry-table:end -->

## 4. Scoring math

1. Each computed parameter is mapped to a band and gets **points 0-100** (`config.json`).
2. **Effective weight** = nominal weight, times `review_weight_factor` (0.5) when an input needs review (section 5);
   0 when the parameter is not computed.
3. **Index** = sum(effective weight x points) / sum(effective weight), over computed parameters only, rounded to one
   decimal. Pending and not-applicable parameters never lower the index; they appear instead in coverage.
4. **Coverage** = sum(effective weight of computed parameters) / sum(nominal weight of applicable parameters in the
   weight base). It is printed beside every index, with a label (`high` >= 75%, `moderate` >= 50%, `partial` >= 25%,
   `minimal`). Removing a document therefore lowers coverage (and moves the index only through the parameters that
   remain), and below 25% coverage the grade is `insufficient_data`, so withholding documents cannot buy a better
   grade.
5. **Grade**: `strong` >= 75, `moderate` >= 55, `cautious` >= 35, else `weak`; `insufficient_data` when coverage is
   under 25% or nothing is computed. Placeholder thresholds.
6. **Critical cap**: a weighted average can hide one fatal fact. `di.balance_math` (statement does not reconcile:
   possible tampering) and `di.tax_registration_link` (PAN inside GSTIN does not match the PAN card) are *critical*;
   if either scores 0 the grade is capped at `cautious` and the card says so in `grade_capped_by`. The numeric index
   is not altered. (This mirrors the readiness score's cap at 49 for failed balance math.)
7. **Pending parameters** are shown with `status: pending`, `points: null`, a reason, and `waits_for` naming the
   exact field or document. A pending parameter whose schema field exists but whose document was not uploaded says
   which document. **Not applicable** parameters (for example the warehouse parameter for a service or
   manufacturing business, from Udyam `major_activity`) show `status: not_applicable` and leave the weight base.
8. **Categories** (company profile, promoter profile, banking conduct, financial strength, risk and bureau, data
   integrity) each get their own index and coverage so a lender can see which block is thin.
9. **Provisional flag**: `provisional` is true when the index rests on unconfirmed or unverified inputs (a mock or
   self-declared bureau score, low-confidence fields, a failed reconciliation); `provisional_reasons` lists why.
10. `strengths` and `concerns` list the highest weighted shortfalls and strengths, in plain language, with the same
    reasons as the parameter rows. Structural parameters under fairness review (constitution, size class, turnover
    scale, cash share) are scored but never headlined as a concern or strength.

Caveat of averaging: many cheap "pass" parameters (registrations, consistent names) dilute a few serious ones. That
is why the critical cap exists and why weights need calibration; do not read a high index as low risk when coverage
is partial.

## 5. Conflicting and low-confidence data

Judged on **field and row confidence**, not on envelope status (a statement that fails the balance check is
`needs_review` as a document, but its bounce and FOIR figures still count, otherwise a tampered statement would
make the applicant look better by dropping bad parameters).

| Situation | Treatment |
|---|---|
| Every input field >= 0.85 confidence, or confirmed by the SME (`user_confirmed`) | scored at full weight |
| An input field needs review (confidence < 0.85, unconfirmed), or >= 10% of table rows (bank transactions, GSTR-3B months) are below 0.85 | scored, flagged `low_confidence`, counted at **50%** of its weight (lowers coverage; the reason says so), card is `provisional` |
| An input field is missing or below 0.50 confidence, or >= 50% of table rows are | **not scored**: shown as pending, `waits_for` = "SME confirmation or re-upload of <document.field>" |
| Source itself is unverified (bureau score from `mock` or `self_declared`, not a bureau pull) | counted at 50% weight, flagged, card is `provisional` |
| Bank statement fails the balance check (possible edited row) | `di.balance_math` scores 0 (weight 3) and is critical (grade capped); every bank-derived parameter keeps its weight but its reason says it may include an edited row and is unverified |
| Documents disagree (names, addresses, PAN vs GSTIN, GST turnover vs bank credits, missing months) | the disagreement is itself scored by a data-integrity parameter; only the check *status* is used, never the conflicting text |
| A document is missing | its parameters are pending with `waits_for`; coverage falls; the index is computed on what remains |

Known limitation of the half-weight rule: halving a weak parameter can raise the index slightly. It is visible
(flag, `provisional`, coverage) and conservative alternatives are listed under calibration.

## 6. Field lock and fairness

**Field lock (DPDP Act 2023 data minimisation).** The model-facing feature table (`ScoreCard.features`) has exactly
one column per registry parameter (null when pending). `fieldlock.py` enforces:

- keys are an **allowlist**: only registry ids;
- keys must not contain words naming a protected or proxy attribute (gender, religion, caste, community, age, dob,
  birth, nationality, marital, race, ethnicity, pincode, state, district, city, region, location, address) or an
  identifier (gstin, aadhaar, ifsc, phone, email, passport, account);
- values are numbers, booleans, or short lower_snake category tokens (`pass`, `micro`); anything that looks like a
  PAN, GSTIN, Udyam number, long digit string (Aadhaar, account, phone), e-mail or ISO date is rejected.

Reasons are composed from bands and statuses, never copied from document text: the cross-check messages for names,
addresses and PAN/GSTIN contain personal data, so only their pass/warn/fail status is read. Narrations and
counterparty names are not used (customer concentration waits for a pseudonymous key). Tests serialise the feature
table and the whole ScoreCard and assert that none of the sample applicants' PAN, GSTIN, names, dates of birth,
addresses, account digits, IFSC or Udyam number appear.

**No protected attributes or proxies.** Gender (present on the Aadhaar model) is never read. Age and date of birth
are never read as scored inputs (age stays a lender eligibility rule in the recommendation engine); the
PAN-vs-Aadhaar record check parameter uses only the status of a comparison. State, pincode, district and city are
not scored, and the GSTIN state code is never used. A sector or geography view (`cp.sector_view`) is pending and,
if built, must be limited to non-personal business data and go to human fairness review first.

**Structural parameters flagged for review.** `cp.constitution`, `cp.msme_category`, `bc.turnover_scale` and
`bc.cash_credit_share` describe the business, not the person, but can disadvantage small or informal businesses
(micro enterprises, proprietorships, cash-heavy trades). They have `review_flag` text in the registry, weight 1
each, and are never headlined. The lender's credit/compliance team must document why each is a risk factor and
check its effect on outcomes across business sizes before relying on it.

**Disparate-impact check (planned, needs outcomes data):** compare grade distribution and downstream decisions by
business size class and constitution, and by state at an aggregate level, held outside the scoring path.

## 7. Schema additions to propose

**Status:** the bureau, financial-statements, sanction-letter and settlement-report proposals below are
implemented (schema 1.1 and 1.2) and the engine now reads them, so those twelve parameters are computable. The
other proposals are still open. Originally these were read-only dependencies, so this package registered the
parameters as pending. To raise with
Shivansh (`SmeProfile` / `DocumentEnvelope` owner). Field names mirror the document schemas already drafted under
`backend/schemas/documents/v1/` where they exist.

| Proposal | Exact fields | Unlocks (parameter ids) |
|---|---|---|
| **Implemented.** Extend `BureauScore` (or add `BureauReport` to `SmeProfile`) from the bureau report | `cmr_rank` (int 1-10, 1 is best), `max_dpd_24m`, `enquiries_90d`, `written_off_or_settled`, `suit_filed_or_wilful_default`, optionally `active_accounts`, `overdue_amount` | `rb.cmr`, `rb.worst_dpd_24m`, `rb.enquiries_90d`, `rb.adverse_flags` |
| **Implemented.** New `DocumentType` `financial_statements` and model | `revenue`, `prior_revenue`, `profit_after_tax`, `net_margin`, `debt_to_equity` (or borrowings and `net_worth`), `dscr` (or `ebitda`, `depreciation`, `interest_expense`, `principal_repayments`), `audit_status` | `fn.revenue_growth_yoy`, `fn.net_margin`, `fn.leverage`, `fn.dscr`, partly `fn.unit_economics`, `bc.macro_shock` |
| **Implemented.** New `DocumentType` `sanction_letter` and model | `facility_type`, `sanctioned_amount`, `sanction_date`, `fd_lien_or_margin`, `security`, plus bureau `accounts[].outstanding` for utilisation | `bc.od_utilisation`, `bc.margin_facility`, `bc.facility_trend` |
| **Implemented.** New `DocumentType` `settlement_report` and model | `monthly[].gross`, `period_from`, `period_to`, `months_covered` | `bc.pg_settlements` |
| Pseudonymous counterparty key on `Transaction` | `counterparty_key` (hashed, never a name) | `bc.customer_concentration` |
| New document types for premises and licences | `rent_agreement` (`lease_end_date`, `is_registered`, `premises_type`), `operating_licence` (`licence_type`, `valid_to`), `epfo_esic_return` (`employee_count`, `months_filed_12m`) | `cp.premises_proof`, `cp.operating_licence`, `cp.employee_base`, `cp.warehouse_status` |
| New document types for the promoter and the business | `net_worth_statement` (`net_worth`), `asset_register` (`total_value`, `registrable_share`) | `sp.promoter_net_worth`, `rb.company_assets` |

`BureauScore.source` (`mock` / `self_declared` / `bureau`) already exists and the engine uses it to halve the weight of unverified scores; keep it.

Pending for reasons no document fixes (not schema work): `cp.sector_view` (external sector rating feed),
`bc.macro_shock` (analytical event calendar plus three years of revenue), `fn.unit_economics` (SME's CRM data plus
P&L), `rb.voluntary_disclosure` (relationship-manager interview), `rb.responsiveness` (relationship-manager
timestamps; outside the weight base).

## 8. Placeholder weights and calibration plan

**All 40 weights not documented in the reference are placeholders**, chosen from the reference's category structure
and a default of 1 or 2: 3 for the signals every Indian lender treats as primary (bounces, FOIR, bureau score, the
critical integrity checks, DSCR, CMR, DPD), 2 for consistency, trend and track-record signals, 1 for the rest. The
11 `reference` weights are the reference scorecard's own, unvalidated for India. Bands and grade thresholds are
placeholders too. `config.json` says `"calibrated": false` and every ScoreCard carries `weights_calibrated: false`
and the `config_version`. **They must be calibrated by the lender's credit team before the index is used for more
than a conversation starter.**

How a lender would calibrate with its own default outcomes:

1. Assemble a back-test set of past SME applications with documents and an observed outcome (for example 90+ days
   past due within 12 months of disbursal), including rejected and unbooked applications handled with reject
   inference, or the results are biased to the accepted population.
2. Run `score_sme` on each with `as_of` set to the application date (the engine is deterministic and takes no clock).
3. Evaluate each parameter alone (bad-rate by band, information value) and the index overall (rank-ordering: KS,
   Gini / AUC, bad-rate by grade). Bands whose bad rate is not monotonic need new cut-offs.
4. Fit weights (for example regularised logistic regression on band points, then constrain to non-negative round
   numbers so the card stays readable), then freeze, version (`config_version`) and record who approved.
5. Validate on an out-of-time sample, check stability by month, and run the disparate-impact review of section 6.
6. Re-run after any change to extraction or validation, and monitor drift (share of pending parameters, coverage,
   grade mix) in production.

Until then, treat grade labels as ordinal hints about which files deserve a closer look.

## 9. Limitations

- Weights, bands and grade thresholds are uncalibrated; no back-test exists. Nothing here estimates loss.
- Coverage is partial by construction today (45% on the sample applicants): bureau depth, financial statements,
  facilities and settlements need the schema additions above.
- Mock or self-declared bureau scores are not bureau data; a real pull is a separate, consented step.
- Extraction quality bounds everything. The engine uses field and row confidence only; it does not re-read documents.
- Bank-derived metrics rest on tags from narration matching in validation; unusual narrations can be mis-tagged.
- Samples are synthetic; thresholds were not tuned to them, but the planted problems drive the A-vs-B gap.
- Averaging dilutes serious signals; only two critical parameters cap the grade.
- Account Aggregator statements are not special-cased; they would enter as ordinary structured bank statements.

## 10. What we can honestly claim (for the pitch)

CreditSetu gives a lender a transparent, parameter-by-parameter assessment of an SME file: each signal (bounces,
EMI burden, balance cushion, GST consistency, bureau score and so on) is computed by fixed rules, shown with the
document fields behind it, scored against published bands and combined with visible weights. Every number comes
with its coverage, meaning how much of the scorecard we could compute from the documents provided, and anything we
could not compute stays visible as a blank that says what it is waiting for. It is an indicative aid for the
lender's own credit decision, built on placeholder weights that the lender's credit team calibrates against its own
outcomes. It is not a probability of default, not a credit score, and it does not approve or reject anyone.
