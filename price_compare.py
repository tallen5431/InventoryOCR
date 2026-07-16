"""
Price Compare — scrape several saved product pages for the *same kind* of item,
work out each one's **price per unit** (many listings sell packs of N at a
bundle price), and rank them so the best deal is obvious without trawling the
web by hand.

It reuses ``product_import.extract_from_html`` for the heavy scraping, adds
pack-size / quantity detection, ties results back to items already in the
inventory index, and keeps a small history so the same tracked "search" can be
re-run over time to see how prices move.

Persistence: ``price_compare.json`` (next to inventory.json). A *search* is a
product you track (e.g. "AA Batteries"); each run appends a dated *snapshot*.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import data as _data
import product_import as _pi

PRICE_FILE = Path(_data.INVENTORY_JSON).parent / "price_compare.json"


# --------------------------------------------------------------------
# Price + quantity parsing
# --------------------------------------------------------------------

_CURRENCY_SYMBOLS = {"$": "$", "£": "£", "€": "€", "¥": "¥"}


def _parse_price(text: str) -> Optional[float]:
    """Pull a numeric price out of a messy string ('US $11.99' -> 11.99)."""
    if not text:
        return None
    s = text.replace(" ", "")
    # European decimal ("8,99" / "1.299,00") — comma as the decimal separator.
    if re.search(r"\d,\d{2}(?:\D|$)", s) and not re.search(r"\d\.\d{2}(?:\D|$)", s):
        s = s.replace(".", "").replace(",", ".")
    # Grab the first number that looks like money (allow thousands separators).
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)", s)
    if not m:
        return None
    try:
        return round(float(m.group(1).replace(",", "")), 2)
    except ValueError:
        return None


def _currency(text: str) -> str:
    for sym in _CURRENCY_SYMBOLS:
        if sym in (text or ""):
            return sym
    if re.search(r"\bUSD\b", text or "", re.I):
        return "$"
    if re.search(r"\b(GBP|EUR)\b", text or "", re.I):
        return "£" if "GBP" in (text or "").upper() else "€"
    return "$"


# Words that mark a pack / multi-count listing.
_UNIT_WORDS = (
    r"pcs?|pieces?|packs?|pkgs?|count|cts?|pairs?|sets?|units?|rolls?|sheets?|"
    r"bags?|boxe?s?|lots?|bundles?|packets?|tablets?|capsules?|ct"
)


def detect_quantity(name: str, specs: Optional[List[str]] = None,
                    description: str = "") -> Tuple[int, str]:
    """Best-effort pack-size detection so we can compute price *per unit*.

    Returns ``(quantity, unit_label)``. Defaults to ``(1, "each")`` when nothing
    obvious is found. Prefers explicit pack markers ("150PCS", "Pack of 6",
    "6-Pack", "Qty: 50", "x100") and, among those, the largest count — bundle
    sizes are usually the biggest number in a title.
    """
    haystacks = [name or ""]
    if specs:
        haystacks.append(" ; ".join(str(s) for s in specs))
    if description:
        haystacks.append(description)
    text = "  ".join(haystacks)

    candidates: List[Tuple[int, str]] = []

    def _add(n: str, unit: str):
        try:
            v = int(n)
        except (TypeError, ValueError):
            return
        if 1 < v <= 100000:
            candidates.append((v, unit))

    # "150PCS", "50 count", "12 pieces", "6 pack" (number then unit word)
    for m in re.finditer(rf"(\d[\d,]*)\s*(?:-|\s)?\s*({_UNIT_WORDS})\b", text, re.I):
        _add(m.group(1).replace(",", ""), _norm_unit(m.group(2)))
    # "Pack of 6", "Set of 3", "Box of 24"
    for m in re.finditer(rf"\b({_UNIT_WORDS})\s+of\s+(\d[\d,]*)", text, re.I):
        _add(m.group(2).replace(",", ""), _norm_unit(m.group(1)))
    # "x100" bundle notation ("x" THEN the count) — but NOT a dimension like
    # "16x24" (digits on both sides) nor an 'x' buried in a model number like
    # "MAX7219" (x preceded by a letter), so the 'x' must sit at a token boundary.
    # NOTE: the reverse "100x" form is deliberately NOT matched — it can't be told
    # apart from a magnification ("40X-1000X microscope", "10X loupe"), which would
    # otherwise be misread as a huge pack and wreck the per-unit value. Real packs
    # written that way almost always carry a unit word ("100 pcs", "6-pack") caught
    # above, so nothing useful is lost.
    for m in re.finditer(r"(?<![A-Za-z0-9])x\s*(\d{2,})(?!\s*[x\d])", text, re.I):
        _add(m.group(1), "each")
    # "Qty: 50" / "Quantity 50"
    for m in re.finditer(r"\b(?:qty|quantity)\.?\s*[:=]?\s*(\d[\d,]*)", text, re.I):
        _add(m.group(1).replace(",", ""), "each")

    if not candidates:
        return 1, "each"
    # Largest count wins (bundle sizes dominate), keeping its unit label.
    qty, unit = max(candidates, key=lambda c: c[0])
    return qty, unit


def _norm_unit(word: str) -> str:
    w = (word or "").lower().rstrip("s")
    mapping = {
        "pc": "piece", "piece": "piece", "pcs": "piece",
        "pack": "pack", "pkg": "pack", "packet": "pack",
        "count": "each", "ct": "each", "unit": "each",
        "pair": "pair", "set": "set", "roll": "roll", "sheet": "sheet",
        "bag": "bag", "box": "box", "boxe": "box", "lot": "lot",
        "bundle": "bundle", "tablet": "tablet", "capsule": "capsule",
    }
    return mapping.get(w, "each")


def per_unit_value(price_text: str, name: str = "",
                   specs: Optional[List[str]] = None, description: str = "") -> Dict[str, Any]:
    """Per-unit pricing for a single listing.

    Reuses the pack-size detection to turn a listing's *total* price into a price
    *per unit*. Returns a dict:
      list_price – parsed total price (float) or None
      unit_price – list_price / detected quantity (float) or None
      qty, unit  – detected pack size and unit label (defaults 1, "each")
      currency   – best-guess currency symbol ("$" default)
      formatted  – display string, e.g. "$1.40 each (pack of 10 @ $13.99)"
    """
    pv = _parse_price(price_text or "")
    qty, unit = detect_quantity(name or "", specs, description or "")
    cur = _currency(price_text or "")
    unit_price = round(pv / qty, 4) if (pv is not None and qty) else None
    if unit_price is None:
        formatted = ""
    elif qty > 1:
        formatted = f"{cur}{unit_price:.2f} each (pack of {qty} @ {cur}{pv:.2f})"
    else:
        formatted = f"{cur}{unit_price:.2f}"
    return {"list_price": pv, "unit_price": unit_price, "qty": qty,
            "unit": unit, "currency": cur, "formatted": formatted}


# --------------------------------------------------------------------
# Tie back to the inventory index
# --------------------------------------------------------------------

def match_inventory(name: str, tags: Optional[List[str]] = None,
                    rows: Optional[List[Dict[str, Any]]] = None) -> Tuple[Optional[Any], str]:
    """Find the inventory item this product most likely is (token overlap).

    Requires at least two shared significant words to avoid noise. Returns
    ``(item_id, item_name)`` or ``(None, "")``.
    """
    rows = rows if rows is not None else _data.inventory()
    want = set(_data._tokenize(name or ""))
    for t in tags or []:
        want |= set(_data._tokenize(str(t)))
    if not want:
        return None, ""
    best, best_score = None, 0
    for r in rows:
        have = set(_data._tokenize(r.get("name", "")))
        have |= set(_data._tokenize(r.get("category", "")))
        for t in r.get("tags", []) or []:
            have |= set(_data._tokenize(str(t)))
        score = len(want & have)
        if score > best_score:
            best, best_score = r, score
    if best and best_score >= 2:
        return best.get("id"), best.get("name", "")
    return None, ""


# --------------------------------------------------------------------
# Analyse a batch of uploaded HTML files
# --------------------------------------------------------------------

def analyze_htmls(files: List[Tuple[str, str]]) -> Dict[str, Any]:
    """Scrape each (filename, html) pair, compute unit prices, and rank them.

    Returns ``{products:[...ranked...], errors:[{source,error}], best}``.
    """
    rows = _data.inventory()
    products: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []

    for fname, html_text in files or []:
        try:
            res = _pi.extract_from_html(html_text or "", "")
        except Exception as e:  # pragma: no cover - defensive
            errors.append({"source": fname, "error": f"parse error: {e}"})
            continue
        if not res.get("ok"):
            errors.append({"source": fname, "error": res.get("error", "couldn't read that page")})
            continue
        d = res.get("data", {})
        name = d.get("name", "").strip() or fname
        price_text = (res.get("price") or d.get("estimated_value") or "").strip()
        pv = _parse_price(price_text)
        qty, unit = detect_quantity(name, d.get("specifications", []), d.get("what_it_is", ""))
        unit_price = round(pv / qty, 4) if (pv is not None and qty) else None
        mid, mname = match_inventory(name, d.get("tags"), rows)
        products.append({
            "source": fname,
            "name": name,
            "price_text": price_text,
            "price_value": pv,
            "currency": _currency(price_text),
            "quantity": qty,
            "unit": unit,
            "unit_price": unit_price,
            "url": d.get("product_url", ""),
            "image_url": d.get("image_url", ""),
            "category": d.get("category", ""),
            "tags": d.get("tags", []),
            "matched_item_id": mid,
            "matched_item_name": mname,
        })

    ranked = _rank(products)
    best = next((p for p in ranked if p.get("best")), None)
    return {"products": ranked, "errors": errors, "best": best}


def _rank(products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sort cheapest unit-price first (unknowns last) and flag the winner."""
    def key(p):
        up = p.get("unit_price")
        return (0, up) if up is not None else (1, 0.0)
    ranked = sorted(products, key=key)
    for i, p in enumerate(ranked):
        p["best"] = bool(i == 0 and p.get("unit_price") is not None)
    return ranked


