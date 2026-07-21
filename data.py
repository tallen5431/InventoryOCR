from __future__ import annotations
import json
import os
import tempfile
import threading
import functools
import re as _re_date
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from config import (INVENTORY_JSON, ASSET_IMAGE_PATH, ASSET_THUMB_PATH,
                    ASSET_PREVIEW_PATH, ASSET_DOCS_PATH)

# --------------------------------------------------------------------
# Write serialization
# --------------------------------------------------------------------
# waitress serves with multiple worker threads, so inventory callbacks can run
# concurrently. Every mutator does read (inventory()) -> modify -> write
# (_save()); without a lock two of those cycles can interleave and silently drop
# one update (last-writer-wins). atomic_write_text keeps each file from ever
# being *partial*, but it can't stop a *lost update* — that needs serialization.
#
# One reentrant lock guards the whole read-modify-write of every mutator (see the
# _synchronized(...) wrapping block at the end of this module). RLock because some
# mutators call others (e.g. merge_groups -> merge_group). Reads stay lock-free:
# a reader always sees a complete file thanks to the atomic replace.
_WRITE_LOCK = threading.RLock()


def _synchronized(fn):
    @functools.wraps(fn)
    def _wrapped(*args, **kwargs):
        with _WRITE_LOCK:
            return fn(*args, **kwargs)
    return _wrapped

# --------------------------------------------------------------------
# Persistence helpers
# --------------------------------------------------------------------

def atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically (temp file + os.replace + fsync).

    A plain ``write_text`` truncates the file first, so a crash or full disk
    mid-write leaves a partial/empty file — catastrophic for the one file that
    holds the whole inventory. Writing a sibling temp file and renaming it into
    place means readers only ever see the old file or the fully-written new one.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=path.suffix or ".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)  # atomic on POSIX and Windows
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _safe_read(path: Path) -> List[Dict[str, Any]]:
    try:
        txt = path.read_text(encoding="utf-8")
        data = json.loads(txt)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []

def _load() -> List[Dict[str, Any]]:
    path = Path(INVENTORY_JSON)
    if not path.exists():
        # A missing file is a genuinely empty inventory — seed and return it.
        atomic_write_text(path, "[]")
        return []
    # The file EXISTS. If it can't be parsed as a JSON list it's corrupt/
    # half-written, NOT empty — returning [] here would let the very next write
    # overwrite a recoverable file with near-empty data (total data loss). Raise
    # so mutators abort before _save() and the original bytes are preserved.
    data = _load_or_none()
    if data is None:
        raise RuntimeError(
            f"{INVENTORY_JSON} exists but is not readable as a JSON list; "
            "refusing to read or overwrite it to avoid data loss. "
            "Restore from .undo.json/backup or fix the file, then retry."
        )
    return data


def _load_or_none() -> Optional[List[Dict[str, Any]]]:
    """Like ``_load`` but returns ``None`` when the inventory file EXISTS yet can't
    be read/parsed, instead of masking the failure as an empty list.

    Callers that DELETE files based on what's referenced (the prune helpers) use
    this to tell a corrupt / half-written inventory.json apart from a genuinely
    empty inventory — pruning on the former would wipe assets that are still in
    use. A missing file is a real empty inventory, so that still returns ``[]``.
    """
    path = Path(INVENTORY_JSON)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, list) else None

def _save(rows: List[Dict[str, Any]]) -> None:
    atomic_write_text(Path(INVENTORY_JSON), json.dumps(rows, ensure_ascii=False, indent=2))

# --------------------------------------------------------------------
# "Date added" tracking
# --------------------------------------------------------------------
# Every item carries a created_at ISO timestamp so the dashboard can sort by
# when it was scanned in. New items are stamped on save. Legacy items (added
# before this field existed) are backfilled from their images: app-saved photos
# embed the upload time in the filename (…-<ms>.<ext>), which is exactly "when it
# was submitted to the index"; otherwise we fall back to the photo's EXIF capture
# time, then the image file's modification time.

def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")

# App-saved images end in "-<13-digit-ms>.<ext>" (see utils.save_image).
_STAMP_RE = _re_date.compile(r"-(\d{13})\.[A-Za-z0-9]+$")


def _dt_from_filename(filename: str) -> Optional[datetime]:
    m = _STAMP_RE.search(filename or "")
    if not m:
        return None
    try:
        return datetime.fromtimestamp(int(m.group(1)) / 1000.0)
    except (ValueError, OSError, OverflowError):
        return None


def _dt_from_exif(path: Path) -> Optional[datetime]:
    """Read a photo's capture time (EXIF DateTimeOriginal/DateTime), if present."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            exif = im.getexif()
            if not exif:
                return None
            val = None
            try:
                ifd = exif.get_ifd(0x8769)  # Exif sub-IFD
                val = ifd.get(36867) or ifd.get(36868)  # DateTimeOriginal / Digitized
            except Exception:
                val = None
            val = val or exif.get(306)  # DateTime (base IFD)
            if val:
                return datetime.strptime(str(val).strip(), "%Y:%m:%d %H:%M:%S")
    except Exception:
        return None
    return None


def _derive_created_at(record: Dict[str, Any]) -> str:
    """Best-effort 'date added' for a record with no stored created_at.

    Uses the earliest signal across the item's images: upload stamp embedded in
    the filename → EXIF capture time → file mtime. Returns an ISO string or "".
    """
    images = record.get("images") or []
    if isinstance(images, str):
        images = [images]
    best: Optional[datetime] = None
    for fn in images:
        if not fn:
            continue
        dt = _dt_from_filename(fn)
        if dt is None:
            p = Path(ASSET_IMAGE_PATH) / fn
            dt = _dt_from_exif(p)
            if dt is None:
                try:
                    dt = datetime.fromtimestamp(p.stat().st_mtime)
                except (OSError, OverflowError):
                    dt = None
        if dt is not None and (best is None or dt < best):
            best = dt
    return best.isoformat(timespec="seconds") if best else ""


def _earliest_created(items: List[Dict[str, Any]]) -> str:
    """Earliest non-empty created_at across items (ISO strings compare correctly)."""
    vals = [(r.get("created_at") or "") for r in items]
    vals = [v for v in vals if v]
    return min(vals) if vals else ""


def _safe_str(v: Any) -> str:
    """Coerce any stored value to a trimmed string, tolerating a JSON number/bool
    where a string was expected (hand-edited files) instead of raising."""
    return str(v or "").strip()


def _safe_qty(v: Any) -> int:
    """Coerce a stored quantity to int, tolerating '2.5', 'many', None, etc."""
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return 0


def _min_record(rid: Optional[int], r: Dict[str, Any]) -> Dict[str, Any]:
    """Last-resort normalized row for a record too malformed to process, so one
    bad entry can't take down the whole inventory read. Keeps id/name/qty."""
    return {
        "id": rid,
        "name": _safe_str(r.get("name")) or (f"Item {rid}" if rid is not None else "Item"),
        "description": _safe_str(r.get("description")),
        "category": "", "type": "", "location": "", "location_code": "",
        "qty": _safe_qty(r.get("qty")), "reorder_at": None,
        "images": [], "ocr_text": "", "thumb_url": "",
        "specifications": [], "estimated_value": "", "dimensions": "",
        "product_url": "", "tags": [], "source_title": "",
        "attachments": [], "order_number": "", "purchase_date": "",
        "price_paid": "", "seller": "", "created_at": "",
    }


def inventory() -> List[Dict[str, Any]]:
    rows = _load()

    # Every record must have a unique id — the UI selects, edits, and opens
    # photos for items by id. Legacy / hand-edited files may omit it, which would
    # collapse multiple records to id=None and cross-wire them. Backfill stable
    # unique ids for any id-less record (deterministic across reads).
    used: set = set()
    for r in rows:
        # AttributeError guards against a non-dict entry (hand-edited bare
        # string/number); the normalization loop below skips those entirely.
        try:
            used.add(int(r.get("id")))
        except (TypeError, ValueError, AttributeError):
            pass
    next_free = (max(used) + 1) if used else 1

    # Normalize schema
    norm = []
    seen_ids: set = set()
    for r in rows:
        # A hand-edited file can contain a non-object entry (a bare string/number/
        # null); skip it rather than crash the whole read on r.get(...).
        if not isinstance(r, dict):
            continue
        try:
            rid = int(r.get("id"))
        except (TypeError, ValueError):
            rid = None
        # Reassign a fresh id when it's missing OR when an earlier record already
        # claimed it. Two records sharing an id would otherwise be cross-wired —
        # remove_item/bulk_remove would delete both, and the by-id maps used by
        # organize/fit/merge would silently collapse one onto the other.
        if rid is None or rid in seen_ids:
            while next_free in used:
                next_free += 1
            rid = next_free
            used.add(rid)
        seen_ids.add(rid)

        # One malformed record must not blank the whole catalogue — normalize
        # defensively and fall back to a minimal safe row on any surprise.
        try:
            # Backward compatibility: normalize images to a list.
            # Accept a bare string (hand-edited/legacy data) as a single image, and
            # fall back to the old single image_filename field.
            images = r.get("images", [])
            if isinstance(images, str):
                images = [images] if images.strip() else []
            if not isinstance(images, list):
                images = []
            if not images:
                old_img = r.get("image_filename")
                if old_img:
                    images = [old_img]

            rec = {
                "id": rid,
                "name": _safe_str(r.get("name")),
                "description": _safe_str(r.get("description")),
                "category": _safe_str(r.get("category")),
                "type": _safe_str(r.get("type")),
                "location": _safe_str(r.get("location")),
                "location_code": _safe_str(r.get("location_code")),
                "qty": _safe_qty(r.get("qty")),
                # Optional per-item reorder point: low ⇔ set AND qty <= reorder_at.
                "reorder_at": _coerce_reorder(r.get("reorder_at")),
                "images": images if isinstance(images, list) else [],
                "ocr_text": _safe_str(r.get("ocr_text")),
                "thumb_url": _safe_str(r.get("thumb_url")),
                # Richer catalogue fields (from vision AI / web lookup). All optional.
                "specifications": _norm_list(r.get("specifications")),
                "estimated_value": _safe_str(r.get("estimated_value")),
                "dimensions": _safe_str(r.get("dimensions")),
                "product_url": _safe_str(r.get("product_url")),
                "tags": _norm_tags(r.get("tags")),
                # Raw marketplace title kept when the display name was condensed, so
                # the original stays searchable without cluttering the name/tags.
                "source_title": _safe_str(r.get("source_title")),
                # Attached documents (invoices, saved product pages, receipts, …) and
                # the purchase details read off them. All optional / free-text.
                "attachments": _norm_attachments(r.get("attachments")),
                "order_number": _safe_str(r.get("order_number")),
                "purchase_date": _safe_str(r.get("purchase_date")),
                "price_paid": _safe_str(r.get("price_paid")),
                "seller": _safe_str(r.get("seller")),
            }
            # Coarse Type: keep a stored/hand-edited value, else auto-classify from
            # the category/name/tags so grouping works without a manual pass.
            if not rec["type"]:
                rec["type"] = _classify_type(rec)
            # Backfill a reorder/verify link from an ASIN we already scraped into
            # specs — most Amazon items have one, and the field is otherwise blank.
            if not rec["product_url"]:
                rec["product_url"] = _derive_product_url(rec)
            # When it was added: keep the stored value, else derive from the images.
            rec["created_at"] = _safe_str(r.get("created_at")) or _derive_created_at(rec)
        except Exception:
            rec = _min_record(rid, r)
        norm.append(rec)
    return norm


