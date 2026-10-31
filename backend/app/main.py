from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import config
from app.api.v1 import router as v1_router
from app.storage.crypto import encrypt


@asynccontextmanager
async def lifespan(_: FastAPI):
    encrypt(b"startup check")  # fails fast in production without CREDITSETU_SECRET
    yield


app = FastAPI(title="CreditSetu API", version="0.1.0", lifespan=lifespan)
if config.CORS_ORIGINS:  # the deployed frontend calls the API directly (Vercel -> Render)
    app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"],
                       allow_headers=["Authorization", "Content-Type"])
app.include_router(v1_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
