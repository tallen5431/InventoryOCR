from __future__ import annotations
import os, base64, io, re, time
from pathlib import Path
from typing import Dict, Any, Optional
from PIL import Image, ImageOps
from config import ASSET_IMAGE_PATH, ASSET_THUMB_PATH

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
URL_PREFIX = os.getenv("URL_PREFIX", "/inventory").rstrip("/")
if URL_PREFIX and not URL_PREFIX.startswith("/"):
    URL_PREFIX = "/" + URL_PREFIX

if URL_PREFIX:
    ASSET_URL_BASE = f"{URL_PREFIX}/assets"
else:
    ASSET_URL_BASE = "/assets"


def _decode_upload(contents: str) -> tuple[bytes, str]:
    """dcc.Upload contents -> (bytes, ext)"""
    header, b64 = contents.split(",", 1)
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

    # Thumbnail
    thumb = img.copy()
    thumb.thumbnail((320, 320))
    thumb_path = ASSET_THUMB_PATH / filename
    _save_image_bytes(thumb, thumb_path)

    return {
        "filename": filename,
        "path": str(out_path),
        "thumb_path": str(thumb_path),
        "url": _asset_url("images", filename),
        "thumb_url": _asset_url("thumbnails", filename),
    }


def get_thumbnail_url(filename: str | None) -> str:
    if not filename:
        return ""
    t = ASSET_THUMB_PATH / filename
    if not t.exists():
        # Best effort on-demand recreation if the full image exists
        full = ASSET_IMAGE_PATH / filename
        if full.exists():
            img = _ensure_pil(full.read_bytes())
            img.thumbnail((320, 320))
            _save_image_bytes(img, t)
    return _asset_url("thumbnails", filename) if t.exists() else ""
