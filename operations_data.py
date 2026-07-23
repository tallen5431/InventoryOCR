"""Operations data layer — production **materials** and the **batches** they roll
up into.

This is the sibling of :mod:`data` (the sellable-inventory store) for the
Operations tab. It tracks the things you buy to *run* the business rather than
the things you sell: boards you ordered, packaging and shipping supplies,
marketing materials — each with its photos, invoices, specs and what it cost.

Two records, two files (both under ``BASE_DIR``, kept apart from
``inventory.json``):

* **Material** — one purchased line (``materials.json``). Carries an optional
  ``batch_id`` linking it to the production run it was ordered for.
* **Batch** — a production run / job (``batches.json``). A batch rolls up the
  cost of every material assigned to it and, given the number of units it
  produced, tells you the **cost per unit**.

Design notes
------------
* Photos and documents are saved with the very same ``utils.save_image`` /
  ``utils.save_attachment`` helpers the dashboard uses, into the very same
  ``assets/`` folders — so nothing about the "upload format" changes. Because
  the asset pool is shared, :mod:`data`'s prune helpers are taught (via
  :func:`referenced_image_filenames` / :func:`referenced_document_filenames`)
  to also count material references before deleting anything.
* Writes go through :func:`data.atomic_write_text` (temp-file + fsync +
  ``os.replace``) and are serialized under one re-entrant lock, exactly like the
  inventory store, so concurrent waitress worker threads can't lose an update.
* Reads are defensive: one malformed record can never blank the whole list.
"""
from __future__ import annotations

import functools
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import MATERIALS_JSON, BATCHES_JSON
# Reuse the inventory store's battle-tested primitives rather than re-implementing
# them: atomic writes (no partial files) and free-text money parsing.
from data import atomic_write_text, parse_value

# --------------------------------------------------------------------
# Write serialization (see data.py for the full rationale)
# --------------------------------------------------------------------
# One re-entrant lock guards every read-modify-write across BOTH files. It's a
# single lock because cross-file mutators exist (deleting a batch unassigns its
# materials), and a batch job is low-traffic — there's no contention to optimise
# away. Reads stay lock-free; the atomic replace guarantees a whole file.
_OPS_LOCK = threading.RLock()


def _synchronized(fn):
    @functools.wraps(fn)
    def _wrapped(*args, **kwargs):
        with _OPS_LOCK:
            return fn(*args, **kwargs)
    return _wrapped


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# --------------------------------------------------------------------
# Persistence helpers (per-file, mirroring data.py)
# --------------------------------------------------------------------

def _load_or_none(path: Path) -> Optional[List[Dict[str, Any]]]:
    """Return the parsed JSON list, or ``None`` when the file EXISTS but can't be
    read as a list (corrupt / half-written). A missing file is a genuine empty
    store and returns ``[]``. Callers that overwrite or prune use ``None`` to
    refuse acting on a file they can't trust."""
    path = Path(path)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, list) else None


def _load(path: Path) -> List[Dict[str, Any]]:
    rows = _load_or_none(path)
    if rows is None:
        # File exists but is unreadable — do NOT treat as empty, or the next
        # save would clobber a recoverable file. Abort the mutator instead.
        raise RuntimeError(
            f"{path} exists but is not readable as a JSON list; refusing to "
            "read or overwrite it to avoid data loss. Fix or restore the file."
        )
    if not Path(path).exists():
        atomic_write_text(path, "[]")
    return rows


def _save(path: Path, rows: List[Dict[str, Any]]) -> None:
    atomic_write_text(Path(path), json.dumps(rows, ensure_ascii=False, indent=2))


# --------------------------------------------------------------------
# Small coercers
# --------------------------------------------------------------------

def _safe_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    return str(v).strip()


def _safe_qty(v: Any) -> int:
    try:
        n = int(float(str(v).strip()))
    except (TypeError, ValueError):
        return 0
    return n if n >= 0 else 0


