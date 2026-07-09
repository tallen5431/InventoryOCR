"""
Web lookup helpers for identifying inventory items with the browser.

Local vision models are handy but often miss exact products. The browser's
"Search image with Google Lens" reverse-image lookup is far more accurate, so
this module builds the URLs the UI needs:

  * A **Google text search** for the item's name/specs — always works on any
    network (it opens in the user's browser, not from the server).
  * A **Google Lens by-image** search — only useful when the item's photo is
    reachable from Google's servers, i.e. the app is exposed on a public URL.
    We detect that from configuration and only surface the Lens button when it
    can actually return results.

Configuration (environment variables):
  PUBLIC_BASE            Public base URL of this app, e.g. https://host.example.com
                         (may include a path). Highest priority.
  TAILSCALE_FUNNEL_BASE  Public Tailscale Funnel base, e.g.
                         https://my-host.my-tailnet.ts.net  (optionally :8443).
"""
from __future__ import annotations
import os
from urllib.parse import quote, quote_plus


# URL prefix this app is mounted under (mirrors app.py / utils.py logic) so the
# public image URL we hand to Google matches the route that actually serves it.
_URL_PREFIX = os.getenv("URL_PREFIX", "/inventory").strip().rstrip("/")
if _URL_PREFIX and not _URL_PREFIX.startswith("/"):
    _URL_PREFIX = "/" + _URL_PREFIX


def public_base() -> str:
    """Return the configured public base URL (no trailing slash), or ""."""
    for var in ("PUBLIC_BASE", "TAILSCALE_FUNNEL_BASE"):
        val = (os.getenv(var) or "").strip().rstrip("/")
        if val:
            return val
    return ""


def public_image_url(filename: str | None) -> str:
    """Build a publicly reachable URL for a stored image, or "" if we can't.

    Google Lens can only fetch the photo when the app is exposed publicly, so
    this returns "" unless a public base is configured — the UI uses that to
    decide whether to show the Lens-by-image button.
    """
    base = public_base()
    if not base or not filename:
        return ""
    fname = str(filename).lstrip("/")
    # Matches the Flask route in app.py: <prefix>/assets/images/<file>
    return f"{base}{_URL_PREFIX}/assets/images/{quote(fname)}"


def google_lens_url(image_url: str) -> str:
    """Google Lens reverse-image-search URL for a *public* image URL."""
    if not image_url:
        return ""
    return f"https://lens.google.com/uploadbyurl?url={quote_plus(image_url)}"


def google_text_url(query: str) -> str:
    """Plain Google search URL for a text query (always usable)."""
    q = (query or "").strip()
    if not q:
        return ""
    return f"https://www.google.com/search?q={quote_plus(q)}"


def google_shopping_url(query: str) -> str:
    """Google Shopping search URL — good for prices/product listings."""
    q = (query or "").strip()
    if not q:
        return ""
    return f"https://www.google.com/search?tbm=shop&q={quote_plus(q)}"


def build_query(*parts: str) -> str:
    """Join non-empty query fragments (name, brand, specs) into one string."""
    seen: list[str] = []
    for p in parts:
        t = (p or "").strip()
        if t and t.lower() not in {s.lower() for s in seen}:
            seen.append(t)
    return " ".join(seen)


def links_for(name: str = "", specs=None, filename: str | None = None) -> dict:
    """Convenience bundle of the search links the UI needs for one item.

    Returns keys: ``text``, ``shopping``, ``lens`` (each a URL or ""),
    plus ``lens_available`` and ``image_url``.
    """
    spec_bits = []
    if isinstance(specs, (list, tuple)):
        spec_bits = [str(s) for s in specs][:3]
    elif isinstance(specs, str):
        spec_bits = [specs]
    query = build_query(name, *spec_bits)
    img_url = public_image_url(filename)
    return {
        "query": query,
        "text": google_text_url(query),
        "shopping": google_shopping_url(query),
        "image_url": img_url,
        "lens": google_lens_url(img_url) if img_url else "",
        "lens_available": bool(img_url),
    }
