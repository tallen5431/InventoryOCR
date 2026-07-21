"""Keep only the item-relevant part of scanned/attached text for the search index.

Why this exists
---------------
Auto-OCR happily reads a *whole* screenshot. When that screenshot is a retailer
product page (the common case here — a saved Amazon/eBay listing), the raw text
is mostly stuff that has nothing to do with the item you saved:

  * site navigation ("Prime Video · Kindle Books · Whole Foods …")
  * the buy-box / delivery chrome ("Add to cart", "FREE delivery", prices)
  * cross-sell carousels — *other* products ("Customers also bought",
    "Products related to this item", "More from frequently bought brands",
    even a completely unrelated sponsored "Tree Pruner")
  * the whole review section ("Customers say", "Reviewed in the United States…")
  * footer / legal boilerplate (return policy, feedback, warranty blurbs)

If all of that lands in ``ocr_text`` it pollutes the search index: searching
"multimeter" or "pruner" would wrongly surface a *soldering kit* just because
those words appeared in its page's recommendation strips. That is exactly the
"matching too many unrelated items" problem.

``for_index(text)`` returns the subset that actually describes the item — the
title area, "About this item" bullets, the product-description / specification
blocks — and drops the rest.

Design
------
The useful and the noisy blocks are *interleaved* on a full-page screenshot
(on Amazon the real spec table sits **below** several cross-sell carousels), so
a naive "cut everything past the reviews" doesn't work. Instead we run a tiny
state machine over the lines:

  * recognised **KEEP** headers ("About this item", "Product description",
    "Product information", "Specifications", "In the box"…) switch us into a
    keep state;
  * recognised **DROP** headers (cross-sell / reviews / Q&A / footer) switch us
    into a drop state;
  * everything else inherits the current state.

Header matching is deliberately OCR-tolerant (headers often trail junk, e.g.
"Products related to this item spons0s0 Page 1 of 58"), and DROP matching is a
little greedier than KEEP matching — when in doubt we'd rather drop a noisy line
than index it.

For a **retailer page** we start dropping (the preamble is nav) and only keep
what sits under a real item section. For anything **without** recognised item
sections — a plain datasheet screenshot, a photo of a label, a receipt — there
is nothing to anchor on, so we fall back to keeping everything (minus obvious UI
noise) and simply cut the tail once a cross-sell/review header appears.

Nothing here raises; the worst case returns the lightly-cleaned input.
"""
from __future__ import annotations

import re
from typing import List, Optional

# Indexed item text is compact by nature; cap well under the raw-OCR cap so a
# pathological page can't bloat inventory.json.
_MAX_INDEX_CHARS = 8000

# --------------------------------------------------------------------------
# Section headers
# --------------------------------------------------------------------------
# KEEP: blocks that describe THIS item. Matched strictly (exact / prefix only)
# so a stray phrase in body text can't re-open a keep region inside noise.
_KEEP_HEADERS = (
    "about this item", "about this product", "item description",
    "product description", "product information", "product details",
    "product features", "features specs", "item details",
    "technical details", "technical specifications", "technical specification",
    "specifications", "specification", "in the box", "package includes",
    "package contents", "included in the box", "in the package",
    "from the manufacturer", "description",
)

# DROP: blocks about OTHER products, social proof, Q&A, media, or legal chrome.
# Matched greedily (exact / prefix / short-contained) — these are what pollute
# the index, so we err toward removing them.
_DROP_HEADERS = (
    # cross-sell / recommendations
    "customers also bought", "customers also viewed", "customers who bought",
    "customers who viewed", "customers frequently viewed",
    "frequently bought together", "more from frequently bought",
    "products related to this item", "products related", "related to this item",
    "related products", "similar item", "similar items", "similar products",
    "compare with similar", "from the brand", "brands in this category",
    "bundles with this item", "recommended for you", "inspired by your",
    "based on your recent", "best sellers", "you might also like",
    "may also like", "explore more", "buy it again", "new and used",
    "deals related", "sponsored",
    # reviews / social proof
    "customer reviews", "customer review", "top reviews", "reviews from",
    "review this product", "write a customer review", "rate this product",
    "customers say", "customer photos", "customer questions",
    "questions answers", "how customer reviews",
    # Q&A / media / search widgets
    "looking for specific info", "ask alexa", "product videos", "product video",
    "videos for this product",
    # footer / legal
    "warranty support", "return policy", "feedback",
    "would you like to tell us", "report an issue", "important information",
    "legal disclaimer", "product guides",
)

