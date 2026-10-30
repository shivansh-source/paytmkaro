"""Tag bank transactions from their narration. Extraction only reads rows; tagging happens here.

Bounce entries ("NACH RTN INSUFFICIENT FUNDS") are tagged `bounce`; the penalty line that follows
("NACH RTN CHGS") is tagged `charges` only, so a bounce is never counted twice.
"""

from __future__ import annotations

import re

from app.schemas.documents import BankStatement, Transaction, TransactionTag

_CHARGES = re.compile(r"\b(CHG|CHGS|CHRG|CHRGS|CHARGES?|PENAL(TY)?|FEE)\b")
_BOUNCE = re.compile(r"\b(RTN|RETURN(ED)?|BOUNCE[D]?|DISHONOU?R(ED)?|INSUFF(ICIENT)?)\b")
_NACH = re.compile(r"\b(NACH|ECS|ACH)\b")
_EMI = re.compile(r"\b(EMI|LOAN|LN)\b")
_UPI = re.compile(r"\bUPI\b")
_CASH = re.compile(r"\b(CASH|ATM|CDM)\b")
_GST = re.compile(r"\b(GST|GSTN|CBIC)\b")


def tag_transaction(txn: Transaction) -> Transaction:
    text = re.sub(r"[/\-_.:]", " ", txn.narration.upper())
    tags: set[TransactionTag] = set(txn.tags)
    is_charge = bool(_CHARGES.search(text))
    if is_charge:
        tags.add("charges")
    if _BOUNCE.search(text) and not is_charge:
        tags.add("bounce")
    if _NACH.search(text):
        tags.add("nach")
    if txn.debit > 0 and not is_charge and "bounce" not in tags and (_EMI.search(text) or _NACH.search(text)):
        tags.add("emi")
    if _UPI.search(text):
        tags.add("upi")
    if _CASH.search(text):
        tags.add("cash")
    if _GST.search(text) and txn.debit > 0 and not is_charge:  # "CHGS INCL GST" is a bank charge, not a GST payment
        tags.add("gst_payment")
    return txn.model_copy(update={"tags": sorted(tags)})


def tag_statement(statement: BankStatement) -> BankStatement:
    return statement.model_copy(update={"transactions": [tag_transaction(t) for t in statement.transactions]})
