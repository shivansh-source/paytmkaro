"""Transaction tagging from bank narrations (bounce / EMI / NACH / charges / UPI)."""
from datetime import date

import pytest

from app.schemas.documents import Transaction
from app.validation.tagging import tag_transaction


@pytest.mark.parametrize(
    ("narration", "debit", "credit", "tags"),
    [
        ("NACH RTN INSUFFICIENT FUNDS SAMPLE NBFC", 0, 40000, {"bounce", "nach"}),
        ("NACH RTN CHGS INCL GST", 590, 0, {"charges", "nach"}),
        ("NACH/DR/SAMPLE NBFC LOAN EMI", 40000, 0, {"emi", "nach"}),
        ("UPI/CR/SAMPLE RETAIL CUSTOMERS", 0, 24000, {"upi"}),
        ("CHQ RETURNED - DISHONOURED", 0, 15000, {"bounce"}),
    ],
)
def test_transaction_tagging(narration, debit, credit, tags):
    txn = Transaction(date=date(2026, 4, 5), narration=narration, debit=debit, credit=credit, balance=0)
    assert set(tag_transaction(txn).tags) == tags

