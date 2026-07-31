from __future__ import annotations
import base64, io, re, time
from pathlib import Path
from typing import Dict, Any, Optional
from PIL import Image, ImageOps
from config import (
    ASSET_IMAGE_PATH, ASSET_THUMB_PATH, ASSET_DOCS_PATH, ASSET_PREVIEW_PATH,
    PREVIEW_MAX_EDGE, PREVIEW_QUALITY, ASSET_URL_BASE,
)

# --------------------------------------------------------------------
# URL base for assets when served behind Caddy
# --------------------------------------------------------------------
# URL_PREFIX is set by your server manager for this app:
#   URL_PREFIX=/inventory
#
# We want browser URLs like:
#   /inventory/assets/images/<file>
#   /inventory/assets/thumbnails/<file>
#
# When running locally without a prefix, this cleanly falls back to:
#   /assets/images/<file>, etc.
# --------------------------------------------------------------------
# ASSET_URL_BASE is defined once in config (alongside URL_PREFIX) so the app's
# routes and the URLs generated here can never drift apart.


def _decode_upload(contents: str) -> tuple[bytes, str]:
    """dcc.Upload contents -> (bytes, ext)"""
    # dcc.Upload payloads are data URIs ("data:<mime>;base64,<b64>"), but guard
    # against a header-less/base64-only string so we don't raise ValueError on
    # split — save_attachment already handles this same case defensively.
    contents = contents or ""
    if "," in contents:
        header, b64 = contents.split(",", 1)
    else:
        header, b64 = "", contents
    raw = base64.b64decode(b64)
    # Try to infer extension from header
    ext = "png"
    if "jpeg" in header or "jpg" in header:
        ext = "jpg"
    elif "webp" in header:
        ext = "webp"
    elif "png" in header:
        ext = "png"
    return raw, ext


def _slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "image"


def _ensure_pil(img_bytes: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(img_bytes))
    img.load()
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    if img.mode not in ("L", "RGB"):
        img = img.convert("RGB")
    return img


def _save_image_bytes(img: Image.Image, path: Path):
    if path.suffix.lower() in (".jpg", ".jpeg"):
        img.save(path, format="JPEG", quality=92)
    elif path.suffix.lower() == ".webp":
        img.save(path, format="WEBP", quality=92, method=6)
    else:
        img.save(path, format="PNG", compress_level=6)


def _downscale(img: Image.Image, max_edge: int) -> Image.Image:
    """Return a copy whose longest edge is <= ``max_edge`` (no upscaling)."""
    w, h = img.size
    longest = max(w, h)
    if longest <= max_edge:
        return img.copy()
    scale = max_edge / float(longest)
    return img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)


def _save_preview_bytes(img: Image.Image, path: Path):
    """Save a mid-size preview: lossy formats at PREVIEW_QUALITY (small over the
    wire), PNG kept lossless-but-optimized so screenshots/text stay crisp."""
    ext = path.suffix.lower()
    if ext in (".jpg", ".jpeg"):
        img.save(path, format="JPEG", quality=PREVIEW_QUALITY, optimize=True)
    elif ext == ".webp":
        img.save(path, format="WEBP", quality=PREVIEW_QUALITY, method=6)
    else:
        img.save(path, format="PNG", optimize=True, compress_level=9)


def _write_preview(img: Image.Image, filename: str) -> None:
    """Downscale + write the preview tier for ``filename`` (best-effort)."""
    try:
        ASSET_PREVIEW_PATH.mkdir(parents=True, exist_ok=True)
        _save_preview_bytes(_downscale(img, PREVIEW_MAX_EDGE), ASSET_PREVIEW_PATH / filename)
    except Exception:
        pass


def _asset_url(kind: str, filename: str) -> str:
    """Build /inventory/assets/<kind>/<filename> (or /assets/... without prefix)."""
    kind = kind.strip("/")
    filename = filename.lstrip("/")
    return f"{ASSET_URL_BASE}/{kind}/{filename}"


