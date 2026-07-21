"""Keep only the item-relevant part of scanned/attached text for the search index.

Why this exists
---------------
Auto-OCR happily reads a *whole* screenshot. When that screenshot is a retailer
product page (the common case here — a saved Amazon/eBay/Walmart listing), the
raw text is mostly stuff that has nothing to do with the item you saved:

  * site navigation ("Prime Video · Kindle Books · Whole Foods …")
  * the buy-box / delivery chrome ("Add to cart", "FREE delivery", prices)
  * cross-sell carousels — *other* products ("Customers also bought",
    "Products related to this item", eBay's "People who viewed this item also
    viewed", even a completely unrelated sponsored "Tree Pruner")
  * the whole review section ("Customers say", "Reviewed in the United States…")
  * footer / legal boilerplate (return policy, feedback, warranty blurbs)

If all of that lands in ``ocr_text`` it pollutes the search index: searching
"multimeter" or "pruner" would wrongly surface a *soldering kit* just because
those words appeared in its page's recommendation strips. That is exactly the
"matching too many unrelated items" problem.

``for_index(text)`` returns the subset that actually describes the item — the
"About this item" bullets, the product-description / specification blocks, an
eBay "Item specifics" table — and drops the rest.

Design
------
The useful and the noisy blocks are *interleaved* on a full-page screenshot
(on Amazon the real spec table sits **below** several cross-sell carousels), so
a naive "cut everything past the reviews" doesn't work. Instead we run a tiny
state machine over the lines:

  * recognised **KEEP** headers ("About this item", "Product description",
    "Product information", "Specifications", "Item specifics", "In the box"…)
    switch us into a keep state;
  * recognised **DROP** headers (cross-sell / reviews / Q&A / footer) switch us
    into a drop state;
  * everything else inherits the current state.

Header matching is OCR-tolerant but strict about *where* the marker sits (exact
line, or the marker as a line *prefix* — headers often trail junk like
"Products related to this item  Page 1 of 58"). It deliberately does NOT fire on
a marker merely *contained* in a longer line, so ordinary prose like "great
value from the brand" can't be mistaken for a "from the brand" header.

Two passes:

  * **Primary** (retailer mode): start dropping — the preamble is nav/ads — and
    keep only what sits under a real item section. Chosen when at least one KEEP
    section was recognised.
  * **Fallback** (everything else — a plain datasheet, a photo of a label, a
    receipt, a page whose section header the OCR garbled): keep from the top,
    skipping obvious UI noise. A lone cross-sell/"Sponsored" label here only
    *skips that line* — it must not wipe the item's own specs. Only a genuine
    **terminal** header (the review section, the footer, a real "customers also
    bought" block) ends keeping, and only once real content has been captured,
    so a screenshot whose first OCR line happens to be "Sponsored" or "IMPORTANT
    INFORMATION" is never reduced to nothing.

Known limitation: the primary pass discards the pre-section preamble, which on a
retailer page holds the product *title* — but also the site nav and top-of-page
competitor ads sitting right beside it. Keeping it would re-leak other products
into the index, so the title is intentionally left to the item's own ``name`` /
``source_title`` fields (already indexed separately) rather than recovered here.

Nothing here raises; the worst case returns the lightly-cleaned input.
"""
from __future__ import annotations

import re
import unicodedata
from typing import List, Optional, Tuple

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
    "product features", "features specs", "item details", "item specifics",
    "technical details", "technical specifications", "technical specification",
    "specifications", "specification", "in the box", "package includes",
    "package contents", "included in the box", "in the package",
    "from the manufacturer", "description",
)

