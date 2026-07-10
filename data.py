from __future__ import annotations
import json
import re as _re_date
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from config import INVENTORY_JSON, ASSET_IMAGE_PATH

# --------------------------------------------------------------------
# Persistence helpers
# --------------------------------------------------------------------

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
        # Create empty file – don’t seed unless you prefer
        path.write_text("[]", encoding="utf-8")
        return []
    return _safe_read(path)

def _save(rows: List[Dict[str, Any]]) -> None:
    Path(INVENTORY_JSON).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

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


def inventory() -> List[Dict[str, Any]]:
    rows = _load()

    # Every record must have a unique id — the UI selects, edits, and opens
    # photos for items by id. Legacy / hand-edited files may omit it, which would
    # collapse multiple records to id=None and cross-wire them. Backfill stable
    # unique ids for any id-less record (deterministic across reads).
    used: set = set()
    for r in rows:
        try:
            used.add(int(r.get("id")))
        except (TypeError, ValueError):
            pass
    next_free = (max(used) + 1) if used else 1

    # Normalize schema
    norm = []
    for r in rows:
        try:
            rid = int(r.get("id"))
        except (TypeError, ValueError):
            rid = None
        if rid is None:
            while next_free in used:
                next_free += 1
            rid = next_free
            used.add(rid)

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
            "name": r.get("name", ""),
            "description": r.get("description", ""),
            "category": (r.get("category") or "").strip(),
            "location": (r.get("location") or "").strip(),
            "location_code": (r.get("location_code") or "").strip(),
            "qty": int(r.get("qty") or 0),
            "images": images if isinstance(images, list) else [],
            "ocr_text": r.get("ocr_text", ""),
            "thumb_url": r.get("thumb_url", ""),
            # Richer catalogue fields (from vision AI / web lookup). All optional.
            "specifications": _norm_list(r.get("specifications")),
            "estimated_value": (r.get("estimated_value") or "").strip(),
            "dimensions": (r.get("dimensions") or "").strip(),
            "product_url": (r.get("product_url") or "").strip(),
            "tags": _norm_list(r.get("tags")),
        }
        # When it was added: keep the stored value, else derive from the images.
        rec["created_at"] = (r.get("created_at") or "").strip() or _derive_created_at(rec)
        norm.append(rec)
    return norm


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
        "images": _clean_images(images),
        "ocr_text": ocr_text or "",
        "created_at": _now_iso(),
        "specifications": _norm_list(specifications),
        "estimated_value": (estimated_value or "").strip(),
        "dimensions": (dimensions or "").strip(),
        "product_url": (product_url or "").strip(),
        "tags": _norm_list(tags),
    }
    rows.append(row)
    _save(rows)
    return row

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
) -> Dict[str, Any]:
    rows = inventory()
    found = None

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
                r["tags"] = _norm_list(tags)
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


# Fields that may be patched in place without a full form round-trip.
_PATCHABLE = {"name", "description", "category", "location", "location_code",
              "qty", "estimated_value", "dimensions", "product_url"}


def update_item_fields(item_id: int, **fields: Any) -> Optional[Dict[str, Any]]:
    """Patch specific fields on one item (e.g. write a price back). Returns it."""
    rows = inventory()
    found = None
    for r in rows:
        if int(r.get("id") or 0) == int(item_id):
            for k, v in fields.items():
                if k in _PATCHABLE and v is not None:
                    r[k] = int(v) if k == "qty" else (str(v).strip() if isinstance(v, str) else v)
            found = r
            break
    if found is not None:
        _save(rows)
    return found