def save_image(
    contents: str,
    out_dir: Path = ASSET_IMAGE_PATH,
    *,
    base_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Save dcc.Upload contents to assets/images and a thumbnail to assets/thumbnails."""
    raw, ext = _decode_upload(contents)
    img = _ensure_pil(raw)

    stamp = int(time.time() * 1000)
    stem = _slugify(base_name or f"item-{stamp}")
    filename = f"{stem}-{stamp}.{ext}"
    out_path = out_dir / filename

    _save_image_bytes(img, out_path)

    # Thumbnail (table grid) + medium preview (fast lightbox loads off-LAN).
    thumb = img.copy()
    thumb.thumbnail((320, 320))
    thumb_path = ASSET_THUMB_PATH / filename
    _save_image_bytes(thumb, thumb_path)
    _write_preview(img, filename)

    return {
        "filename": filename,
        "path": str(out_path),
        "thumb_path": str(thumb_path),
        "url": _asset_url("images", filename),
        "thumb_url": _asset_url("thumbnails", filename),
        "preview_url": _asset_url("previews", filename),
    }


def attachment_kind(name: str) -> str:
    """Classify an attachment by extension: image / html / pdf / other.

    Drives the icon shown for it and whether we try to parse it (images and
    HTML are parsed; everything else is kept as a record only).
    """
    ext = Path(name or "").suffix.lower().lstrip(".")
    if ext in {"jpg", "jpeg", "png", "webp", "gif", "bmp", "tif", "tiff", "heic"}:
        return "image"
    if ext in {"html", "htm"}:
        return "html"
    if ext == "pdf":
        return "pdf"
    return "other"


def save_attachment(contents: str, original_name: str,
                    out_dir: Path = ASSET_DOCS_PATH) -> Dict[str, Any]:
    """Save a dcc.Upload payload of ANY type to assets/documents.

    Unlike ``save_image`` this never re-encodes — the bytes are written verbatim,
    so invoices, saved product pages, manuals, spreadsheets, etc. are preserved
    exactly. Returns metadata stored on the item's ``attachments`` list.
    """
    if "," in (contents or ""):
        raw = base64.b64decode(contents.split(",", 1)[1])
    else:
        raw = base64.b64decode(contents or "")

    src = Path(original_name or "attachment")
    stem = _slugify(src.stem) or "attachment"
    ext = src.suffix.lower().lstrip(".")
    ext = re.sub(r"[^a-z0-9]+", "", ext)[:8]  # keep the extension, sanitised
    stamp = int(time.time() * 1000)
    filename = f"{stem}-{stamp}.{ext}" if ext else f"{stem}-{stamp}"

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / filename).write_bytes(raw)

    return {
        "filename": filename,
        "original_name": (original_name or filename).strip(),
        "kind": attachment_kind(original_name or filename),
        "size": len(raw),
        "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "url": _asset_url("documents", filename),
    }


def read_attachment_text(filename: str) -> str:
    """Best-effort text for a stored attachment, for (re)parsing.

    HTML is decoded as text; images and PDFs are OCR'd. Other types return ""
    (kept as a record but not parsed). Never raises — returns "" on any failure.
    """
    path = ASSET_DOCS_PATH / filename
    if not path.exists():
        return ""
    kind = attachment_kind(filename)
    try:
        if kind == "html":
            return path.read_text(encoding="utf-8", errors="replace")
        if kind in ("image", "pdf"):
            # Go through the shared background scanner so an attached invoice is
            # OCR'd ONCE — this call reuses the same result the searchable-text
            # scan produces (and vice-versa) instead of running a second, whole
            # separate OCR pass. It also gets PDFs parsed for purchase fields.
            import ocr_auto
            return ocr_auto.text_for([f"doc:{filename}"], wait=True)
    except Exception:
        return ""
    return ""


def get_thumbnail_url(filename: str | None) -> str:
    if not filename:
        return ""
    t = ASSET_THUMB_PATH / filename
    if not t.exists():
        # Best effort on-demand recreation if the full image exists. Guarded like
        # its sibling get_preview_url: this runs inside the dashboard's main
        # table/form callback, so one truncated or undecodable file in the photo
        # folder used to blow up the whole page on every load.
        full = ASSET_IMAGE_PATH / filename
        if full.exists():
            try:
                img = _ensure_pil(full.read_bytes())
                img.thumbnail((320, 320))
                _save_image_bytes(img, t)
            except Exception:
                pass
    return _asset_url("thumbnails", filename) if t.exists() else ""


def get_image_url(filename: str | None) -> str:
    """Get the full-size (original) image URL."""
    if not filename:
        return ""
    return _asset_url("images", filename)


def get_preview_url(filename: str | None) -> str:
    """URL of the medium preview used by the photo viewer. Created on demand from
    the original if it doesn't exist yet (so pre-existing photos get one on first
    view). Falls back to the full-size URL if a preview can't be produced."""
    if not filename:
        return ""
    p = ASSET_PREVIEW_PATH / filename
    if not p.exists():
        full = ASSET_IMAGE_PATH / filename
        if full.exists():
            try:
                _write_preview(_ensure_pil(full.read_bytes()), filename)
            except Exception:
                pass
    return _asset_url("previews", filename) if p.exists() else get_image_url(filename)


# --------------------------------------------------------------------
# Image payload helpers, shared by the lookup clients
# --------------------------------------------------------------------
# Used by both vision_lookup (Ollama) and web_detect (SerpApi / Google Vision).
# They lived as byte-identical copies in each of those modules.

def image_to_bytes(image) -> bytes:
    """Accept raw bytes or a data URL / base64 string and return bytes."""
    if isinstance(image, (bytes, bytearray)):
        return bytes(image)
    if isinstance(image, str):
        s = image
        if "," in s and s.strip().lower().startswith("data:"):
            s = s.split(",", 1)[1]
        return base64.b64decode(s)
    raise TypeError(f"Unsupported image type: {type(image)}")


def downscale_to_b64(image_bytes: bytes, max_side: int = 1024, quality: int = 85) -> str:
    """Downscale (a lookup doesn't need full-res) and return base64 JPEG."""
    img = Image.open(io.BytesIO(image_bytes))
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode("ascii")
