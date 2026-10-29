from fastapi import APIRouter

from app.recommendation import LenderProduct, load_lender_products

router = APIRouter(tags=["recommendation"])


@router.get("/lenders", response_model=list[LenderProduct])
def list_lender_products() -> list[LenderProduct]:
    return load_lender_products()
