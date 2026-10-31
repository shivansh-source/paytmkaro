# CreditSetu API. Build without OCR (fits a 512 MB host; digital PDFs only):
#   docker build -t creditsetu-api backend
# With OCR for photos and scans (needs ~2 GB RAM at runtime):
#   docker build --build-arg WITH_OCR=1 -t creditsetu-api backend
FROM python:3.13-slim

ARG WITH_OCR=0
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements-base.txt requirements.txt ./
RUN if [ "$WITH_OCR" = "1" ]; then \
        apt-get update && apt-get install -y --no-install-recommends libgomp1 libglib2.0-0 libgl1 && rm -rf /var/lib/apt/lists/* && \
        pip install -r requirements.txt; \
    else \
        pip install -r requirements-base.txt; \
    fi

COPY app ./app
COPY data/lenders.json ./data/lenders.json
COPY schemas ./schemas

RUN useradd --create-home creditsetu && chown -R creditsetu /app
USER creditsetu

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
