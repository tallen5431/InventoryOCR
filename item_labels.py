"""Printable QR labels for inventory items.

Each item carries a short, never-reused ``code`` (see ``data._next_code``). A
label pairs that code with a QR of the URL that opens the item's scan page, so
finding a stray part is: point phone at label, read where it lives, put it back.

The hard part is not the QR — it is choosing the URL to bake into it. A printed
label outlives any given network address, so this module ranks the addresses the
app is reachable at by how long they are likely to keep working, and lets the
caller override the choice before printing:

  1. ``PUBLIC_BASE``            — an explicit public URL; the operator owns it.
  2. ``TAILSCALE_FUNNEL_BASE``  — public HTTPS, stable hostname.
  3. Tailscale IP (100.64/10)   — stable per-machine, reachable off-LAN on the
                                  tailnet, immune to the home router's DHCP.
  4. LAN IP                     — fastest at home, but a DHCP lease change or a
                                  new router silently kills every printed label.
  5. localhost                  — only useful for a test print.

Nothing here writes to the inventory; it is pure derivation from a row plus a
chosen base URL.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import os

import net_info
from config import URL_PREFIX

# Path segment the scan page is served under, e.g. /inventory/i/0042. Short on
# purpose: it goes inside every QR, and fewer characters means a coarser, more
# forgiving QR at the same printed size.
LABEL_ROUTE = "/i"

# How durable each address kind is, best first. Mirrors the ranking above.
_KIND_RANK = {"public": 0, "funnel": 1, "tailscale": 2, "lan": 3, "other": 4, "loopback": 5}

_KIND_NOTE = {
    "public": "Public URL — works anywhere.",
    "funnel": "Tailscale Funnel — public HTTPS, works anywhere.",
    "tailscale": "Tailscale — works anywhere the phone is on your tailnet.",
    "lan": "Home network only. Breaks if this machine's IP changes.",
    "loopback": "This machine only — not useful on a printed label.",
    "other": "",
}


def base_options(port: int, scheme: str = "http") -> List[Dict[str, str]]:
    """Addresses a label could point at, most durable first.

    Each entry: ``{"base", "kind", "label", "note"}`` where ``base`` has no
    trailing slash and excludes URL_PREFIX (added by :func:`item_url`).
    """
    out: List[Dict[str, str]] = []
    seen = set()

    def _add(base: str, kind: str, label: str):
        base = (base or "").rstrip("/")
        if not base or base in seen:
            return
        seen.add(base)
        out.append({"base": base, "kind": kind, "label": label,
                    "note": _KIND_NOTE.get(kind, "")})

    # An explicitly configured public base wins: the operator chose it and can
    # keep it pointing here. Same precedence as web_search.public_base().
    pub = (os.getenv("PUBLIC_BASE") or "").strip().rstrip("/")
    if pub:
        _add(pub, "public", "Public URL")
    funnel = (os.getenv("TAILSCALE_FUNNEL_BASE") or "").strip().rstrip("/")
    if funnel:
        _add(funnel, "funnel", "Tailscale Funnel")

    # A configured base may already include URL_PREFIX; strip it so item_url can
    # add it exactly once.
    if URL_PREFIX:
        for row in out:
            if row["base"].endswith(URL_PREFIX):
                row["base"] = row["base"][: -len(URL_PREFIX)].rstrip("/")

    for ep in net_info.access_endpoints(port, "", scheme):
        _add(f"{scheme}://{ep['ip']}:{port}", ep["kind"], ep["label"])

    out.sort(key=lambda r: _KIND_RANK.get(r["kind"], 9))
    return out


def default_base(port: int, scheme: str = "http") -> str:
    """The most durable address available, or "" if none could be determined."""
    opts = base_options(port, scheme)
    return opts[0]["base"] if opts else ""


def item_url(code: str, base: str = "") -> str:
    """Full URL that opens the scan page for ``code``.

    With no ``base`` this returns a site-relative path, which is what the in-app
    links use — only a *printed* label needs an absolute address.
    """
    code = (code or "").strip()
    if not code:
        return ""
    path = f"{URL_PREFIX}{LABEL_ROUTE}/{code}"
    return f"{(base or '').rstrip('/')}{path}" if base else path


def qr_data_uri(url: str) -> str:
    """SVG data URI QR code for ``url``, or "" if the qrcode package is absent.

    SVG rather than PNG so labels stay crisp at any printer DPI. Shared with the
    Connect panel via net_info.
    """
    return net_info.qr_data_uri(url)


def qr_available() -> bool:
    """True when QR images can actually be produced (the qrcode package is installed)."""
    try:
        import qrcode
        from qrcode.image import svg
        return bool(qrcode and svg)
    except Exception:
        return False


def label_for(row: Dict[str, Any], base: str = "") -> Optional[Dict[str, str]]:
    """One printable label for ``row``, or None if it has no code yet."""
    code = str(row.get("code") or "").strip()
    if not code:
        return None
    url = item_url(code, base)
    return {
        "id": str(row.get("id") or ""),
        "code": code,
        "name": str(row.get("name") or "").strip(),
        "location": str(row.get("location") or "").strip(),
        "location_code": str(row.get("location_code") or "").strip(),
        "url": url,
        "qr": qr_data_uri(url),
    }


def labels_for(rows: List[Dict[str, Any]], base: str = "") -> List[Dict[str, str]]:
    """Printable labels for every row that has a code, in the order given."""
    out = []
    for r in rows or []:
        lab = label_for(r, base)
        if lab:
            out.append(lab)
    return out
