from fastapi import APIRouter

from app.api.v1 import documents, lenders, match, offers, profile

router = APIRouter(prefix="/v1")
router.include_router(documents.router)
router.include_router(profile.router)
router.include_router(match.router)
router.include_router(lenders.router)
router.include_router(offers.router)
