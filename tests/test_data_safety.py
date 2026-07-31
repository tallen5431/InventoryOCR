"""Tests for the destructive / irreversible data paths.

These had no coverage of any kind, which is the wrong place for a gap: every
function here either deletes files, deletes records, or is the last line of
defence for getting them back.

  * the one-step undo net (snapshot / commit / restore) behind Merge and
    bulk-delete;
  * prune_unreferenced_images / _documents, which unlink files outright —
    including the grace period that stops them eating photos the user is still
    staging in another form, and the undo-snapshot union that stops them
    unlinking files an Undo is about to need;
  * find_duplicate_groups + merge_group, i.e. what the Merge Duplicates UI
    actually calls (the older suite only checked raw similarity scores);
  * stats-style valuation over a group.

Run: python3 tests/test_data_safety.py   (no pytest dependency required)
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import data

_ok = True


def _check(name, cond):
    global _ok
    print(("PASS" if cond else "FAIL"), "-", name)
    _ok = cond and _ok


def _aged(path, seconds):
    """Backdate a file so the prune grace period doesn't protect it."""
    old = time.time() - seconds
    os.utime(path, (old, old))


def _reset(tmp):
    data.INVENTORY_JSON = tmp
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("[]")
    data._clear_undo()


def main():
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    tmp.write("[]")
    tmp.close()
    original = data.INVENTORY_JSON
    made = []
    try:
        _reset(tmp.name)

        # ---- Undo: a bulk delete is recoverable -------------------------
        a = data.add_item("Widget A", "", 2, [], "")
        b = data.add_item("Widget B", "", 3, [], "")
        data.snapshot_inventory()
        data.remove_item(a["id"])
        data.remove_item(b["id"])
        _check("both items deleted", len(data.inventory()) == 0)
        data.commit_undo()
        _check("undo is available after commit", data.has_undo())
        _check("restore reports success", data.restore_inventory() == "restored")
        names = sorted(r["name"] for r in data.inventory())
        _check("undo restores both records", names == ["Widget A", "Widget B"])
        _check("undo restores quantities",
               sorted(r["qty"] for r in data.inventory()) == [2, 3])
        _check("undo is spent after use", not data.has_undo())

        # ---- Undo: an edit made after the merge invalidates it ----------
        _reset(tmp.name)
        c = data.add_item("Widget C", "", 1, [], "")
        data.snapshot_inventory()
        data.remove_item(c["id"])
        data.commit_undo()
        data.add_item("Added Later", "", 1, [], "")
        # The inventory no longer matches the post-op checkpoint, so undoing
        # would silently discard that later edit — it must refuse, not clobber.
        _check("a later edit makes the undo stale rather than destructive",
               data.restore_inventory() == "stale")
        _check("the later edit survived the refused undo",
               any(r["name"] == "Added Later" for r in data.inventory()))

        # ---- Prune: reclaims real orphans -------------------------------
        _reset(tmp.name)
        orphan = config.IMAGE_DIR / "t-safety-orphan.jpg"
        orphan.write_bytes(b"x")
        made.append(orphan)
        _aged(orphan, 7200)
        data.prune_unreferenced_images()
        _check("a genuine orphan photo is reclaimed", not orphan.exists())

        # ---- Prune: keeps files a saved item references ------------------
        kept = config.IMAGE_DIR / "t-safety-kept.jpg"
        kept.write_bytes(b"x")
        made.append(kept)
        _aged(kept, 7200)
        data.add_item("Has A Photo", "", 1, ["t-safety-kept.jpg"], "")
        data.prune_unreferenced_images()
        _check("a referenced photo is never pruned", kept.exists())

        # ---- Prune: leaves just-staged files alone ----------------------
        # Photos hit disk the moment they're chosen, before any item exists.
        # A prune fired from another surface must not eat them.
        staging = config.IMAGE_DIR / "t-safety-staging.jpg"
        staging.write_bytes(b"x")
        made.append(staging)
        data.prune_unreferenced_images()
        _check("a photo staged seconds ago survives a prune", staging.exists())

        # ---- Prune: respects a pending undo snapshot --------------------
        _reset(tmp.name)
        doomed = config.IMAGE_DIR / "t-safety-undoable.jpg"
        doomed.write_bytes(b"x")
        made.append(doomed)
        _aged(doomed, 7200)
        row = data.add_item("Doomed", "", 1, ["t-safety-undoable.jpg"], "")
        data.snapshot_inventory()
        data.remove_item(row["id"])
        data.prune_unreferenced_images()
        _check("a photo an Undo still needs is not unlinked", doomed.exists())

        # ---- Prune: documents behave the same ---------------------------
        _reset(tmp.name)
        doc = config.DOCS_DIR / "t-safety-orphan.pdf"
        doc.write_bytes(b"x")
        made.append(doc)
        _aged(doc, 7200)
        data.prune_unreferenced_documents()
        _check("an orphan document is reclaimed", not doc.exists())

        # ---- Duplicate detection: what the Merge UI actually calls ------
        _reset(tmp.name)
        data.add_item("AA Battery", "", 2, [], "")
        data.add_item("AA Batteries", "", 3, [], "")
        data.add_item("Cordless Drill", "", 1, [], "")
        groups = data.find_duplicate_groups(level="balanced")
        _check("near-identical names group together", len(groups) == 1)
        ids = groups[0]["item_ids"] if groups else []
        _check("the group holds exactly the two batteries", len(ids) == 2)

        # Different sizes must NOT be grouped — the guard the feature exists for.
        _reset(tmp.name)
        data.add_item("AA Battery", "", 1, [], "")
        data.add_item("9V Battery", "", 1, [], "")
        _check("different sizes are held apart",
               len(data.find_duplicate_groups(level="balanced")) == 0)

        # ---- merge_group: sums quantities, unions photos, removes rows ---
        _reset(tmp.name)
        p = data.add_item("AA Battery", "", 2, ["p1.jpg"], "",
                          specifications=["Chem: alkaline"], tags=["battery"])
        q = data.add_item("AA Batteries", "", 3, ["p2.jpg"], "",
                          specifications=["Count: 4"], tags=["aa"])
        merged = data.merge_group(p["id"], [q["id"]])
        _check("merge sums the quantities", merged["qty"] == 5)
        _check("merge keeps every photo",
               sorted(merged["images"]) == ["p1.jpg", "p2.jpg"])
        _check("merge keeps every spec", len(merged["specifications"]) == 2)
        _check("merge keeps every tag", sorted(merged["tags"]) == ["aa", "battery"])
        _check("merge removes the absorbed row", len(data.inventory()) == 1)

        # ---- merge_group: can't create a duplicate name -----------------
        _reset(tmp.name)
        x = data.add_item("Thing One", "", 1, [], "")
        y = data.add_item("Thing Two", "", 1, [], "")
        data.add_item("Taken Name", "", 1, [], "")
        try:
            data.merge_group(x["id"], [y["id"]], {"name": "Taken Name"})
            _check("merge rejects a name another item already holds", False)
        except ValueError:
            _check("merge rejects a name another item already holds", True)
        _check("the rejected merge changed nothing", len(data.inventory()) == 3)

        # ---- Valuation over a group -------------------------------------
        _reset(tmp.name)
        data.add_item("In Stock", "", 3, [], "", estimated_value="$9.00")
        data.add_item("Out Of Stock", "", 0, [], "", estimated_value="$24.99")
        rows = data.inventory()
        _check("an out-of-stock item contributes nothing to the total",
               abs(data._sum_group_value(rows) - 27.00) < 1e-6)

        print("\nRESULT:", "ALL PASS" if _ok else "SOME FAILED")
        return 0 if _ok else 1
    finally:
        for f in made:
            try:
                f.unlink()
            except OSError:
                pass
        data._clear_undo()
        data.INVENTORY_JSON = original
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def test_main():
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
