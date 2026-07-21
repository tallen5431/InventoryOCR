"""Automatic, non-blocking OCR for uploaded images.

Why a separate module (not the OCR Lab engine)?
  * The OCR Lab is tuned for *photos of labels* — adaptive threshold + a
    character whitelist that strips punctuation. That actively hurts the case
    the user cares about here: **screenshots of web pages / invoices**, which
    are already clean, high-contrast text full of punctuation and symbols.
  * OCR is slow (seconds per image, much longer for a long screenshot), so it
    must NEVER run inside the upload callback — that would freeze the photo
    gallery for as long as OCR takes. Instead we OCR on a small background
    thread pool the moment an image is saved, keying every result by the
    image's on-disk filename. Whoever needs the text later (the live preview in
    the form, or the save-time write-back) reads that cache — instantly if it's
    ready, and OCR is never run twice for the same file.

Reliability choices for screenshots / long images (extract_document_text):
  * light preprocessing only (grayscale + autocontrast) — aggressive binarising
    damages anti-aliased screenshot text;
  * upscale small images and downscale very wide ones to a sweet-spot width;
  * TILE very tall images vertically (with overlap) so Tesseract stays fast and
    never hits its internal height limits — this is what makes "very long
    screenshots" work;
  * PSM 3 (automatic page segmentation) for whole images, PSM 6 per tile;
  * no character whitelist, generous timeout, everything fails soft to "".
"""
from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional

from PIL import Image, ImageOps

from config import ASSET_IMAGE_PATH

# --------------------------------------------------------------------
# Tunables
# --------------------------------------------------------------------
# Two workers: enough that a couple of photos scan in parallel without pegging
# every core on the box that also serves the web app.
_MAX_WORKERS = 2
# Target working width. Below this we upscale (small text OCRs poorly); above
# _MAX_WIDTH we downscale (huge screenshots waste time for no accuracy gain).
_TARGET_WIDTH = 1600
_MAX_WIDTH = 2600
# Tiling: once an image is taller than this, slice it into overlapping vertical
# strips. Tesseract slows super-linearly on tall inputs and refuses images past
# ~32k px, so tiling is what lets a full-page screenshot scan at all.
_TILE_HEIGHT = 2400
_TILE_OVERLAP = 160
# Never spend longer than this on a single Tesseract call (seconds).
_OCR_TIMEOUT = 45
# Cap stored text so a pathological screenshot can't bloat inventory.json.
_MAX_CHARS = 20000

# --------------------------------------------------------------------
# Background cache: filename -> extracted text ("" means "scanned, no text")
# --------------------------------------------------------------------
_RESULTS: Dict[str, str] = {}
_FUTURES: Dict[str, Future] = {}
_LOCK = threading.Lock()
_POOL: Optional[ThreadPoolExecutor] = None


def _pool() -> ThreadPoolExecutor:
    global _POOL
    if _POOL is None:
        _POOL = ThreadPoolExecutor(max_workers=_MAX_WORKERS,
                                   thread_name_prefix="ocr-auto")
    return _POOL


# --------------------------------------------------------------------
# The OCR routine (screenshot / document tuned)
# --------------------------------------------------------------------

def _tesseract_string(img: Image.Image, psm: int) -> str:
    """One Tesseract call, or "" if OCR is unavailable / times out / errors."""
    try:
        import pytesseract
    except Exception:
        return ""
    try:
        # oem 1 = LSTM engine; no char whitelist so punctuation/symbols survive.
        cfg = f"--oem 1 --psm {int(psm)}"
        return pytesseract.image_to_string(img, lang="eng", config=cfg,
                                           timeout=_OCR_TIMEOUT) or ""
    except Exception:
        # RuntimeError on timeout, or any Tesseract/binary problem — fail soft.
        return ""


def _prep(img: Image.Image) -> Image.Image:
    """Light, screenshot-friendly preprocessing → grayscale, sized, autocontrast."""
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    img = ImageOps.grayscale(img)

    w, h = img.size
    if w and w < _TARGET_WIDTH:
        scale = _TARGET_WIDTH / float(w)
        # Cap the upscale so a tiny thumbnail isn't blown up absurdly.
        scale = min(scale, 3.0)
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                         Image.LANCZOS)
    elif w > _MAX_WIDTH:
        scale = _MAX_WIDTH / float(w)
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                         Image.LANCZOS)

    try:
        img = ImageOps.autocontrast(img, cutoff=1)
    except Exception:
        pass
    return img


def _dedupe_lines(lines: List[str]) -> List[str]:
    """Drop blank lines and consecutive duplicates (tile overlap repeats a row)."""
    out: List[str] = []
    prev = None
    for ln in lines:
        s = ln.strip()
        if not s or s == prev:
            continue
        out.append(s)
        prev = s
    return out


