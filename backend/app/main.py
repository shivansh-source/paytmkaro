from fastapi import FastAPI

from app.api.v1 import router as v1_router

app = FastAPI(title="CreditSetu API", version="0.1.0")
app.include_router(v1_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