# Cross-sell / recommendation carousels — OTHER products.
_DROP_CROSS_SELL = (
    "customers also bought", "customers also viewed", "customers who bought",
    "customers who viewed", "customers frequently viewed",
    "frequently bought together", "more from frequently bought",
    "products related to this item", "products related", "related to this item",
    "related products", "people who viewed", "who viewed this item",
    "from the brand", "brands in this category", "you may also like",
    "may also like", "more to love", "related searches", "popular items",
)
# Weaker "shelf" labels that can appear as a stray heading ABOVE the item's own
# content too, so they must not end an unstructured page (fallback) — only mark
# a drop region inside a structured one (primary).
_DROP_SHELF = (
    "similar item", "similar items", "similar products", "compare with similar",
    "compare similar", "bundles with this item", "recommended for you",
    "inspired by your", "based on your", "best sellers", "explore more",
    "buy it again", "new and used", "deals related", "sponsored",
)
# Reviews / social proof.
_DROP_REVIEWS = (
    "customer reviews", "customer review", "customer ratings",
    "ratings and reviews", "ratings reviews", "top reviews", "reviews from",
    "review this product", "write a customer review", "rate this product",
    "customers say", "customer photos", "customer questions",
    "questions answers", "how customer reviews", "seller feedback",
    "about this seller", "shop with confidence",
)
# Q&A / media / search widgets (not end-of-item, but never item text either).
_DROP_WIDGETS = (
    "looking for specific info", "ask alexa", "product videos", "product video",
    "videos for this product",
)
# Footer / legal.
_DROP_FOOTER = (
    "warranty support", "return policy", "feedback", "would you like to tell us",
    "report an issue", "important information", "legal disclaimer",
    "product guides",
)

_DROP_HEADERS = (_DROP_CROSS_SELL + _DROP_SHELF + _DROP_REVIEWS
                 + _DROP_WIDGETS + _DROP_FOOTER)

# Terminal headers reliably mark "the item's own content has ended". Used by the
# fallback path to truncate the tail. The weak shelf labels are excluded — they
# can sit above real content on an unstructured page.
_TERMINAL_HEADERS = (_DROP_CROSS_SELL + _DROP_REVIEWS + _DROP_FOOTER)

# --------------------------------------------------------------------------
# Line-level UI noise (buy-box, delivery, ratings, review meta) + site nav
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
    "gift options", "top reviews from", "was this review", "last purchased",
    "best price", "would have saved", "create a free account",
)
# Site chrome that appears in the pre-section preamble; used to reject nav lines
# so they never reach the index (a title's own words never contain these).
_NAV_PHRASES = (
    "prime video", "kindle", "whole foods", "best sellers", "bestsellers",
    "gift cards", "gift ideas", "todays deals", "deals and savings",
    "customer service", "deliver to", "browsing history", "new releases",
    "video games", "medical care", "amazon basics", "your account", "sign in",
    "departments", "same day delivery", "buy again", "keep shopping for",
    "shop by room", "launchpad", "add to cart",
)
# Pure price / rating-count / bare-symbol tokens.
_PRICE_ONLY_RE = re.compile(r"^[\$£€¥]?\s?\d[\d.,]*\s?[%]?$")
_RATING_ONLY_RE = re.compile(r"^\(?\d[\d.,]*\)?$")
_VPRIME_RE = re.compile(r"^v?prime\b|\bvprime\b")
_BREADCRUMB_CHARS = (">", "»", "›", "|")

_NORM_RE = re.compile(r"[^a-z0-9]+")
_VOWEL_RE = re.compile(r"[aeiou]")


