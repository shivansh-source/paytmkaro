from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BACKEND_DIR / "data"
LENDERS_FILE = DATA_DIR / "lenders.json"
