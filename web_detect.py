"""
Automatic web lookup for inventory items — pluggable, free-tier friendly.

Local vision models describe an item well but often miss the *exact* product.
This module adds an automatic web lookup during Identify so it can return the
real product name, keyword tags, source links, and a real price — no manual
searching or copy-paste.

It supports several back-ends so you can pick a **free** one:

  serpapi         SerpApi (https://serpapi.com) — free tier is 100 searches/mo
                  with NO credit card. Does Google Lens reverse-image (when the
                  photo is reachable on a public URL) and Google search, and
                  returns real prices. Recommended free option.
  google_vision   Google Cloud Vision "Web Detection". Free tier is 1000/mo but
                  requires enabling billing (a card). Accepts image bytes, so it
                  works on a private LAN with no public URL.
  none            Fully local — nothing is sent anywhere (default).

Provider selection (env ``WEB_DETECT_PROVIDER``):
  auto (default)  Use serpapi if SERPAPI_KEY is set, else google_vision if
                  GOOGLE_VISION_API_KEY is set, else none.
  serpapi | google_vision | none   Force a specific provider.

Privacy / opt-in: with no key configured the app stays fully local. A request
only goes out when the user presses Identify AND a provider is configured.

Other env:
  SERPAPI_KEY             SerpApi API key (free tier, no card).
  GOOGLE_VISION_API_KEY   Google Cloud Vision key (free tier needs billing on).
  WEB_DETECT_TIMEOUT      Request timeout, seconds. Default 30.
  WEB_DETECT_MAX_RESULTS  Max entities / pages to keep. Default 8.

No extra dependencies: stdlib urllib + Pillow (already used elsewhere).
"""
from __future__ import annotations
import os
import io
import json
import base64
import urllib.request
import urllib.parse
import urllib.error
from typing import Dict, Any, List, Union, Optional

from PIL import Image, ImageOps

_DEFAULT_VISION_ENDPOINT = "https://vision.googleapis.com/v1/images:annotate"
_DEFAULT_SERPAPI_ENDPOINT = "https://serpapi.com/search.json"

_PROVIDER_LABELS = {"serpapi": "SerpApi", "google_vision": "Google Vision"}


def _env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return v if v not in (None, "") else default


def active_provider() -> str:
    """Resolve which back-end to use from WEB_DETECT_PROVIDER + which keys exist."""
    choice = _env("WEB_DETECT_PROVIDER", "auto").strip().lower()
    if choice in ("serpapi", "google_vision", "none"):
        return choice
    # auto: prefer the no-card free option, then vision, else off.
    if _env("SERPAPI_KEY"):
        return "serpapi"
    if _env("GOOGLE_VISION_API_KEY"):
        return "google_vision"
    return "none"


def is_configured() -> bool:
    """True when a usable provider (with its key) is selected."""
    p = active_provider()
    if p == "serpapi":
        return bool(_env("SERPAPI_KEY"))
    if p == "google_vision":
        return bool(_env("GOOGLE_VISION_API_KEY"))
    return False


def provider_name() -> str:
    return _PROVIDER_LABELS.get(active_provider(), "")


def _timeout() -> int:
    return int(_env("WEB_DETECT_TIMEOUT", "30") or 30)


def _max_results() -> int:
    return int(_env("WEB_DETECT_MAX_RESULTS", "8") or 8)


def _opener():
    # Reach the provider directly, bypassing any ambient HTTP proxy.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


# ---------------------------------------------------------------------------
# Image helpers (shared)
# ---------------------------------------------------------------------------

def _to_bytes(image: Union[bytes, bytearray, str]) -> bytes:
    """Accept raw bytes or a data URL / base64 string and return bytes."""
    if isinstance(image, (bytes, bytearray)):
        return bytes(image)
    if isinstance(image, str):
        s = image
        if "," in s and s.strip().lower().startswith("data:"):
            s = s.split(",", 1)[1]
        return base64.b64decode(s)
    raise TypeError(f"Unsupported image type: {type(image)}")


def _downscale_to_b64(image_bytes: bytes, max_side: int = 1024, quality: int = 85) -> str:
    """Downscale (web detection doesn't need full-res) and return base64 JPEG."""
    img = Image.open(io.BytesIO(image_bytes))
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _dedupe(seq: List[str], limit: int) -> List[str]:
    out: List[str] = []
    for s in seq:
        s = (s or "").strip()
        if s and s.lower() not in {x.lower() for x in out}:
            out.append(s)
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def detect_web(
    image: Union[bytes, bytearray, str, None] = None,
    *,
    query: str = "",
    image_url: str = "",
) -> Dict[str, Any]:
    """Run the configured web-lookup provider.

    ``image``      raw bytes / data URL — used by google_vision.
    ``query``      the local model's best guess — used by serpapi text search.
    ``image_url``  a *public* URL to the photo — lets serpapi use Google Lens.

    Returns on success:
      {"ok": True, "provider": ..., "best_guess": str, "entities": [str],
       "pages": [{"title","url"}], "price": str}
    On failure: {"ok": False, "provider": ..., "error": str}
    When unconfigured: {"ok": False, "configured": False}
    """
    provider = active_provider()
    if provider == "none":
        return {"ok": False, "configured": False}
    if provider == "serpapi":
        return _detect_serpapi(query=query, image_url=image_url)
    if provider == "google_vision":
        return _detect_google_vision(image)
    return {"ok": False, "configured": False}


