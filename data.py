from __future__ import annotations
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from config import INVENTORY_JSON

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
    # Normalize schema
    norm = []
    for r in rows:
        norm.append({
            "id": r.get("id"),
            "name": r.get("name", ""),
            "description": r.get("description", ""),
            "qty": int(r.get("qty") or 0),
            "image_filename": r.get("image_filename"),
            "ocr_text": r.get("ocr_text", ""),
            "thumb_url": r.get("thumb_url", ""),
        })
    return norm

def _next_id(rows: List[Dict[str, Any]]) -> int:
    mx = 0
    for r in rows:
        try:
            mx = max(mx, int(r.get("id") or 0))
        except Exception:
            pass
    return mx + 1

def add_item(name: str, description: str, qty: Optional[int], image_filename: Optional[str], ocr_text: str) -> Dict[str, Any]:
    rows = inventory()
    # Unique by name
    key = name.strip().lower()
    if any((r.get("name","").strip().lower() == key) for r in rows):
        raise ValueError("An item with this name already exists.")
    row = {
        "id": _next_id(rows),
        "name": name.strip(),
        "description": (description or "").strip(),
        "qty": int(qty or 0),
        "image_filename": image_filename,
        "ocr_text": ocr_text or "",
    }
    rows.append(row)
    _save(rows)
    return row

def update_item(item_id: int, name: str, description: str, qty: Optional[int], image_filename: Optional[str], ocr_text: str) -> Dict[str, Any]:
    rows = inventory()
    found = None
    for r in rows:
        if int(r.get("id") or 0) == int(item_id):
            r["name"] = (name or "").strip()
            r["description"] = (description or "").strip()
            r["qty"] = int(qty or 0)
            r["image_filename"] = image_filename
            r["ocr_text"] = ocr_text or ""
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

def search(q: str) -> List[Dict[str, Any]]:
    q = (q or "").strip().lower()
    if not q:
        return inventory()
    out = []
    for r in inventory():
        hay = " ".join([str(r.get("name","")), str(r.get("description","")), str(r.get("ocr_text",""))]).lower()
        if q in hay:
            out.append(r)
    return out
