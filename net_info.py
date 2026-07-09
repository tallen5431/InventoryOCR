"""
Discover every address this app is reachable at (localhost, LAN, Tailscale).

The Dash server binds ``0.0.0.0``, so it already listens on every interface at
once. This module enumerates those interfaces so the UI can *show* each URL —
handy when you want to open the app locally on the LAN AND over Tailscale from
your phone.

Pure stdlib: parses ``ip``/``ipconfig`` where available, with socket fallbacks.
"""
from __future__ import annotations
import os
import re
import socket
import subprocess
import ipaddress
from typing import List, Dict


def _primary_ip() -> str:
    """The LAN IP the OS would use for outbound traffic (UDP trick, no packets sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return ""
    finally:
        s.close()


def _from_ip_command() -> List[str]:
    """Linux/mac: parse `ip -o -4 addr` (or `ifconfig`) for IPv4 addresses."""
    out: List[str] = []
    for cmd in (["ip", "-o", "-4", "addr", "show"], ["ifconfig"]):
        try:
            txt = subprocess.run(cmd, capture_output=True, text=True, timeout=3).stdout
        except Exception:
            continue
        if txt:
            out += re.findall(r"inet\s+(\d+\.\d+\.\d+\.\d+)", txt)
            if out:
                break
    return out


def _from_socket() -> List[str]:
    """Cross-platform fallback via hostname resolution."""
    out: List[str] = []
    try:
        host = socket.gethostname()
        try:
            out += list(socket.gethostbyname_ex(host)[2])
        except Exception:
            pass
        for info in socket.getaddrinfo(host, None, socket.AF_INET):
            out.append(info[4][0])
    except Exception:
        pass
    return out


def _all_ipv4() -> List[str]:
    ips = set(_from_ip_command()) | set(_from_socket())
    p = _primary_ip()
    if p:
        ips.add(p)
    ips.add("127.0.0.1")
    return list(ips)


def _classify(ip: str) -> str:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return "other"
    if addr.is_loopback:
        return "loopback"
    # Tailscale hands out addresses from the 100.64.0.0/10 CGNAT range.
    if addr in ipaddress.ip_network("100.64.0.0/10"):
        return "tailscale"
    if addr.is_private:
        return "lan"
    return "other"


_KIND_ORDER = {"lan": 0, "tailscale": 1, "loopback": 2, "other": 3}
_KIND_LABEL = {
    "lan": "Local network",
    "tailscale": "Tailscale",
    "loopback": "This device",
    "other": "Other",
}


def access_endpoints(port: int, url_prefix: str = "", scheme: str = "http") -> List[Dict[str, str]]:
    """Return the distinct URLs this app is reachable at, best-first.

    Each item: {"ip", "kind", "label", "url"}. LAN first, then Tailscale, then
    localhost. Duplicate IPs are collapsed.
    """
    prefix = (url_prefix or "").rstrip("/")
    seen = set()
    rows: List[Dict[str, str]] = []
    for ip in _all_ipv4():
        if ip in seen:
            continue
        seen.add(ip)
        kind = _classify(ip)
        url = f"{scheme}://{ip}:{port}{prefix}/"
        rows.append({"ip": ip, "kind": kind, "label": _KIND_LABEL.get(kind, "Other"), "url": url})
    rows.sort(key=lambda r: (_KIND_ORDER.get(r["kind"], 9), r["ip"]))
    return rows


def qr_data_uri(url: str) -> str:
    """Return an SVG data URI QR code for ``url``, or "" if qrcode isn't installed."""
    try:
        import qrcode
        import qrcode.image.svg
        import base64
        img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
        import io
        buf = io.BytesIO()
        img.save(buf)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/svg+xml;base64,{b64}"
    except Exception:
        return ""
