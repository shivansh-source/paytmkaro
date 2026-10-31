import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BACKEND_DIR / "data"
LENDERS_FILE = DATA_DIR / "lenders.json"
DOCUMENT_SCHEMAS_DIR = BACKEND_DIR / "schemas" / "documents" / "v1"

# backend/.env (gitignored) holds GROQ_API_KEY; real environment variables win.
load_dotenv(BACKEND_DIR / ".env")

# Upload limits: the upload endpoint is a security boundary.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_PAGES = 40
RENDER_DPI = 200  # PDF page -> image for OCR/VLM
MAX_IMAGE_PIXELS = 40_000_000  # decompression-bomb guard for images

# OCR: PaddleOCR, local. "hi" is the Devanagari PP-OCRv5 model, which also reads English.
OCR_LANG = os.getenv("OCR_LANG", "hi")
# OCR_ENABLED=0 switches PaddleOCR off for uploads (the code stays): digital files are read from their text layer
# (PyMuPDF) and scans/photos go to the VLM. Page images then reach the VLM without Aadhaar blacking-out.
OCR_ENABLED = os.getenv("OCR_ENABLED", "1") != "0"

# VLM: Groq's OpenAI-compatible API, Qwen vision model. Fallback only (free tier is ~30 RPM / 1K RPD).
GROQ_API_KEY = os.getenv("GROQ_API_KEY")


def _groq_keys() -> list[str]:
    """Every configured Groq key, in order, without blanks or duplicates: GROQ_API_KEYS (comma separated),
    then GROQ_API_KEY, GROQ_API_KEY_2, GROQ_API_KEY_3 ... Each key is one worker in the VLM pool."""
    found = [k.strip() for k in os.getenv("GROQ_API_KEYS", "").split(",")]
    found.append(os.getenv("GROQ_API_KEY", ""))
    found += [os.getenv(f"GROQ_API_KEY_{n}", "") for n in range(2, 11)]
    return list(dict.fromkeys(k.strip() for k in found if k and k.strip()))


GROQ_API_KEYS = _groq_keys()
# Per-key limits and patience. 8,000 tokens a minute is the free-plan limit measured for the model below.
VLM_TPM_LIMIT = int(os.getenv("VLM_TPM_LIMIT", "8000"))
# Longest an upload will wait for a free key before it carries on without the vision model. This is what keeps
# an upload comfortably inside the web proxy's limit (3 minutes) however busy the keys are.
VLM_MAX_WAIT_SECONDS = float(os.getenv("VLM_MAX_WAIT_SECONDS", "15"))
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_VLM_MODEL = os.getenv("GROQ_VLM_MODEL", "qwen/qwen3.8-27b")
VLM_MAX_REQUESTS_PER_DOCUMENT = int(os.getenv("VLM_MAX_REQUESTS_PER_DOCUMENT", "3"))
# Page images reach the hosted VLM only after OCR has found and blacked out Aadhaar numbers. Without OCR
# (PaddleOCR not installed) the VLM is off for uploads unless this is set to 1, knowingly.
VLM_WITHOUT_OCR = os.getenv("VLM_WITHOUT_OCR", "0") == "1"

# LLM for understanding free-typed answers (questionnaire): Sarvam, built for Indian languages.
# Key goes in backend/.env as SARVAM_API_KEY; without it the questionnaire falls back to rules + chips.
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
SARVAM_BASE_URL = os.getenv("SARVAM_BASE_URL", "https://api.sarvam.ai/v1")
SARVAM_CHAT_MODEL = os.getenv("SARVAM_CHAT_MODEL", "sarvam-105b-conversations")
SARVAM_TIMEOUT_SECONDS = float(os.getenv("SARVAM_TIMEOUT_SECONDS", "15"))

# ---- Storage and deployment -------------------------------------------------------------------------
# Database: Supabase Postgres in production (DATABASE_URL, the "Session pooler" URI), a local SQLite file
# otherwise. CREDITSETU_DB overrides the SQLite path (tests use a temp file).
DATABASE_URL = os.getenv("DATABASE_URL")
SQLITE_PATH = Path(os.getenv("CREDITSETU_DB", DATA_DIR / "creditsetu.sqlite3"))
# Uploaded files: Supabase Storage when SUPABASE_URL + SUPABASE_SERVICE_KEY are set, else a local folder.
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")  # service_role key: server-side only, never the browser
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "documents")
UPLOADS_DIR = Path(os.getenv("CREDITSETU_UPLOADS", DATA_DIR / "uploads"))
# Encryption at rest for uploaded files, extracted documents, progress and applications. Any long random
# string; required when CREDITSETU_ENV=production. Changing it makes stored data unreadable.
CREDITSETU_ENV = os.getenv("CREDITSETU_ENV", "development")
CREDITSETU_SECRET = os.getenv("CREDITSETU_SECRET")
SESSION_DAYS = int(os.getenv("SESSION_DAYS", "14"))
# Browser origins allowed to call the API directly (the Vercel URL), comma-separated. Not needed when the
# frontend proxies /api/v1 (local dev).
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
SEED_DEMO = os.getenv("CREDITSETU_SEED", "1") == "1"