# A subset of DROP headers that reliably mark the "below the fold" tail. Used
# only by the fallback path to truncate once real content has ended.
_TAIL_HEADERS = _DROP_HEADERS

# --------------------------------------------------------------------------
# Line-level UI noise (buy-box, delivery, ratings, review meta)
# --------------------------------------------------------------------------
_UI_NOISE = (
    "add to cart", "add to list", "add to auto buy", "add to registry",
    "buy now", "add both to cart", "add all", "free delivery", "free returns",
    "free shipping", "in stock", "out of stock", "bought in past month",
    "ships from", "sold by", "price history", "best price on amazon",
    "verified purchase", "people found this helpful", "person found this helpful",
    "helpful report", "reviewed in the", "quantity", "see all reviews",
    "search this page", "click to see", "view order", "order within",
    "one time purchase", "subscribe save", "available at checkout",
    "gift options", "top reviews from", "was this review",
)
# Pure price / rating-count / bare-symbol tokens.
_PRICE_ONLY_RE = re.compile(r"^[\$£€¥]?\s?\d[\d.,]*\s?[%]?$")
_RATING_ONLY_RE = re.compile(r"^\(?\d[\d.,]*\)?$")
_VPRIME_RE = re.compile(r"^v?prime\b|\bvprime\b")

_NORM_RE = re.compile(r"[^a-z0-9]+")
_VOWEL_RE = re.compile(r"[aeiou]")


def _norm(line: str) -> str:
    """Lower-case, keep only alnum+space, collapse runs — the header/match form."""
    return _NORM_RE.sub(" ", (line or "").lower()).strip()


def _match_header(norm: str, markers, *, greedy: bool) -> Optional[str]:
    """Return the marker this line acts as a header for, else None.

    exact or prefix always count. ``greedy`` also allows a multi-word marker
    found anywhere in a short line (headers sometimes trail OCR junk). Single
    word markers only ever match a very short line so ordinary prose can't trip
    them.
    """
    if not norm:
        return None
    words = norm.split()
    nw = len(words)
    for m in markers:
        mw = m.count(" ") + 1
        if norm == m:
            return m
        if norm.startswith(m) and (mw >= 2 or nw <= 4):
            return m
        if greedy and mw >= 2 and m in norm and nw <= mw + 4:
            return m
    return None


def _wordish(tok: str) -> bool:
    """A token that carries real information (a word, a number, a measurement)."""
    if tok.isdigit():
        return True
    if any(c.isdigit() for c in tok) and any(c.isalpha() for c in tok):
        return True  # 60w, 120v, 900m, 0.8mm, 200c …
    if len(tok) >= 3 and _VOWEL_RE.search(tok):
        return True
    return tok in ("a", "i")


def _symbol_density(s: str) -> float:
    s = s.strip()
    if not s:
        return 1.0
    sym = sum(1 for c in s if not (c.isalnum() or c.isspace()))
    return sym / len(s)


def _is_ui_noise(norm: str) -> bool:
    if not norm:
        return True
    if _PRICE_ONLY_RE.match(norm) or _RATING_ONLY_RE.match(norm) or _VPRIME_RE.search(norm):
        return True
    return any(p in norm for p in _UI_NOISE)