def _norm_attachments(v: Any) -> List[Dict[str, Any]]:
    """Coerce stored attachments into a clean list of metadata dicts.

    Each entry keeps ``filename`` (on disk under assets/documents), plus the
    original name, kind, size and upload time for display. A bare string is
    accepted as a filename for hand-edited data. Entries without a filename are
    dropped so a broken record can never point the download route at nothing.
    """
    if not v:
        return []
    if isinstance(v, dict):
        v = [v]
    if not isinstance(v, list):
        return []
    out: List[Dict[str, Any]] = []
    for a in v:
        if isinstance(a, str):
            fn = a.strip()
            if fn:
                out.append({"filename": fn, "original_name": fn, "kind": "other",
                            "size": 0, "uploaded_at": "", "url": ""})
            continue
        if not isinstance(a, dict):
            continue
        fn = str(a.get("filename") or "").strip()
        if not fn:
            continue
        out.append({
            "filename": fn,
            "original_name": str(a.get("original_name") or fn).strip(),
            "kind": str(a.get("kind") or "other").strip(),
            "size": int(a.get("size") or 0),
            "uploaded_at": str(a.get("uploaded_at") or "").strip(),
            "url": str(a.get("url") or "").strip(),
        })
    return out


def _norm_list(v: Any) -> List[str]:
    """Coerce a stored value into a clean list of non-empty strings.

    Accepts a list, a comma/newline-separated string, or None. Used for the
    ``specifications`` and ``tags`` fields, which the UI edits as free text.
    """
    if v is None:
        return []
    if isinstance(v, str):
        parts = [p.strip() for p in v.replace("\n", ",").split(",")]
        return [p for p in parts if p]
    if isinstance(v, list):
        return [str(p).strip() for p in v if str(p).strip()]
    return []

import re as _re_auto


# --------------------------------------------------------------------
# Value parsing, tag hygiene, and product-link derivation
# --------------------------------------------------------------------
# These keep the free-text catalogue fields usable: a value we can total, tags
# without machine-junk, and a reorder link derived from an ASIN we already have.

_MONEY_RE = _re_auto.compile(r"[\d,]+(?:\.\d+)?")
_PACK_PRICE_RE = _re_auto.compile(r"@\s*\$\s*([\d,]+(?:\.\d+)?)")
_RANGE_RE = _re_auto.compile(r"\d\s*(?:-|–|—|to)\s*\$?\s*\d")


def _to_float(s: Any) -> Optional[float]:
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse_value(s: Any) -> Optional[float]:
    """Parse a free-text ``estimated_value`` into a number, or ``None``.

    Handles ``$13.99``, ranges like ``USD $10 - $25`` (midpoint), pack totals
    such as ``... @ $7.99``, and returns ``None`` for qualitative buckets
    (``Low to Medium``, ``small``) that carry no number.
    """
    txt = "" if s is None else str(s).strip()
    if not txt:
        return None
    m = _PACK_PRICE_RE.search(txt)
    if m:
        return _to_float(m.group(1))
    nums = [n for n in (_to_float(x) for x in _MONEY_RE.findall(txt)) if n is not None]
    if not nums:
        return None
    if len(nums) >= 2 and _RANGE_RE.search(txt):
        return round((nums[0] + nums[1]) / 2, 2)
    return nums[0]


def item_value(row: Dict[str, Any]) -> Optional[float]:
    """Best estimate of the value of ONE unit (one ``qty``) of an item.

    Prefers a pack total (``@ $X``) found in the value or specs over a per-piece
    figure, so a 600-piece kit stored as ``$0.01 each`` is valued at its real
    pack price rather than a cent. Returns ``None`` when nothing numeric exists.
    """
    for src in (row.get("estimated_value"), *(row.get("specifications") or [])):
        m = _PACK_PRICE_RE.search(str(src or ""))
        if m:
            v = _to_float(m.group(1))
            if v is not None:
                return v
    return parse_value(row.get("estimated_value"))


_UUID_RE = _re_auto.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
# Substrings that mark a tag as a dumped marketplace title rather than a facet.
_TAG_NOISE_SUBSTR = ("amazon.com", "amazon.ae", "walmart.com", "aliexpress",
                     ".com:", ": electronics", ": industrial")


def _clean_tags(tags: List[str]) -> List[str]:
    """Drop junk tags — UUIDs, raw marketplace titles, overlong noise — and dedupe.

    Deliberately conservative: only clear machine-junk is removed so genuine
    short facets (``usb-c``, ``M3``, a brand) are always kept.
    """
    out: List[str] = []
    seen: set = set()
    for t in tags or []:
        s = str(t).strip()
        if not s:
            continue
        low = s.lower()
        if _UUID_RE.match(s) or len(s) > 60:
            continue
        if any(sub in low for sub in _TAG_NOISE_SUBSTR):
            continue
        if low in seen:
            continue
        seen.add(low)
        out.append(s)
    return out[:15]


def _norm_tags(v: Any) -> List[str]:
    """Normalise a tags value like ``_norm_list`` but also strip junk."""
    return _clean_tags(_norm_list(v))


_ASIN_RE = _re_auto.compile(r"\b(B0[0-9A-Z]{8})\b")


def _derive_product_url(rec: Dict[str, Any]) -> str:
    """Best-effort Amazon product URL from an ASIN already sitting in specs/tags."""
    for src in list(rec.get("specifications") or []) + list(rec.get("tags") or []):
        m = _ASIN_RE.search(str(src))
        if m:
            return f"https://www.amazon.com/dp/{m.group(1)}"
    return ""


def next_auto_name(prefix: str = "Item") -> str:
    """Next auto-number name like ``Item 0007`` — for quick photo-only capture.

    Scans existing ``<prefix> NNNN`` names and returns the next free number so
    you can snap-and-save on your phone without typing, then rename later.
    """
    rows = inventory()
    mx = 0
    pat = _re_auto.compile(rf"^{_re_auto.escape(prefix)}\s*0*(\d+)$", _re_auto.IGNORECASE)
    for r in rows:
        m = pat.match((r.get("name") or "").strip())
        if m:
            try:
                mx = max(mx, int(m.group(1)))
            except ValueError:
                pass
    return f"{prefix} {mx + 1:04d}"


def _next_id(rows: List[Dict[str, Any]]) -> int:
    mx = 0
    for r in rows:
        try:
            mx = max(mx, int(r.get("id") or 0))
        except Exception:
            pass
    return mx + 1

def _clean_images(images: Optional[List[str]]) -> List[str]:
    if images is None:
        return []
    if isinstance(images, str):
        return [images] if images else []
    return [i for i in images if i]

def _coerce_reorder(v: Any) -> Optional[int]:
    """Parse a per-item reorder point into a non-negative int, or None if unset.

    None means 'no reorder point set' — the item is never flagged low. 0 is a
    valid point. Non-numeric/blank input becomes None.
    """
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        n = int(float(str(v).strip()))
    except (TypeError, ValueError, OverflowError):
        # OverflowError guards against inf/Infinity — json.loads accepts a bare
        # Infinity, and this runs on every row of every read, so an uncaught throw
        # here would take down the whole inventory.
        return None
    return n if n >= 0 else None


def add_item(
    name: str,
    description: str,
    qty: Optional[int],
    images: Optional[List[str]],
    ocr_text: str,
    category: str = "",
    location: str = "",
    location_code: str = "",
    specifications: Any = None,
    estimated_value: str = "",
    dimensions: str = "",
    product_url: str = "",
    tags: Any = None,
    item_type: str = "",
    reorder_at: Any = None,
    source_title: str = "",
    attachments: Any = None,
    order_number: str = "",
    purchase_date: str = "",
    price_paid: str = "",
    seller: str = "",
) -> Dict[str, Any]:
    rows = inventory()
    # Unique by name
    key = name.strip().lower()
    if any((r.get("name", "").strip().lower() == key) for r in rows):
        raise ValueError("An item with this name already exists.")

    row = {
        "id": _next_id(rows),
        "name": name.strip(),
        "description": (description or "").strip(),
        "category": (category or "").strip(),
        "location": (location or "").strip(),
        "location_code": (location_code or "").strip(),
        "qty": int(qty or 0),
        "reorder_at": _coerce_reorder(reorder_at),
        "images": _clean_images(images),
        "ocr_text": ocr_text or "",
        "created_at": _now_iso(),
        "specifications": _norm_list(specifications),
        "estimated_value": (estimated_value or "").strip(),
        "dimensions": (dimensions or "").strip(),
        "product_url": (product_url or "").strip(),
        "tags": _norm_tags(tags),
        "source_title": (source_title or "").strip(),
        "attachments": _norm_attachments(attachments),
        "order_number": (order_number or "").strip(),
        "purchase_date": (purchase_date or "").strip(),
        "price_paid": (price_paid or "").strip(),
        "seller": (seller or "").strip(),
    }
    # Use the given Type, else auto-classify so new items are grouped on entry.
    row["type"] = (item_type or "").strip() or _classify_type(row)
    if not row["product_url"]:
        row["product_url"] = _derive_product_url(row)
    rows.append(row)
    _save(rows)
    return row


