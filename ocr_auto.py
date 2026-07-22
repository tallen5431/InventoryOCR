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

import io
import os
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageOps

from config import ASSET_IMAGE_PATH, ASSET_DOCS_PATH

# --------------------------------------------------------------------
# Tunables
# --------------------------------------------------------------------
# How many images/PDFs to OCR at once in the background. This is the real cap on
# OCR's CPU footprint (each Tesseract process is pinned to one thread via
# OMP_THREAD_LIMIT in config), so keep it small: background scanning is a
# convenience, not something that should ever make the machine sluggish. Default
# 1 (fully serial — the safest choice on the small boxes this tends to run on);
# raise INVENTORY_OCR_WORKERS on a beefier host if you want photos to scan in
# parallel.
def _default_workers() -> int:
    try:
        n = int(os.getenv("INVENTORY_OCR_WORKERS", "1"))
    except (TypeError, ValueError):
        n = 1
    return max(1, n)

_MAX_WORKERS = _default_workers()
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
# PDFs: how many pages to read at most, and the render DPI used only when a page
# has no text layer and must be OCR'd. 200 dpi is the accuracy/speed sweet spot.
_PDF_MAX_PAGES = 40
_PDF_RENDER_DPI = 200
# A page with fewer than this many characters of embedded text is treated as
# "no real text layer" (i.e. a scan) and rendered + OCR'd instead.
_PDF_TEXT_MIN = 20
# Attachment kinds worth scanning. HTML product pages are parsed elsewhere
# (product_import); other/unknown types carry no reliable text.
_OCRABLE_DOC_KINDS = ("image", "pdf")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


# Accuracy tunables (all safe defaults; opt-in for the slower/riskier passes):
#   * Drop OCR words below this confidence at the source — this is what removes
#     the garbled-graphics "soup" ("3c ce)", "OBooVoeZoo") before it ever reaches
#     the text, sharpening both the stored text and the relevance filter. 0
#     disables the filter (keep every word, old behaviour).
_MIN_CONF = _env_int("INVENTORY_OCR_MIN_CONF", 35)
#   * Multi-pass: also try PSM 4 (single uniform column — how most retailer /
#     invoice pages are laid out) on whole images and keep whichever pass reads
#     with higher mean confidence. Costs a second Tesseract call, so opt-in.
_MULTIPASS = _env_flag("INVENTORY_OCR_MULTIPASS")
#   * Auto-rotate via Tesseract OSD before OCR. A real win for sideways photos of
#     labels, but it can misjudge sparse screenshots, so it's opt-in and only
#     ever applies a clean 90/180/270 turn.
_DESKEW = _env_flag("INVENTORY_OCR_DESKEW")

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

def _ocr_pass(img: Image.Image, psm: int) -> Tuple[str, float]:
    """One Tesseract pass → (text, mean_confidence).

    Uses ``image_to_data`` so we can drop low-confidence words at the source
    (the garbled-graphics soup) and rebuild clean lines, and so multi-pass can
    compare passes by confidence. Falls back to plain ``image_to_string`` if the
    data call isn't available, and to "" on any timeout / binary problem.
    """
    try:
        import pytesseract
        from pytesseract import Output
    except Exception:
        return "", 0.0
    # oem 1 = LSTM engine; no char whitelist so punctuation/symbols survive.
    cfg = f"--oem 1 --psm {int(psm)}"
    try:
        data = pytesseract.image_to_data(img, lang="eng", config=cfg,
                                         timeout=_OCR_TIMEOUT,
                                         output_type=Output.DICT)
    except Exception:
        # image_to_data unsupported / timed out — fall back to the plain call.
        try:
            txt = pytesseract.image_to_string(img, lang="eng", config=cfg,
                                              timeout=_OCR_TIMEOUT) or ""
            return txt, 0.0
        except Exception:
            return "", 0.0

    words = data.get("text", []) or []
    confs = data.get("conf", []) or []
    # Group words back into their source lines, keeping only confident ones.
    lines: Dict[Tuple[int, int, int], List[str]] = {}
    order: List[Tuple[int, int, int]] = []
    kept_confs: List[float] = []
    for i, word in enumerate(words):
        w = (word or "").strip()
        if not w:
            continue
        try:
            c = float(confs[i])
        except (TypeError, ValueError, IndexError):
            c = -1.0
        if c >= 0 and _MIN_CONF > 0 and c < _MIN_CONF:
            continue
        # Group by (block, paragraph, line) to rebuild the source line. Fall back
        # to the running index if a key column is absent (non-standard result).
        def _at(col: str) -> int:
            try:
                return int(data[col][i])
            except (KeyError, IndexError, TypeError, ValueError):
                return i
        key = (_at("block_num"), _at("par_num"), _at("line_num"))
        if key not in lines:
            lines[key] = []
            order.append(key)
        lines[key].append(w)
        if c >= 0:
            kept_confs.append(c)
    text = "\n".join(" ".join(lines[k]) for k in order)
    mean_conf = (sum(kept_confs) / len(kept_confs)) if kept_confs else 0.0
    return text, mean_conf


