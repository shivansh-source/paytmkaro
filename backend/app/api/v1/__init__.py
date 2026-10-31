from fastapi import APIRouter

from app.api.v1 import assess, documents, lenders, match, offers, profile, samples, score

router = APIRouter(prefix="/v1")
router.include_router(documents.router)
router.include_router(profile.router)
router.include_router(assess.router)
router.include_router(score.router)
router.include_router(match.router)
router.include_router(lenders.router)
router.include_router(offers.router)
router.include_router(samples.router)
