from __future__ import annotations
from pathlib import Path
import os

# ---------- Paths ----------
BASE_DIR: Path = Path(__file__).resolve().parent
ASSETS_DIR: Path = BASE_DIR / "assets"
IMAGE_DIR: Path = ASSETS_DIR / "images"
THUMB_DIR: Path = ASSETS_DIR / "thumbnails"
# Attached documents (invoices, saved product pages, receipts, manuals…). Any
# file type is kept here as a record; images/HTML are also parsed to fill fields.
DOCS_DIR: Path = ASSETS_DIR / "documents"
DATA_FILE: Path = BASE_DIR / "inventory.json"

# Ensure folders exist
for p in (ASSETS_DIR, IMAGE_DIR, THUMB_DIR, DOCS_DIR):
    p.mkdir(parents=True, exist_ok=True)
if not DATA_FILE.exists():
    DATA_FILE.write_text("[]", encoding="utf-8")

# ---------- Tesseract wiring ----------
TESSERACT_DIR = BASE_DIR / "Tesseract-OCR"
TESSERACT_EXE = TESSERACT_DIR / "tesseract.exe"
TESSDATA_DIR = TESSERACT_DIR / "tessdata"

# Help child processes/libraries find Tesseract & tessdata
if TESSERACT_EXE.exists():
    os.environ["PATH"] = f"{str(TESSERACT_DIR)}{os.pathsep}{os.environ.get('PATH','')}"
    if TESSDATA_DIR.exists():
        os.environ.setdefault("TESSDATA_PREFIX", str(TESSDATA_DIR))
    print(f"[Config] Using bundled Tesseract at {TESSERACT_EXE}")
else:
    print("[Config] Warning: tesseract.exe not found at", TESSERACT_EXE)

# Make pytesseract import resilient to user-site package issues
try:
    import pytesseract  # type: ignore
    if TESSERACT_EXE.exists():
        pytesseract.pytesseract.tesseract_cmd = str(TESSERACT_EXE)
except Exception as e:
    # Do not crash app import if user-level pandas/pyarrow are broken
    print("[Config] Warning: pytesseract import failed:", e)
    pytesseract = None  # pylint: disable=invalid-name

# ---------- UI / Theme ----------
THEME_LIGHT = "https://cdn.jsdelivr.net/npm/bootswatch@5.3.3/dist/flatly/bootstrap.min.css"
THEME_DARK = "https://cdn.jsdelivr.net/npm/bootswatch@5.3.3/dist/darkly/bootstrap.min.css"
THEME_DEFAULT_MODE = os.getenv("INVENTORY_THEME", "dark").strip().lower()

DATATABLE_PAGE_SIZE = 10
TOAST_DURATION = 3500
LOW_STOCK_THRESHOLD = 5
OCR_TEXT_MAX_CHARS = 400

# Public helpers (used by other modules)
ASSET_IMAGE_PATH = IMAGE_DIR
ASSET_THUMB_PATH = THUMB_DIR
ASSET_DOCS_PATH = DOCS_DIR
INVENTORY_JSON = DATA_FILE
