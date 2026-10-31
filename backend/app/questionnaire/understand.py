"""Understand a free-typed questionnaire answer (English, Hindi or Hinglish).

1. Mask private numbers (PAN, Aadhaar/phone/account-like digit runs) before anything leaves the server.
2. Deterministic rules for short, common answers: "5 lakh", "₹5,00,000", "2022", "kirana dukaan",
   "koi loan nahi", "3 bounces". Instant and free.
3. Otherwise the LLM (Sarvam) extracts fields into a fixed schema. It may also pick up answers to later
   questions ("kirana, teen saal se, 5 lakh chahiye"), so the chat can skip them.
4. Every value is re-validated; anything out of range or not clearly stated is dropped, never guessed.
The LLM only fills answer fields; it never scores, matches or decides.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.llm import LLMError, StructuredLLM, get_llm

StepId = Literal["sector", "constitution", "started", "annual_sales", "loan_amount", "tenure", "purpose", "emi", "bounces", "have", "score"]

# Which answer fields each question is about.
STEP_FIELDS: dict[str, tuple[str, ...]] = {
    "sector": ("sector",),
    "constitution": ("constitution",),
    "started": ("started_year",),
    "annual_sales": ("annual_sales",),
    "loan_amount": ("loan_amount",),
    "tenure": ("tenure_months",),
    "purpose": ("purpose",),
    "emi": ("existing_emi_monthly",),
    "bounces": ("bounces_6m",),
    "have": ("has_gst", "has_udyam", "has_itr"),
    "score": ("credit_score",),
}

SECTORS = ("retail", "trading", "manufacturing", "services", "food", "other")
CONSTITUTIONS = ("proprietorship", "partnership", "llp", "pvt_ltd", "not_sure")
SALES_BANDS = ("under_10l", "10l_25l", "25l_1cr", "over_1cr")
BOUNCE_BANDS = ("none", "1_2", "3_plus", "not_sure")


class InterpretRequest(BaseModel):
    step: StepId
    text: str = Field(min_length=1, max_length=500)
    today: date | None = None


class Interpretation(BaseModel):
    updates: dict[str, Any]  # validated answer fields, possibly for later questions too
    understood: str | None  # "Got it: Retail shop, started around 2023"
    answered_step: bool  # did we get what the current question asked for?
    source: Literal["rules", "ai", "none"]
    message: str | None = None  # shown when we didn't understand


# ---------- 1. Privacy ----------

_PAN = re.compile(r"\b[A-Za-z]{5}\d{4}[A-Za-z]\b")
_LONG_DIGITS = re.compile(r"\b\d[\d -]{8,}\d\b")  # 10+ chars of digits: phone, Aadhaar, account numbers


def mask_private(text: str) -> str:
    text = _PAN.sub("[PAN]", text)
    return _LONG_DIGITS.sub(lambda m: m.group(0) if _looks_like_money(m.group(0)) else "[NUMBER]", text)


def _looks_like_money(s: str) -> bool:
    # "5,00,000" has commas; a 10-digit phone number doesn't.
    return "," in s


# ---------- 2. Rules ----------

_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_NEGATION = re.compile(r"\b(no|not|nahi|nahin|nai|na|never|don'?t|without)\b|नहीं|ना")
_UNITS = {
    "crore": 10_000_000, "cr": 10_000_000, "करोड़": 10_000_000, "करोड": 10_000_000,
    "lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000, "l": 100_000, "लाख": 100_000,
    "thousand": 1_000, "k": 1_000, "hazar": 1_000, "hazaar": 1_000, "हज़ार": 1_000, "हजार": 1_000,
}
_AMOUNT = re.compile(r"(?:₹|rs\.?|inr)?\s*(\d[\d,]*(?:\.\d+)?)\s*(crore|cr|lakhs?|lacs?|l|k|thousand|hazaa?r|करोड़?|लाख|हज़ार|हजार)?\b", re.I)


def _norm(text: str) -> str:
    return text.translate(_DEVANAGARI_DIGITS).lower().strip()


def amounts_in(text: str) -> set[int]:
    """Every rupee amount written with digits in the text, units applied: grounding for model output."""
    out: set[int] = set()
    for m in _AMOUNT.finditer(_norm(text)):
        try:
            out.add(int(round(float(m.group(1).replace(",", "")) * _UNITS.get((m.group(2) or "").lower(), 1))))
        except ValueError:
            continue
    return out


def parse_amount(text: str) -> int | None:
    """'5 lakh' -> 500000, '₹5,00,000' -> 500000, '50k' -> 50000, '1.5 cr' -> 15000000."""
    found = [(m.group(1), m.group(2)) for m in _AMOUNT.finditer(_norm(text)) if m.group(1)]
    if len(found) != 1:
        return None
    number, unit = found[0]
    try:
        value = float(number.replace(",", ""))
    except ValueError:
        return None
    return int(round(value * _UNITS.get((unit or "").lower(), 1)))


_WORDS: dict[str, tuple[tuple[str, ...], ...]] = {
    "sector": (
        ("retail", "shop", "dukaan", "dukan", "kirana", "store", "दुकान", "किराना", "general store"),
        ("trading", "wholesale", "wholesaler", "distributor", "trader", "thok", "थोक"),
        ("manufacturing", "factory", "manufactur", "production", "फैक्ट्री"),
        ("services", "service", "salon", "parlour", "repair", "consult", "agency", "clinic", "tuition", "transport"),
        ("food", "restaurant", "dhaba", "cafe", "hotel", "catering", "bakery", "sweet", "mithai", "tiffin", "ढाबा"),
    ),
    "constitution": (
        ("proprietorship", "proprietor", "akela", "khud", "own name", "sole", "अकेले"),
        ("partnership", "partner"),
        ("llp",),
        ("pvt_ltd", "pvt", "private limited", "company", "ltd"),
        ("not_sure", "not sure", "pata nahi", "don't know", "dont know", "पता नहीं"),
    ),
}


def _keyword(kind: str, text: str) -> str | None:
    hits = {group[0] for group in _WORDS[kind] if any(word in text for word in group)}
    return hits.pop() if len(hits) == 1 else None


def _band(annual: int) -> str:
    return "under_10l" if annual < 1_000_000 else "10l_25l" if annual < 2_500_000 else "25l_1cr" if annual < 10_000_000 else "over_1cr"


def _rules(step: str, text: str, today: date) -> dict[str, Any]:
    t = _norm(text)
    negated = bool(_NEGATION.search(t))
    if step in ("sector", "constitution"):
        value = _keyword(step, t)
        return {STEP_FIELDS[step][0]: value} if value and (step == "constitution" or not negated) else {}
    if step == "started":
        if m := re.search(r"\b(19[5-9]\d|20\d\d)\b", t):
            return {"started_year": int(m.group(1))}
        if m := re.search(r"\b(\d{1,2})\s*(saal|sal|years?|yrs?|साल)\b", t):
            return {"started_year": today.year - int(m.group(1))}
        return {}
    if step in ("loan_amount", "annual_sales", "emi"):
        if step == "emi" and (negated or re.fullmatch(r"(none|zero|0|nil)", t)):
            return {"existing_emi_monthly": 0}
        amount = parse_amount(t)
        if amount is None:
            return {}
        if step == "annual_sales":
            per_month = re.search(r"month|mahin|महीन", t)
            return {"annual_sales": _band(amount * 12 if per_month else amount)}
        return {"loan_amount" if step == "loan_amount" else "existing_emi_monthly": amount}
    if step == "tenure":
        if m := re.search(r"\b(\d{1,3})\s*(months?|mahine|mahina|महीने)\b", t):
            return {"tenure_months": int(m.group(1))}
        if m := re.search(r"\b(\d{1,2})\s*(saal|sal|years?|yrs?|साल)\b", t):
            return {"tenure_months": int(m.group(1)) * 12}
        if re.fullmatch(r"\d{1,3}", t):
            n = int(t)
            return {"tenure_months": n * 12 if n <= 5 else n}
        return {}
    if step == "bounces":
        if re.search(r"pata nahi|not sure|don'?t know|पता नहीं", t):
            return {"bounces_6m": "not_sure"}
        if negated or re.fullmatch(r"(none|zero|0)", t):
            return {"bounces_6m": "none"}
        if m := re.fullmatch(r"(\d{1,2})\s*(bounces?|times?|baar|बार)?", t):
            n = int(m.group(1))
            return {"bounces_6m": "none" if n == 0 else "1_2" if n <= 2 else "3_plus"}
        return {}
    if step == "score":
        if m := re.fullmatch(r"(\d{3})", t):
            n = int(m.group(1))
            return {"credit_score": n} if 300 <= n <= 900 else {}
        return {}
    return {}  # "have" and "purpose" read better with the model (negations, free wording)


# ---------- 3. Model ----------

_NULLABLE = lambda t: {"type": [t, "null"]}  # noqa: E731

LLM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "sector", "constitution", "started_year", "years_in_business", "sales_amount", "sales_period", "loan_amount",
        "tenure_months", "tenure_years", "purpose", "emi_amounts", "bounces_6m_count", "has_gst", "has_udyam", "has_itr",
        "credit_score",
    ],
    "properties": {
        "sector": {"type": ["string", "null"], "enum": [*SECTORS, None]},
        "constitution": {"type": ["string", "null"], "enum": [*CONSTITUTIONS, None]},
        "started_year": _NULLABLE("integer"),
        "years_in_business": _NULLABLE("integer"),
        "sales_amount": _NULLABLE("integer"),
        "sales_period": {"type": ["string", "null"], "enum": ["month", "year", None]},
        "loan_amount": _NULLABLE("integer"),
        "tenure_months": _NULLABLE("integer"),
        "tenure_years": _NULLABLE("integer"),
        "purpose": _NULLABLE("string"),
        "emi_amounts": {"type": ["array", "null"], "items": {"type": "integer"}},
        "bounces_6m_count": _NULLABLE("integer"),
        "has_gst": _NULLABLE("boolean"),
        "has_udyam": _NULLABLE("boolean"),
        "has_itr": _NULLABLE("boolean"),
        "credit_score": _NULLABLE("integer"),
    },
}

SYSTEM_PROMPT = """You read answers from Indian small-business owners applying for a business loan. They may write
in English, Hindi (Devanagari) or Hinglish. Extract ONLY what the message clearly states into the JSON schema.
Use null for anything not clearly stated. Never guess or fill in typical values.