def extract_document_text(source) -> str:
    """Best-effort text from an image path / PIL image, tuned for screenshots.

    Never raises: returns "" on any failure (missing Tesseract, unreadable file,
    timeout). Tall images are tiled so even very long screenshots complete.
    """
    try:
        img = source if isinstance(source, Image.Image) else Image.open(source)
        img.load()
    except Exception:
        return ""

    img = _prep(img)
    w, h = img.size

    lines: List[str] = []
    if h <= _TILE_HEIGHT:
        # Whole image: PSM 3 lets Tesseract segment columns/blocks itself.
        lines = _tesseract_string(img, psm=3).splitlines()
    else:
        # Overlapping vertical strips; PSM 6 treats each strip as one text block.
        top = 0
        step = _TILE_HEIGHT - _TILE_OVERLAP
        while top < h:
            bottom = min(top + _TILE_HEIGHT, h)
            tile = img.crop((0, top, w, bottom))
            lines.extend(_tesseract_string(tile, psm=6).splitlines())
            if bottom >= h:
                break
            top += step

    text = "\n".join(_dedupe_lines(lines)).strip()
    if len(text) > _MAX_CHARS:
        cut = text.rfind(" ", 0, _MAX_CHARS)
        text = text[: cut if cut != -1 else _MAX_CHARS].rstrip()
    return text


# --------------------------------------------------------------------
# Background queue keyed by filename
# --------------------------------------------------------------------

def _worker(filename: str) -> str:
    text = ""
    try:
        path = Path(ASSET_IMAGE_PATH) / filename
        if path.exists():
            text = extract_document_text(path)
    except Exception:
        text = ""
    with _LOCK:
        _RESULTS[filename] = text
        _FUTURES.pop(filename, None)
    return text


def queue_image(filename: str) -> None:
    """Start background OCR for a saved image. Idempotent and non-blocking."""
    filename = (filename or "").strip()
    if not filename:
        return
    with _LOCK:
        if filename in _RESULTS or filename in _FUTURES:
            return
        self_pool = _pool()
        self_pool_submit = self_pool.submit
    # Submit outside the lock; record the future under the lock.
    fut = self_pool_submit(_worker, filename)
    with _LOCK:
        # A concurrent queue_image may have already recorded/finished it.
        if filename not in _RESULTS and filename not in _FUTURES:
            _FUTURES[filename] = fut


def result(filename: str) -> Optional[str]:
    """Cached OCR text for a filename, or None if it hasn't finished (or wasn't
    queued this session)."""
    with _LOCK:
        return _RESULTS.get(filename)


def is_pending(filename: str) -> bool:
    with _LOCK:
        return filename in _FUTURES


def preview(filenames: List[str]) -> Dict[str, object]:
    """Snapshot for the live form panel.

    Only reflects images queued THIS session (existing images from a past
    session were never queued, so they're ignored here). Returns:
        scanned  – how many of these have a cached result
        pending  – how many are still being OCR'd
        text     – combined text of the ready ones (in the given order)
    """
    files = [f for f in (filenames or []) if f]
    scanned = 0
    pending = 0
    texts: List[str] = []
    with _LOCK:
        for f in files:
            if f in _RESULTS:
                scanned += 1
                if _RESULTS[f]:
                    texts.append(_RESULTS[f])
            elif f in _FUTURES:
                pending += 1
    return {"scanned": scanned, "pending": pending, "text": "\n".join(texts).strip()}


def text_for(filenames: List[str], *, wait: bool = False) -> str:
    """Combined OCR text for the given images.

    With ``wait`` (used by the save-time write-back, which runs off the request
    thread) this blocks up to the OCR timeout for any still-running scans, so a
    save that happens before the preview finished still captures the text.
    """
    files = [f for f in (filenames or []) if f]
    texts: List[str] = []
    for f in files:
        if wait:
            queue_image(f)  # no-op if already queued/done
            with _LOCK:
                fut = _FUTURES.get(f)
            if fut is not None:
                try:
                    fut.result(timeout=_OCR_TIMEOUT + 5)
                except Exception:
                    pass
        t = result(f)
        if t:
            texts.append(t)
    return "\n".join(texts).strip()


def merge_text(base: str, addition: str) -> str:
    """Append ``addition`` to ``base`` unless it's already there. Keeps the
    existing OCR text of an edited item and adds only what a new image found."""
    base = (base or "").strip()
    addition = (addition or "").strip()
    if not addition or addition in base:
        return base
    return f"{base}\n{addition}".strip() if base else addition
