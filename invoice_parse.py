"""Pull purchase details out of an invoice / receipt / order confirmation.

Given free text — OCR'd from a receipt photo, or read from a saved order page —
this best-effort extracts the fields worth keeping for later analysis:

    order_number   e.g. "112-4472839-1234567"
    purchase_date  normalised to ISO "YYYY-MM-DD" when the date is understood
    price_paid     the amount actually paid, e.g. "$23.98"
    seller         who it was bought from, e.g. "Amazon"

Everything is optional: a field we can't find comes back as "". Nothing here
raises — a receipt is messy input, so the caller always gets a dict it can show
for review. This is deliberately conservative: it would rather leave a field
blank than guess wrong, since the user confirms before saving.
"""
from __future__ import annotations

import re
from datetime import date as _date_cls
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

# --------------------------------------------------------------------------
# Order number
# --------------------------------------------------------------------------
# A label ("order", "invoice", "confirmation"…) followed by an id token. We keep
# the token liberal (digits, letters, dashes) but require at least a few chars so
# stray "Order 1" style noise doesn't win.
_ORDER_LABEL = r"(?:order|invoice|confirmation|receipt|transaction|reference|ref|po)"
_ORDER_RE = re.compile(
    rf"{_ORDER_LABEL}\s*(?:number|no\.?|num|id|#)?\s*[:#]?\s*"
    r"([A-Z0-9][A-Z0-9\-]{4,29})",
    re.IGNORECASE,
)

# --------------------------------------------------------------------------
# Money / totals
# --------------------------------------------------------------------------
_CUR = r"(?:USD|US\$|\$|£|€|CAD|AUD)"
_AMT = r"\d[\d,]*(?:\.\d{2})?"
# Prefer a labelled grand/order total over an unlabelled number. Ordered by how
# trustworthy the label is.
_TOTAL_LABELS = [
    r"grand\s*total",
    r"order\s*total",
    r"total\s*paid",
    r"amount\s*paid",
    r"total\s*amount",
    r"total\s*charged",
    r"payment\s*total",
    r"total\s*due",
    r"total",
]
# The leading \b keeps "total" from matching inside "subtotal" — a receipt's
# subtotal must never be picked over its grand total.
_TOTAL_RES = [
    re.compile(rf"\b{lbl}\s*[:\-]?\s*({_CUR})\s*({_AMT})", re.IGNORECASE)
    for lbl in _TOTAL_LABELS
]

# --------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
# "June 14, 2026" / "14 June 2026" / "Jun 14 2026"
_DATE_TEXT_RE = re.compile(
    r"\b(\d{1,2})?\s*"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
    r"\s*(\d{1,2})?,?\s*(\d{4})\b",
    re.IGNORECASE,
)
# 2026-06-14 (ISO)
_DATE_ISO_RE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
# 06/14/2026 or 14/06/2026 or 6-14-26
_DATE_NUM_RE = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b")
# A label that marks the date we care about (order/purchase date, not a
# ship-by/delivery estimate).
_DATE_LABEL_RE = re.compile(
    r"(?:order(?:ed)?|purchase[d]?|placed|invoice|transaction|bought)"
    r"[^\n]{0,24}?"
    r"(\d{4}-\d{1,2}-\d{1,2}"
    r"|\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}"
    r"|(?:\d{1,2}\s+)?[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4}"
    r"|[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4})",
    re.IGNORECASE,
)

# --------------------------------------------------------------------------
# Sellers — friendly names for hosts / marketplace mentions
# --------------------------------------------------------------------------
_SELLER_HOSTS = {
    "amazon": "Amazon", "ebay": "eBay", "homedepot": "Home Depot",
    "lowes": "Lowe's", "walmart": "Walmart", "newegg": "Newegg",
    "aliexpress": "AliExpress", "mouser": "Mouser", "digikey": "DigiKey",
    "adafruit": "Adafruit", "sparkfun": "SparkFun", "microcenter": "Micro Center",
    "target": "Target", "etsy": "Etsy", "banggood": "Banggood",
    "harborfreight": "Harbor Freight", "mcmaster": "McMaster-Carr",
    "grainger": "Grainger", "bestbuy": "Best Buy", "temu": "Temu",
}

# Brand keys that are also ordinary English words — too ambiguous to match in a
# blind full-text scan. They can still be resolved from the source URL or an
# explicit "sold by …" cue, just not from an incidental mention in body text.
_AMBIGUOUS_SELLER_KEYS = {"target"}
_SOLD_BY_RE = re.compile(r"(?:sold\s*by|ships?\s*from|seller|vendor|store)\s*[:\-]?\s*"
                         r"([A-Z0-9][\w&'.,\- ]{1,40})", re.IGNORECASE)