# ---------------------------------------------------------------------------
# Provider: SerpApi (free tier, no card)
# ---------------------------------------------------------------------------

def _serpapi_endpoint() -> str:
    return _env("WEB_DETECT_ENDPOINT", _DEFAULT_SERPAPI_ENDPOINT)


def _detect_serpapi(*, query: str = "", image_url: str = "") -> Dict[str, Any]:
    key = _env("SERPAPI_KEY")
    if not key:
        return {"ok": False, "configured": False}

    # Prefer Google Lens (reverse image) when the photo is publicly reachable;
    # otherwise fall back to a Google search grounded on the local model's guess.
    if image_url:
        params = {"engine": "google_lens", "url": image_url, "api_key": key}
        mode = "lens"
    else:
        q = (query or "").strip()
        if not q:
            return {"ok": False, "provider": "SerpApi",
                    "error": "No public image URL and no query to search."}
        params = {"engine": "google", "q": q, "api_key": key}
        mode = "search"

    url = f"{_serpapi_endpoint()}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, method="GET")
    try:
        with _opener().open(req, timeout=_timeout()) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        hint = ""
        if e.code in (401, 403):
            hint = " — check SERPAPI_KEY."
        elif e.code == 429:
            hint = " — SerpApi rate/quota limit reached (free tier is 100/month)."
        return {"ok": False, "provider": "SerpApi",
                "error": f"SerpApi returned HTTP {e.code}.{hint} {body}".strip()}
    except Exception as e:
        return {"ok": False, "provider": "SerpApi", "error": f"Could not reach SerpApi ({e})."}

    try:
        data = json.loads(raw)
    except Exception as e:
        return {"ok": False, "provider": "SerpApi", "error": f"Bad response: {e}"}

    if isinstance(data, dict) and data.get("error"):
        return {"ok": False, "provider": "SerpApi", "error": f"SerpApi: {data['error']}"}

    parsed = _parse_serpapi_lens(data) if mode == "lens" else _parse_serpapi_search(data)
    parsed.update({"ok": True, "provider": "SerpApi"})
    return parsed


def _price_str(price: Any) -> str:
    """Normalise a SerpApi price (str or {value/extracted_value/currency}) to text."""
    if isinstance(price, str):
        return price.strip()
    if isinstance(price, dict):
        v = price.get("value")
        if isinstance(v, str) and v.strip():
            return v.strip()
        ev = price.get("extracted_value")
        cur = price.get("currency") or "$"
        if ev is not None:
            return f"{cur}{ev}"
    return ""


def _parse_serpapi_lens(data: Dict[str, Any]) -> Dict[str, Any]:
    matches = data.get("visual_matches") or []
    best_guess = ""
    # SerpApi sometimes returns a knowledge graph title for the image.
    kg = data.get("knowledge_graph") or []
    if isinstance(kg, list) and kg:
        best_guess = (kg[0].get("title") or "").strip()
    if not best_guess and matches:
        best_guess = (matches[0].get("title") or "").strip()

    pages, entities, price = [], [], ""
    for m in matches[: _max_results()]:
        title = (m.get("title") or "").strip()
        link = (m.get("link") or "").strip()
        if title and link:
            pages.append({"title": title, "url": link})
        if not price:
            price = _price_str(m.get("price"))
        src = (m.get("source") or "").strip()
        if src:
            entities.append(src)
    entities = _dedupe(entities, _max_results())
    return {"best_guess": best_guess, "entities": entities, "pages": pages, "price": price}


def _parse_serpapi_search(data: Dict[str, Any]) -> Dict[str, Any]:
    best_guess, price = "", ""
    entities: List[str] = []
    pages: List[Dict[str, str]] = []

    kg = data.get("knowledge_graph") or {}
    if isinstance(kg, dict):
        best_guess = (kg.get("title") or "").strip()
        t = (kg.get("type") or "").strip()
        if t:
            entities.append(t)

    shopping = data.get("shopping_results") or []
    for s in shopping[: _max_results()]:
        title = (s.get("title") or "").strip()
        link = (s.get("link") or s.get("product_link") or "").strip()
        if title and link:
            pages.append({"title": title, "url": link})
        if not price:
            price = _price_str(s.get("price"))
        if not best_guess and title:
            best_guess = title

    organic = data.get("organic_results") or []
    for o in organic[: _max_results()]:
        title = (o.get("title") or "").strip()
        link = (o.get("link") or "").strip()
        if title and link:
            pages.append({"title": title, "url": link})
        if not best_guess and title:
            best_guess = title

    for r in (data.get("related_searches") or []):
        q = (r.get("query") or "").strip()
        if q:
            entities.append(q)

    entities = _dedupe(entities, _max_results())
    pages = pages[: _max_results()]
    return {"best_guess": best_guess, "entities": entities, "pages": pages, "price": price}


