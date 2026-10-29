from fastapi import APIRouter

router = APIRouter(tags=["offers"])


@router.get("/offers/{offer_id}/explain")
def explain_offer(offer_id: str, language: str = "en") -> dict:
    return {
        "offer_id": offer_id,
        "language": language,
        "kfs": {
            "true_apr": "18.0% - 20.0%",
            "emi": "₹ 38,000 (example)",
            "total_payback": "₹ 13,68,000 (example)",
            "cooling_off": "You can cancel within the lender's cooling-off window.",
        },
    }
