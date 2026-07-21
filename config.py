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
# Medium-size "preview" images for fast lightbox loads over the internet / on a
# phone. The full-resolution original is always kept in IMAGE_DIR and stays one
# tap away; the preview is what the photo viewer loads by default.
PREVIEW_DIR: Path = ASSETS_DIR / "previews"
DATA_FILE: Path = BASE_DIR / "inventory.json"
# Operations module data. Materials (boards, packaging, shipping supplies,
# marketing…) and the production Batches they roll up into live in their own
# files, kept separate from the sellable inventory but sharing the same
# assets/ dirs (images/thumbnails/documents) and helper code.
MATERIALS_FILE: Path = BASE_DIR / "materials.json"
BATCHES_FILE: Path = BASE_DIR / "batches.json"

# Ensure folders exist
for p in (ASSETS_DIR, IMAGE_DIR, THUMB_DIR, DOCS_DIR, PREVIEW_DIR):
    p.mkdir(parents=True, exist_ok=True)
for _f in (DATA_FILE, MATERIALS_FILE, BATCHES_FILE):
    if not _f.exists():
        _f.write_text("[]", encoding="utf-8")

# ---------- Tesseract wiring ----------
# OCR needs the Tesseract *binary* (pytesseract is only the Python wrapper).
# Windows: the app ships a bundled Tesseract-OCR/ folder next to the code, so it
#   works with no install.
# Linux / macOS: there is no bundled binary — the app uses the system Tesseract,
#   which you install once with your package manager, e.g.
#       Debian/Ubuntu:  sudo apt install tesseract-ocr
#       Fedora:         sudo dnf install tesseract
#       macOS (brew):   brew install tesseract
#   If it isn't installed, the app still runs fine; images/PDFs are just saved
#   without their text being scanned for search.
import shutil

TESSERACT_DIR = BASE_DIR / "Tesseract-OCR"
TESSERACT_EXE = TESSERACT_DIR / "tesseract.exe"   # bundled Windows build
TESSDATA_DIR = TESSERACT_DIR / "tessdata"

# Resolve which tesseract we'll use: the bundled Windows exe if present, else
# whatever's on PATH (the system package on Linux/macOS).
_TESS_CMD: "str | None" = None
if TESSERACT_EXE.exists():
    os.environ["PATH"] = f"{str(TESSERACT_DIR)}{os.pathsep}{os.environ.get('PATH','')}"
    if TESSDATA_DIR.exists():
        os.environ.setdefault("TESSDATA_PREFIX", str(TESSDATA_DIR))
    _TESS_CMD = str(TESSERACT_EXE)
    print(f"[Config] OCR: using bundled Tesseract at {TESSERACT_EXE}")
else:
    _sys_tess = shutil.which("tesseract")
    if _sys_tess:
        _TESS_CMD = _sys_tess
        print(f"[Config] OCR: using system Tesseract at {_sys_tess}")
    else:
        print("[Config] OCR: Tesseract not found — image/PDF text scanning is "
              "disabled. Install it (Ubuntu/Debian: 'sudo apt install "
              "tesseract-ocr') to enable OCR. The app runs fine without it.")

# Make pytesseract import resilient to user-site package issues
try:
    import pytesseract  # type: ignore
    if _TESS_CMD:
        pytesseract.pytesseract.tesseract_cmd = _TESS_CMD
except Exception as e:
    # Do not crash app import if user-level pandas/pyarrow are broken
    print("[Config] Warning: pytesseract import failed:", e)
    pytesseract = None  # pylint: disable=invalid-name

# True when OCR is actually usable, so the UI can tell the user if it isn't.
OCR_AVAILABLE = bool(_TESS_CMD) and pytesseract is not None

# ---------- UI / Theme ----------
THEME_LIGHT = "https://cdn.jsdelivr.net/npm/bootswatch@5.3.3/dist/flatly/bootstrap.min.css"
THEME_DARK = "https://cdn.jsdelivr.net/npm/bootswatch@5.3.3/dist/darkly/bootstrap.min.css"
THEME_DEFAULT_MODE = os.getenv("INVENTORY_THEME", "dark").strip().lower()

DATATABLE_PAGE_SIZE = 10
TOAST_DURATION = 3500
LOW_STOCK_THRESHOLD = 5
OCR_TEXT_MAX_CHARS = 400

# ---------- Image serving / mobile performance ----------
# The photo viewer loads a downscaled "preview" (longest edge <= PREVIEW_MAX_EDGE,
# re-encoded at PREVIEW_QUALITY) instead of the multi-MB original, which is what
# makes viewing snappy over the internet. The original is untouched on disk and
# reachable via the "View full resolution" link. Tune with env vars if needed.
try:
    PREVIEW_MAX_EDGE = int(os.getenv("INVENTORY_PREVIEW_MAX_EDGE", "1600"))
except (TypeError, ValueError):
    PREVIEW_MAX_EDGE = 1600
try:
    PREVIEW_QUALITY = int(os.getenv("INVENTORY_PREVIEW_QUALITY", "82"))
except (TypeError, ValueError):
    PREVIEW_QUALITY = 82
# Content-addressed asset filenames (…-<ms>.<ext>) never change, so they can be
# cached hard. Seconds in the Cache-Control max-age (1 year) + "immutable".
ASSET_CACHE_MAX_AGE = 31536000

# Public helpers (used by other modules)
ASSET_IMAGE_PATH = IMAGE_DIR
ASSET_THUMB_PATH = THUMB_DIR
ASSET_PREVIEW_PATH = PREVIEW_DIR
ASSET_DOCS_PATH = DOCS_DIR
INVENTORY_JSON = DATA_FILE
MATERIALS_JSON = MATERIALS_FILE
BATCHES_JSON = BATCHES_FILE
