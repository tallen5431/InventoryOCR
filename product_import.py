"""
Pull product details from a retailer page — by URL or from pasted/saved HTML.

Visual search usually lands you on an Amazon / retailer product page. Amazon and
many large sites block automated fetches, so this module accepts two inputs:

  * a URL   — fetched server-side with a browser-like User-Agent. Works for many
              sites; big stores (esp. Amazon) often block it.
  * raw HTML — paste the page source or upload the saved .html file. Always works
              because your browser already fetched the page.

From either input it reads the structured data virtually all e-commerce pages
embed, so no brittle scraping of visible text is needed:

  * JSON-LD  <script type="application/ld+json"> with @type "Product"
  * Open Graph / Twitter card <meta> tags
  * <title> as a last resort

Output is shaped like the vision "Identify" result (``{"ok", "data": {...}}``) so
the existing Apply-to-item flow consumes it directly.

Stdlib only (html.parser + urllib + json). No new dependencies.
"""
from __future__ import annotations
import os
import re
import json
import socket
import ipaddress
import urllib.request
import urllib.error
from html.parser import HTMLParser
from urllib.parse import urlparse
from typing import Dict, Any, List, Optional, Tuple

_CURRENCY = {"USD": "$", "CAD": "$", "AUD": "$", "GBP": "£", "EUR": "€", "JPY": "¥", "INR": "₹"}

# BeautifulSoup unlocks richer extraction (spec tables, Amazon detail bullets).
# Optional — without it we still parse JSON-LD / Open Graph via the stdlib path.
try:
    from bs4 import BeautifulSoup  # type: ignore
    _HAS_BS4 = True
except Exception:
    _HAS_BS4 = False

# Spec rows whose key mentions any of these are noise, not helpful specs.
_SPEC_NOISE = (
    "customer review", "best sellers rank", "date first available", "warranty & support",
    "feedback", "lower price", "shipping", "return policy", "questions", "would you like",
    "report incorrect", "new & used", "video", "compare with", "manufacturer contact",
    "legal disclaimer", "warranty description", "from the manufacturer", "add to cart",
    "in stock", "availability", "sold by", "ships from",
)
_DIM_HINT = "dimension"
_ZW = "‎‏​﻿"  # invisible marks Amazon sprinkles into detail bullets

# Placeholder "values" that carry no real info (eBay's Brand field, etc.).
_PLACEHOLDER_VALUES = {
    "does not apply", "does not apply.", "doesn't apply", "n/a", "na", "none",
    "unbranded", "unspecified", "not applicable", "not specified", "-", "--", "—",
    "see description", "see photos", "no", "unknown",
}


def _is_placeholder(v: str) -> bool:
    return (v or "").strip().lower() in _PLACEHOLDER_VALUES


def _clean_price_text(s: str) -> str:
    """Normalise retailer price text, e.g. 'US $11.99' -> '$11.99', 'AU $5' -> '$5'."""
    s = re.sub(r"\s+", " ", (s or "").strip())
    # drop a leading country/locale code before the currency symbol
    s = re.sub(r"^[A-Za-z]{1,3}\s*(?=[$£€¥₹])", "", s)
    # keep just the first price-looking token if there's trailing junk
    m = re.search(r"[$£€¥₹]\s?\d[\d,]*(?:\.\d+)?", s)
    return m.group(0).replace(" ", "") if m else s


def _fmt_price(value: Any, currency: str = "") -> str:
    if value in (None, ""):
        return ""
    v = str(value).strip()
    if not v:
        return ""
    if v[0] in "$£€¥₹":
        return v
    sym = _CURRENCY.get((currency or "").upper(), "")
    if sym:
        return f"{sym}{v}"
    return f"{v} {currency.upper()}".strip() if currency else v


def _clean_text(s: str, limit: int = 600) -> str:
    s = re.sub(r"\s+", " ", (s or "").strip())
    if len(s) > limit:
        cut = s.rfind(" ", 0, limit)
        s = s[: (cut if cut > 0 else limit)].rstrip() + "…"
    return s