def _strong(tok: str) -> bool:
    """A token that pins a line as real text: a plausible word or a measurement."""
    if len(tok) >= 4 and tok.isalpha() and _VOWEL_RE.search(tok):
        return True
    digits = sum(c.isdigit() for c in tok)
    if digits >= 2 and any(c.isalpha() for c in tok):
        return True   # 60w, 200c, 900m, 6.5mm …
    return digits >= 3   # 1202, 5300 …


def _is_content(raw: str, norm: str) -> bool:
    """A line worth indexing: enough real words, not UI chrome, not OCR soup.

    The junk this rejects is OCR of A+ product-image graphics ("3c ce) .",
    "OBooVoeZooBoo", "<< Sar ool") — harmless for search but ugly in the display
    column. The tests here are deliberately conservative so real short lines
    (a spec value, "Red & Black", a lone acronym in a richer line) survive.
    """
    if len(norm) < 3:
        return False
    if _is_ui_noise(norm):
        return False
    if _symbol_density(raw) > 0.5:
        return False
    toks = norm.split()
    if not toks:
        return False
    wordish = sum(1 for t in toks if _wordish(t))
    if (wordish / len(toks)) < 0.34:
        return False
    # A single very long spaceless alpha token is graphic OCR, never real prose.
    if len(toks) == 1 and toks[0].isalpha() and len(toks[0]) >= 12:
        return False
    # A run of only tiny tokens with nothing solid in it ("3c ce", "rah cee oos")
    # is garbled graphics; a real line carries at least one strong token.
    if max(len(t) for t in toks) <= 3 and not any(_strong(t) for t in toks):
        return False
    return True


def _run(lines: List[str], *, initial_keep: bool):
    """State machine over lines. Returns (kept_lines, n_keep_headers_seen)."""
    kept: List[str] = []
    keeping = initial_keep
    n_keep = 0
    for raw in lines:
        norm = _norm(raw)
        if not norm:
            continue
        if _match_header(norm, _KEEP_HEADERS, greedy=False):
            keeping = True
            n_keep += 1
            continue  # skip the header label itself
        if _match_header(norm, _DROP_HEADERS, greedy=True):
            keeping = False
            continue
        if keeping and _is_content(raw, norm):
            kept.append(re.sub(r"[ \t]+", " ", raw.strip()))
    return kept, n_keep


def _dedupe(lines: List[str]) -> List[str]:
    """Drop repeats (carousels echo a product name many times), case-insensitive."""
    out: List[str] = []
    seen = set()
    for ln in lines:
        key = _norm(ln)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(ln)
    return out


def _cap(text: str) -> str:
    text = (text or "").strip()
    if len(text) > _MAX_INDEX_CHARS:
        cut = text.rfind(" ", 0, _MAX_INDEX_CHARS)
        text = text[: cut if cut != -1 else _MAX_INDEX_CHARS].rstrip()
    return text


def for_index(text: str) -> str:
    """The item-relevant subset of scanned text, for the search index / display.

    Primary pass drops the (navigation) preamble and keeps only recognised item
    sections. If that recognised nothing — or almost nothing — we fall back to
    keeping the page top down to the first cross-sell/review header, which is the
    right behaviour for plain screenshots, labels and receipts that have no
    section structure to anchor on. Never raises.
    """
    if not text or not text.strip():
        return ""
    try:
        lines = text.splitlines()
        # Primary: retailer-page mode — preamble is nav, so start dropping.
        kept, n_keep = _run(lines, initial_keep=False)
        primary = _cap("\n".join(_dedupe(kept)))
        if n_keep >= 1 and len(primary) >= 40:
            return primary
        # Fallback: no real item section found. Keep from the top, cut the tail
        # at the first cross-sell/review header, strip obvious UI noise.
        kept, _ = _run(lines, initial_keep=True)
        fallback = _cap("\n".join(_dedupe(kept)))
        return fallback or primary
    except Exception:
        # Worst case: never lose everything — hand back the lightly cleaned input.
        return _cap(text)


# Backwards-friendly alias.
item_relevant = for_index