# ---------------------------------------------------------------------------
# Provider: Google Cloud Vision — Web Detection (free tier needs billing)
# ---------------------------------------------------------------------------

def _vision_endpoint() -> str:
    return _env("WEB_DETECT_ENDPOINT", _DEFAULT_VISION_ENDPOINT)


def _parse_web_detection(wd: Dict[str, Any], max_results: int) -> Dict[str, Any]:
    best = [(g.get("label") or "").strip() for g in (wd.get("bestGuessLabels") or []) if (g.get("label") or "").strip()]
    entities = _dedupe([(e.get("description") or "") for e in (wd.get("webEntities") or [])], max_results)
    pages = []
    for p in (wd.get("pagesWithMatchingImages") or []):
        u = (p.get("url") or "").strip()
        if not u:
            continue
        title = (p.get("pageTitle") or "").strip()
        pages.append({"title": title or u, "url": u})
        if len(pages) >= max_results:
            break
    return {"best_guess": best[0] if best else "", "entities": entities, "pages": pages, "price": ""}


def _detect_google_vision(image: Union[bytes, bytearray, str, None]) -> Dict[str, Any]:
    key = _env("GOOGLE_VISION_API_KEY")
    if not key:
        return {"ok": False, "configured": False}
    if image is None:
        return {"ok": False, "provider": "Google Vision", "error": "No image to analyse."}

    try:
        b64 = _downscale_to_b64(_to_bytes(image))
    except Exception as e:
        return {"ok": False, "provider": "Google Vision", "error": f"Could not read the image: {e}"}

    payload = {"requests": [{"image": {"content": b64},
                             "features": [{"type": "WEB_DETECTION", "maxResults": _max_results()}]}]}
    url = f"{_vision_endpoint()}?key={key}"
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with _opener().open(req, timeout=_timeout()) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        hint = " — check GOOGLE_VISION_API_KEY and that the Vision API is enabled." if e.code in (401, 403) else ""
        return {"ok": False, "provider": "Google Vision",
                "error": f"Vision API returned HTTP {e.code}.{hint} {body}".strip()}
    except Exception as e:
        return {"ok": False, "provider": "Google Vision", "error": f"Could not reach Google Vision ({e})."}

    try:
        outer = json.loads(raw)
        first = (outer.get("responses") or [{}])[0]
        if "error" in first:
            return {"ok": False, "provider": "Google Vision",
                    "error": f"Vision API: {(first.get('error') or {}).get('message', 'unknown error')}"}
        wd = first.get("webDetection") or {}
    except Exception as e:
        return {"ok": False, "provider": "Google Vision", "error": f"Bad response: {e}"}

    parsed = _parse_web_detection(wd, _max_results())
    parsed.update({"ok": True, "provider": "Google Vision"})
    return parsed


# ---------------------------------------------------------------------------
# Merge with the local model result
# ---------------------------------------------------------------------------

def merge_into(local_data: Optional[Dict[str, Any]], web: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Combine the local vision model result with a web-lookup result.

    The web match is trusted for the *name* (usually the exact product) and, if it
    reports one, the *price* (a real listing beats the AI's guess). The local model
    supplies category / dimensions / specs; web entities fold into tags; the top
    matching page becomes the product link. Returns a dict shaped like the local
    model's data so the existing "Apply to item" path can consume it.
    """
    out: Dict[str, Any] = dict(local_data or {})
    if not (web and web.get("ok")):
        return out

    best = (web.get("best_guess") or "").strip()
    if best:
        # Condense the marketplace title the same way the HTML importer does, so
        # a photo→web lookup doesn't store a 200-char SEO title as the name. The
        # full title is retained (searchable) in source_title.
        try:
            from product_import import _short_name
            cleaned = _short_name(best)
        except Exception:
            cleaned = best
        out["name"] = cleaned or best
        if cleaned and cleaned.strip().lower() != best.lower():
            out["source_title"] = best
        if not out.get("confidence") or str(out.get("confidence")).lower() == "low":
            out["confidence"] = "medium"

    price = (web.get("price") or "").strip()
    if price:
        out["estimated_value"] = price  # real listed price > AI estimate

    tags: List[str] = []
    for src in (out.get("tags") or []), (web.get("entities") or []):
        for t in src:
            t = str(t).strip()
            if t and t.lower() not in {x.lower() for x in tags}:
                tags.append(t)
    if tags:
        out["tags"] = tags[:12]

    pages = web.get("pages") or []
    if pages and not out.get("product_url"):
        out["product_url"] = pages[0]["url"]

    return out
