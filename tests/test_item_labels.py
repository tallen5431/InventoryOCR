"""Tests for the QR label codes, label URLs, and the scan page.

The property this whole feature rests on is that a code is **never reused**. A
label is glued to a physical object; if a code could be reissued, a scan would
one day open the wrong item and send a part back to the wrong bin — silently,
and with no way to notice. ``id`` cannot serve here precisely because
``_next_id`` is max+1 and so recycles ids after a delete. That contrast is
asserted directly below.

Also covers: the round trip a phone actually performs (QR image -> decoded URL
-> route key -> the right item), that codes survive an edit, and that the base
URL baked into a label is the most durable one available.

Run: python3 tests/test_item_labels.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data
import item_labels

_ok = True


def _check(name, cond):
    global _ok
    print(("PASS" if cond else "FAIL"), "-", name)
    _ok = cond and _ok


def _reset(d):
    data.INVENTORY_JSON = d / "inventory.json"
    data.CODE_SEQ_FILE = d / "item_codes.json"
    (d / "inventory.json").write_text("[]", encoding="utf-8")
    if (d / "item_codes.json").exists():
        (d / "item_codes.json").unlink()


def main():
    d = Path(tempfile.mkdtemp())
    orig_inv, orig_seq = data.INVENTORY_JSON, data.CODE_SEQ_FILE
    try:
        _reset(d)

        # ---- Codes are allocated, padded, and sequential -----------------
        a = data.add_item("Toggle Switches", "", 12, [], "", location_code="BIN-04")
        b = data.add_item("1k Resistors", "", 500, [], "")
        _check("first item gets code 0001", a["code"] == "0001")
        _check("second item gets code 0002", b["code"] == "0002")

        # ---- THE invariant: a code is never reused, unlike an id ---------
        old_id, old_code = b["id"], b["code"]
        data.remove_item(b["id"])
        c = data.add_item("Something Else", "", 1, [], "")
        _check("ids ARE recycled after a delete (why id can't be the label)",
               c["id"] == old_id)
        _check("codes are NOT recycled after a delete", c["code"] != old_code)
        _check("the next code continues past the deleted one", c["code"] == "0003")

        # ---- ...even if the counter file is lost -------------------------
        data.CODE_SEQ_FILE.unlink()
        e = data.add_item("After Counter Loss", "", 1, [], "")
        _check("a lost counter file can't reissue a live code",
               e["code"] not in {a["code"], c["code"]})
        _check("a lost counter file resumes from the highest code in use",
               e["code"] == "0004")

        # ---- A code survives edits and follows its item ------------------
        data.update_item(a["id"], "Toggle Switches", "renamed", 9, [], "")
        _check("an edit keeps the code", data.item_by_code("0001")["name"] == "Toggle Switches")
        _check("an edit keeps the code attached to the same id",
               data.item_by_code("0001")["id"] == a["id"])

        # ---- Lookup takes what a person would type -----------------------
        for typed in ("0001", "1", "#1", " 0001 ", "#0001"):
            _check(f"lookup accepts {typed!r}",
                   (data.item_by_code(typed) or {}).get("id") == a["id"])
        for junk in ("", None, "abc", "0", "9999", "12-34"):
            _check(f"lookup rejects {junk!r}", data.item_by_code(junk) is None)

        # ---- Codes are searchable, so a typed code finds the item --------
        _check("a code is findable via search",
               [r["id"] for r in data.search("0001")] == [a["id"]])

        # ---- Backfill for an inventory that predates the feature ---------
        _reset(d)
        (d / "inventory.json").write_text(json.dumps([
            {"id": 7, "name": "Older", "qty": 1, "created_at": "2024-01-01T00:00:00"},
            {"id": 8, "name": "Newer", "qty": 1, "created_at": "2025-01-01T00:00:00"},
        ]), encoding="utf-8")
        _check("backfill assigns a code to every unlabelled item",
               data.ensure_item_codes() == 2)
        _check("backfill is idempotent", data.ensure_item_codes() == 0)
        got = {r["name"]: r["code"] for r in data.inventory()}
        _check("backfill numbers in creation order (oldest first)",
               got == {"Older": "0001", "Newer": "0002"})

        # ---- A merge must not orphan the absorbed item's printed label ----
        # Merging duplicates is part of the documented workflow, so a QR already
        # stuck on the absorbed item has to keep resolving.
        _reset(d)
        m1 = data.add_item("AA Battery", "", 2, [], "", location_code="BIN-01")
        m2 = data.add_item("AA Batteries", "", 3, [], "", location_code="BIN-01")
        merged = data.merge_group(m1["id"], [m2["id"]])
        _check("the survivor keeps its own code", merged["code"] == m1["code"])
        _check("the absorbed code is kept as an alias",
               m2["code"] in (merged.get("alt_codes") or []))
        _check("scanning the survivor's label still works",
               (data.item_by_code(m1["code"]) or {}).get("id") == m1["id"])
        _check("scanning the merged-away label finds the survivor",
               (data.item_by_code(m2["code"]) or {}).get("id") == m1["id"])
        after = data.add_item("Added After Merge", "", 1, [], "")
        _check("a merged-away code is never handed to a new item",
               after["code"] not in ([merged["code"]] + list(merged.get("alt_codes") or [])))
        data.CODE_SEQ_FILE.unlink()
        after2 = data.add_item("Added After Counter Loss", "", 1, [], "")
        _check("...even when the counter file is gone",
               after2["code"] not in ([merged["code"], after["code"]]
                                      + list(merged.get("alt_codes") or [])))

        # ---- Label URLs --------------------------------------------------
        prefix = item_labels.URL_PREFIX
        _check("a bare code makes a site-relative path",
               item_labels.item_url("0042") == f"{prefix}/i/0042")
        _check("a base makes an absolute URL",
               item_labels.item_url("0042", "https://h.ts.net")
               == f"https://h.ts.net{prefix}/i/0042")
        _check("a trailing slash on the base doesn't double up",
               item_labels.item_url("0042", "https://h.ts.net/")
               == f"https://h.ts.net{prefix}/i/0042")
        _check("no code means no URL", item_labels.item_url("") == "")

        # ---- Base ranking: durability first ------------------------------
        saved_env = {k: os.environ.get(k) for k in ("PUBLIC_BASE", "TAILSCALE_FUNNEL_BASE")}
        try:
            os.environ["TAILSCALE_FUNNEL_BASE"] = "https://box.tail1234.ts.net"
            os.environ.pop("PUBLIC_BASE", None)
            opts = item_labels.base_options(8001)
            kinds = [o["kind"] for o in opts]
            _check("a public address outranks a LAN one",
                   "funnel" in kinds and kinds.index("funnel") < kinds.index("lan")
                   if "lan" in kinds else "funnel" in kinds)
            _check("the default base is the most durable option",
                   item_labels.default_base(8001) == "https://box.tail1234.ts.net")
            os.environ["PUBLIC_BASE"] = f"https://inv.example.com{prefix}"
            _check("an explicit public base wins over the funnel",
                   item_labels.default_base(8001) == "https://inv.example.com")
            _check("URL_PREFIX already in the base isn't added twice",
                   item_labels.item_url("0042", item_labels.default_base(8001))
                   == f"https://inv.example.com{prefix}/i/0042")
        finally:
            for k, v in saved_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

        # ---- A label carries everything the sheet needs ------------------
        rows = data.inventory()
        labels = item_labels.labels_for(rows, "https://h.ts.net")
        _check("one label per item", len(labels) == len(rows))
        _check("a label carries code, name and url",
               all(l["code"] and l["name"] and l["url"] for l in labels))
        _check("an item with no code yields no label",
               item_labels.label_for({"id": 1, "name": "No code"}) is None)

        # ---- The round trip a phone performs -----------------------------
        # Same qrcode.make() call the SVG label uses, rasterised so it can be
        # decoded — this is what the camera sees.
        try:
            import cv2
            import numpy as np
            import qrcode
        except Exception:
            print("SKIP - QR decode round trip (cv2/qrcode unavailable)")
        else:
            probe = data.inventory()[0]
            url = item_labels.item_url(probe["code"], "https://box.tail1234.ts.net")
            arr = np.array(qrcode.make(url).convert("RGB"))
            decoded, _pts, _ = cv2.QRCodeDetector().detectAndDecode(arr)
            _check("the QR decodes back to exactly the label URL", decoded == url)

            import app as A
            from urllib.parse import urlparse
            key = A._route_key(urlparse(decoded).path)
            _check("the decoded path routes to the scan page",
                   key == f"/i/{probe['code']}")
            _check("the code in the scanned path resolves to the right item",
                   (data.item_by_code(key[3:]) or {}).get("id") == probe["id"])

        # ---- The scan page itself ----------------------------------------
        import components_scan

        def _texts(node, out):
            if isinstance(node, str):
                out.append(node)
                return out
            ch = getattr(node, "children", None)
            if isinstance(ch, (list, tuple)):
                for x in ch:
                    _texts(x, out)
            elif ch is not None:
                _texts(ch, out)
            return out

        target = data.inventory()[0]
        data.update_item_fields(target["id"], location="Red bag", location_code="BIN-04")
        page = _texts(components_scan.scan_layout(target["code"]), [])
        _check("the scan page shows the bin it goes back in", "BIN-04" in page)
        _check("the scan page shows the bag inside the bin", "Red bag" in page)
        _check("the scan page shows the code", target["code"] in page)
        _check("the scan page shows the item name", target["name"] in page)

        missing = _texts(components_scan.scan_layout("9999"), [])
        _check("an unknown code gets a helpful not-found page",
               any("No item with that code" in t for t in missing))
        _check("a blank code doesn't crash the page",
               components_scan.scan_layout("") is not None)

        print("\nRESULT:", "ALL PASS" if _ok else "SOME FAILED")
        return 0 if _ok else 1
    finally:
        data.INVENTORY_JSON, data.CODE_SEQ_FILE = orig_inv, orig_seq


def test_main():
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
