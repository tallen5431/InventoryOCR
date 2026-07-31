"""Optional HTTP Basic Auth for exposing the app beyond the LAN.

Kept pure and dependency-light (only ``os`` + ``hmac``) so it can be unit-tested
without Flask. ``app.py`` wires these into a Flask ``before_request`` hook.

Enable by setting either:
  * ``INVENTORY_AUTH_USER`` and ``INVENTORY_AUTH_PASSWORD``, or
  * ``INVENTORY_AUTH`` = ``"user:password"`` (shorthand).

When neither is set, auth is OFF and the app behaves exactly as before (LAN
use). Basic Auth transmits the password on every request, so only expose the
app over HTTPS — e.g. Tailscale Funnel or a Cloudflare Tunnel, both of which
terminate TLS for you.
"""
from __future__ import annotations
import os
import hmac
from typing import Mapping, Optional, Tuple


def configured_credentials(env: Optional[Mapping[str, str]] = None) -> Tuple[str, str]:
    """Return the (user, password) the operator configured, or ("", "")."""
    env = env if env is not None else os.environ
    user = (env.get("INVENTORY_AUTH_USER") or "").strip()
    pw = env.get("INVENTORY_AUTH_PASSWORD") or ""
    # Fill in whichever half is missing from the shorthand. Gating the whole
    # shorthand on ``if not user`` meant that setting INVENTORY_AUTH_USER alone
    # — a natural half-configuration — made the correctly-set INVENTORY_AUTH
    # shorthand invisible, and auth then silently stayed OFF.
    combined = env.get("INVENTORY_AUTH") or ""
    if ":" in combined:
        s_user, s_pw = combined.split(":", 1)
        user = user or s_user.strip()
        pw = pw or s_pw
    return user, pw


def auth_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    """True only when a non-empty user AND password are configured."""
    user, pw = configured_credentials(env)
    return bool(user and pw)


def credentials_match(username: Optional[str], password: Optional[str],
                      env: Optional[Mapping[str, str]] = None) -> bool:
    """Constant-time check of a supplied user/password against the configured pair.

    Returns False when auth isn't configured, so callers can't be tricked into
    allowing access with empty credentials.
    """
    user, pw = configured_credentials(env)
    if not (user and pw):
        return False
    # Compare both fields in constant time; AND the results so timing can't
    # reveal which of the two was wrong. Compare *bytes*: compare_digest raises
    # TypeError on a str containing any non-ASCII character, which turned a
    # perfectly reasonable passphrase into an unhandled 500 on every request
    # (and locked the operator out of their own app).
    user_ok = hmac.compare_digest((username or "").encode("utf-8"), user.encode("utf-8"))
    pw_ok = hmac.compare_digest((password or "").encode("utf-8"), pw.encode("utf-8"))
    return user_ok and pw_ok
