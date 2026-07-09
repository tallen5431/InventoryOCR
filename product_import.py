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

        specs: List[str] = []
        for prop in (obj.get("additionalProperty") or []):
            if isinstance(prop, dict):
                nm, val = str(prop.get("name", "")).strip(), str(prop.get("value", "")).strip()
                if nm and val:
                    specs.append(f"{nm}: {val}")
        sku = obj.get("sku") or obj.get("mpn") or ""
        if sku:
            specs.append(f"SKU: {sku}")

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
            "specifications": specs,
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

    def pick(k):
        return ((prod or {}).get(k) or "").strip() if isinstance((prod or {}).get(k), str) else meta.get(k, "")

    name = (pick("name") or meta.get("name", "")).strip()
    if not name:
        return {"ok": False,
                "error": "Couldn't find product details in that page. Try a different product "
                         "page, or use the 'paste HTML' option with the full page source.",
                "suggest_html": True}

    price = (prod or {}).get("price") or meta.get("price", "")
    image_url = pick("image_url") or meta.get("image_url", "")
    brand = pick("brand") or meta.get("brand", "")
    description = _clean_text(pick("description") or meta.get("description", ""))
    specs = (prod or {}).get("specifications") or []
    category_raw = (prod or {}).get("category") or ""

    tags: List[str] = []
    if brand:
        tags.append(brand)
    for w in re.split(r"[>/›»|,]", category_raw):
        w = w.strip()
        if w and w.lower() not in {t.lower() for t in tags}:
            tags.append(w)

    data = {
        "name": name,
        "category": _short_category(category_raw, brand),
        "what_it_is": description,
        "specifications": specs,
        "estimated_value": price,
        "dimensions": "unknown",
        "tags": tags,
        "product_url": source_url,
        "confidence": "high" if prod else "medium",
        "image_url": image_url,
    }
    return {"ok": True, "data": data, "source": source_url, "price": price,
            "image_url": image_url, "brand": brand,
            "via": "JSON-LD" if prod else "Open Graph"}


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