def add_photo_items(filenames: List[str], prefix: str = "Item") -> List[Dict[str, Any]]:
    """Create one item per photo with an auto-numbered name — quick bulk capture.

    Each photo becomes its own item (``Item 0007`` …) carrying that single image,
    so a set of shots populates the list instantly for naming/refining later. If
    several photos are actually the same thing, tick those rows and use Merge to
    combine them (images stack, quantities add). Writes once and returns the
    created rows.
    """
    rows = inventory()
    pat = _re_auto.compile(rf"^{_re_auto.escape(prefix)}\s*0*(\d+)$", _re_auto.IGNORECASE)
    n = 0
    for r in rows:
        m = pat.match((r.get("name") or "").strip())
        if m:
            try:
                n = max(n, int(m.group(1)))
            except ValueError:
                pass
    taken = {(r.get("name", "").strip().lower()) for r in rows}
    next_id = _next_id(rows)
    created: List[Dict[str, Any]] = []
    for fn in filenames or []:
        fn = (fn or "").strip()
        if not fn:
            continue
        n += 1
        name = f"{prefix} {n:04d}"
        while name.strip().lower() in taken:
            n += 1
            name = f"{prefix} {n:04d}"
        taken.add(name.strip().lower())
        row = {
            "id": next_id,
            "name": name,
            "description": "",
            "category": "",
            "location": "",
            "location_code": "",
            "qty": 1,
            "reorder_at": None,
            "images": [fn],
            "ocr_text": "",
            "created_at": _now_iso(),
            "specifications": [],
            "estimated_value": "",
            "dimensions": "",
            "product_url": "",
            "tags": [],
            "source_title": "",
            "attachments": [],
            "order_number": "",
            "purchase_date": "",
            "price_paid": "",
            "seller": "",
        }
        row["type"] = _classify_type(row)
        rows.append(row)
        created.append(row)
        next_id += 1
    if created:
        _save(rows)
    return created

# Sentinel: distinguishes "caller omitted this field" (preserve existing value)
# from "caller passed empty" (clear the field). Only used for the optional
# catalogue fields so partial updates (OCR save-back, quantity tweaks) never wipe
# data another screen populated.
_KEEP = object()

def update_item(
    item_id: int,
    name: str,
    description: str,
    qty: Optional[int],
    images: Optional[List[str]],
    ocr_text: str,
    category: str = "",
    location: str = "",
    location_code: Any = _KEEP,
    specifications: Any = _KEEP,
    estimated_value: Any = _KEEP,
    dimensions: Any = _KEEP,
    product_url: Any = _KEEP,
    tags: Any = _KEEP,
    item_type: Any = _KEEP,
    reorder_at: Any = _KEEP,
    source_title: Any = _KEEP,
    attachments: Any = _KEEP,
    order_number: Any = _KEEP,
    purchase_date: Any = _KEEP,
    price_paid: Any = _KEEP,
    seller: Any = _KEEP,
) -> Dict[str, Any]:
    rows = inventory()
    found = None

    # Enforce unique-by-name on rename too (add_item already does): reject a name
    # already held by a DIFFERENT item, so an edit can't silently create a
    # duplicate the rest of the code treats as impossible.
    new_key = (name or "").strip().lower()
    if new_key and any(
        int(r.get("id") or 0) != int(item_id)
        and (r.get("name", "").strip().lower() == new_key)
        for r in rows
    ):
        raise ValueError("An item with this name already exists.")

    for r in rows:
        if int(r.get("id") or 0) == int(item_id):
            r["name"] = (name or "").strip()
            r["description"] = (description or "").strip()
            r["category"] = (category or "").strip()
            r["location"] = (location or "").strip()
            r["qty"] = int(qty or 0)
            r["images"] = _clean_images(images)
            r["ocr_text"] = ocr_text or ""
            # Optional fields: only overwrite when the caller supplied a value.
            if item_type is not _KEEP:
                # Blank Type falls back to an auto-classification rather than
                # being left empty, so an edited item stays grouped.
                r["type"] = (item_type or "").strip() or _classify_type(r)
            if location_code is not _KEEP:
                r["location_code"] = (location_code or "").strip()
            if specifications is not _KEEP:
                r["specifications"] = _norm_list(specifications)
            if estimated_value is not _KEEP:
                r["estimated_value"] = (estimated_value or "").strip()
            if dimensions is not _KEEP:
                r["dimensions"] = (dimensions or "").strip()
            if product_url is not _KEEP:
                r["product_url"] = (product_url or "").strip()
            if tags is not _KEEP:
                r["tags"] = _norm_tags(tags)
            if reorder_at is not _KEEP:
                r["reorder_at"] = _coerce_reorder(reorder_at)
            if source_title is not _KEEP:
                r["source_title"] = (source_title or "").strip()
            if attachments is not _KEEP:
                r["attachments"] = _norm_attachments(attachments)
            if order_number is not _KEEP:
                r["order_number"] = (order_number or "").strip()
            if purchase_date is not _KEEP:
                r["purchase_date"] = (purchase_date or "").strip()
            if price_paid is not _KEEP:
                r["price_paid"] = (price_paid or "").strip()
            if seller is not _KEEP:
                r["seller"] = (seller or "").strip()
            found = r
            break
    if found is None:
        raise ValueError("Item not found.")
    _save(rows)
    return found

def adjust_qty(item_id: int, delta: int) -> Optional[Dict[str, Any]]:
    """Increment/decrement an item's quantity (never below zero)."""
    rows = inventory()
    found = None
    for r in rows:
        if int(r.get("id") or 0) == int(item_id):
            r["qty"] = max(0, int(r.get("qty") or 0) + int(delta))
            found = r
            break
    if found is None:
        raise ValueError("Item not found.")
    _save(rows)
    return found

def remove_item(item_id: int) -> Optional[Dict[str, Any]]:
    rows = inventory()
    new = []
    removed = None
    for r in rows:
        if int(r.get("id") or 0) == int(item_id):
            removed = r
        else:
            new.append(r)
    _save(new)
    return removed


def prune_unreferenced_images() -> int:
    """Delete image/thumbnail files not referenced by any inventory item.

    Photos are written to disk the moment they're taken/chosen (so several can
    accumulate on an item before it's saved). If the entry is then cancelled, a
    photo is removed, or an item is deleted, its files become orphans — this
    reclaims them. Returns the number of files removed. Safe to call anytime:
    anything still referenced by a saved item is kept.
    """
    referenced: set = set()
    rows = _load_or_none()
    if rows is None:
        # inventory.json is unreadable/corrupt — we can't tell what's still in
        # use, so pruning now could delete assets that ARE referenced. Bail out.
        return 0
    for r in rows:
        imgs = r.get("images", [])
        if isinstance(imgs, str):
            imgs = [imgs]
        for fn in imgs or []:
            name = str(fn).strip()
            if name:
                referenced.add(name)
        old = str(r.get("image_filename") or "").strip()
        if old:
            referenced.add(old)

    # The Operations module (materials) shares assets/images & assets/thumbnails
    # with the inventory. Count its references too, or deleting an inventory item
    # would orphan-prune a material's photo. If that file is unreadable we can't
    # tell what's in use — bail rather than risk deleting live assets.
    try:
        import operations_data
        mat_refs = operations_data.referenced_image_filenames()
    except Exception:
        mat_refs = None
    if mat_refs is None:
        return 0
    referenced |= mat_refs

    removed = 0
    for directory in (Path(ASSET_IMAGE_PATH), Path(ASSET_THUMB_PATH), Path(ASSET_PREVIEW_PATH)):
        if not directory.exists():
            continue
        for f in directory.iterdir():
            if f.is_file() and f.name not in referenced:
                try:
                    f.unlink()
                    removed += 1
                except OSError:
                    pass
    return removed


def prune_unreferenced_documents() -> int:
    """Delete attachment files no longer referenced by any item.

    Attachments are written to disk the moment they're chosen (so several can be
    staged before an item is saved). If the entry is cancelled, an attachment is
    removed, or an item is deleted, its files become orphans — this reclaims them.
    """
    referenced: set = set()
    rows = _load_or_none()
    if rows is None:
        # Corrupt/unreadable inventory — refuse to prune (see prune images).
        return 0
    for r in rows:
        for a in _norm_attachments(r.get("attachments")):
            fn = str(a.get("filename") or "").strip()
            if fn:
                referenced.add(fn)

    # Materials share assets/documents with the inventory — count their attached
    # invoices/specs too (bail if unreadable, as above).
    try:
        import operations_data
        mat_refs = operations_data.referenced_document_filenames()
    except Exception:
        mat_refs = None
    if mat_refs is None:
        return 0
    referenced |= mat_refs

    removed = 0
    directory = Path(ASSET_DOCS_PATH)
    if directory.exists():
        for f in directory.iterdir():
            if f.is_file() and f.name not in referenced:
                try:
                    f.unlink()
                    removed += 1
                except OSError:
                    pass
    return removed


# Fields that may be patched in place without a full form round-trip.
_PATCHABLE = {"name", "description", "category", "type", "location", "location_code",
              "qty", "estimated_value", "dimensions", "product_url", "reorder_at",
              "source_title", "order_number", "purchase_date", "price_paid", "seller"}


def update_item_fields(item_id: int, **fields: Any) -> Optional[Dict[str, Any]]:
    """Patch specific fields on one item (e.g. write a price back). Returns it."""
    rows = inventory()
    found = None
    for r in rows:
        if int(r.get("id") or 0) == int(item_id):
            for k, v in fields.items():
                if k in _PATCHABLE and v is not None:
                    if k == "reorder_at":
                        r[k] = _coerce_reorder(v)
                    elif k == "qty":
                        r[k] = int(v)
                    else:
                        r[k] = str(v).strip() if isinstance(v, str) else v
            found = r
            break
    if found is not None:
        _save(rows)
    return found


def set_ocr_text(item_id: int, text: str, merge: bool = False) -> Optional[Dict[str, Any]]:
    """Write an item's scanned OCR text (from auto-OCR / the OCR Lab). Returns it.

    Kept separate from ``update_item_fields`` (whose ``_PATCHABLE`` set is short
    single-line fields) because this is a bulk free-text field written by a
    background thread after an image is scanned — it must serialize against every
    other mutator like any other write.

    With ``merge=True`` the new text is appended to whatever OCR text the item
    currently holds (deduped) *inside the write lock*, rather than replacing it.
    That's what the background write-back uses: it reads the item's live text at
    write time, so two scans of the same item racing (e.g. a quick second save)
    can't clobber each other — each only adds what it found.
    """
    rows = inventory()
    found = None
    for r in rows:
        if int(r.get("id") or 0) == int(item_id):
            if merge:
                from ocr_auto import merge_text
                r["ocr_text"] = merge_text(r.get("ocr_text", ""), text or "")
            else:
                r["ocr_text"] = text or ""
            found = r
            break
    if found is not None:
        _save(rows)
    return found