def _norm(line: str) -> str:
    """Lower-case, fold accents, keep only alnum+space — the header/match form.

    Accents are folded to ASCII (``Réglé`` -> ``regle``) and apostrophes are
    dropped rather than split (``l'usine`` -> ``lusine``) so accented/possessive
    words stay whole words instead of shattering into sub-3-char fragments that
    would later be mistaken for OCR soup. NFKD also unpacks ligatures (``ﬁ`` ->
    ``fi``), which helps some garbled headers.
    """
    s = unicodedata.normalize("NFKD", (line or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("'", "").replace("’", "")
    return _NORM_RE.sub(" ", s).strip()


def _match_header(norm: str, markers) -> Optional[str]:
    """Return the marker this line acts as a header for, else None.

    Only an exact line or a marker at the line *start* counts — headers often
    trail OCR junk ("Products related to this item  Page 1 of 58"), but a marker
    merely embedded in prose must not fire (so "great value from the brand" is
    not read as a "from the brand" header). Single-word markers additionally
    require a very short line so ordinary text can't trip them.
    """
    if not norm:
        return None
    nw = norm.count(" ") + 1
    for m in markers:
        mw = m.count(" ") + 1
        if norm == m:
            return m
        if norm.startswith(m) and (mw >= 2 or nw <= 4):
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


def _strong(tok: str) -> bool:
    """A token that pins a line as real text: a plausible word or a measurement."""
    if len(tok) >= 4 and tok.isalpha() and _VOWEL_RE.search(tok):
        return True
    digits = sum(c.isdigit() for c in tok)
    if digits >= 2 and any(c.isalpha() for c in tok):
        return True   # 60w, 200c, 900m, 6.5mm …
    return digits >= 3   # 1202, 5300 …


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


def _is_nav(raw: str, norm: str) -> bool:
    """Site navigation / breadcrumb chrome — never the item's own text."""
    if any(p in norm for p in _NAV_PHRASES):
        return True
    return sum(raw.count(c) for c in _BREADCRUMB_CHARS) >= 2


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


def _clean_line(raw: str) -> str:
    return re.sub(r"[ \t]+", " ", raw.strip())


def _run_primary(lines: List[str]) -> Tuple[List[str], int]:
    """Retailer mode: drop the preamble, keep only recognised item sections."""
    kept: List[str] = []
    keeping = False
    n_keep = 0
    for raw in lines:
        norm = _norm(raw)
        if not norm:
            continue
        if _match_header(norm, _KEEP_HEADERS):
            keeping = True
            n_keep += 1
            continue  # skip the header label itself
        if _match_header(norm, _DROP_HEADERS):
            keeping = False
            continue
        if keeping and _is_content(raw, norm):
            kept.append(_clean_line(raw))
    return kept, n_keep


def _run_fallback(lines: List[str]) -> List[str]:
    """Unstructured mode: keep from the top, skipping UI noise and section
    labels, and stop only at a genuine terminal header once we've kept content.

    A lone cross-sell / "Sponsored" label here just skips its own line — it must
    not wipe the item's specs — which is what keeps a screenshot whose first line
    is "Sponsored" or "IMPORTANT INFORMATION" from being reduced to nothing.
    """
    kept: List[str] = []
    for raw in lines:
        norm = _norm(raw)
        if not norm:
            continue
        if kept and _match_header(norm, _TERMINAL_HEADERS):
            break  # the item's content has ended; the tail is noise
        if _match_header(norm, _KEEP_HEADERS) or _match_header(norm, _DROP_HEADERS):
            continue  # skip a section label, but keep scanning for real content
        if _is_nav(raw, norm):
            continue
        if _is_content(raw, norm):
            kept.append(_clean_line(raw))
    return kept


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

    Primary (retailer) pass keeps only recognised item sections; if it found at
    least one and produced real content, that wins. Otherwise the fallback keeps
    the page from the top (minus UI noise) down to the first terminal header —
    right for plain screenshots, labels and receipts with no section structure.
    As a final guard it never returns empty when the input held real content.
    Never raises.
    """
    if not text or not text.strip():
        return ""
    try:
        lines = text.splitlines()
        kept, n_keep = _run_primary(lines)
        primary = _cap("\n".join(_dedupe(kept)))
        if n_keep >= 1 and len(primary) >= 40:
            return primary
        fallback = _cap("\n".join(_dedupe(_run_fallback(lines))))
        if fallback:
            return fallback
        if primary:
            return primary
        # Last resort: keep every real content line so a page that is *all*
        # drop-headers-plus-content (e.g. leads with "Sponsored") is never
        # zeroed out. UI noise / nav are still stripped.
        salvage = [_clean_line(l) for l in lines
                   if (n := _norm(l)) and not _is_nav(l, n) and _is_content(l, n)]
        return _cap("\n".join(_dedupe(salvage)))
    except Exception:
        # Worst case: never lose everything — hand back the lightly cleaned input.
        return _cap(text)


# Backwards-friendly alias.
item_relevant = for_index