def _tesseract_string(img: Image.Image, psm: int) -> str:
    """Confident OCR text for an image/tile, or "" if OCR is unavailable.

    With ``INVENTORY_OCR_MULTIPASS`` and a whole-page segmentation (PSM 3) it
    also tries PSM 4 (single column) and keeps the higher-confidence read; every
    other case is a single pass. Never raises."""
    text, conf = _ocr_pass(img, psm)
    if _MULTIPASS and int(psm) == 3:
        alt_text, alt_conf = _ocr_pass(img, 4)
        # Prefer the more confident pass; on a tie prefer the one that read more.
        if (alt_conf, len(alt_text)) > (conf, len(text)):
            return alt_text
    return text


def _deskew(img: Image.Image) -> Image.Image:
    """Rotate a sideways image upright using Tesseract OSD (opt-in, best-effort).

    Only a clean 90/180/270 turn with a non-trivial orientation confidence is
    applied; anything else (or any failure) leaves the image untouched, so a
    normal screenshot is never rotated on a bad guess."""
    if not _DESKEW:
        return img
    try:
        import pytesseract
        from pytesseract import Output
        osd = pytesseract.image_to_osd(img, output_type=Output.DICT)
        rotate = int(osd.get("rotate", 0) or 0)
        conf = float(osd.get("orientation_conf", 0) or 0)
        if rotate in (90, 180, 270) and conf >= 1.0:
            # PIL rotates counter-clockwise; OSD 'rotate' is the clockwise turn
            # needed to upright the page, so negate it. expand keeps all pixels.
            return img.rotate(-rotate, expand=True)
    except Exception:
        pass
    return img


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

    # Deskew (opt-in) before prep so a sideways label photo reads at all; a no-op
    # for the common upright screenshot.
    img = _deskew(img)
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

    return _cap("\n".join(_dedupe_lines(lines)))


def _cap(text: str) -> str:
    text = (text or "").strip()
    if len(text) > _MAX_CHARS:
        cut = text.rfind(" ", 0, _MAX_CHARS)
        text = text[: cut if cut != -1 else _MAX_CHARS].rstrip()
    return text


def extract_pdf_text(source) -> str:
    """Best-effort text from a PDF path, tuned for invoices / saved pages.

    Digital PDFs (most invoices, saved web pages) carry a real text layer, which
    we read directly — fast and exact. A scanned PDF has little/no text layer, so
    each such page is rendered to an image and run through the same tuned OCR as
    a screenshot. Needs PyMuPDF (``fitz``); returns "" if it isn't installed or
    anything goes wrong — the PDF is still kept as an attachment either way.
    """
    try:
        import fitz  # PyMuPDF
    except Exception:
        return ""
    parts: List[str] = []
    try:
        with fitz.open(source) as doc:
            for i, page in enumerate(doc):
                if i >= _PDF_MAX_PAGES:
                    break
                try:
                    t = (page.get_text("text") or "").strip()
                    if len(t) < _PDF_TEXT_MIN:
                        # No usable text layer — render the page and OCR it.
                        pix = page.get_pixmap(dpi=_PDF_RENDER_DPI)
                        img = Image.open(io.BytesIO(pix.tobytes("png")))
                        t = extract_document_text(img)
                except Exception:
                    t = ""
                if t.strip():
                    parts.append(t.strip())
    except Exception:
        return ""
    return _cap("\n".join(parts))


# --------------------------------------------------------------------
# Background queue keyed by an opaque "ref"
# --------------------------------------------------------------------
# A ref is a plain filename for an item photo (lives in assets/images — this is
# the historical case, kept as-is so callers pass bare filenames), or
# "doc:<filename>" for an attached document (assets/documents). Documents may be
# a screenshot (OCR'd like a photo) or a PDF (text-layer or render+OCR).

_DOC_PREFIX = "doc:"


def _resolve(ref: str):
    """(path, kind) for a ref. kind is 'image' | 'pdf' | 'html' | 'other'."""
    if ref.startswith(_DOC_PREFIX):
        fn = ref[len(_DOC_PREFIX):]
        try:
            from utils import attachment_kind
            kind = attachment_kind(fn)
        except Exception:
            kind = "other"
        return Path(ASSET_DOCS_PATH) / fn, kind
    return Path(ASSET_IMAGE_PATH) / ref, "image"


def _worker(ref: str) -> str:
    text = ""
    try:
        path, kind = _resolve(ref)
        if path.exists():
            if kind == "pdf":
                text = extract_pdf_text(path)
            elif kind == "image":
                text = extract_document_text(path)
            # html/other: nothing to OCR (html is parsed by product_import).
    except Exception:
        text = ""
    with _LOCK:
        _RESULTS[ref] = text
        _FUTURES.pop(ref, None)
    return text


