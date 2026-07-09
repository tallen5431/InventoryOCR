"""
Automatic reverse-image web detection for inventory items.

Local vision models describe an item well but often miss the *exact* product.
This module adds an automatic reverse-image lookup — the same idea as Google
Lens — so the Identify flow can return the accurate product name, keyword
entities, and links to matching pages, with no manual search/copy-paste.

It uses **Google Cloud Vision — Web Detection**, which (unlike Google Lens /
SerpApi) accepts the raw image *bytes*. That means it works on a private LAN
without exposing the app on a public URL: the photo only leaves your network
when the user clicks Identify AND a key is configured.

Privacy / opt-in:
  * If GOOGLE_VISION_API_KEY is not set, ``is_configured()`` is False and the
    app stays fully local (nothing is sent anywhere).
  * When set, the downscaled photo is POSTed to Google's Vision API on demand.

Configuration (environment variables):
  GOOGLE_VISION_API_KEY   API key for a Google Cloud project with the Vision API
                          enabled. Enables automatic reverse-image detection.
  WEB_DETECT_TIMEOUT      Request timeout in seconds. Default 30.
  WEB_DETECT_MAX_RESULTS  Max entities / pages to keep. Default 8.

No extra dependencies: stdlib urllib + Pillow (already used elsewhere).
"""
from __future__ import annotations
import os
import io
import json
import base64
import urllib.request
import urllib.error
from typing import Dict, Any, List, Union

from PIL import Image, ImageOps

_DEFAULT_VISION_ENDPOINT = "https://vision.googleapis.com/v1/images:annotate"


def _env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return v if v not in (None, "") else default


def _vision_endpoint() -> str:
    # Overridable for self-hosted proxies / testing; defaults to Google's API.
    return _env("WEB_DETECT_ENDPOINT", _DEFAULT_VISION_ENDPOINT)


def is_configured() -> bool:
    """True when a provider key is set, so reverse-image lookup can run."""
    return bool(_env("GOOGLE_VISION_API_KEY"))


def provider_name() -> str:
    return "Google Vision" if is_configured() else ""


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


def _parse_web_detection(wd: Dict[str, Any], max_results: int) -> Dict[str, Any]:
    """Turn a Vision ``webDetection`` block into flat, UI-friendly fields."""
    best_guesses = [
        (g.get("label") or "").strip()
        for g in (wd.get("bestGuessLabels") or [])
        if (g.get("label") or "").strip()
    ]
    entities = []
    for e in (wd.get("webEntities") or []):
        desc = (e.get("description") or "").strip()
        if desc and desc.lower() not in {x.lower() for x in entities}:
            entities.append(desc)
    entities = entities[:max_results]

    pages = []
    for p in (wd.get("pagesWithMatchingImages") or []):
        url = (p.get("url") or "").strip()
        if not url:
            continue
        title = (p.get("pageTitle") or "").strip()
        pages.append({"title": title or url, "url": url})
        if len(pages) >= max_results:
            break

    return {
        "best_guess": best_guesses[0] if best_guesses else "",
        "entities": entities,
        "pages": pages,
    }


def detect_web(image: Union[bytes, bytearray, str]) -> Dict[str, Any]:
    """Reverse-image lookup for ``image`` via Google Vision Web Detection.

    Returns:
      {"ok": True,  "provider": "Google Vision", "best_guess": str,
       "entities": [str], "pages": [{"title","url"}]}
      {"ok": False, "provider": ..., "error": str}         on failure
      {"ok": False, "configured": False}                   when no key is set
    """
    key = _env("GOOGLE_VISION_API_KEY")
    if not key:
        return {"ok": False, "configured": False}

    timeout = int(_env("WEB_DETECT_TIMEOUT", "30") or 30)
    max_results = int(_env("WEB_DETECT_MAX_RESULTS", "8") or 8)

    try:
        b64 = _downscale_to_b64(_to_bytes(image))
    except Exception as e:
        return {"ok": False, "provider": "Google Vision", "error": f"Could not read the image: {e}"}

    payload = {
        "requests": [
            {
                "image": {"content": b64},
                "features": [{"type": "WEB_DETECTION", "maxResults": max_results}],
            }
        ]
    }
    url = f"{_vision_endpoint()}?key={key}"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    # Reach Google directly, bypassing any ambient HTTP proxy (matches vision_lookup).
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        hint = ""
        if e.code in (401, 403):
            hint = " — check GOOGLE_VISION_API_KEY and that the Vision API is enabled."
        return {"ok": False, "provider": "Google Vision",
                "error": f"Vision API returned HTTP {e.code}.{hint} {body}".strip()}
    except Exception as e:
        return {"ok": False, "provider": "Google Vision",
                "error": f"Could not reach Google Vision ({e})."}

    try:
        outer = json.loads(raw)
        responses = outer.get("responses") or []
        first = responses[0] if responses else {}
        if "error" in first:
            msg = (first.get("error") or {}).get("message", "unknown error")
            return {"ok": False, "provider": "Google Vision", "error": f"Vision API: {msg}"}
        wd = first.get("webDetection") or {}
    except Exception as e:
        return {"ok": False, "provider": "Google Vision", "error": f"Bad response: {e}"}

    parsed = _parse_web_detection(wd, max_results)
    parsed.update({"ok": True, "provider": "Google Vision"})
    return parsed


def merge_into(local_data: Dict[str, Any] | None, web: Dict[str, Any] | None) -> Dict[str, Any]:
    """Combine the local vision model result with a web-detection result.

    The web reverse-image match is trusted for the *name* (it's usually the exact
    product), while the local model supplies category / value / dimensions /
    specs. Web entities are folded into tags. Returns a fresh dict shaped like the
    local model's data so the existing "Apply to item" path can consume it.
    """
    out: Dict[str, Any] = dict(local_data or {})

    if not (web and web.get("ok")):
        return out

    best = (web.get("best_guess") or "").strip()
    if best:
        # Prefer the reverse-image product name; keep the local one as a fallback
        # only if the web guess is empty (handled above).
        out["name"] = best
        # A confirmed web match raises our confidence.
        if not out.get("confidence") or str(out.get("confidence")).lower() == "low":
            out["confidence"] = "medium"

    # Fold web entities into tags (dedupe, case-insensitive).
    tags: List[str] = []
    for src in (out.get("tags") or []), web.get("entities") or []:
        for t in src:
            t = str(t).strip()
            if t and t.lower() not in {x.lower() for x in tags}:
                tags.append(t)
    if tags:
        out["tags"] = tags[:12]

    # Attach the top matching page as a product link, if any.
    pages = web.get("pages") or []
    if pages and not out.get("product_url"):
        out["product_url"] = pages[0]["url"]

    return out