def suggest_label(products: List[Dict[str, Any]]) -> str:
    """Guess a tracking name from the words the products share."""
    if not products:
        return ""
    tok_sets = [set(_data._tokenize(p.get("name", ""))) for p in products if p.get("name")]
    if not tok_sets:
        return ""
    common = set.intersection(*tok_sets) if len(tok_sets) > 1 else tok_sets[0]
    if not common:
        # fall back to the most frequent tokens across products
        freq: Dict[str, int] = {}
        for s in tok_sets:
            for t in s:
                freq[t] = freq.get(t, 0) + 1
        common = {t for t, _ in sorted(freq.items(), key=lambda kv: -kv[1])[:3]}
    words = [w for w in _data._tokenize(products[0].get("name", "")) if w in common][:4]
    return " ".join(w.capitalize() for w in words) if words else ""


# --------------------------------------------------------------------
# Persistence: tracked searches + dated snapshots (price over time)
# --------------------------------------------------------------------

def _slug(label: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (label or "").lower()).strip("-")
    if s:
        return s
    # Non-ASCII / punctuation-only labels (電池, "$$$") would all collapse to the
    # same id and cross-contaminate their histories — give each a stable hash.
    import hashlib
    return "s-" + hashlib.md5((label or "").encode("utf-8")).hexdigest()[:8]