# ---------------------------------------------------------------------------
# HTML parsing (stdlib)
# ---------------------------------------------------------------------------

class _Extractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.jsonld: List[str] = []
        self.metas: List[Dict[str, str]] = []
        self.title = ""
        self._in_ld = False
        self._in_title = False
        self._buf: List[str] = []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self._in_ld, self._buf = True, []
        elif tag == "meta":
            self.metas.append(a)
        elif tag == "title":
            self._in_title, self._buf = True, []

    def handle_endtag(self, tag):
        if tag == "script" and self._in_ld:
            self.jsonld.append("".join(self._buf))
            self._in_ld, self._buf = False, []
        elif tag == "title" and self._in_title:
            self.title = "".join(self._buf).strip()
            self._in_title, self._buf = False, []

    def handle_data(self, data):
        if self._in_ld or self._in_title:
            self._buf.append(data)


def _iter_jsonld(blocks: List[str]):
    for raw in blocks:
        raw = (raw or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            try:  # tolerate leading/trailing junk around the object
                data = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
            except Exception:
                continue
        yield from _flatten(data)


def _flatten(data):
    if isinstance(data, list):
        for x in data:
            yield from _flatten(x)
    elif isinstance(data, dict):
        graph = data.get("@graph")
        if isinstance(graph, list):
            for x in graph:
                yield from _flatten(x)
        yield data


def _is_product(obj: Dict[str, Any]) -> bool:
    t = obj.get("@type")
    if isinstance(t, list):
        return any(str(x).lower() == "product" for x in t)
    return str(t).lower() == "product"


def _first(v):
    return v[0] if isinstance(v, list) and v else v


def _product_from_jsonld(blocks: List[str]) -> Optional[Dict[str, Any]]:
    for obj in _iter_jsonld(blocks):
        if not isinstance(obj, dict) or not _is_product(obj):
            continue

        name = obj.get("name") if isinstance(obj.get("name"), str) else ""
        desc = obj.get("description") if isinstance(obj.get("description"), str) else ""

        brand = obj.get("brand")
        if isinstance(brand, dict):
            brand = brand.get("name", "")
        brand = brand if isinstance(brand, str) else ""

        img = obj.get("image")
        if isinstance(img, dict):
            img = img.get("url", "")
        img = _first(img) if isinstance(img, list) else img
        image_url = img if isinstance(img, str) else ""

        price, currency = "", ""
        off = _first(obj.get("offers")) if isinstance(obj.get("offers"), list) else obj.get("offers")
        if isinstance(off, dict):
            price = off.get("price") or ""
            currency = off.get("priceCurrency") or ""
            if not price:
                ps = _first(off.get("priceSpecification")) if isinstance(off.get("priceSpecification"), list) else off.get("priceSpecification")
                if isinstance(ps, dict):
                    price = ps.get("price") or ""
                    currency = currency or ps.get("priceCurrency") or ""

        spec_pairs: List[tuple] = []
        for prop in (obj.get("additionalProperty") or []):
            if isinstance(prop, dict):
                nm, val = str(prop.get("name", "")).strip(), str(prop.get("value", "")).strip()
                if nm and val:
                    spec_pairs.append((nm, val))
        sku = obj.get("sku") or obj.get("mpn") or ""
        if sku:
            spec_pairs.append(("SKU", str(sku)))

        category = obj.get("category") or ""
        if isinstance(category, list):
            category = " / ".join(str(c) for c in category)
        category = category if isinstance(category, str) else ""

        return {
            "name": (name or "").strip(),
            "description": desc,
            "brand": brand.strip(),
            "image_url": image_url.strip(),
            "price": _fmt_price(price, currency),
            "spec_pairs": spec_pairs,
            "category": category,
        }
    return None


def _meta_map(metas: List[Dict[str, str]]) -> Dict[str, str]:
    m: Dict[str, str] = {}
    for a in metas:
        key = (a.get("property") or a.get("name") or "").lower()
        content = a.get("content")
        if key and content is not None and key not in m:
            m[key] = content
    return m


def _product_from_meta(metas: List[Dict[str, str]], title: str) -> Dict[str, Any]:
    m = _meta_map(metas)
    return {
        "name": (m.get("og:title") or m.get("twitter:title") or title or "").strip(),
        "description": (m.get("og:description") or m.get("twitter:description") or "").strip(),
        "brand": (m.get("og:brand") or m.get("product:brand") or "").strip(),
        "image_url": (m.get("og:image") or m.get("twitter:image") or "").strip(),
        "price": _fmt_price(
            m.get("product:price:amount") or m.get("og:price:amount") or "",
            m.get("product:price:currency") or m.get("og:price:currency") or "",
        ),
        "specifications": [],
        "category": "",
    }


def _short_category(category: str, brand: str) -> str:
    """Turn a breadcrumb path like 'Tools > Power Tools > Drills' into 'Drills'."""
    if category:
        parts = [p.strip() for p in re.split(r"[>/›»|]", category) if p.strip()]
        if parts:
            return parts[-1]
    return ""


def _clean_kv(k: str, v: str):
    trans = {ord(c): None for c in _ZW}
    k = re.sub(r"\s+", " ", (k or "").translate(trans)).strip().strip(":").strip()
    v = re.sub(r"\s+", " ", (v or "").translate(trans)).strip().strip(":").strip()
    return k, v


def _isolate_specs(pairs: List[tuple]):
    """Filter raw key/value pairs down to helpful specs, pulling out dimensions.

    Returns (specs_list_of_"Key: value"_strings, dimensions_string).
    """
    specs: List[str] = []
    dims = ""
    seen = set()
    for k, v in pairs:
        k, v = _clean_kv(k, v)
        if not k or not v or _is_placeholder(v):
            continue
        kl = k.lower()
        if len(k) > 45 or len(v) > 160:
            continue
        if any(n in kl for n in _SPEC_NOISE):
            continue
        if _DIM_HINT in kl:
            # dimensions get their own field; prefer product/item over package.
            if not dims or "product" in kl or "item" in kl:
                dims = v
            continue
        sig = (kl, v.lower())
        if sig in seen:
            continue
        seen.add(sig)
        specs.append(f"{k}: {v}")
        if len(specs) >= 15:
            break
    return specs, dims


def _enrich_with_bs4(html_text: str) -> Dict[str, Any]:
    """Pull name/price/image/brand/specs/bullets from messy retailer HTML.

    Targets common structures (spec tables, Amazon detail bullets & feature
    bullets). Returns {} if BeautifulSoup isn't available or nothing is found.
    """
    out: Dict[str, Any] = {"name": "", "price": "", "image_url": "", "brand": "",
                           "description": "", "category": "", "spec_pairs": [], "bullets": []}
    if not _HAS_BS4:
        return out
    try:
        soup = BeautifulSoup(html_text, "html.parser")
    except Exception:
        return out

    def _text(sel):
        el = soup.select_one(sel)
        return el.get_text(" ", strip=True) if el else ""

    out["name"] = (_text("#productTitle") or _text("h1#title") or _text("h1.product-title")
                   or _text("h1.x-item-title__mainTitle") or _text("h1[class*='item-title']"))

    for sel in (".a-price .a-offscreen", "#corePrice_feature_div .a-offscreen",
                "#priceblock_ourprice", "#priceblock_dealprice", "#price_inside_buybox",
                ".x-price-primary span", ".x-price-primary", "[itemprop='price']"):
        p = _text(sel)
        if p:
            out["price"] = _clean_price_text(p)
            break

    img = (soup.select_one("#landingImage") or soup.select_one("#imgBlkFront")
           or soup.select_one("img#main-image") or soup.select_one(".ux-image-carousel-item img")
           or soup.select_one("img.x-image"))
    if img:
        out["image_url"] = img.get("data-old-hires") or img.get("src") or img.get("data-src") or ""

    byline = _text("#bylineInfo")
    if byline:
        out["brand"] = re.sub(r"(?i)^\s*(brand:|visit the|store)\s*", "", byline).replace(" Store", "").strip()

    out["description"] = _text("#productDescription")

    # Category from the breadcrumb trail (Amazon or eBay).
    crumbs = [a.get_text(" ", strip=True) for a in
              soup.select("#wayfinding-breadcrumbs_feature_div a, nav.breadcrumbs a, "
                          "nav[aria-label*='readcrumb'] a")]
    if crumbs:
        out["category"] = " / ".join(c for c in crumbs if c)

    # Spec tables — prefer the known spec/detail tables, else any 2-column table.
    pairs: List[tuple] = []
    rows = soup.select(
        "#productDetails_techSpec_section_1 tr, #productDetails_techSpec_section_2 tr, "
        "#productDetails_detailBullets_sections1 tr, .prodDetTable tr, table.a-keyvalue tr, "
        "#technicalSpecifications_section_1 tr, #technical-details tr, table.product-specs tr"
    )
    if not rows:
        for table in soup.find_all("table"):
            trs = table.find_all("tr")
            kv = [tr for tr in trs if len(tr.find_all(["th", "td"])) == 2]
            if len(kv) >= 2 and len(kv) >= 0.6 * max(1, len(trs)):
                rows.extend(kv)
    for tr in rows:
        cells = tr.find_all(["th", "td"])
        if len(cells) >= 2:
            k = cells[0].get_text(" ", strip=True)
            v = cells[1].get_text(" ", strip=True)
            if k and v:
                pairs.append((k, v))

    # Amazon detail bullets: <li><span class="a-text-bold">Key</span> value</li>
    for li in soup.select("#detailBullets_feature_div li, .detail-bullet-list li"):
        bold = li.select_one(".a-text-bold, .a-list-item .a-text-bold")
        if bold:
            k = bold.get_text(" ", strip=True)
            full = li.get_text(" ", strip=True)
            v = full.replace(bold.get_text(" ", strip=True), "", 1)
            if k and v:
                pairs.append((k, v))

    # eBay item specifics: <dl class="ux-labels-values"><dt __labels><dd __values>.
    # (Shipping/returns use <div>, so selecting <dl> keeps just the real specifics.)
    for dl in soup.select("dl.ux-labels-values"):
        lab = dl.select_one(".ux-labels-values__labels")
        val = dl.select_one(".ux-labels-values__values")
        if lab and val:
            k = lab.get_text(" ", strip=True)
            v = val.get_text(" ", strip=True)
            if k and v and k != v:
                pairs.append((k, v))
                if k.lower() == "brand" and not _is_placeholder(v) and not out["brand"]:
                    out["brand"] = v

    # Generic definition lists (<dl><dt>label</dt><dd>value</dd>) used by many
    # other retailers / manufacturer spec sheets.
    for dl in soup.find_all("dl"):
        if "ux-labels-values" in " ".join(dl.get("class") or []):
            continue  # already handled above
        dts = dl.find_all("dt")
        dds = dl.find_all("dd")
        for dt, dd in zip(dts, dds):
            k = dt.get_text(" ", strip=True)
            v = dd.get_text(" ", strip=True)
            if k and v and k != v:
                pairs.append((k, v))

    out["spec_pairs"] = pairs

    # Feature bullets (concise selling points that read like specs).
    for li in soup.select("#feature-bullets li, #feature-bullets .a-list-item"):
        txt = li.get_text(" ", strip=True)
        if txt:
            out["bullets"].append(txt)

    return out


_SITE_PREFIX_RE = re.compile(
    r"^\s*(amazon(?:\.com)?|ebay|aliexpress|walmart|etsy|target|newegg)\s*[:\-–—|]\s*", re.I)
_SITE_SUFFIX_RE = re.compile(
    r"\s*[:\-–—|]\s*(amazon(?:\.com)?|ebay|aliexpress|walmart|etsy)\b.*$", re.I)


def _short_name(full: str, limit: int = 64) -> str:
    """Condense a long retailer title into a concise product name.

    Amazon/eBay titles cram the brand, every feature and the category onto one
    line. Strip the marketplace noise, cut at the first strong separator (the
    lead segment is almost always the product), then cap the length on a word
    boundary. The caller keeps the FULL title as a search tag so nothing is lost.
    """
    s = re.sub(r"\s+", " ", (full or "")).strip()
    if not s:
        return s
    s = _SITE_SUFFIX_RE.sub("", s)
    s = _SITE_PREFIX_RE.sub("", s).strip()
    # Cut at the earliest strong delimiter that leaves a meaningful lead.
    cuts = []
    for sep in (",", " - ", " – ", " — ", " : ", " | ", " (", ": ", "|"):
        i = s.find(sep)
        if i >= 12:
            cuts.append(i)
    if cuts:
        s = s[:min(cuts)]
    s = s.strip(" -–—|:,·").strip()
    if len(s) > limit:
        s = (s[:limit].rsplit(" ", 1)[0] or s[:limit]).rstrip(" -–—|:,")
    return s or re.sub(r"\s+", " ", (full or "")).strip()


def extract_from_html(html_text: str, source_url: str = "") -> Dict[str, Any]:
    """Parse product details out of a page's HTML. Returns {ok, data|error}."""
    if not html_text or not html_text.strip():
        return {"ok": False, "error": "No HTML to read."}

    ex = _Extractor()
    try:
        ex.feed(html_text)
    except Exception:
        pass  # lenient: keep whatever we parsed before a malformed chunk

    prod = _product_from_jsonld(ex.jsonld)
    meta = _product_from_meta(ex.metas, ex.title)
    enr = _enrich_with_bs4(html_text)

    def base(k: str) -> str:
        for src in (prod or {}), meta, enr:
            v = src.get(k) if isinstance(src, dict) else ""
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""

    name = base("name")
    if not name:
        return {"ok": False,
                "error": "Couldn't find product details in that page. Open the product page in "
                         "your browser, save it (Ctrl+S) or copy its source, and use “paste / "
                         "upload the page HTML”.",
                "suggest_html": True}
    # Long Amazon-style titles make an unwieldy item name; keep a concise one for
    # display and retain the full title as a search tag (added below).
    full_title = name
    name = _short_name(name)

    price = ((prod or {}).get("price") or meta.get("price") or enr.get("price") or "").strip()
    image_url = base("image_url")
    brand = base("brand")
    if _is_placeholder(brand):
        brand = ""

    # Combine specs from every source, then isolate the helpful ones + dimensions.
    pairs = list((prod or {}).get("spec_pairs", [])) + list(enr.get("spec_pairs", []))
    # Derive a brand from the specifics if we still don't have one.
    if not brand:
        for k, v in pairs:
            if k.strip().lower() == "brand" and v.strip() and not _is_placeholder(v):
                brand = v.strip()
                break
    specs, dimensions = _isolate_specs(pairs)
    # Add a few concise feature bullets if there's room — they're often the specs.
    for b in enr.get("bullets", []):
        if len(specs) >= 18:
            break
        b = re.sub(r"\s+", " ", b).strip()
        if 8 <= len(b) <= 110 and b not in specs:
            specs.append(b)

    description = _clean_text(base("description"))
    if not description and enr.get("bullets"):
        description = _clean_text(" ".join(enr["bullets"][:2]))

    category_raw = (prod or {}).get("category") or enr.get("category") or meta.get("category", "") or ""
    tags: List[str] = []
    if brand:
        tags.append(brand)
    # Only the most specific 1-2 breadcrumb segments make useful search tags —
    # not the whole "Business & Industrial > … > Toggle Switches" path.
    cat_parts = [w.strip() for w in re.split(r"[>/›»|,]", category_raw) if w.strip()]
    for w in cat_parts[-2:]:
        if w.lower() not in {t.lower() for t in tags}:
            tags.append(w)
    # Promote key identifiers (model / part number) to tags so they're easy to
    # search for later — critical for finding a specific part or material.
    _ID_KEYS = ("model", "mpn", "part number", "manufacturer part number", "model number", "model name")
    for k, v in pairs:
        kl = k.strip().lower()
        v = v.strip()
        if v and not _is_placeholder(v) and any(idk in kl for idk in _ID_KEYS):
            if len(v) <= 40 and v.lower() not in {t.lower() for t in tags}:
                tags.append(v)
    tags = tags[:10]
    # Keep the full original title searchable even though we display a short name.
    if full_title and full_title != name and full_title.lower() not in {t.lower() for t in tags}:
        tags.append(full_title)

    data = {
        "name": name,
        "category": _short_category(category_raw, brand),
        "what_it_is": description,
        "specifications": specs,
        "estimated_value": price,
        "dimensions": dimensions or "unknown",
        "tags": tags,
        "product_url": source_url,
        "confidence": "high" if (prod or dimensions or len(specs) >= 3) else "medium",
        "image_url": image_url,
    }
    via = "JSON-LD" if prod else ("Open Graph" if meta.get("name") else "page HTML")
    return {"ok": True, "data": data, "source": source_url, "price": price,
            "image_url": image_url, "brand": brand, "via": via, "spec_count": len(specs)}


# ---------------------------------------------------------------------------
# URL fetch (best-effort; blocked by some big stores)
# ---------------------------------------------------------------------------

def _is_public_host(url: str) -> bool:
    """Reject URLs that resolve to private/loopback/link-local hosts (SSRF guard)."""
    try:
        host = urlparse(url).hostname
        if not host:
            return False
        for info in socket.getaddrinfo(host, None):
            addr = ipaddress.ip_address(info[4][0])
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                return False
        return True
    except Exception:
        return False


def fetch_url(url: str, timeout: Optional[int] = None) -> Tuple[str, str]:
    """Fetch a product page. Returns (html, error)."""
    if not re.match(r"^https?://", url or "", re.I):
        return "", "Enter a full http(s):// product URL."
    if not _is_public_host(url):
        return "", "That URL points to a private/local address — only public product pages are allowed."

    timeout = int(timeout or os.getenv("PRODUCT_IMPORT_TIMEOUT", "20") or 20)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as r:
            charset = r.headers.get_content_charset() or "utf-8"
            raw = r.read(3_000_000)  # cap at ~3 MB
            return raw.decode(charset, "replace"), ""
    except urllib.error.HTTPError as e:
        if e.code in (403, 429, 503):
            return "", (f"The site blocked the fetch (HTTP {e.code}). Big stores like Amazon block "
                        "bots — open the page in your browser and use “paste HTML” instead.")
        return "", f"Fetch failed (HTTP {e.code})."
    except Exception as e:
        return "", f"Couldn't fetch the URL ({e}). Try the “paste HTML” option."


def import_product(url: str = "", html_text: str = "") -> Dict[str, Any]:
    """Top-level: extract from pasted HTML if given, else fetch the URL and extract."""
    url = (url or "").strip()
    if (html_text or "").strip():
        return extract_from_html(html_text, url)
    if url:
        page, err = fetch_url(url)
        if err:
            return {"ok": False, "error": err, "suggest_html": True}
        res = extract_from_html(page, url)
        if not res.get("ok"):
            res["suggest_html"] = True
        return res
    return {"ok": False, "error": "Paste a product URL, or the page's HTML."}