def _clean(text: str) -> str:
    return re.sub(r"[ \t]+", " ", (text or "")).strip()


def _norm_two_digit_year(y: int) -> int:
    return 2000 + y if y < 100 else y


def _iso(y: int, m: int, d: int) -> str:
    # Validate against the real calendar (rejects 02/30, 04/31, etc.) rather than
    # a loose 1..31 day check, so we never emit a nonexistent date that later
    # blows up date.fromisoformat or shows the user an impossible purchase date.
    try:
        return _date_cls(y, m, d).isoformat()
    except (ValueError, TypeError):
        return ""


def _parse_one_date(s: str) -> str:
    """Normalise a single date string to ISO, or "" if not understood."""
    s = s.strip()
    m = _DATE_ISO_RE.search(s)
    if m:
        return _iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _DATE_TEXT_RE.search(s)
    if m:
        mon = _MONTHS.get(m.group(2).lower()[:3])
        day = m.group(1) or m.group(3)
        if mon and day and m.group(4):
            return _iso(int(m.group(4)), mon, int(day))
    m = _DATE_NUM_RE.search(s)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), _norm_two_digit_year(int(m.group(3)))
        # Assume US month/day ordering; fall back to day/month if month > 12.
        month, day = (a, b) if a <= 12 else (b, a)
        return _iso(y, month, day)
    return ""


def _find_date(text: str) -> str:
    # Prefer a date sitting next to an order/purchase label.
    m = _DATE_LABEL_RE.search(text)
    if m:
        iso = _parse_one_date(m.group(1))
        if iso:
            return iso
    # Otherwise take the first understandable date anywhere.
    for rx in (_DATE_ISO_RE, _DATE_TEXT_RE, _DATE_NUM_RE):
        m = rx.search(text)
        if m:
            iso = _parse_one_date(m.group(0))
            if iso:
                return iso
    return ""


def _find_total(text: str) -> str:
    for rx in _TOTAL_RES:
        m = rx.search(text)
        if m:
            cur = m.group(1).upper().replace("US$", "$").replace("USD", "$")
            amt = m.group(2)
            return f"{cur}{amt}"
    return ""


def _find_order(text: str) -> str:
    for m in _ORDER_RE.finditer(text):
        tok = m.group(1).strip("-")
        # Require at least one digit — pure words ("NUMBER") aren't order ids.
        if any(c.isdigit() for c in tok):
            return tok
    return ""


def _seller_from_url(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    host = re.sub(r"^www\.", "", host)
    core = host.split(".")[0] if host else ""
    if core in _SELLER_HOSTS:
        return _SELLER_HOSTS[core]
    # Second-level for things like "shop.example.co.uk".
    parts = host.split(".")
    for p in parts:
        if p in _SELLER_HOSTS:
            return _SELLER_HOSTS[p]
    return ""


def _find_seller(text: str, source_url: str = "") -> str:
    if source_url:
        s = _seller_from_url(source_url)
        if s:
            return s
    low = text.lower()
    for key, name in _SELLER_HOSTS.items():
        # This is a blind full-text scan, so match conservatively:
        #  * exclude brand names that are also common English words ("target") —
        #    they'd false-positive constantly ("the target location"); those are
        #    still resolved via the URL or the explicit "sold by" cue below.
        #  * require boundaries that also exclude hyphenated compounds, so
        #    "etsy-style" / "amazon-compatible" don't count as the seller.
        if key in _AMBIGUOUS_SELLER_KEYS:
            continue
        if re.search(rf"(?<![\w-]){re.escape(key)}(?![\w-])", low):
            return name
    m = _SOLD_BY_RE.search(text)
    if m:
        val = _clean(m.group(1))
        # Trim trailing noise (a following label word).
        val = re.split(r"\b(?:order|invoice|total|qty|quantity|price)\b", val, 1,
                       flags=re.IGNORECASE)[0].strip(" .,-")
        if 2 <= len(val) <= 40:
            return val
    return ""


def extract_purchase(text: str, source_url: str = "") -> Dict[str, Any]:
    """Extract purchase fields from receipt/order text.

    Returns ``{order_number, purchase_date, price_paid, seller, found}`` where
    ``found`` lists the keys that were populated (for a "read N fields" message).
    """
    text = _clean(text)
    out = {
        "order_number": _find_order(text) if text else "",
        "purchase_date": _find_date(text) if text else "",
        "price_paid": _find_total(text) if text else "",
        "seller": _find_seller(text, source_url) if (text or source_url) else "",
    }
    out["found"] = [k for k in ("order_number", "purchase_date", "price_paid", "seller") if out[k]]
    return out