Rules:
- Copy facts, never calculate: do not add, multiply or convert periods. Code does the arithmetic.
- Money in rupees as integers, each amount exactly as written: 1 lakh = 100000, 1 crore = 10000000, "20k" = 20000.
- sector: retail (shop, kirana, store), trading (wholesale, distributor), manufacturing (factory),
  services (salon, repair, consulting, clinic, transport), food (restaurant, dhaba, bakery), other.
- constitution: proprietorship (runs it alone / own name), partnership, llp, pvt_ltd, not_sure.
- started_year: only if a calendar year is stated. years_in_business: if they say how long ("teen saal se" = 3).
- sales_amount + sales_period: the sales figure as stated and whether it is per "month" or per "year".
- tenure_months or tenure_years: the repayment period in the unit they used ("2 saal" -> tenure_years 2).
- purpose: a short English phrase, e.g. "Buy stock", "Working capital", "Machinery or equipment",
  "Business expansion".
- emi_amounts: each current monthly loan EMI as a separate item, as written; [] if they say they have no loans.
- bounces_6m_count: EMI/cheque bounces in the last 6 months; 0 if they say none.
- has_gst / has_udyam / has_itr: true or false only if they say so explicitly ("GST hai" = true, "GST nahi hai" = false).
- credit_score: CIBIL/credit score between 300 and 900 if stated.
Today is {today}. The question they were answering: "{question}"."""

QUESTIONS = {
    "sector": "What does your business do?",
    "constitution": "How is the business set up (proprietorship, partnership, LLP, private limited)?",
    "started": "When did you start the business?",
    "annual_sales": "Roughly how much do you sell in a year?",
    "loan_amount": "How much loan do you need?",
    "tenure": "Over how many months do you want to repay?",
    "purpose": "What is the loan for?",
    "emi": "Do you pay any loan EMIs today, and how much per month?",
    "bounces": "In the last 6 months, did any EMI or cheque bounce? How many?",
    "have": "Which do you have: GST registration, Udyam registration, filed ITR, a known credit score?",
    "score": "What is your credit score?",
}


def _validate(raw: dict[str, Any], today: date, grounding: set[int] | None = None) -> dict[str, Any]:
    """Keep only well-formed, in-range values, and do the arithmetic here, never in the model.

    `grounding`: when the user typed digits, every rupee amount must be one of the amounts in their own
    text, so a model slip like "20k" -> 2000 is dropped instead of reaching the lender match.
    """
    out: dict[str, Any] = {}

    def int_in(key: str, lo: int, hi: int) -> int | None:
        v = raw.get(key)
        return v if isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi else None

    def grounded(v: int) -> bool:
        return not grounding or v in grounding

    if raw.get("sector") in SECTORS:
        out["sector"] = raw["sector"]
    if raw.get("constitution") in CONSTITUTIONS:
        out["constitution"] = raw["constitution"]
    if (y := int_in("started_year", 1950, today.year)) is not None:
        out["started_year"] = y
    elif (n := int_in("years_in_business", 0, 75)) is not None:
        out["started_year"] = today.year - n
    if (a := int_in("sales_amount", 1, 10_000_000_000)) is not None and grounded(a):
        out["annual_sales"] = _band(a * 12 if raw.get("sales_period") == "month" else a)
    elif raw.get("annual_sales") in SALES_BANDS:  # from rules
        out["annual_sales"] = raw["annual_sales"]
    if (v := int_in("loan_amount", 10_000, 50_000_000)) is not None and grounded(v):
        out["loan_amount"] = v
    if (v := int_in("tenure_months", 3, 120)) is not None:
        out["tenure_months"] = v
    elif (v := int_in("tenure_years", 1, 10)) is not None:
        out["tenure_months"] = v * 12
    if isinstance(raw.get("purpose"), str) and 2 <= len(raw["purpose"].strip()) <= 120:
        out["purpose"] = raw["purpose"].strip()[:1].upper() + raw["purpose"].strip()[1:]
    emis = raw.get("emi_amounts")
    if isinstance(emis, list) and all(isinstance(e, int) and not isinstance(e, bool) and 0 <= e <= 10_000_000 for e in emis):
        if all(grounded(e) for e in emis if e):
            out["existing_emi_monthly"] = sum(emis)
    elif (v := int_in("existing_emi_monthly", 0, 10_000_000)) is not None:  # from rules
        out["existing_emi_monthly"] = v
    if (v := int_in("bounces_6m_count", 0, 99)) is not None:
        out["bounces_6m"] = "none" if v == 0 else "1_2" if v <= 2 else "3_plus"
    for key in ("has_gst", "has_udyam", "has_itr"):
        if isinstance(raw.get(key), bool):
            out[key] = raw[key]
    if (v := int_in("credit_score", 300, 900)) is not None:
        out["credit_score"] = v
    return out


# Models fill "safe" defaults for things nobody mentioned ("no loans, no bounces"). An answer to a question
# other than the current one is kept only if the text actually talks about that topic.
TOPICS: dict[str, re.Pattern[str]] = {
    "sector": re.compile(r"shop|dukaan|dukan|kirana|store|retail|wholesale|trad|distribut|factory|manufactur|service|salon|repair|"
                         r"consult|clinic|restaurant|dhaba|cafe|hotel|food|bakery|business|dhanda|kaam|दुकान|किराना|व्यापार|धंधा"),
    "constitution": re.compile(r"proprietor|partner|llp|pvt|private|limited|company|akela|khud|sole|अकेले|पार्टनर"),
    "started_year": re.compile(r"saal|sal\b|year|since|started|shuru|se\b|purana|साल|से|शुरू|\b(19|20)\d\d\b"),
    "annual_sales": re.compile(r"sale|sell|bikri|bechta|turnover|revenue|kamai|income|बिक्री|कमाई|टर्नओवर"),
    "loan_amount": re.compile(r"loan|chahiye|need|want|lakh|crore|amount|lena|लोन|चाहिए|लाख|करोड़"),
    "tenure_months": re.compile(r"month|mahin|saal|year|chuka|repay|tenure|emi|महीन|साल|चुका"),
    "purpose": re.compile(r"stock|maal|inventory|machine|equipment|expan|shop|outlet|branch|capital|kharch|ke liye|for\b|माल|मशीन|के लिए"),
    "existing_emi_monthly": re.compile(r"emi|loan|kist|qist|installment|instalment|लोन|किस्त|ईएमआई"),
    "bounces_6m": re.compile(r"bounce|return|cheque|chq|check|dishonou?r|बाउंस|चेक"),
    "has_gst": re.compile(r"gst|जीएसटी"),
    "has_udyam": re.compile(r"udyam|msme|उद्यम"),
    "has_itr": re.compile(r"itr|income tax|return|आयकर|रिटर्न"),
    "credit_score": re.compile(r"score|cibil|credit|experian|स्कोर|सिबिल"),
}


_NOTHING = {0, "none", False}


def _on_topic(updates: dict[str, Any], step: str, text: str) -> dict[str, Any]:
    t = _norm(text)
    negated = bool(_NEGATION.search(t)) or "koi" in t
    current = set(STEP_FIELDS[step]) | ({"credit_score"} if step == "have" else set())

    def keep(k: str, v: Any) -> bool:
        if k in current:
            return True
        if k not in TOPICS or not TOPICS[k].search(t):
            return False
        # "do baar EMI bounce hui" mentions EMIs but does not say "no loans": a nothing-answer needs a "no".
        return v not in _NOTHING or negated

    return {k: v for k, v in updates.items() if keep(k, v)}


# ---------- 4. Echo ----------

LABELS = {
    "sector": {"retail": "Retail shop", "trading": "Trading / wholesale", "manufacturing": "Manufacturing", "services": "Services",
               "food": "Food & restaurants", "other": "Other business"},
    "constitution": {"proprietorship": "Proprietorship", "partnership": "Partnership", "llp": "LLP", "pvt_ltd": "Private limited",
                     "not_sure": "Not sure of the business type"},
    "annual_sales": {"under_10l": "sales under ₹10 lakh a year", "10l_25l": "sales ₹10–25 lakh a year",
                     "25l_1cr": "sales ₹25 lakh–1 crore a year", "over_1cr": "sales over ₹1 crore a year"},
    "bounces_6m": {"none": "no bounces", "1_2": "1–2 bounces", "3_plus": "3 or more bounces", "not_sure": "not sure about bounces"},
}


def _rupees(n: int) -> str:
    if n >= 10_000_000:
        return f"₹{n / 10_000_000:g} crore"
    if n >= 100_000:
        return f"₹{n / 100_000:g} lakh"
    return f"₹{n:,}"


def describe(updates: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, value in updates.items():
        if key in LABELS:
            parts.append(LABELS[key][value])
        elif key == "started_year":
            parts.append(f"started in {value}")
        elif key == "loan_amount":
            parts.append(f"loan of {_rupees(value)}")
        elif key == "tenure_months":
            parts.append(f"{value} months")
        elif key == "purpose":
            parts.append(f"purpose: {value}")
        elif key == "existing_emi_monthly":
            parts.append("no existing loans" if value == 0 else f"EMIs of {_rupees(value)} a month")
        elif key in ("has_gst", "has_udyam", "has_itr"):
            name = {"has_gst": "GST", "has_udyam": "Udyam", "has_itr": "ITR"}[key]
            parts.append(f"{name}: {'yes' if value else 'no'}")
        elif key == "credit_score":
            parts.append(f"credit score {value}")
    return "Got it: " + ", ".join(parts) if parts else ""


# ---------- Entry point ----------


def interpret(request: InterpretRequest, llm: StructuredLLM | None = None, *, use_default_llm: bool = True) -> Interpretation:
    today = request.today or date.today()
    text = mask_private(request.text)
    wanted = STEP_FIELDS[request.step]

    rules = _rules(request.step, text, today)
    rules = _validate_rules(rules, today)
    short = len(text.split()) <= 4
    if rules and short:
        return Interpretation(updates=rules, understood=describe(rules), answered_step=True, source="rules")

    model = llm if llm is not None else (get_llm() if use_default_llm else None)
    updates: dict[str, Any] = {}
    source: Literal["rules", "ai", "none"] = "none"
    if model is not None:
        prompt = SYSTEM_PROMPT.format(today=today.isoformat(), today_year=today.year, question=QUESTIONS[request.step])
        try:
            raw = model.extract(system=prompt, user=text, schema=LLM_SCHEMA, name="questionnaire_answer")
            grounding = amounts_in(text) if re.search(r"\d", _norm(text)) else None
            updates = _on_topic(_validate(raw, today, grounding), request.step, text)
            source = "ai" if updates else "none"
        except LLMError:
            updates = {}
    # Rules win for the field they parsed confidently; the model adds the rest.
    if rules:
        updates = {**updates, **rules}
        source = "ai" if source == "ai" else "rules"

    answered = any(f in updates for f in wanted)
    if request.step == "have" and not answered and "credit_score" in updates:
        answered = True
    if not updates:
        return Interpretation(
            updates={}, understood=None, answered_step=False, source="none",
            message="Sorry, I didn't catch that. You can tap an option, or say it another way.",
        )
    return Interpretation(
        updates=updates,
        understood=describe(updates),
        answered_step=answered,
        source=source,
        message=None if answered else "Thanks! And for this question: " + QUESTIONS[request.step],
    )


def _validate_rules(rules: dict[str, Any], today: date) -> dict[str, Any]:
    """Range-check rule results with the same bounds as the model's output."""
    raw = dict(rules)
    if "annual_sales" in raw:
        band = raw.pop("annual_sales")
        checked = _validate(raw, today)
        return {**checked, "annual_sales": band} if band in SALES_BANDS else checked
    if "bounces_6m" in raw:
        band = raw.pop("bounces_6m")
        return {**_validate(raw, today), "bounces_6m": band}
    return _validate(raw, today)