def _today() -> str:
    return date.today().isoformat()


def searches() -> List[Dict[str, Any]]:
    if not PRICE_FILE.exists():
        return []
    try:
        raw = json.loads(PRICE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    return raw if isinstance(raw, list) else []


def _save_all(items: List[Dict[str, Any]]) -> None:
    PRICE_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _trim_product(p: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only what's worth remembering for a snapshot."""
    return {
        "source": p.get("source", ""),
        "name": p.get("name", ""),
        "price_text": p.get("price_text", ""),
        "price_value": p.get("price_value"),
        "currency": p.get("currency", "$"),
        "quantity": p.get("quantity", 1),
        "unit": p.get("unit", "each"),
        "unit_price": p.get("unit_price"),
        "url": p.get("url", ""),
        "matched_item_id": p.get("matched_item_id"),
        "matched_item_name": p.get("matched_item_name", ""),
    }


def save_snapshot(label: str, products: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Append a dated snapshot to the tracked search named ``label``.

    Find-or-create by label. If a snapshot already exists for today it's
    replaced (re-running the same day just refreshes it). Returns the search.
    """
    label = (label or "").strip()
    if not label:
        label = suggest_label(products) or "Untitled search"
    sid = _slug(label)
    items = searches()
    search = next((s for s in items if s.get("id") == sid), None)
    if search is None:
        search = {"id": sid, "label": label, "snapshots": []}
        items.append(search)
    else:
        search["label"] = label  # keep the freshest display label

    valid = [p.get("unit_price") for p in products if p.get("unit_price") is not None]
    best = min(valid) if valid else None
    best_p = None
    if best is not None:
        best_p = min((p for p in products if p.get("unit_price") is not None),
                     key=lambda p: p["unit_price"])
    snap = {
        "date": _today(),
        "count": len(products),
        "best_unit_price": best,
        "best_source": (best_p or {}).get("source", ""),
        "best_name": (best_p or {}).get("name", ""),
        "currency": (best_p or (products[0] if products else {})).get("currency", "$"),
        "products": [_trim_product(p) for p in products],
    }
    snaps = search.setdefault("snapshots", [])
    if snaps and snaps[-1].get("date") == snap["date"]:
        snaps[-1] = snap
    else:
        snaps.append(snap)
    _save_all(items)
    return search


def get_search(sid: str) -> Optional[Dict[str, Any]]:
    return next((s for s in searches() if s.get("id") == sid), None)


def delete_search(sid: str) -> bool:
    items = searches()
    kept = [s for s in items if s.get("id") != sid]
    if len(kept) == len(items):
        return False
    _save_all(kept)
    return True


def label_options() -> List[Dict[str, str]]:
    """Dropdown options for the saved searches, newest activity first."""
    opts = []
    for s in searches():
        snaps = s.get("snapshots", [])
        last = snaps[-1].get("date", "") if snaps else ""
        n = len(snaps)
        label = f"{s.get('label', s.get('id'))}  ·  {n} run{'s' if n != 1 else ''}"
        if last:
            label += f"  ·  last {last}"
        opts.append({"label": label, "value": s.get("id"), "_last": last})
    opts.sort(key=lambda o: o.get("_last", ""), reverse=True)
    for o in opts:
        o.pop("_last", None)
    return opts


def history_series(search: Dict[str, Any]) -> List[Dict[str, Any]]:
    """[{date, best_unit_price, currency, count}] oldest→newest for charting."""
    out = []
    for s in search.get("snapshots", []):
        out.append({
            "date": s.get("date", ""),
            "best_unit_price": s.get("best_unit_price"),
            "currency": s.get("currency", "$"),
            "count": s.get("count", 0),
            "best_name": s.get("best_name", ""),
        })
    return out
