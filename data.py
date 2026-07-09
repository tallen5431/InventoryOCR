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
