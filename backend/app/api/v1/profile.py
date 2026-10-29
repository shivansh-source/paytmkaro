from fastapi import APIRouter

router = APIRouter(tags=["profile"])


@router.get("/profile/{sme_id}")
def get_validated_profile(sme_id: str) -> dict:
    return {
        "sme_id": sme_id,
        "kyc_status": "pending",
        "readiness_score": 0,
        "message": "Skeleton profile. Hook document extraction pipeline here.",
    }