def bulk_set_fields(ids: List[int], category: Optional[str] = None,
                    location: Optional[str] = None,
                    location_code: Optional[str] = None,
                    item_type: Optional[str] = None) -> int:
    """Set type / category / location / bin on many items at once (only given
    fields).

    Passing ``None`` leaves a field untouched; passing ``""`` clears it.
    Returns the number of items changed.
    """
    id_set = {int(i) for i in ids or []}
    if not id_set:
        return 0
    rows = inventory()
    changed = 0
    for r in rows:
        if int(r.get("id") or 0) in id_set:
            if item_type is not None:
                r["type"] = item_type.strip()
            if category is not None:
                r["category"] = category.strip()
            if location is not None:
                r["location"] = location.strip()
            if location_code is not None:
                r["location_code"] = location_code.strip()
            changed += 1
    if changed:
        _save(rows)
    return changed


def bulk_remove(ids: List[int]) -> int:
    """Delete many items at once. Returns the number removed."""
    id_set = {int(i) for i in ids or []}
    if not id_set:
        return 0
    rows = inventory()
    kept = [r for r in rows if int(r.get("id") or 0) not in id_set]
    removed = len(rows) - len(kept)
    if removed:
        _save(kept)
    return removed


# --------------------------------------------------------------------
# One-step undo for destructive operations (merge / bulk delete)
# --------------------------------------------------------------------
# Snapshot inventory.json just before a destructive change so it can be rolled
# back in one click. Single level — the newest snapshot wins.

def _undo_path() -> Path:
    # Name ends in .json so it's covered by the *.json gitignore (stays local).
    p = Path(INVENTORY_JSON)
    return p.with_name(p.stem + ".undo.json")


def _undo_chk_path() -> Path:
    """The state the destructive op produced — undo is only safe while it holds."""
    p = Path(INVENTORY_JSON)
    return p.with_name(p.stem + ".undo.chk.json")


def _clear_undo() -> None:
    for p in (_undo_path(), _undo_chk_path()):
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass


def snapshot_inventory() -> None:
    """Copy the current inventory aside so the next change can be undone."""
    src = Path(INVENTORY_JSON)
    try:
        atomic_write_text(_undo_path(), src.read_text(encoding="utf-8"))
        # A fresh snapshot invalidates any earlier op's validity checkpoint.
        _undo_chk_path().unlink(missing_ok=True)
    except Exception:
        # If snapshotting fails we must not leave a STALE snapshot paired with a
        # fresh checkpoint from the upcoming commit_undo() — a later undo would
        # then roll back to the wrong (older) state. Drop the undo state entirely.
        _clear_undo()


def commit_undo() -> None:
    """Record the state the op produced, so a later undo can confirm nothing
    else has changed the inventory since (guards against clobbering new edits)."""
    try:
        atomic_write_text(_undo_chk_path(),
                          Path(INVENTORY_JSON).read_text(encoding="utf-8"))
    except Exception:
        pass


def has_undo() -> bool:
    return _undo_path().exists()


def restore_inventory() -> str:
    """Roll inventory back to the last snapshot.

    Returns ``"restored"`` on success, ``"stale"`` if the inventory has changed
    since the operation (so undoing would lose that change — refused), or
    ``"none"`` if there's nothing to undo.
    """
    bak = _undo_path()
    if not bak.exists():
        return "none"
    # Require a checkpoint that still matches the current inventory. If it's
    # missing (checkpoint write failed / crash) or differs (edited since), refuse
    # rather than blindly overwriting — never trade a convenience for data loss.
    chk = _undo_chk_path()
    if not chk.exists():
        _clear_undo()
        return "stale"
    try:
        current = json.loads(Path(INVENTORY_JSON).read_text(encoding="utf-8"))
        produced = json.loads(chk.read_text(encoding="utf-8"))
    except Exception:
        _clear_undo()
        return "stale"
    if current != produced:
        _clear_undo()  # user has since changed things — don't clobber them
        return "stale"
    try:
        atomic_write_text(Path(INVENTORY_JSON), bak.read_text(encoding="utf-8"))
        _clear_undo()  # one-shot: consume the snapshot so undo isn't repeatable
        return "restored"
    except Exception:
        return "none"

def add_image_to_item(item_id: int, image_filename: str) -> Dict[str, Any]:
    """Add an image to an existing item's image list."""
    rows = inventory()
    found = None
    for r in rows:
        if int(r.get("id") or 0) == int(item_id):
            images = r.get("images", [])
            if not isinstance(images, list):
                images = []
            if image_filename not in images:
                images.append(image_filename)
            r["images"] = images
            found = r
            break
    if found is None:
        raise ValueError("Item not found.")
    _save(rows)
    return found

def remove_image_from_item(item_id: int, image_filename: str) -> Dict[str, Any]:
    """Remove a specific image from an item's image list."""
    rows = inventory()
    found = None
    for r in rows:
        if int(r.get("id") or 0) == int(item_id):
            images = r.get("images", [])
            if isinstance(images, list) and image_filename in images:
                images.remove(image_filename)
            r["images"] = images
            found = r
            break
    if found is None:
        raise ValueError("Item not found.")
    _save(rows)
    return found

def _haystack(r: Dict[str, Any]) -> str:
    """All searchable text for a record, lower-cased."""
    return " ".join([
        str(r.get("name", "")),
        str(r.get("description", "")),
        str(r.get("category", "")),
        str(r.get("type", "")),
        str(r.get("location", "")),
        str(r.get("location_code", "")),
        str(r.get("ocr_text", "")),
        " ".join(r.get("specifications", []) or []),
        " ".join(r.get("tags", []) or []),
        str(r.get("dimensions", "")),
        str(r.get("source_title", "")),
        # Purchase details are worth searching ("what did I buy from Mouser?",
        # or looking up an order number).
        str(r.get("order_number", "")),
        str(r.get("seller", "")),
        str(r.get("purchase_date", "")),
    ]).lower()

def search(q: str) -> List[Dict[str, Any]]:
    q = (q or "").strip().lower()
    if not q:
        return inventory()
    # Match every whitespace-separated term (AND search) so "drill garage"
    # narrows instead of widening — better for "where did I put the X" lookups.
    terms = [t for t in q.split() if t]
    out = []
    for r in inventory():
        hay = _haystack(r)
        if all(t in hay for t in terms):
            out.append(r)
    return out

# --------------------------------------------------------------------
# Organization helpers (categories / locations / summaries)
# --------------------------------------------------------------------

def categories(rows: Optional[List[Dict[str, Any]]] = None) -> List[str]:
    """Distinct, sorted, non-empty category names."""
    rows = rows if rows is not None else inventory()
    seen = {(r.get("category") or "").strip() for r in rows}
    return sorted((c for c in seen if c), key=str.lower)

def locations(rows: Optional[List[Dict[str, Any]]] = None) -> List[str]:
    """Distinct, sorted, non-empty location names."""
    rows = rows if rows is not None else inventory()
    seen = {(r.get("location") or "").strip() for r in rows}
    return sorted((l for l in seen if l), key=str.lower)


# --------------------------------------------------------------------
# Type (coarse top-level grouping)
# --------------------------------------------------------------------
# The scraped `category` field is granular and noisy (Amazon breadcrumbs), so a
# short, stable top-level "Type" makes browsing sane: tools with tools, parts
# with parts. `category` stays as the detailed sub-label underneath.
TYPE_GROUPS = ["Tools", "Components", "Cables & Adapters", "Devices",
               "Consumables", "Other"]

# Ordered keyword rules for auto-classifying an item into a TYPE_GROUP. First
# match wins, so the order resolves overlaps between the noisy scraped strings:
#   - Tools before Consumables so "tape measure" isn't read as "tape".
#   - Tools before Other so a "desoldering pump" isn't read as a "pump".
#   - Consumables before Cables so "cable ties" aren't read as a "cable".
#   - Components (connectors/modules) before Cables so a "JST connector kit"
#     whose name also says "cable" lands in Components, while a plain flat/ribbon
#     cable falls through to Cables.
#   - Devices last (before Other) so a network cable's name mentioning
#     "router/modem" doesn't win over its cable signal.
# Keywords with a leading space only match at a word boundary (" brush" won't
# match "airbrush"). Matched against category + name + tags, never the long
# description (too noisy).
_TYPE_RULES: List[tuple] = [
    ("Tools", [
        "tape measure", "measuring tool", "wrench", "socket", "screwdriver",
        "plier", "scalpel", "lab knife", " knife", "blade", "wire brush",
        " brush", "desolder", "solder sucker", "solder removal", "sand drum",
        "mandrel", "dremel", "rotary tool", "caliper", "hex key", "allen key",
        "chisel", "hammer", "drill bit", "utility knife", "hand tool", "tool set",
    ]),
    ("Consumables", [
        "cable tie", "zip tie", "fastening", "electrical tape", "duct tape",
        " tape", "glue", "adhesive", "sewing", "thread", "office supplies",
        "craft", "solder wire", "flux",
    ]),
    ("Components", [
        "jst", "pin header", "header connector", " header", "dupont", "breadboard",
        "led segment", "dot matrix", "max7219", "segment display", "led display",
        "slide switch", " switch", "buck", "boost", "converter", "regulator",
        "trigger board", "charging board", "charger module", "tp4056", "voltage",
        "diode", "emitter", "receiver", "resistor", "capacitor", "transistor",
        "single board", "camera module", "module", " lens", "sensor", "ic chip",
        "potentiometer",
    ]),
    ("Cables & Adapters", [
        "cable", "cord", "pigtail", "ribbon", "ffc", "fpc", "flex", "ethernet",
        "cat6", "cat 6", "patch cord", "csi", "hdmi", "sd card", "microsd",
        "memory card", "sd memory", "adapter",
    ]),
    ("Devices", [
        "speaker", "amplifier", "flash drive", "thumb drive", "headphone",
        "earbud", "microphone", " webcam", "power bank", "bluetooth", "soundbar",
    ]),
    ("Other", [
        "cooler", "backpack", "water pump", " pump", "bottle", " bag", "fountain",
    ]),
]


def _classify_type(row: Dict[str, Any]) -> str:
    """Best-guess TYPE_GROUP for an item from its category, name, and tags.

    Deterministic and side-effect free. Always returns one of TYPE_GROUPS,
    defaulting to "Other" when nothing matches.
    """
    hay = " ".join([
        str(row.get("category", "")),
        str(row.get("name", "")),
        " ".join(str(t) for t in (row.get("tags") or [])),
    ]).lower()
    # Pad so a leading-space keyword can also match a term at the very start.
    hay = " " + hay
    for group, keywords in _TYPE_RULES:
        if any(kw in hay for kw in keywords):
            return group
    return "Other"


