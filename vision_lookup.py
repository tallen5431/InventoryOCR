"""
Identify an inventory item from a photo using a local vision LLM.

Sends the item's photo to an Ollama server (the same local/Tailscale endpoint the
rest of the stack uses) and asks a vision model to return structured info about
the item: what it is, specifications, an estimated value, and dimensions.

Nothing here leaves your network unless OLLAMA_HOST points somewhere remote, and
no extra Python dependencies are required (stdlib urllib + Pillow, already used).

Configuration (environment variables):
  OLLAMA_HOST          Base URL of the Ollama server. Default http://100.98.112.1:11434
                       A trailing "/v1" (OpenAI-compat form) is accepted and stripped.
  OLLAMA_VISION_MODEL  Vision-capable model to use. Default "llava:13b".
                       Pull one first, e.g.  ollama pull llava:13b
  VISION_TIMEOUT       Request timeout in seconds. Default 60.
"""
from __future__ import annotations
import os
import json
import urllib.request
import urllib.error
from typing import Dict, Any, Optional, Union



def _env(name: str, default: str) -> str:
    v = os.getenv(name)
    return v if v not in (None, "") else default


def get_config() -> Dict[str, Any]:
    """Resolve the current Ollama config (read live so env edits take effect)."""
    return {
        "host": _normalize_base(_env("OLLAMA_HOST", "http://localhost:11434")),
        "model": _env("OLLAMA_VISION_MODEL", "llava:13b"),
        "timeout": int(_env("VISION_TIMEOUT", "60") or 60),
    }


def _normalize_base(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    # Accept the OpenAI-compatible base (…:11434/v1) that other cards use, but
    # talk to Ollama's native API here.
    if url.endswith("/v1"):
        url = url[:-3]
    return url


# Image payload helpers are shared with web_detect — see utils.
from utils import image_to_bytes as _to_bytes, downscale_to_b64 as _downscale_to_b64


PROMPT = (
    "You are an expert appraiser and cataloguer identifying a single physical item "
    "from a photo for an inventory record. Identify the main item in the image and "
    "respond with ONLY a JSON object (no prose, no markdown) using exactly these keys:\n"
    '  "name": short item/product name,\n'
    '  "category": one or two word category (e.g. "Power Tools", "Kitchen"),\n'
    '  "what_it_is": one or two sentences describing what the item is and its use,\n'
    '  "specifications": array of short spec strings (brand, model, material, capacity, etc.),\n'
    '  "estimated_value": string with a currency and a plausible RANGE, clearly an estimate,\n'
    '  "dimensions": string with an approximate size, or "unknown",\n'
    '  "tags": array of 3-6 short lowercase keywords someone might search to find this item,\n'
    '  "search_query": a concise web-search query (brand + model + product type) to look it up,\n'
    '  "confidence": one of "low", "high", or "medium".\n'
    "Use \"unknown\" for anything you cannot determine. Do NOT invent exact prices or "
    "model numbers; prefer ranges and say when you are unsure."
)


def identify_item(
    image: Union[bytes, bytearray, str],
    *,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    timeout: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Identify the item in ``image`` via an Ollama vision model.

    Returns a dict:
      {"ok": True,  "model": ..., "endpoint": ..., "raw": <text>, "data": <parsed dict or None>}
      {"ok": False, "error": <message>, "endpoint": ..., "model": ...}
    """
    cfg = get_config()
    base = _normalize_base(base_url or cfg["host"])
    model = model or cfg["model"]
    timeout = int(timeout or cfg["timeout"])

    try:
        b64 = _downscale_to_b64(_to_bytes(image))
    except Exception as e:
        return {"ok": False, "error": f"Could not read the image: {e}", "endpoint": base, "model": model}

    payload = {
        "model": model,
        "prompt": PROMPT,
        "images": [b64],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.2},
    }
    url = f"{base}/api/generate"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    # Talk directly to the Ollama host, bypassing any ambient HTTP proxy so a
    # LAN / Tailscale address is reached directly.
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
        if e.code == 404:
            hint = f" — model '{model}' may not be pulled. Try: ollama pull {model}"
        return {"ok": False, "error": f"Ollama returned HTTP {e.code}.{hint} {body}".strip(),
                "endpoint": url, "model": model}
    except Exception as e:
        return {"ok": False,
                "error": f"Could not reach Ollama at {base} ({e}). "
                         f"Check OLLAMA_HOST and that the server is running.",
                "endpoint": url, "model": model}

    # Ollama /api/generate (non-streaming) returns {"response": "...", ...}
    text = raw
    try:
        outer = json.loads(raw)
        if isinstance(outer, dict) and "response" in outer:
            text = outer.get("response") or ""
    except Exception:
        pass

    result: Dict[str, Any] = {"ok": True, "model": model, "endpoint": url, "raw": text}
    try:
        parsed = json.loads(text)
        result["data"] = parsed if isinstance(parsed, dict) else None
    except Exception:
        result["data"] = None
    return result
