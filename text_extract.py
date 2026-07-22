"""Pull structured, high-signal fields out of scanned/OCR'd item text.

Why this exists
---------------
``text_relevance.for_index`` keeps the item-relevant *prose* for the search
index, but a lot of the most useful search anchors on a label or product page
are short structured tokens buried in that prose: the UPC/EAN barcode number,
the model / part / MPN, the brand, an ASIN, plus the odd measurement (12V,
5000mAh, 15.6"). Those are exactly what you type when hunting for one specific
item, and matching them exactly is what stops a search from dragging in
near-neighbours.

``extract(text)`` returns a small, deduped list of ``"Label: value"`` strings
(and bare identifiers) detected in the text. The caller stores them in the
item's ``ocr_fields`` — searchable and shown in the form, but kept separate
from the user-curated ``specifications`` so auto-detection never clobbers what
a person typed.

Design
------
* Everything is regex / heuristic — no dependencies, fully offline.
* Precision over recall: only *labelled* values (``Model: …``) and identifiers
  that pass a checksum / shape test are emitted, so this doesn't fill the field
  with noise. A 13-digit run that isn't a valid GTIN is dropped, not guessed.
* Never raises: any surprise yields ``[]`` and the scan is still stored raw.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Optional, Tuple

# Cap the number of detected fields so a pathological page can't bloat the row.
_MAX_FIELDS = 40
# A detected value longer than this is almost certainly a mis-parse (a whole
# sentence captured as a "value"); drop it rather than store junk.
_MAX_VALUE_LEN = 80


# --------------------------------------------------------------------------
# Labelled fields:  "<label> : <value>"  /  "<label>  <value>"
# --------------------------------------------------------------------------
# Each entry maps a normalized output label to the alternative spellings a
# retailer / datasheet might print. Order matters: the FIRST group whose label
# matches a line wins, so more specific labels precede generic ones.
_LABELLED: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("Brand", ("brand", "brand name")),
    ("Manufacturer", ("manufacturer", "made by", "mfr", "mfg")),
    ("Model", ("item model number", "model number", "model no", "model name",
               "model", "modelo")),
    ("Part number", ("manufacturer part number", "mfr part number",
                     "part number", "part no", "part #", "mpn", "catalog number",
                     "catalogue number")),
    ("SKU", ("sku", "item number", "item #")),
    ("ASIN", ("asin",)),
    ("UPC", ("upc", "upc-a", "upc a")),
    ("EAN", ("ean", "ean-13", "ean 13")),
    ("Color", ("colour", "color")),
    ("Material", ("material", "materials")),
    ("Capacity", ("capacity",)),
    ("Voltage", ("voltage", "input voltage", "rated voltage")),
    ("Wattage", ("wattage", "power", "rated power")),
    ("Size", ("size", "dimensions", "item dimensions", "product dimensions")),
    ("Weight", ("weight", "item weight", "net weight")),
)

# Split a "Key: Value" (or "Key - Value") line. The separator is a colon or a
# space-padded dash only — an unspaced hyphen stays part of the key so "EAN-13"
# and "Wi-Fi" aren't sliced in half. Requiring a separator also means ordinary
# prose ("great value") can't be read as a labelled field.
_KV_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 /.#'\-]{1,34}?)\s*(?::|\s[-–—]\s)\s*(.+?)\s*$")

# ASIN: Amazon's 10-char base-36-ish id, almost always starting with B0.
_ASIN_RE = re.compile(r"\b(B0[0-9A-Z]{8})\b")
# A run of 12/13/14 digits, possibly split by spaces/hyphens (barcodes OCR that
# way). Validated as a GTIN checksum before being trusted.
_GTIN_RE = re.compile(r"(?<!\d)(\d[\d\s\-]{10,16}\d)(?!\d)")

# Measurements worth indexing, matched anywhere in a line. Each yields a
# "<Label>: <match>" field. Kept tight so only real units fire.
_MEASURE: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("Voltage", re.compile(r"\b\d{1,4}(?:\.\d+)?\s?v(?:olts?)?\b", re.I)),
    ("Wattage", re.compile(r"\b\d{1,5}(?:\.\d+)?\s?w(?:atts?)?\b", re.I)),
    ("Current", re.compile(r"\b\d{1,4}(?:\.\d+)?\s?m?a(?:mps?)?\b", re.I)),
    ("Capacity", re.compile(r"\b\d{2,6}\s?m?ah\b", re.I)),
    ("Frequency", re.compile(r"\b\d{1,5}(?:\.\d+)?\s?[kmg]?hz\b", re.I)),
    ("Storage", re.compile(r"\b\d{1,4}\s?(?:gb|tb|mb)\b", re.I)),
)


def _norm(s: str) -> str:
    """Lower-case, fold accents, collapse runs of non-alnum to single spaces."""
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _gtin_check(digits: str) -> bool:
    """Validate a UPC-A(12) / EAN-13(13) / GTIN-14 modulo-10 check digit."""
    n = len(digits)
    if n not in (12, 13, 14) or not digits.isdigit():
        return False
    body, check = digits[:-1], int(digits[-1])
    total = 0
    # Weight alternates 3/1 from the RIGHTMOST body digit outward.
    for i, ch in enumerate(reversed(body)):
        total += int(ch) * (3 if i % 2 == 0 else 1)
    return (10 - (total % 10)) % 10 == check


def _clean_value(v: str) -> str:
    v = re.sub(r"\s+", " ", (v or "").strip()).strip(" .,:;-–—")
    return v


def _labelled_field(line: str) -> Optional[Tuple[str, str]]:
    """If ``line`` is a recognised ``Label: value`` pair, return (label, value)."""
    m = _KV_RE.match(line)
    if not m:
        return None
    key_norm = _norm(m.group(1))
    val = _clean_value(m.group(2))
    if not val or len(val) > _MAX_VALUE_LEN:
        return None
    for out_label, aliases in _LABELLED:
        for a in aliases:
            # Exact label, or the alias as the whole normalized key (so "model"
            # matches "model" and "model number" via its own alias, but a stray
            # "model of behaviour" sentence — normalized "model of behaviour" —
            # does not, because it isn't equal to any alias).
            if key_norm == a:
                # Canonicalise a labelled barcode to bare digits so it collapses
                # with the checksum-detected identifier instead of doubling up.
                if out_label in ("UPC", "EAN", "GTIN"):
                    digits = re.sub(r"[\s\-]", "", val)
                    if _gtin_check(digits):
                        val = digits
                return out_label, val
    return None


def _identifiers(text: str) -> List[Tuple[str, str]]:
    """Barcode / ASIN identifiers found anywhere in the text (checksum-gated)."""
    found: List[Tuple[str, str]] = []
    for m in _ASIN_RE.finditer(text):
        found.append(("ASIN", m.group(1)))
    for m in _GTIN_RE.finditer(text):
        digits = re.sub(r"[\s\-]", "", m.group(1))
        if _gtin_check(digits):
            label = {12: "UPC", 13: "EAN", 14: "GTIN"}[len(digits)]
            found.append((label, digits))
    return found


def _measurements(text: str) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for label, pat in _MEASURE:
        m = pat.search(text)
        if m:
            out.append((label, _clean_value(m.group(0))))
    return out


def extract(text: str) -> List[str]:
    """Detected ``"Label: value"`` fields for the search index / display.

    Deduped case-insensitively by label so one field per label survives (the
    first, strongest hit), plus every distinct identifier. Never raises.
    """
    if not text or not text.strip():
        return []
    try:
        pairs: List[Tuple[str, str]] = []

        # Labelled lines first — the strongest, least ambiguous signal.
        for raw in text.splitlines():
            got = _labelled_field(raw)
            if got:
                pairs.append(got)

        # Identifiers anywhere (may repeat a labelled UPC/ASIN — deduped below).
        pairs.extend(_identifiers(text))
        # Measurements only backfill labels not already captured.
        have = {lbl for lbl, _ in pairs}
        for lbl, val in _measurements(text):
            if lbl not in have:
                pairs.append((lbl, val))
                have.add(lbl)

        # Dedupe: one value per (label,value); and for single-valued labels
        # (Brand, Model, …) keep only the first. Identifiers may list several.
        _MULTI = {"UPC", "EAN", "GTIN", "ASIN", "Part number", "SKU"}
        out: List[str] = []
        seen_pair: set = set()
        seen_label: set = set()
        for lbl, val in pairs:
            val = _clean_value(val)
            if not val:
                continue
            key = (lbl.lower(), val.lower())
            if key in seen_pair:
                continue
            if lbl not in _MULTI and lbl in seen_label:
                continue
            seen_pair.add(key)
            seen_label.add(lbl)
            out.append(f"{lbl}: {val}")
            if len(out) >= _MAX_FIELDS:
                break
        return out
    except Exception:
        return []