def types(rows: Optional[List[Dict[str, Any]]] = None) -> List[str]:
    """Distinct type groups present, ordered by the canonical TYPE_GROUPS."""
    rows = rows if rows is not None else inventory()
    present = {(r.get("type") or "").strip() for r in rows}
    present.discard("")
    ordered = [g for g in TYPE_GROUPS if g in present]
    # Include any non-canonical values a user typed, after the known groups.
    ordered += sorted(present - set(TYPE_GROUPS), key=str.lower)
    return ordered


def assign_types(overwrite: bool = False) -> int:
    """Persist an auto-classified Type onto stored items.

    By default only fills items that don't already have a stored Type (so manual
    choices are preserved); pass ``overwrite=True`` to reclassify everything.
    Returns the number of items changed.
    """
    rows = _load()
    changed = 0
    for r in rows:
        current = (r.get("type") or "").strip()
        if current and not overwrite:
            continue
        new_type = _classify_type(r)
        if new_type != current:
            r["type"] = new_type
            changed += 1
    if changed:
        _save(rows)
    return changed

def summary_by(field: str, rows: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """
    Group rows by ``field`` ("category" or "location") and total up the item
    count and quantity per group. Empty values are grouped under "Uncategorized"
    / "Unassigned". Returns a list sorted by total quantity (desc).
    """
    rows = rows if rows is not None else inventory()
    fallback = {"category": "Uncategorized", "location": "Unassigned",
                "type": "Unclassified"}.get(field, "—")
    buckets: Dict[str, Dict[str, int]] = {}
    for r in rows:
        key = (r.get(field) or "").strip() or fallback
        b = buckets.setdefault(key, {"items": 0, "qty": 0})
        b["items"] += 1
        b["qty"] += int(r.get("qty") or 0)
    out = [{"name": k, "items": v["items"], "qty": v["qty"]} for k, v in buckets.items()]
    out.sort(key=lambda d: (-d["qty"], -d["items"], d["name"].lower()))
    return out

def is_low_stock(row: Dict[str, Any]) -> bool:
    """An item needs reordering only when it has a reorder point set and its
    quantity has fallen to or below it. Items with no reorder point are never
    flagged — low stock is opt-in, per item."""
    ra = _coerce_reorder(row.get("reorder_at"))
    return ra is not None and int(row.get("qty") or 0) <= ra


def stats(rows: Optional[List[Dict[str, Any]]] = None, low_stock_threshold: int = 5) -> Dict[str, int]:
    """Headline numbers for the KPI bar. ``low_stock_threshold`` is retained for
    backward compatibility but ignored — low stock is now per-item (reorder_at)."""
    rows = rows if rows is not None else inventory()
    total_items = len(rows)
    total_qty = sum(int(r.get("qty") or 0) for r in rows)
    low_stock = sum(1 for r in rows if is_low_stock(r))
    return {
        "items": total_items,
        "qty": total_qty,
        "low": low_stock,
        "categories": len(categories(rows)),
        "locations": len(locations(rows)),
        "value": _sum_group_value(rows),
    }

# --------------------------------------------------------------------
# Storage / retrieval system
# --------------------------------------------------------------------
# Every item can carry a short *location code* (a bin/box/shelf label such as
# "BIN-01"). Like items are stored together so that, later, a keyword search
# surfaces the item and tells you exactly which bin to open.

import re as _re


def location_codes(rows: Optional[List[Dict[str, Any]]] = None) -> List[str]:
    """Distinct, sorted, non-empty location codes currently in use."""
    rows = rows if rows is not None else inventory()
    seen = {(r.get("location_code") or "").strip() for r in rows}
    return sorted((c for c in seen if c), key=str.lower)


def _next_bin_number(existing: List[str]) -> int:
    """Highest trailing integer across existing BIN-style codes, +1."""
    mx = 0
    for code in existing:
        m = _re.search(r"(\d+)\s*$", code or "")
        if m:
            try:
                mx = max(mx, int(m.group(1)))
            except ValueError:
                pass
    return mx + 1


def set_location(item_id: int, location: Any = _KEEP, location_code: Any = _KEEP) -> Optional[Dict[str, Any]]:
    """Assign a location name and/or code to a single item."""
    rows = inventory()
    found = None
    for r in rows:
        if int(r.get("id") or 0) == int(item_id):
            if location is not _KEEP:
                r["location"] = (location or "").strip()
            if location_code is not _KEEP:
                r["location_code"] = (location_code or "").strip()
            found = r
            break
    if found is None:
        raise ValueError("Item not found.")
    _save(rows)
    return found


# Common/generic words that shouldn't drive a grouping ("150pcs black mini set").
_GROUP_STOP = {
    "the", "and", "for", "with", "set", "kit", "pack", "packs", "pcs", "pc", "piece",
    "pieces", "lot", "lots", "new", "assorted", "assortment", "universal", "mini",
    "micro", "small", "large", "pro", "premium", "high", "quality", "type", "size",
    "black", "white", "red", "blue", "green", "silver", "gray", "grey", "yellow",
    "color", "colour", "value", "genuine", "original", "oem", "pack", "count", "unit",
    "units", "inch", "inches", "cm", "mm", "long", "short", "wide", "each", "per",
}


def _tokenize(text: str) -> List[str]:
    """Significant type words in ``text`` (lower-cased, de-duped, stop-words removed)."""
    out: List[str] = []
    for t in _re.findall(r"[a-z][a-z0-9\-]{2,}", (text or "").lower()):
        t = t.strip("-")
        if len(t) >= 3 and t not in _GROUP_STOP and t not in out:
            out.append(t)
    return out


def _sum_group_value(rows: List[Dict[str, Any]]) -> float:
    """Total estimated value of a group (per-item value × quantity).

    Uses :func:`item_value`, so qualitative buckets and ranges are handled and a
    bulk pack is valued at its real pack price rather than a per-piece cent.
    """
    total = 0.0
    found = False
    for r in rows:
        v = item_value(r)
        if v is not None:
            total += v * max(1, int(r.get("qty") or 1))
            found = True
    return round(total, 2) if found else 0.0


def auto_organize(
    rows: Optional[List[Dict[str, Any]]] = None,
    *,
    prefix: str = "BIN",
    mode: str = "smart",
) -> List[Dict[str, Any]]:
    """Analyse every item and propose a storage plan that groups like things together.

    Returns a list of group dicts (does NOT persist anything):
        {group, location_code, location_name, keywords, item_ids, items, qty, value, existing}

    Grouping (``mode="smart"``, the default) looks at each item's **name and
    category** and clusters items that share a significant type word — so
    "Toggle Switches" and "Slide Switches" land together under "Switches", while
    unrelated things stay apart. Items with no shared word fall back to their
    category, or a single "Miscellaneous" bin. ``mode="category"`` groups by the
    exact category field only.

    Bins are stable across re-runs: if any item in a group already has a
    location_code that code is reused, and new groups get the next ``<prefix>-NN``.
    """
    from collections import Counter

    rows = rows if rows is not None else inventory()
    if not rows:
        return []

    buckets: Dict[str, Dict[str, Any]] = {}

    def _add(key, name, kw, r):
        b = buckets.setdefault(key, {"name": name, "rows": [], "kw": list(kw)})
        b["rows"].append(r)

    if mode == "category":
        for r in rows:
            cat = (r.get("category") or "").strip()
            _add(("cat::" + cat.lower()) if cat else "\x00misc", cat or "Miscellaneous", [], r)
    else:
        # Split into categorised vs not.
        cat_rows: Dict[str, List[Dict[str, Any]]] = {}
        uncat: List[Dict[str, Any]] = []
        for r in rows:
            cat = (r.get("category") or "").strip()
            if cat:
                cat_rows.setdefault(cat, []).append(r)
            else:
                uncat.append(r)

        # Merge only DIFFERENT categories that share a word (Toggle Switches +
        # Slide Switches -> Switches); a lone category keeps its full name.
        cat_tokens = {c: _tokenize(c) for c in cat_rows}
        cat_df: "Counter[str]" = Counter()
        for toks in cat_tokens.values():
            for t in set(toks):
                cat_df[t] += 1
        for c, rws in cat_rows.items():
            shared = [t for t in cat_tokens[c] if cat_df[t] >= 2]
            if shared:
                shared.sort(key=lambda t: (-cat_df[t], -len(t), t))
                key, name, kw = "kw::" + shared[0], shared[0].title(), shared[:4]
            else:
                key, name, kw = "cat::" + c.lower(), c, []
            for r in rws:
                _add(key, name, kw, r)

        # Uncategorised items cluster among themselves by name keyword, else Misc.
        if uncat:
            utoks = {int(r.get("id")): _tokenize(r.get("name") or "") for r in uncat}
            udf: "Counter[str]" = Counter()
            for ts in utoks.values():
                for t in set(ts):
                    udf[t] += 1
            for r in uncat:
                ts = utoks[int(r.get("id"))]
                shared = [t for t in ts if udf[t] >= 2]
                if shared:
                    shared.sort(key=lambda t: (-udf[t], -len(t), t))
                    _add("kw::" + shared[0], shared[0].title(), shared[:4], r)
                else:
                    _add("\x00misc", "Miscellaneous", [], r)

    reserved = set(location_codes(rows))
    next_num = _next_bin_number(list(reserved))

    plan: List[Dict[str, Any]] = []
    for key in sorted(buckets.keys(), key=lambda k: (k == "\x00misc", k)):
        b = buckets[key]
        group_rows = b["rows"]

        existing_code = ""
        for gr in group_rows:
            c = (gr.get("location_code") or "").strip()
            if c:
                existing_code = c
                break
        if existing_code:
            code = existing_code
        else:
            code = f"{prefix}-{next_num:02d}"
            while code in reserved:
                next_num += 1
                code = f"{prefix}-{next_num:02d}"
            next_num += 1
        reserved.add(code)

        plan.append({
            "group": b["name"],
            "location_code": code,
            "location_name": b["name"],
            "keywords": b.get("kw", []),
            "item_ids": [int(gr.get("id")) for gr in group_rows],
            "items": len(group_rows),
            "qty": sum(int(gr.get("qty") or 0) for gr in group_rows),
            "value": _sum_group_value(group_rows),
            "existing": bool(existing_code),
        })

    plan.sort(key=lambda g: (-g["items"], g["location_code"]))
    return plan


def apply_organization(plan: List[Dict[str, Any]], *, set_location_name: bool = True) -> int:
    """Persist a plan from :func:`auto_organize`. Returns the item count updated."""
    rows = inventory()
    by_id = {int(r.get("id")): r for r in rows}
    updated = 0
    for group in plan or []:
        code = (group.get("location_code") or "").strip()
        loc_name = (group.get("location_name") or "").strip()
        for iid in group.get("item_ids", []):
            r = by_id.get(int(iid))
            if not r:
                continue
            r["location_code"] = code
            # Only fill an empty location name so hand-set labels are preserved.
            if set_location_name and not (r.get("location") or "").strip():
                r["location"] = loc_name
            updated += 1
    if updated:
        _save(rows)
    return updated


def storage_map(rows: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Current physical layout: what actually lives in each bin right now.

    Groups persisted records by their ``location_code`` so you can print/scan a
    "bin BIN-03 → these items" map. Items without a code are grouped last.
    """
    rows = rows if rows is not None else inventory()
    buckets: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        code = (r.get("location_code") or "").strip() or "\x00unfiled"
        b = buckets.setdefault(code, {
            "location_code": "" if code == "\x00unfiled" else code,
            "location_name": (r.get("location") or "").strip(),
            "names": [],
            "items": 0,
            "qty": 0,
        })
        if not b["location_name"] and (r.get("location") or "").strip():
            b["location_name"] = (r.get("location") or "").strip()
        b["names"].append(r.get("name", "") or "(unnamed)")
        b["items"] += 1
        b["qty"] += int(r.get("qty") or 0)

    out = list(buckets.values())
    # Coded bins first (by code), then the unfiled bucket.
    out.sort(key=lambda d: (d["location_code"] == "", d["location_code"].lower()))
    return out


# --------------------------------------------------------------------
# Physical containers + constrained "fit to my bins" allocation
# --------------------------------------------------------------------
# You describe the storage you actually have (each with a capacity), and
# ``fit_to_containers`` packs the inventory into them — keeping like items
# together where possible and respecting each bin's capacity.

from pathlib import Path as _Path
CONTAINERS_FILE = _Path(INVENTORY_JSON).parent / "containers.json"


def _clean_bags(v: Any) -> List[str]:
    """Normalise a bin's sub-compartment ('bag') labels into a clean, de-duped list.

    Accepts a list or a comma/newline-separated string. Order is preserved and
    case-insensitive duplicates are dropped.
    """
    if isinstance(v, str):
        v = v.replace("\n", ",").split(",")
    if not isinstance(v, (list, tuple)):
        return []
    out: List[str] = []
    seen = set()
    for b in v:
        s = str(b).strip()
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out


def containers() -> List[Dict[str, Any]]:
    """Load the user-defined containers: [{code, name, capacity, bags}].

    ``bags`` are optional sub-compartment labels within a bin (e.g. different
    bags of parts on one shelf). Legacy files without ``bags`` load as [].
    """
    p = CONTAINERS_FILE
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    seen = set()
    for c in raw if isinstance(raw, list) else []:
        code = str(c.get("code", "")).strip()
        if not code or code.lower() in seen:
            continue
        seen.add(code.lower())
        try:
            cap = max(0, int(c.get("capacity") or 0))
        except (TypeError, ValueError):
            cap = 0
        out.append({"code": code, "name": (c.get("name") or code).strip(),
                    "capacity": cap, "bags": _clean_bags(c.get("bags"))})
    return out


def save_containers(conts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    clean: List[Dict[str, Any]] = []
    seen = set()
    for c in conts or []:
        code = str(c.get("code", "")).strip()
        if not code or code.lower() in seen:
            continue
        seen.add(code.lower())
        try:
            cap = max(0, int(c.get("capacity") or 0))
        except (TypeError, ValueError):
            cap = 0
        clean.append({"code": code, "name": (c.get("name") or code).strip(),
                      "capacity": cap, "bags": _clean_bags(c.get("bags"))})
    atomic_write_text(CONTAINERS_FILE, json.dumps(clean, ensure_ascii=False, indent=2))
    return clean


def make_bins(count: Any, prefix: str = "BIN", capacity: Any = 25,
              start: int = 1, bags: Any = None) -> List[Dict[str, Any]]:
    """Generate ``count`` sequentially-numbered bins, e.g. BIN-01 … BIN-09.

    The number is zero-padded to a consistent width so codes sort naturally.
    Any ``bags`` given are applied to every generated bin as starting labels.
    """
    try:
        count = int(count)
    except (TypeError, ValueError):
        count = 0
    count = max(0, min(count, 200))  # sane upper bound
    try:
        capacity = max(0, int(capacity))
    except (TypeError, ValueError):
        capacity = 25
    prefix = (str(prefix or "").strip() or "BIN").rstrip("-")
    bag_list = _clean_bags(bags)
    last = start + count - 1
    width = max(2, len(str(last)))
    out: List[Dict[str, Any]] = []
    for i in range(start, start + count):
        code = f"{prefix}-{str(i).zfill(width)}"
        out.append({"code": code, "name": f"{prefix.title()} {i}",
                    "capacity": capacity, "bags": list(bag_list)})
    return out


def containers_from_rows(names: Any, bags_texts: Any = None, slots: Any = None) -> List[Dict[str, Any]]:
    """Build saved container dicts from the visual editor's parallel field lists.

    Skips rows with a blank name, derives a unique code per container, and
    defaults capacity to 25. The row-editor equivalent of parse_containers_text.
    """
    names = names or []
    bags_texts = bags_texts or []
    slots = slots or []
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for i, nm in enumerate(names):
        name = (nm or "").strip()
        if not name:
            continue
        bags = _clean_bags(bags_texts[i] if i < len(bags_texts) else "")
        raw_cap = slots[i] if i < len(slots) else None
        try:
            cap = int(raw_cap) if raw_cap not in (None, "") else 25
        except (TypeError, ValueError):
            cap = 25
        base = _derive_code(name)
        code, k = base, 2
        while code.lower() in seen:
            code = f"{base}-{k}"
            k += 1
        seen.add(code.lower())
        out.append({"code": code, "name": name, "capacity": max(1, cap), "bags": bags})
    return out


def _derive_code(name: str) -> str:
    """Make a short, stable code from a container's name.

    A container can be any kind of box, drawer, tote, bag or shelf, so people
    shouldn't have to invent codes. If the text already looks like a code
    (SHELF-01, A1) it's kept verbatim; a descriptive name becomes its initials
    (e.g. 'Small parts drawer' → 'SPD').
    """
    s = (name or "").strip()
    if not s:
        return "BIN"
    if " " not in s and len(s) <= 16 and _re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", s):
        return s
    words = _re.findall(r"[A-Za-z0-9]+", s)
    if len(words) >= 2:
        code = "".join(w[0] for w in words).upper()[:8]
    else:
        code = _re.sub(r"[^A-Za-z0-9]+", "", s).upper()[:8]
    return code or "BIN"


def parse_containers_text(text: str) -> List[Dict[str, Any]]:
    """Parse the storage editor. One container per line. The friendly form is just
    a name, with its bags after a dash or colon::

        Small parts drawer — resistors, capacitors, diodes
        Garage tote: usb cables, ribbon
        Workshop shelf

    The explicit form still works too (any field optional)::

        CODE | Name | slots | bag1, bag2, bag3

    Codes are derived from names when not given, and made unique.
    """
    out: List[Dict[str, Any]] = []
    seen: set = set()

    def _uniq(code: str) -> str:
        base = code or "BIN"
        c, i = base, 2
        while c.lower() in seen:
            c = f"{base}-{i}"
            i += 1
        seen.add(c.lower())
        return c

    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "|" in line:
            parts = [p.strip() for p in line.split("|")]
            bags = _clean_bags(parts[3]) if len(parts) >= 4 else []
            if len(parts) >= 3:
                code, name, cap = parts[0], parts[1], parts[2]
            elif len(parts) == 2:
                code, name, cap = parts[0], parts[0], parts[1]
            else:
                code, name, cap = parts[0], parts[0], "25"
            m = _re.search(r"\d+", cap or "")
            capacity = int(m.group(0)) if m else 25
            name = name or code
            code = code or _derive_code(name)
        else:
            # Plain "Name — bags" / "Name: bags" line — no code needed.
            name, bags = line, []
            split = _re.split(r"\s+[—–]\s+|\s*:\s+|\s+-\s+", line, maxsplit=1)
            if len(split) == 2:
                name, bags = split[0].strip(), _clean_bags(split[1])
            code, capacity = _derive_code(name), 25
        if code:
            out.append({"code": _uniq(code), "name": name or code,
                        "capacity": capacity, "bags": bags})
    return out


def containers_to_text(conts: Optional[List[Dict[str, Any]]] = None) -> str:
    conts = conts if conts is not None else containers()
    lines = []
    for c in conts:
        name = c.get("name") or c["code"]
        bags = c.get("bags") or []
        # Keep the friendly "Name — bags" form when the code is just derived from
        # the name and the capacity is the default; otherwise show the explicit
        # "CODE | Name | slots | bags" so custom codes/capacities survive.
        if c["code"] == _derive_code(name) and int(c.get("capacity") or 0) == 25:
            line = name + (" — " + ", ".join(bags) if bags else "")
        else:
            line = f"{c['code']} | {name} | {c['capacity']}"
            if bags:
                line += " | " + ", ".join(bags)
        lines.append(line)
    return "\n".join(lines)


def storage_overview(rows: Optional[List[Dict[str, Any]]] = None,
                     conts: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Every defined bin (even empty) merged with what's actually in it now.

    Combines your bin definitions (code / name / capacity / planned bags) with
    the live per-bin counts, plus any bin codes that hold items but were never
    defined, plus an 'Unfiled' bucket. Each bin also reports ``used_bags`` — the
    distinct item ``location`` values seen inside it — so the bags actually in
    use show up next to the ones you planned.
    """
    rows = rows if rows is not None else inventory()
    conts = conts if conts is not None else containers()

    smap: Dict[str, Dict[str, Any]] = {}
    unfiled: Optional[Dict[str, Any]] = None
    for b in storage_map(rows):
        if b["location_code"]:
            smap[b["location_code"]] = b
        elif b["items"]:
            unfiled = b

    # Distinct in-use sub-groups (item.location) per bin code, with counts.
    used_bags: Dict[str, Dict[str, int]] = {}
    for r in rows:
        code = (r.get("location_code") or "").strip()
        loc = (r.get("location") or "").strip()
        if not code or not loc:
            continue
        used_bags.setdefault(code, {})
        used_bags[code][loc] = used_bags[code].get(loc, 0) + 1

    def _entry(code, name, capacity, bags, b, defined):
        return {
            "code": code,
            "name": name,
            "capacity": capacity,
            "bags": bags,
            "used_bags": sorted(used_bags.get(code, {}).items(), key=lambda kv: kv[0].lower()),
            "items": (b or {}).get("items", 0),
            "qty": (b or {}).get("qty", 0),
            "names": (b or {}).get("names", []),
            "defined": defined,
        }

    out: List[Dict[str, Any]] = []
    seen = set()
    for c in conts:
        code = c["code"]
        seen.add(code.lower())
        out.append(_entry(code, c.get("name") or code, c.get("capacity", 0),
                          list(c.get("bags") or []), smap.get(code), True))
    for code, b in smap.items():
        if code.lower() in seen:
            continue
        out.append(_entry(code, b.get("location_name") or code, 0, [], b, False))
    if unfiled:
        out.append(_entry("", "Unfiled", 0, [], unfiled, False))
    return out


def fit_to_containers(
    rows: Optional[List[Dict[str, Any]]] = None,
    conts: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Pack items into the defined containers, keeping like items together.

    Uses the smart grouping as cohesion units, then First-Fit-Decreasing bin
    packing: each group goes whole into the tightest container it fits; if none
    fits, it's split across the emptiest containers; anything left over is
    reported as overflow. Capacity counts *distinct items* (entries).

    Returns {ok, assignments:[{code,name,capacity,used,item_ids,groups}], overflow, overflow_names}.
    """
    rows = rows if rows is not None else inventory()
    conts = conts if conts is not None else containers()
    if not conts:
        return {"ok": False, "error": "No containers defined yet — add some first.",
                "assignments": [], "overflow": [], "overflow_names": []}

    groups = auto_organize(rows)  # deterministic cohesion units
    remaining = {c["code"]: c["capacity"] for c in conts}
    assign = {c["code"]: {"groups": {}, "ids": []} for c in conts}
    overflow: List[int] = []
    id_name = {int(r.get("id")): r.get("name", "") for r in rows}

    def _place(ids, gname, code):
        a = assign[code]
        a["ids"].extend(ids)
        a["groups"].setdefault(gname, []).extend(ids)
        remaining[code] -= len(ids)

    for g in sorted(groups, key=lambda g: (-g["items"], g["location_code"])):
        ids = list(g["item_ids"])
        gname = g["group"]
        fits = [c for c in conts if remaining[c["code"]] >= len(ids)]
        if fits:
            # tightest fit: smallest remaining that still holds the whole group
            c = min(fits, key=lambda c: (remaining[c["code"]], c["code"]))
            _place(ids, gname, c["code"])
        else:
            # split across the emptiest containers first
            for c in sorted(conts, key=lambda c: (-remaining[c["code"]], c["code"])):
                if not ids:
                    break
                room = remaining[c["code"]]
                if room <= 0:
                    continue
                take = ids[:room]
                _place(take, gname, c["code"])
                ids = ids[len(take):]
            if ids:
                overflow.extend(ids)

    assignments = []
    for c in conts:
        a = assign[c["code"]]
        assignments.append({
            "code": c["code"], "name": c["name"], "capacity": c["capacity"],
            "used": len(a["ids"]), "item_ids": a["ids"],
            "groups": [{"name": n, "ids": i, "count": len(i)}
                       for n, i in sorted(a["groups"].items(), key=lambda kv: -len(kv[1]))],
        })
    return {"ok": True, "assignments": assignments, "overflow": overflow,
            "overflow_names": [id_name.get(int(i), str(i)) for i in overflow]}


def apply_fit(plan: Dict[str, Any]) -> int:
    """Persist a fit_to_containers plan: set each item's bin code + location name."""
    rows = inventory()
    by_id = {int(r.get("id")): r for r in rows}
    updated = 0
    for a in (plan or {}).get("assignments", []):
        for iid in a.get("item_ids", []):
            r = by_id.get(int(iid))
            if not r:
                continue
            r["location_code"] = a["code"]
            r["location"] = a["name"]
            updated += 1
    if updated:
        _save(rows)
    return updated


# --------------------------------------------------------------------
# Duplicate detection + merge
# --------------------------------------------------------------------
# When you scan a big pile of stuff fast, the same thing gets entered more than
# once (slightly different names, split quantities). These helpers find items
# that are identical or very similar and combine them into one — summing the
# quantities and keeping every photo / spec / tag.

from difflib import SequenceMatcher as _SeqMatcher

# Sensitivity presets for "how alike is alike enough" (higher = stricter).
DUP_LEVELS = {"loose": 0.72, "balanced": 0.82, "identical": 0.95}


def _norm_name(name: str) -> str:
    """Lower-case, drop punctuation, collapse whitespace — for name comparison."""
    s = _re.sub(r"[^a-z0-9]+", " ", (name or "").lower())
    return _re.sub(r"\s+", " ", s).strip()


def _norm_url(url: str) -> str:
    u = (url or "").strip().lower().rstrip("/")
    return _re.sub(r"^https?://(www\.)?", "", u)


# Short alpha tokens that are meaningful *sizes/models* (kept as discriminators).
_DEDUP_SIZE_WORDS = {"aa", "aaa", "aaaa"}


def _singular(t: str) -> str:
    """Cheap stemmer so 'batteries'/'cables'/'switches' match their singulars."""
    if len(t) <= 3:
        return t
    if t.endswith("ies"):
        return t[:-3] + "y"
    if t.endswith(("ches", "shes", "ses", "xes", "zes")):
        return t[:-2]
    if t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t


def _content_tokens(row: Dict[str, Any]) -> set:
    """Significant, plural-normalised words for similarity (dedup-specific).

    Unlike ``_tokenize`` this keeps digit-bearing codes (9v, cr2032) and battery
    sizes (aa/aaa), and singularises plurals so 'battery' == 'batteries'.
    """
    text = " ".join([row.get("name") or ""] + [str(t) for t in row.get("tags", []) or []]).lower()
    out = set()
    for t in _re.findall(r"[a-z0-9][a-z0-9\-]*", text):
        t = t.strip("-")
        if any(ch.isdigit() for ch in t):
            out.add(t)                       # size/model code — keep verbatim
        elif t in _DEDUP_SIZE_WORDS:
            out.add(t)
        elif len(t) >= 3 and t not in _GROUP_STOP:
            out.add(_singular(t))
    return out


def _codes(row: Dict[str, Any]) -> set:
    """Distinguishing size/model codes in the name (9v, cr2032, aa, m3, 6ft…)."""
    text = (row.get("name") or "").lower()
    out = set()
    for t in _re.findall(r"[a-z0-9][a-z0-9\-]*", text):
        t = t.strip("-")
        if any(ch.isdigit() for ch in t) or t in _DEDUP_SIZE_WORDS:
            out.add(t)
    return out


def _desc_tokens(row: Dict[str, Any]) -> set:
    """Significant words from the *description*, normalised like content tokens.

    Used only as a light cross-check: a sparsely-named item ("7mm Shallow
    Socket") whose description mentions the brand/kind of a richer item ("Kobalt
    …socket") should read as related even though the names barely overlap.
    """
    text = (row.get("description") or "").lower()
    out = set()
    for t in _re.findall(r"[a-z0-9][a-z0-9\-]*", text):
        t = t.strip("-")
        if any(ch.isdigit() for ch in t):
            out.add(t)
        elif t in _DEDUP_SIZE_WORDS:
            out.add(t)
        elif len(t) >= 3 and t not in _GROUP_STOP:
            out.add(_singular(t))
    return out


def _head_noun(row: Dict[str, Any]) -> str:
    """The item's 'kind' — the last significant, non-code word of the name
    (socket, battery, screwdriver). Lets us tell 'same kind, different size'
    (a loose match worth surfacing) apart from two unrelated items."""
    na = _norm_name(row.get("name", ""))
    nouns = [w for w in na.split()
             if not any(ch.isdigit() for ch in w) and len(w) >= 3 and w not in _GROUP_STOP]
    return _singular(nouns[-1]) if nouns else ""


def item_similarity(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    """Similarity of two items in 0..1. 1.0 == a confident duplicate.

    Strong signals short-circuit: an identical normalised name, or the same
    non-empty product URL. Otherwise blend name closeness (typos / plurals) with
    shared significant words — using an overlap coefficient so a sparse name
    that's a subset of a richer one still scores — then nudge up for a matching
    category, the same head noun ("both sockets"), or a description that echoes
    the other item's words.

    Size/model codes that exist but don't overlap (9V vs AA, 1/4" vs 7mm) still
    hold items apart, but as a *graduated* penalty rather than a hard cut: two
    items that are otherwise the same kind of thing can surface at the loosest
    setting (where the user decides) while staying below the auto-merge tiers;
    genuinely different things are pushed well down.
    """
    na, nb = _norm_name(a.get("name", "")), _norm_name(b.get("name", ""))
    if na and na == nb:
        return 1.0
    ua, ub = _norm_url(a.get("product_url", "")), _norm_url(b.get("product_url", ""))
    if ua and ua == ub:
        return 0.97

    name_ratio = _SeqMatcher(None, na, nb).ratio() if (na and nb) else 0.0

    ta, tb = _content_tokens(a), _content_tokens(b)
    inter = len(ta & tb)
    jac = (inter / len(ta | tb)) if (ta or tb) else 0.0
    # Overlap coefficient rescues sparse names: if the shorter item's words are
    # mostly contained in the richer one, that's a strong signal Jaccard hides.
    overlap = (inter / min(len(ta), len(tb))) if (ta and tb) else 0.0
    tok = 0.5 * jac + 0.5 * overlap

    score = 0.6 * name_ratio + 0.4 * tok

    # Light description cross-check (bounded nudge): one item's description
    # naming the other's brand/kind is a real "these belong together" signal.
    da, db = _desc_tokens(a), _desc_tokens(b)
    if (da & tb) or (db & ta):
        score = min(1.0, score + 0.08)

    cat_a = (a.get("category") or "").strip().lower()
    cat_b = (b.get("category") or "").strip().lower()
    same_cat = bool(cat_a and cat_b and cat_a == cat_b)
    same_kind = bool(_head_noun(a)) and _head_noun(a) == _head_noun(b)

    if cat_a and cat_b:
        score = min(1.0, score + 0.05) if same_cat else score * 0.9
    # Same category *and* same kind of thing → surface as a near-match.
    if same_cat and same_kind:
        score = min(1.0, score + 0.08)

    # Size/model code mismatch.
    ca_codes, cb_codes = _codes(a), _codes(b)
    if ca_codes and cb_codes and not (ca_codes & cb_codes):
        if same_cat and same_kind:
            # Same kind, different size: keep it in the "loose" band — visible to
            # a user who asks for near-matches, but never auto-merged by default.
            score = min(score, DUP_LEVELS["balanced"] - 0.02)
        else:
            # Different things that also disagree on size/model — push down hard.
            score = min(score, 0.55)

    return round(min(1.0, score), 3)


def _pick_primary(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The 'richest' entry becomes the one we keep (most data to preserve)."""
    def richness(r):
        return (
            len(r.get("images", []) or []),
            len(r.get("specifications", []) or []),
            len(r.get("tags", []) or []),
            len((r.get("description") or "")),
            1 if (r.get("estimated_value") or "").strip() else 0,
            1 if (r.get("dimensions") or "").strip() else 0,
            1 if (r.get("product_url") or "").strip() else 0,
            -int(r.get("id") or 0),  # tie-break: keep the earliest id
        )
    return max(items, key=richness)


def _union_list(items: List[Dict[str, Any]], field: str) -> List[str]:
    out: List[str] = []
    for r in items:
        for v in (r.get(field) or []):
            v = str(v).strip()
            if v and v not in out:
                out.append(v)
    return out


def _first_nonempty(items: List[Dict[str, Any]], field: str) -> str:
    for r in items:
        v = (r.get(field) or "").strip()
        if v:
            return v
    return ""


def _union_attachments(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Combine the attachment lists across merged items, deduped by filename."""
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for r in items:
        for a in _norm_attachments(r.get("attachments")):
            fn = a.get("filename")
            if fn and fn not in seen:
                seen.add(fn)
                out.append(a)
    return out


def merge_preview(items: List[Dict[str, Any]],
                  primary: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Compute the combined item without saving.

    The *primary* (survivor) is listed first, so its single-value fields
    (category, location, value…) win. Pass ``primary`` to honour a user's choice;
    otherwise the richest entry is picked automatically.
    """
    if not items:
        return {}
    if primary is None or primary not in items:
        primary = _pick_primary(items)
    ordered = [primary] + [r for r in items if r is not primary]

    descriptions = [(r.get("description") or "").strip() for r in ordered]
    longest_desc = max(descriptions, key=len) if any(descriptions) else ""

    ocr_parts: List[str] = []
    for r in ordered:
        t = (r.get("ocr_text") or "").strip()
        if t and t not in ocr_parts:
            ocr_parts.append(t)

    total_qty = sum(max(0, int(r.get("qty") or 0)) for r in ordered)
    # Keep the tightest reorder point among the merged items (else none).
    _reorders = [_coerce_reorder(r.get("reorder_at")) for r in ordered]
    _reorders = [x for x in _reorders if x is not None]
    merged_reorder = min(_reorders) if _reorders else None

    # Note anything the merge has to choose between, so the user isn't surprised.
    conflicts: List[str] = []
    locs = {(r.get("location") or "").strip() for r in ordered if (r.get("location") or "").strip()}
    if len(locs) > 1:
        conflicts.append("different locations: " + ", ".join(sorted(locs)))
    codes = {(r.get("location_code") or "").strip() for r in ordered if (r.get("location_code") or "").strip()}
    if len(codes) > 1:
        conflicts.append("different bins: " + ", ".join(sorted(codes)))
    vals = {(r.get("estimated_value") or "").strip() for r in ordered if (r.get("estimated_value") or "").strip()}
    if len(vals) > 1:
        conflicts.append("different values: " + ", ".join(sorted(vals)))

    return {
        "name": primary.get("name", ""),
        "description": longest_desc,
        "category": _first_nonempty(ordered, "category"),
        "type": _first_nonempty(ordered, "type"),
        "location": _first_nonempty(ordered, "location"),
        "location_code": _first_nonempty(ordered, "location_code"),
        "qty": total_qty,
        "reorder_at": merged_reorder,
        "images": _union_list(ordered, "images"),
        "ocr_text": "\n".join(ocr_parts),
        "specifications": _union_list(ordered, "specifications"),
        "estimated_value": _first_nonempty(ordered, "estimated_value"),
        "dimensions": _first_nonempty(ordered, "dimensions"),
        "product_url": _first_nonempty(ordered, "product_url"),
        "tags": _union_list(ordered, "tags"),
        # Keep every attached document across the merged items (dedup by filename),
        # and the first non-empty purchase field — so combining two photos of the
        # same item never loses its invoice or order details.
        "attachments": _union_attachments(ordered),
        "order_number": _first_nonempty(ordered, "order_number"),
        "purchase_date": _first_nonempty(ordered, "purchase_date"),
        "price_paid": _first_nonempty(ordered, "price_paid"),
        "seller": _first_nonempty(ordered, "seller"),
        # Keep the earliest scan date so the merged item reflects when it first
        # entered the inventory.
        "created_at": _earliest_created(ordered),
        "_primary_id": int(primary.get("id")),
        "_conflicts": conflicts,
    }


def find_duplicate_groups(
    rows: Optional[List[Dict[str, Any]]] = None,
    level: str = "balanced",
) -> List[Dict[str, Any]]:
    """Cluster items that are identical / very similar into merge candidates.

    ``level`` is one of DUP_LEVELS (loose / balanced / identical) or a float.
    Returns a list of plans, biggest groups first::

        {group, primary_id, primary_name, item_ids, merge_ids, items,
         preview, match_pct, conflicts}
    """
    rows = rows if rows is not None else inventory()
    threshold = DUP_LEVELS.get(level, level if isinstance(level, (int, float)) else 0.82)
    n = len(rows)

    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    # Blocking: rather than compare all n² pairs (slow past a few hundred items),
    # only compare items that share a signal — a significant word, a name prefix
    # (to still catch typos), the same product URL, or the same full name. This
    # keeps a big "scan everything" inventory responsive without missing real dups.
    buckets: Dict[Any, List[int]] = {}

    def _bucket(key, idx):
        buckets.setdefault(key, []).append(idx)

    for i, r in enumerate(rows):
        na = _norm_name(r.get("name", ""))
        if na:
            _bucket(("name", na), i)
            _bucket(("pfx", na[:5]), i)
        u = _norm_url(r.get("product_url", ""))
        if u:
            _bucket(("url", u), i)
        for t in _content_tokens(r):
            _bucket(("tok", t), i)

    candidates: set = set()
    for key, idxs in buckets.items():
        # Skip over-common keys (a token shared by hundreds of items isn't a
        # useful discriminator and would reintroduce the n² blow-up).
        if len(idxs) < 2 or len(idxs) > 400:
            continue
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                i, j = idxs[a], idxs[b]
                candidates.add((i, j) if i < j else (j, i))

    for i, j in candidates:
        if item_similarity(rows[i], rows[j]) >= threshold:
            union(i, j)

    clusters: Dict[int, List[int]] = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(i)

    plans: List[Dict[str, Any]] = []
    for gid, members in clusters.items():
        if len(members) < 2:
            continue
        items = [rows[m] for m in members]
        # Average pairwise similarity within this cluster (for display).
        scores = []
        for a in range(len(items)):
            for b in range(a + 1, len(items)):
                scores.append(item_similarity(items[a], items[b]))
        match_pct = int(round(100 * (sum(scores) / len(scores)))) if scores else 100
        prev = merge_preview(items)
        primary_id = prev["_primary_id"]
        plans.append({
            "group": _norm_name(prev["name"]) or f"group-{gid}",
            "primary_id": primary_id,
            "primary_name": prev["name"],
            "item_ids": [int(r.get("id")) for r in items],
            "merge_ids": [int(r.get("id")) for r in items if int(r.get("id")) != primary_id],
            "items": items,
            "preview": prev,
            "match_pct": match_pct,
            "conflicts": prev.get("_conflicts", []),
        })

    plans.sort(key=lambda p: (-len(p["item_ids"]), -p["match_pct"]))
    return plans


def merge_group(primary_id: int, merge_ids: List[int],
                overrides: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Combine ``merge_ids`` into ``primary_id`` and delete the merged rows.

    Sums quantities and unions images / specs / tags. Returns the merged item.
    """
    rows = inventory()
    by_id = {int(r.get("id")): r for r in rows}
    primary = by_id.get(int(primary_id))
    if not primary:
        return None
    ids = [int(i) for i in merge_ids if int(i) in by_id and int(i) != int(primary_id)]
    if not ids:
        return primary
    group = [primary] + [by_id[i] for i in ids]
    # The chosen survivor's single-value fields (category, location, value…) win.
    merged = merge_preview(group, primary=primary)
    if overrides:
        merged.update(overrides)

    # Write the merged fields onto the primary row (keep its id), drop the rest.
    for k in ("name", "description", "category", "type", "location", "location_code", "qty",
              "reorder_at", "images", "ocr_text", "specifications", "estimated_value",
              "dimensions", "product_url", "tags", "created_at",
              "attachments", "order_number", "purchase_date", "price_paid", "seller"):
        primary[k] = merged.get(k, primary.get(k))

    kept = [r for r in rows if int(r.get("id")) not in ids]
    _save(kept)
    return primary


def merge_groups(plans: List[Dict[str, Any]]) -> Dict[str, int]:
    """Apply several merge plans. Returns {groups, items_removed}."""
    removed = 0
    done = 0
    for p in plans or []:
        res = merge_group(p.get("primary_id"), p.get("merge_ids", []))
        if res is not None and p.get("merge_ids"):
            removed += len(p["merge_ids"])
            done += 1
    return {"groups": done, "items_removed": removed}


# --------------------------------------------------------------------
# Serialize every state-changing entry point against _WRITE_LOCK. Kept in one
# place (rather than a decorator scattered on each def) so the exact set of
# synchronized mutators is easy to audit. Read-only helpers (inventory(),
# get_item, find_*, etc.) are deliberately NOT wrapped — they stay concurrent.
# --------------------------------------------------------------------
for _name in (
    "add_item", "add_photo_items", "update_item", "update_item_fields",
    "adjust_qty", "remove_item", "bulk_set_fields", "bulk_remove",
    "add_image_to_item", "remove_image_from_item", "assign_types",
    "set_ocr_text", "set_location", "apply_organization", "apply_fit", "merge_group",
    "merge_groups", "prune_unreferenced_images", "prune_unreferenced_documents",
    "snapshot_inventory", "commit_undo", "restore_inventory",
):
    globals()[_name] = _synchronized(globals()[_name])
del _name