def _enqueue(ref: str, force: bool = False) -> None:
    """Start background OCR for a ref. Idempotent and non-blocking.

    With ``force`` a previously-cached result for this ref is discarded first, so
    the file is scanned again (used by an explicit "re-scan" that must replace a
    stale or low-quality read rather than reuse it)."""
    ref = (ref or "").strip()
    if not ref:
        return
    with _LOCK:
        if force:
            _RESULTS.pop(ref, None)  # drop the stale read; a live scan re-runs it
        if ref in _RESULTS or ref in _FUTURES:
            return
        submit = _pool().submit
    # Submit outside the lock; record the future under the lock.
    fut = submit(_worker, ref)
    with _LOCK:
        # A concurrent call may have already recorded/finished it.
        if ref not in _RESULTS and ref not in _FUTURES:
            _FUTURES[ref] = fut


def rescan(refs: List[str]) -> None:
    """Force a fresh OCR of each ref, discarding any cached read. Non-blocking —
    callers that need the text wait via ``text_for``/``raw_for_refs``."""
    for r in refs or []:
        _enqueue((r or "").strip(), force=True)


def queue_image(filename: str) -> None:
    """Start background OCR for a saved item photo (assets/images)."""
    _enqueue((filename or "").strip())


def doc_refs(attachments) -> List[str]:
    """Scan refs for the OCR-worthy documents (images & PDFs) in an attachment
    list. HTML/other are skipped — they carry no OCR text worth indexing."""
    out: List[str] = []
    for a in attachments or []:
        if isinstance(a, dict):
            fn = (a.get("filename") or "").strip()
            kind = a.get("kind") or ""
        else:
            fn = str(a).strip()
            kind = ""
        if not fn:
            continue
        if not kind:
            try:
                from utils import attachment_kind
                kind = attachment_kind(fn)
            except Exception:
                kind = "other"
        if kind in _OCRABLE_DOC_KINDS:
            out.append(f"{_DOC_PREFIX}{fn}")
    return out


def queue_document(attachment) -> Optional[str]:
    """Start background OCR for one attachment (a meta dict or filename) if it's
    an image or PDF. Returns its ref, or None if it isn't OCR-worthy."""
    refs = doc_refs([attachment])
    if not refs:
        return None
    _enqueue(refs[0])
    return refs[0]


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
        text     – combined *item-relevant* text of the ready ones, filtered the
                   same way it will be when saved, so the panel shows exactly
                   what ends up searchable (not the raw page chrome/cross-sell)
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
    return {"scanned": scanned, "pending": pending,
            "text": index_text("\n".join(texts))}


def raw_for_refs(filenames: List[str], *, wait: bool = False) -> Dict[str, str]:
    """Per-ref raw OCR text: ``{ref: text}`` for every ref that yielded any.

    The building block behind ``text_for``. Keeping the text keyed by its source
    file lets the caller store one scan per image, so re-scanning one image
    replaces only its entry and removing an image drops only its entry — no
    stacking, no orphaned text. ``wait`` blocks for still-running scans, as in
    ``text_for``.
    """
    out: Dict[str, str] = {}
    for f in [f for f in (filenames or []) if f]:
        if wait:
            _enqueue(f)  # no-op if already queued/done (f may be a doc: ref)
            with _LOCK:
                fut = _FUTURES.get(f)
            if fut is not None:
                try:
                    fut.result(timeout=_OCR_TIMEOUT + 5)
                except Exception:
                    pass
        t = result(f)
        if t:
            out[f] = t
    return out


def text_for(filenames: List[str], *, wait: bool = False) -> str:
    """Combined OCR text for the given images.

    With ``wait`` (used by the save-time write-back, which runs off the request
    thread) this blocks up to the OCR timeout for any still-running scans, so a
    save that happens before the preview finished still captures the text.
    """
    per = raw_for_refs(filenames, wait=wait)
    # Preserve caller order (raw_for_refs iterates the given list in order).
    return "\n".join(per.values()).strip()


def index_text(raw: str) -> str:
    """The item-relevant subset of raw scan text — for the search index / display.

    A screenshot of a retailer page OCRs into mostly noise: site nav, the buy
    box, cross-sell carousels of OTHER products, the whole review section, footer
    boilerplate. Indexing all of that makes searches match unrelated items, so
    the copy we save/show is passed through this relevance filter.

    The RAW text is still what ``text_for()`` returns — invoice parsing needs the
    buy-box / order details this strips — so only the searchable/displayed copy
    is filtered, never the copy used to read purchase fields.
    """
    try:
        from text_relevance import for_index
        return for_index(raw or "")
    except Exception:
        return (raw or "").strip()


def merge_text(base: str, addition: str) -> str:
    """Append ``addition`` to ``base`` unless it's already there. Keeps the
    existing OCR text of an edited item and adds only what a new image found."""
    base = (base or "").strip()
    addition = (addition or "").strip()
    if not addition or addition in base:
        return base
    return f"{base}\n{addition}".strip() if base else addition
