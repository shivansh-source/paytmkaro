from fastapi import APIRouter, HTTPException, Query

from app.offers import OfferEstimate, estimate_offer
from app.recommendation import load_lender_products

router = APIRouter(tags=["offers"])


@router.get("/offers/{product_id}/explain", response_model=OfferEstimate)
def explain_offer(
    product_id: str,
    amount: int = Query(gt=0, description="Loan amount in rupees"),
    tenure_months: int | None = Query(default=None, gt=0),
) -> OfferEstimate:
    """KFS numbers for one lender product: EMI, schedule, fees, total payback and true APR."""
    product = next((p for p in load_lender_products() if p.id == product_id), None)
    if product is None:
        raise HTTPException(status_code=404, detail=f"Unknown lender product '{product_id}'")
    return estimate_offer(product, amount, tenure_months)
