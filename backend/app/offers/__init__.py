"""Offers: plain numbers for the Key Fact Statement (EMI, fees, total payback, true APR)."""

from app.offers.kfs import OfferEstimate, OfferScenario, amortize, emi_for, estimate_offer, true_apr

__all__ = ["OfferEstimate", "OfferScenario", "amortize", "emi_for", "estimate_offer", "true_apr"]
