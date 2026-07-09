from __future__ import annotations
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from config import INVENTORY_JSON

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

        norm.append({
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
        })
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


def auto_organize(
    rows: Optional[List[Dict[str, Any]]] = None,
    *,
    prefix: str = "BIN",
) -> List[Dict[str, Any]]:
    """Propose a storage plan that groups like items (by category) into bins.

    Returns a list of group dicts (does NOT persist anything):
        {group, location_code, location_name, item_ids, items, qty, existing}

    Grouping rules:
      * Items sharing a category go to the same bin so like things live together.
      * If any item in a group already has a location_code, that code is reused
        for the whole group (keeps codes stable across re-runs).
      * New groups get the next free ``<prefix>-NN`` number.
      * Uncategorized items are grouped under a single "Uncategorised" bin.
    """
    rows = rows if rows is not None else inventory()

    # Bucket by category (case-insensitive), preserving a display name.
    buckets: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        cat = (r.get("category") or "").strip()
        key = cat.lower() or "\x00uncategorised"
        b = buckets.setdefault(key, {"name": cat or "Uncategorised", "rows": []})
        b["rows"].append(r)

    reserved = set(location_codes(rows))
    next_num = _next_bin_number(list(reserved))

    plan: List[Dict[str, Any]] = []
    # Deterministic order: named categories first (alphabetical), uncategorised last.
    for key in sorted(buckets.keys(), key=lambda k: (k == "\x00uncategorised", k)):
        b = buckets[key]
        group_rows = b["rows"]

        # Reuse an existing code if the group already has one.
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
            "item_ids": [int(gr.get("id")) for gr in group_rows],
            "items": len(group_rows),
            "qty": sum(int(gr.get("qty") or 0) for gr in group_rows),
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
