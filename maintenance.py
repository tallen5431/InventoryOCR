"""One-shot maintenance for an existing inventory.

The catalogue accretes raw marketplace titles as item names (e.g.
``Amazon.com: EC Buying MAX7219 Dot Matrix Display ... : Industrial &
Scientific``) whenever an item was captured before the concise-name step existed
or via the photo→web path. This condenses those into short display names while
keeping the full title searchable in a ``source_title`` field.

Safe to run repeatedly — it's idempotent (an already-short name is left alone)
and takes an in-app Undo snapshot before writing.

Usage::

    python maintenance.py            # dry run: preview what would change
    python maintenance.py --apply    # apply the changes (snapshots first)
"""
from __future__ import annotations

import sys
from typing import Any, Dict, List, Tuple

import data
from product_import import _short_name


def plan_name_cleanup(rows: List[Dict[str, Any]]) -> List[Tuple[int, str, str]]:
    """Return ``[(id, old_name, new_name), ...]`` for names worth condensing.

    Skips names that are already short, and skips a rename whose result would
    collide with another item's name (inventory is unique-by-name), so the run
    never creates a duplicate — those are reported separately by the caller.
    """
    taken = {(r.get("name") or "").strip().lower(): int(r.get("id") or 0) for r in rows}
    plan: List[Tuple[int, str, str]] = []
    for r in rows:
        rid = int(r.get("id") or 0)
        old = (r.get("name") or "").strip()
        if not old:
            continue
        new = _short_name(old)
        if not new or len(new) < 3 or new == old:
            continue
        owner = taken.get(new.strip().lower())
        if owner is not None and owner != rid:
            # A different item already holds the shortened name — leave this one
            # untouched rather than create a duplicate.
            continue
        plan.append((rid, old, new))
    return plan


def run(apply: bool = False) -> int:
    rows = data.inventory()
    plan = plan_name_cleanup(rows)
    by_id = {int(r.get("id") or 0): r for r in rows}

    if not plan:
        print("Nothing to clean — all names already look concise. ✓")
        return 0

    print(f"{'APPLYING' if apply else 'DRY RUN'} — {len(plan)} name(s) to condense:\n")
    for rid, old, new in plan:
        print(f"  [{rid}] {old!r}\n      → {new!r}")
    print()

    if not apply:
        print("Re-run with --apply to write these changes (an Undo snapshot is taken first).")
        return 0

    data.snapshot_inventory()  # one-click Undo in the app after this runs
    changed = 0
    for rid, old, new in plan:
        # Preserve the original title (searchable) unless one is already stored.
        existing_src = (by_id.get(rid, {}).get("source_title") or "").strip()
        fields: Dict[str, Any] = {"name": new}
        if not existing_src:
            fields["source_title"] = old
        if data.update_item_fields(rid, **fields) is not None:
            changed += 1
    print(f"Done — condensed {changed} name(s). Use Undo in the app to roll back.")
    return changed


if __name__ == "__main__":
    run(apply="--apply" in sys.argv[1:])
