"""Build/version info surfaced in the navbar so you can confirm which branch and
commit a running instance is on.

This matters because the HTTP_Server manager deploys by git-cloning this repo
straight into its run folder — an old instance you forgot to update looks
identical to a fresh one from the outside otherwise.

Computed once at import time: the manager's update flow always restarts the
process after ``git reset --hard``, so within one process's lifetime the
checked-out branch/commit can't change under it. Never raises — any failure (no
git binary, not a git checkout) degrades to "unknown" rather than blocking
startup, matching config.py's pattern for other optional/environmental info.
"""
from __future__ import annotations
import subprocess
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent


def _git(*args: str) -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", *args], cwd=str(BASE_DIR),
            capture_output=True, text=True, timeout=3, check=True,
        )
        return out.stdout.strip()
    except Exception:
        return None


def _detect() -> dict:
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    if branch == "HEAD":  # detached HEAD (a tag/commit checkout rather than a branch)
        branch = None
    commit = _git("rev-parse", "--short", "HEAD")
    commit_date = _git("log", "-1", "--format=%cd", "--date=short")
    dirty = _git("status", "--porcelain")
    return {
        "available": commit is not None,
        "branch": branch or "(detached)",
        "commit": commit or "unknown",
        "commit_date": commit_date or "",
        "dirty": bool(dirty),
    }


VERSION_INFO = _detect()


def version_label() -> str:
    """Short one-line label for the navbar badge, e.g. 'main @ a1b2c3d'."""
    if not VERSION_INFO["available"]:
        return "version unknown"
    label = f'{VERSION_INFO["branch"]} @ {VERSION_INFO["commit"]}'
    if VERSION_INFO["dirty"]:
        label += " *"
    return label


def version_tooltip() -> str:
    """Longer text for a hover tooltip (native title attribute)."""
    if not VERSION_INFO["available"]:
        return "Could not read git info — this checkout may not be a git clone."
    lines = [f'Branch: {VERSION_INFO["branch"]}', f'Commit: {VERSION_INFO["commit"]}']
    if VERSION_INFO["commit_date"]:
        lines.append(f'Committed: {VERSION_INFO["commit_date"]}')
    if VERSION_INFO["dirty"]:
        lines.append("* Working tree has uncommitted changes")
    return "\n".join(lines)
