"""Checksums: Verhoeff (Aadhaar) and the GSTIN check digit."""
from app.validation.checksums import aadhaar_valid, gstin_check_digit, gstin_checksum_valid, verhoeff_check_digit, verhoeff_valid


def test_verhoeff_textbook_example():
    assert verhoeff_check_digit("236") == "3"
    assert verhoeff_valid("2363")
    assert not verhoeff_valid("2364")


def test_aadhaar_rules():
    body = "23456789012"
    assert aadhaar_valid(body + verhoeff_check_digit(body))
    assert not aadhaar_valid("1" + body[1:] + "0")  # can't start with 0/1
    assert not aadhaar_valid("1234")


def test_gstin_checksum():
    assert gstin_checksum_valid("27AAPFU0939F1ZV")  # published example
    assert not gstin_checksum_valid("27AAPFU0939F1ZW")
    assert gstin_check_digit("27AAPFU0939F1Z") == "V"