def bulk_set_fields(ids: List[int], category: Optional[str] = None,
                    location: Optional[str] = None,
                    location_code: Optional[str] = None) -> int:
    """Set category / location / bin on many items at once (only given fields).

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
        _undo_path().write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        # A fresh snapshot invalidates any earlier op's validity checkpoint.
        _undo_chk_path().unlink(missing_ok=True)
    except Exception:
        pass


def commit_undo() -> None:
    """Record the state the op produced, so a later undo can confirm nothing
    else has changed the inventory since (guards against clobbering new edits)."""
    try:
        _undo_chk_path().write_text(
            Path(INVENTORY_JSON).read_text(encoding="utf-8"), encoding="utf-8")
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
        Path(INVENTORY_JSON).write_text(bak.read_text(encoding="utf-8"), encoding="utf-8")
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
        str(r.get("location", "")),
        str(r.get("location_code", "")),
        str(r.get("ocr_text", "")),
        " ".join(r.get("specifications", []) or []),
        " ".join(r.get("tags", []) or []),
        str(r.get("dimensions", "")),
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

def summary_by(field: str, rows: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """
    Group rows by ``field`` ("category" or "location") and total up the item
    count and quantity per group. Empty values are grouped under "Uncategorized"
    / "Unassigned". Returns a list sorted by total quantity (desc).
    """
    rows = rows if rows is not None else inventory()
    fallback = "Uncategorized" if field == "category" else ("Unassigned" if field == "location" else "—")
    buckets: Dict[str, Dict[str, int]] = {}
    for r in rows:
        key = (r.get(field) or "").strip() or fallback
        b = buckets.setdefault(key, {"items": 0, "qty": 0})
        b["items"] += 1
        b["qty"] += int(r.get("qty") or 0)
    out = [{"name": k, "items": v["items"], "qty": v["qty"]} for k, v in buckets.items()]
    out.sort(key=lambda d: (-d["qty"], -d["items"], d["name"].lower()))
    return out

def stats(rows: Optional[List[Dict[str, Any]]] = None, low_stock_threshold: int = 5) -> Dict[str, int]:
    """Headline numbers for the KPI bar."""
    rows = rows if rows is not None else inventory()
    total_items = len(rows)
    total_qty = sum(int(r.get("qty") or 0) for r in rows)
    low_stock = sum(1 for r in rows if int(r.get("qty") or 0) < low_stock_threshold)
    return {
        "items": total_items,
        "qty": total_qty,
        "low": low_stock,
        "categories": len(categories(rows)),
        "locations": len(locations(rows)),
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
    """Total estimated value of a group (per-item value × quantity)."""
    total = 0.0
    found = False
    for r in rows:
        v = str(r.get("estimated_value") or "").replace(",", "")
        m = _re.search(r"\d+(?:\.\d+)?", v)
        if m:
            try:
                total += float(m.group(0)) * max(1, int(r.get("qty") or 1))
                found = True
            except ValueError:
                pass
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


def containers() -> List[Dict[str, Any]]:
    """Load the user-defined containers: [{code, name, capacity}]."""
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
        out.append({"code": code, "name": (c.get("name") or code).strip(), "capacity": cap})
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
        clean.append({"code": code, "name": (c.get("name") or code).strip(), "capacity": cap})
    CONTAINERS_FILE.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    return clean


def parse_containers_text(text: str) -> List[Dict[str, Any]]:
    """Parse an editor textarea (one container per line: ``CODE | Name | capacity``)."""
    out: List[Dict[str, Any]] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 3:
            code, name, cap = parts[0], parts[1], parts[2]
        elif len(parts) == 2:
            code, name, cap = parts[0], parts[0], parts[1]
        else:
            code, name, cap = parts[0], parts[0], "25"
        m = _re.search(r"\d+", cap or "")
        capacity = int(m.group(0)) if m else 25
        if code:
            out.append({"code": code, "name": name or code, "capacity": capacity})
    return out


def containers_to_text(conts: Optional[List[Dict[str, Any]]] = None) -> str:
    conts = conts if conts is not None else containers()
    return "\n".join(f"{c['code']} | {c['name']} | {c['capacity']}" for c in conts)


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


def item_similarity(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    """Similarity of two items in 0..1. 1.0 == a confident duplicate.

    Strong signals short-circuit: an identical normalised name, or the same
    non-empty product URL. Otherwise blend name closeness (typos / plurals) with
    shared significant words, nudged up when the categories agree. Items whose
    size/model codes exist but don't overlap (9V vs AA, M3 vs M5) are held apart.
    """
    na, nb = _norm_name(a.get("name", "")), _norm_name(b.get("name", ""))
    if na and na == nb:
        return 1.0
    ua, ub = _norm_url(a.get("product_url", "")), _norm_url(b.get("product_url", ""))
    if ua and ua == ub:
        return 0.97

    # A model/size mismatch is a strong "not the same thing" signal.
    ca_codes, cb_codes = _codes(a), _codes(b)
    if ca_codes and cb_codes and not (ca_codes & cb_codes):
        return round(min(0.5, _SeqMatcher(None, na, nb).ratio()), 3)

    name_ratio = _SeqMatcher(None, na, nb).ratio() if (na and nb) else 0.0
    ta, tb = _content_tokens(a), _content_tokens(b)
    jac = (len(ta & tb) / len(ta | tb)) if (ta or tb) else 0.0
    score = 0.6 * name_ratio + 0.4 * jac

    cat_a = (a.get("category") or "").strip().lower()
    cat_b = (b.get("category") or "").strip().lower()
    if cat_a and cat_b:
        score = min(1.0, score + 0.05) if cat_a == cat_b else score * 0.9
    return round(score, 3)


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
        "location": _first_nonempty(ordered, "location"),
        "location_code": _first_nonempty(ordered, "location_code"),
        "qty": total_qty,
        "images": _union_list(ordered, "images"),
        "ocr_text": "\n".join(ocr_parts),
        "specifications": _union_list(ordered, "specifications"),
        "estimated_value": _first_nonempty(ordered, "estimated_value"),
        "dimensions": _first_nonempty(ordered, "dimensions"),
        "product_url": _first_nonempty(ordered, "product_url"),
        "tags": _union_list(ordered, "tags"),
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
    for k in ("name", "description", "category", "location", "location_code", "qty",
              "images", "ocr_text", "specifications", "estimated_value", "dimensions",
              "product_url", "tags", "created_at"):
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