def _safe_float(v: Any, default: float = 0.0) -> float:
    """Non-negative float, or ``default`` on anything unparseable. Used for the
    per-build quantity (how many of a material one produced unit consumes), which
    is often fractional — one board yields four coasters → 0.25 per coaster."""
    try:
        f = float(str(v).strip())
    except (TypeError, ValueError):
        return default
    return f if f >= 0 else default


def _safe_id(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _norm_list(v: Any) -> List[str]:
    """List of clean non-empty strings from a list or comma/newline text."""
    if v is None:
        return []
    if isinstance(v, str):
        parts = [p.strip() for p in v.replace("\n", ",").split(",")]
        return [p for p in parts if p]
    if isinstance(v, list):
        return [str(p).strip() for p in v if str(p).strip()]
    return []


def _clean_images(images: Any) -> List[str]:
    if images is None:
        return []
    if isinstance(images, str):
        return [images] if images.strip() else []
    if isinstance(images, list):
        return [str(i).strip() for i in images if str(i).strip()]
    return []


def _norm_attachments(v: Any) -> List[Dict[str, Any]]:
    """Coerce stored attachments to clean metadata dicts (same shape as the
    inventory store). Entries with no ``filename`` are dropped so the download
    route can never point at nothing. A bare string is treated as a filename."""
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


def _next_id(rows: List[Dict[str, Any]]) -> int:
    mx = 0
    for r in rows:
        try:
            mx = max(mx, int(r.get("id") or 0))
        except Exception:
            pass
    return mx + 1


def _backfill_ids(rows: List[Any]) -> None:
    """Give every dict row a unique int id in place (legacy/hand-edited files may
    omit or collide on ids, which would cross-wire edits/deletes)."""
    used = set()
    for r in rows:
        if isinstance(r, dict):
            rid = _safe_id(r.get("id"))
            if rid is not None:
                used.add(rid)
    nxt = (max(used) + 1) if used else 1
    seen = set()
    for r in rows:
        if not isinstance(r, dict):
            continue
        rid = _safe_id(r.get("id"))
        if rid is None or rid in seen:
            while nxt in used:
                nxt += 1
            rid = nxt
            used.add(rid)
        seen.add(rid)
        r["id"] = rid


# ====================================================================
# MATERIALS
# ====================================================================

# The top-level groups offered as type-ahead suggestions on the form. Free text
# is always allowed — these just seed the datalist so a fresh file isn't empty.
DEFAULT_MATERIAL_TYPES = [
    "Boards", "Packaging", "Shipping", "Marketing", "Raw Materials",
    "Hardware", "Labels", "Tools", "Other",
]


def _min_material(rid: Optional[int], r: Dict[str, Any]) -> Dict[str, Any]:
    """Last-resort normalized material so one bad record can't blank the list."""
    return {
        "id": rid,
        "name": _safe_str(r.get("name")) or (f"Material {rid}" if rid is not None else "Material"),
        "material_type": "", "batch_id": None, "vendor": "",
        "qty": _safe_qty(r.get("qty")), "unit_cost": "", "total_cost": "",
        "qty_per_unit": 1.0,
        "order_number": "", "purchase_date": "", "description": "",
        "specifications": [], "images": [], "thumb_url": "", "ocr_text": "",
        "attachments": [], "tags": [], "created_at": "",
    }


def materials() -> List[Dict[str, Any]]:
    """All materials, id-backfilled and schema-normalized. Never raises on a
    malformed row — it falls back to a minimal safe record instead."""
    rows = _load(MATERIALS_JSON)
    _backfill_ids(rows)
    out: List[Dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        rid = _safe_id(r.get("id"))
        try:
            rec = {
                "id": rid,
                "name": _safe_str(r.get("name")),
                "material_type": _safe_str(r.get("material_type")),
                "batch_id": _safe_id(r.get("batch_id")),
                "vendor": _safe_str(r.get("vendor")),
                "qty": _safe_qty(r.get("qty")),
                "unit_cost": _safe_str(r.get("unit_cost")),
                "total_cost": _safe_str(r.get("total_cost")),
                # How many of this material one produced unit of its batch
                # consumes (the bill-of-materials quantity). Defaults to 1 so a
                # legacy record behaves as "one per unit".
                "qty_per_unit": _safe_float(r.get("qty_per_unit", 1), 1.0),
                "order_number": _safe_str(r.get("order_number")),
                "purchase_date": _safe_str(r.get("purchase_date")),
                "description": _safe_str(r.get("description")),
                "specifications": _norm_list(r.get("specifications")),
                "images": _clean_images(r.get("images")),
                "thumb_url": _safe_str(r.get("thumb_url")),
                "ocr_text": _safe_str(r.get("ocr_text")),
                "attachments": _norm_attachments(r.get("attachments")),
                "tags": _norm_list(r.get("tags")),
                "created_at": _safe_str(r.get("created_at")) or _now_iso(),
            }
        except Exception:
            rec = _min_material(rid, r)
        out.append(rec)
    return out


def get_material(material_id: int) -> Optional[Dict[str, Any]]:
    mid = _safe_id(material_id)
    for r in materials():
        if r.get("id") == mid:
            return r
    return None


@_synchronized
def add_material(
    name: str = "",
    *,
    material_type: str = "",
    batch_id: Any = None,
    vendor: str = "",
    qty: Any = 1,
    unit_cost: str = "",
    total_cost: str = "",
    qty_per_unit: Any = 1,
    order_number: str = "",
    purchase_date: str = "",
    description: str = "",
    specifications: Any = None,
    images: Any = None,
    ocr_text: str = "",
    attachments: Any = None,
    tags: Any = None,
) -> Dict[str, Any]:
    """Create one material line. A blank name is auto-numbered (``Material 0007``)
    so a photo-first capture on a phone needs no typing."""
    rows = _load(MATERIALS_JSON)
    _backfill_ids(rows)
    nm = (name or "").strip() or _auto_material_name(rows)
    row = {
        "id": _next_id(rows),
        "name": nm,
        "material_type": (material_type or "").strip(),
        "batch_id": _safe_id(batch_id),
        "vendor": (vendor or "").strip(),
        "qty": _safe_qty(qty),
        "unit_cost": (unit_cost or "").strip(),
        "total_cost": (total_cost or "").strip(),
        "qty_per_unit": _safe_float(qty_per_unit, 1.0),
        "order_number": (order_number or "").strip(),
        "purchase_date": (purchase_date or "").strip(),
        "description": (description or "").strip(),
        "specifications": _norm_list(specifications),
        "images": _clean_images(images),
        "thumb_url": "",
        "ocr_text": ocr_text or "",
        "attachments": _norm_attachments(attachments),
        "tags": _norm_list(tags),
        "created_at": _now_iso(),
    }
    rows.append(row)
    _save(MATERIALS_JSON, rows)
    return row


# Sentinel so partial updates never wipe a field the caller didn't mention.
_KEEP = object()


@_synchronized
def update_material(
    material_id: int,
    *,
    name: Any = _KEEP,
    material_type: Any = _KEEP,
    batch_id: Any = _KEEP,
    vendor: Any = _KEEP,
    qty: Any = _KEEP,
    unit_cost: Any = _KEEP,
    total_cost: Any = _KEEP,
    qty_per_unit: Any = _KEEP,
    order_number: Any = _KEEP,
    purchase_date: Any = _KEEP,
    description: Any = _KEEP,
    specifications: Any = _KEEP,
    images: Any = _KEEP,
    ocr_text: Any = _KEEP,
    attachments: Any = _KEEP,
    tags: Any = _KEEP,
) -> Optional[Dict[str, Any]]:
    rows = _load(MATERIALS_JSON)
    _backfill_ids(rows)
    mid = _safe_id(material_id)
    found = None
    for r in rows:
        if _safe_id(r.get("id")) != mid:
            continue
        if name is not _KEEP:
            r["name"] = (name or "").strip() or r.get("name") or "Material"
        if material_type is not _KEEP:
            r["material_type"] = (material_type or "").strip()
        if batch_id is not _KEEP:
            r["batch_id"] = _safe_id(batch_id)
        if vendor is not _KEEP:
            r["vendor"] = (vendor or "").strip()
        if qty is not _KEEP:
            r["qty"] = _safe_qty(qty)
        if unit_cost is not _KEEP:
            r["unit_cost"] = (unit_cost or "").strip()
        if total_cost is not _KEEP:
            r["total_cost"] = (total_cost or "").strip()
        if qty_per_unit is not _KEEP:
            r["qty_per_unit"] = _safe_float(qty_per_unit, 1.0)
        if order_number is not _KEEP:
            r["order_number"] = (order_number or "").strip()
        if purchase_date is not _KEEP:
            r["purchase_date"] = (purchase_date or "").strip()
        if description is not _KEEP:
            r["description"] = (description or "").strip()
        if specifications is not _KEEP:
            r["specifications"] = _norm_list(specifications)
        if images is not _KEEP:
            r["images"] = _clean_images(images)
        if ocr_text is not _KEEP:
            r["ocr_text"] = ocr_text or ""
        if attachments is not _KEEP:
            r["attachments"] = _norm_attachments(attachments)
        if tags is not _KEEP:
            r["tags"] = _norm_list(tags)
        found = r
        break
    if found is None:
        return None
    _save(MATERIALS_JSON, rows)
    return found


@_synchronized
def remove_material(material_id: int) -> Optional[Dict[str, Any]]:
    rows = _load(MATERIALS_JSON)
    _backfill_ids(rows)
    mid = _safe_id(material_id)
    removed = None
    kept = []
    for r in rows:
        if _safe_id(r.get("id")) == mid and removed is None:
            removed = r
        else:
            kept.append(r)
    if removed is not None:
        _save(MATERIALS_JSON, kept)
    return removed


@_synchronized
def set_materials_batch(material_ids: List[int], batch_id: Any) -> int:
    """Assign (or clear, with ``batch_id=None``) the batch on several materials at
    once. Returns how many were changed."""
    want = {_safe_id(i) for i in (material_ids or [])}
    want.discard(None)
    bid = _safe_id(batch_id)
    rows = _load(MATERIALS_JSON)
    _backfill_ids(rows)
    n = 0
    for r in rows:
        if _safe_id(r.get("id")) in want and _safe_id(r.get("batch_id")) != bid:
            r["batch_id"] = bid
            n += 1
    if n:
        _save(MATERIALS_JSON, rows)
    return n


def _auto_material_name(rows: List[Dict[str, Any]]) -> str:
    import re
    pat = re.compile(r"^material\s*0*(\d+)$", re.IGNORECASE)
    mx = 0
    for r in rows:
        m = pat.match(str(r.get("name") or "").strip())
        if m:
            try:
                mx = max(mx, int(m.group(1)))
            except ValueError:
                pass
    return f"Material {mx + 1:04d}"


def material_types(rows: Optional[List[Dict[str, Any]]] = None) -> List[str]:
    rows = rows if rows is not None else materials()
    seen = {r.get("material_type", "").strip() for r in rows if r.get("material_type", "").strip()}
    # Union with the defaults so the datalist is useful on a fresh file.
    return sorted(seen | set(DEFAULT_MATERIAL_TYPES), key=str.lower)


def vendors(rows: Optional[List[Dict[str, Any]]] = None) -> List[str]:
    rows = rows if rows is not None else materials()
    return sorted({r.get("vendor", "").strip() for r in rows if r.get("vendor", "").strip()},
                  key=str.lower)


def _haystack(r: Dict[str, Any]) -> str:
    parts = [r.get("name", ""), r.get("material_type", ""), r.get("vendor", ""),
             r.get("order_number", ""), r.get("purchase_date", ""),
             r.get("description", ""), r.get("ocr_text", "")]
    parts += list(r.get("specifications") or [])
    parts += list(r.get("tags") or [])
    for a in r.get("attachments") or []:
        parts.append(a.get("original_name", ""))
    return " ".join(str(p) for p in parts).lower()


def search_materials(q: str, rows: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    rows = rows if rows is not None else materials()
    q = (q or "").strip().lower()
    if not q:
        return rows
    terms = [t for t in q.split() if t]
    return [r for r in rows if all(t in _haystack(r) for t in terms)]


# --------------------------------------------------------------------
# Cost model
# --------------------------------------------------------------------

def material_cost(m: Dict[str, Any]) -> Optional[float]:
    """Best estimate of what ONE material line cost in total.

    Prefers an explicit ``total_cost`` the user typed; otherwise multiplies a
    per-unit ``unit_cost`` by the quantity. Returns ``None`` when nothing numeric
    is available (so it can be shown as "—" and skipped in a sum)."""
    total = parse_value(m.get("total_cost"))
    if total is not None:
        return total
    unit = parse_value(m.get("unit_cost"))
    if unit is not None:
        return round(unit * int(m.get("qty") or 0), 2)
    return None


def material_unit_cost(m: Dict[str, Any]) -> Optional[float]:
    """Best estimate of what ONE unit of a material cost.

    Prefers an explicit ``unit_cost``; otherwise divides the total by the
    quantity — so a material bought as a pack (qty 5 for $7.59) knows its own
    per-unit cost without the user typing it. ``None`` when neither is derivable
    (e.g. no price, or qty 0)."""
    unit = parse_value(m.get("unit_cost"))
    if unit is not None:
        return unit
    total = parse_value(m.get("total_cost"))
    qty = int(m.get("qty") or 0)
    if total is not None and qty > 0:
        return round(total / qty, 4)
    return None


def material_qty_per_unit(m: Dict[str, Any]) -> float:
    """How many of this material one produced unit consumes (default 1)."""
    v = _safe_float(m.get("qty_per_unit", 1), 1.0)
    return v


def material_per_build_cost(m: Dict[str, Any]) -> Optional[float]:
    """What this material contributes to the cost of ONE produced unit:
    per-unit cost × how many are consumed per build. ``None`` when the material
    has no derivable unit cost."""
    unit = material_unit_cost(m)
    if unit is None:
        return None
    return round(unit * material_qty_per_unit(m), 4)


def materials_spend(rows: Optional[List[Dict[str, Any]]] = None) -> float:
    rows = rows if rows is not None else materials()
    return round(sum((material_cost(m) or 0.0) for m in rows), 2)


# ====================================================================
# BATCHES
# ====================================================================

def _min_batch(rid: Optional[int], r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": rid,
        "name": _safe_str(r.get("name")) or (f"Batch {rid}" if rid is not None else "Batch"),
        "product": "", "units_produced": 0, "date": "", "notes": "", "created_at": "",
    }


def batches() -> List[Dict[str, Any]]:
    rows = _load(BATCHES_JSON)
    _backfill_ids(rows)
    out: List[Dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        rid = _safe_id(r.get("id"))
        try:
            rec = {
                "id": rid,
                "name": _safe_str(r.get("name")) or (f"Batch {rid}" if rid is not None else "Batch"),
                "product": _safe_str(r.get("product")),
                "units_produced": _safe_qty(r.get("units_produced")),
                "date": _safe_str(r.get("date")),
                "notes": _safe_str(r.get("notes")),
                "created_at": _safe_str(r.get("created_at")) or _now_iso(),
            }
        except Exception:
            rec = _min_batch(rid, r)
        out.append(rec)
    return out


def get_batch(batch_id: int) -> Optional[Dict[str, Any]]:
    bid = _safe_id(batch_id)
    for b in batches():
        if b.get("id") == bid:
            return b
    return None


@_synchronized
def add_batch(name: str, *, product: str = "", units_produced: Any = 0,
              date: str = "", notes: str = "") -> Dict[str, Any]:
    rows = _load(BATCHES_JSON)
    _backfill_ids(rows)
    nm = (name or "").strip() or _auto_batch_name(rows)
    row = {
        "id": _next_id(rows),
        "name": nm,
        "product": (product or "").strip(),
        "units_produced": _safe_qty(units_produced),
        "date": (date or "").strip(),
        "notes": (notes or "").strip(),
        "created_at": _now_iso(),
    }
    rows.append(row)
    _save(BATCHES_JSON, rows)
    return row


@_synchronized
def update_batch(batch_id: int, *, name: Any = _KEEP, product: Any = _KEEP,
                 units_produced: Any = _KEEP, date: Any = _KEEP,
                 notes: Any = _KEEP) -> Optional[Dict[str, Any]]:
    rows = _load(BATCHES_JSON)
    _backfill_ids(rows)
    bid = _safe_id(batch_id)
    found = None
    for r in rows:
        if _safe_id(r.get("id")) != bid:
            continue
        if name is not _KEEP:
            r["name"] = (name or "").strip() or r.get("name") or "Batch"
        if product is not _KEEP:
            r["product"] = (product or "").strip()
        if units_produced is not _KEEP:
            r["units_produced"] = _safe_qty(units_produced)
        if date is not _KEEP:
            r["date"] = (date or "").strip()
        if notes is not _KEEP:
            r["notes"] = (notes or "").strip()
        found = r
        break
    if found is None:
        return None
    _save(BATCHES_JSON, rows)
    return found


@_synchronized
def remove_batch(batch_id: int) -> Optional[Dict[str, Any]]:
    """Delete a batch and unassign (never delete) any materials that pointed at
    it — the materials you bought still exist, they're just no longer grouped."""
    bid = _safe_id(batch_id)
    rows = _load(BATCHES_JSON)
    _backfill_ids(rows)
    removed = None
    kept = []
    for r in rows:
        if _safe_id(r.get("id")) == bid and removed is None:
            removed = r
        else:
            kept.append(r)
    if removed is None:
        return None
    _save(BATCHES_JSON, kept)
    # Detach materials from the now-gone batch (separate file, same lock held).
    mrows = _load(MATERIALS_JSON)
    _backfill_ids(mrows)
    changed = False
    for m in mrows:
        if _safe_id(m.get("batch_id")) == bid:
            m["batch_id"] = None
            changed = True
    if changed:
        _save(MATERIALS_JSON, mrows)
    return removed


@_synchronized
def find_or_create_batch(name: str) -> Optional[Dict[str, Any]]:
    """Return the batch with this name (case-insensitive), creating it if new.
    Blank name → ``None`` (nothing to create). Synchronized so the check-then-
    create is atomic — two concurrent saves of the same new name can't create
    duplicate batches (add_batch's lock is reentrant, so nesting is safe)."""
    nm = (name or "").strip()
    if not nm:
        return None
    for b in batches():
        if b.get("name", "").strip().lower() == nm.lower():
            return b
    return add_batch(nm)


def _auto_batch_name(rows: List[Dict[str, Any]]) -> str:
    import re
    pat = re.compile(r"^batch\s*0*(\d+)$", re.IGNORECASE)
    mx = 0
    for r in rows:
        m = pat.match(str(r.get("name") or "").strip())
        if m:
            try:
                mx = max(mx, int(m.group(1)))
            except ValueError:
                pass
    return f"Batch {mx + 1:04d}"


def batch_options(rows: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """``dcc.Dropdown`` options for picking a batch (value = id)."""
    rows = rows if rows is not None else batches()
    return [{"label": b.get("name", f"Batch {b.get('id')}"), "value": b.get("id")}
            for b in rows]


def batch_name_map(rows: Optional[List[Dict[str, Any]]] = None) -> Dict[int, str]:
    rows = rows if rows is not None else batches()
    return {b["id"]: b.get("name", f"Batch {b['id']}") for b in rows if b.get("id") is not None}


def materials_for_batch(batch_id: int,
                        rows: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    bid = _safe_id(batch_id)
    rows = rows if rows is not None else materials()
    return [m for m in rows if _safe_id(m.get("batch_id")) == bid]


def batch_rollup(batch: Dict[str, Any],
                 mats: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Cost summary for one batch as a bill of materials.

    ``cost_per_unit`` is what one produced unit costs in materials — the sum of
    each assigned material's per-unit cost × how many that unit consumes
    (``qty_per_unit``). ``run_cost`` scales that by ``units_produced``. This is
    the model that lets a single purchased pack (20 cables for $12.99) feed many
    produced units without duplicating the order — you record "1 cable per unit",
    not one material line per unit.

    ``purchased_cost`` is what the assigned material packs actually cost (kept for
    reference / the spend view).
    """
    mats = mats if mats is not None else materials()
    assigned = materials_for_batch(batch.get("id"), mats)
    per_build = [material_per_build_cost(m) for m in assigned]
    known = [c for c in per_build if c is not None]
    cost_per_unit = round(sum(known), 4) if known else None
    units = int(batch.get("units_produced") or 0)
    run_cost = (round(cost_per_unit * units, 2)
                if (cost_per_unit is not None and units > 0) else None)
    purchased = round(sum((material_cost(m) or 0.0) for m in assigned), 2)
    return {
        "batch": batch,
        "materials": assigned,
        "material_count": len(assigned),
        "cost_per_unit": cost_per_unit,
        "units_produced": units,
        "run_cost": run_cost,
        "purchased_cost": purchased,
        # Back-compat alias for any external reader of the old key.
        "total_cost": purchased,
    }


def unassigned_materials(rows: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    rows = rows if rows is not None else materials()
    return [m for m in rows if _safe_id(m.get("batch_id")) is None]


# ====================================================================
# Headline stats (Operations KPI bar)
# ====================================================================

def stats() -> Dict[str, Any]:
    mats = materials()
    bats = batches()
    spend = materials_spend(mats)
    per_units = [r["cost_per_unit"] for r in (batch_rollup(b, mats) for b in bats)
                 if r["cost_per_unit"] is not None]
    avg_per_unit = round(sum(per_units) / len(per_units), 2) if per_units else None
    return {
        "materials": len(mats),
        "spend": spend,
        "batches": len(bats),
        "unassigned": len(unassigned_materials(mats)),
        "avg_cost_per_unit": avg_per_unit,
    }


# ====================================================================
# Asset-reference reporting (so data.py's prune helpers stay honest)
# ====================================================================
# Materials share assets/images, assets/thumbnails and assets/documents with the
# inventory store. data.prune_unreferenced_*() must count material references
# before deleting an "orphan", or deleting an inventory item would wipe a
# material's photo/invoice. These read defensively and return None on a
# corrupt/unreadable file so the pruner bails out rather than over-deleting.

def referenced_image_filenames() -> Optional[set]:
    rows = _load_or_none(MATERIALS_JSON)
    if rows is None:
        return None
    out: set = set()
    for r in rows:
        if not isinstance(r, dict):
            continue
        for fn in _clean_images(r.get("images")):
            out.add(fn)
    return out


def referenced_document_filenames() -> Optional[set]:
    rows = _load_or_none(MATERIALS_JSON)
    if rows is None:
        return None
    out: set = set()
    for r in rows:
        if not isinstance(r, dict):
            continue
        for a in _norm_attachments(r.get("attachments")):
            fn = str(a.get("filename") or "").strip()
            if fn:
                out.add(fn)
    return out
