"""Fuzzy name and address matching used by the cross-document checks."""
import pytest

from app.schemas import CheckStatus
from app.validation.text import compare_addresses, compare_names


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("RAVI KUMAR", "Ravi  Kumar", CheckStatus.PASS),
        ("RAVI KUMAR", "Mr. Ravi Kumar", CheckStatus.PASS),
        ("RAVI KUMAR", "KUMAR RAVI", CheckStatus.PASS),
        ("RAVI KUMAR", "R. KUMAR", CheckStatus.WARN),
        ("RAVI KUMAR", "RAVI KUMAAR", CheckStatus.WARN),
        ("RAVI KUMAR", "SUNITA SHARMA", CheckStatus.FAIL),
        ("R.KUMAR", "R. KUMAR (KUMAR TRADERS)", CheckStatus.PASS),  # OCR drops the space; bank adds the business
        ("RAVI KUMAR", "R. KUMAR (KUMAR TRADERS)", CheckStatus.WARN),
        ("RAVI KUMAR", "SUNITA SHARMA (KUMAR TRADERS)", CheckStatus.FAIL),
    ],
)
def test_name_matching(a, b, expected):
    assert compare_names(a, b) == expected


def test_address_matching():
    home = "12 Gandhi Bazaar Main Road, Basavanagudi, Bengaluru 560004"
    assert compare_addresses(home, "No 12, Gandhi Bazaar, Basavanagudi, Bengaluru - 560004") == CheckStatus.PASS
    assert compare_addresses(home, "44 MG Road, Pune 411001") == CheckStatus.FAIL

