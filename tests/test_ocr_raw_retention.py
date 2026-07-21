"""Tests that the full raw OCR scan (ocr_raw) is retained across the data layer
without ever leaking into the search index.

The trimmed, item-relevant copy lives in ``ocr_text`` (searchable); the full,
unfiltered scan lives in ``ocr_raw`` (kept for reference / re-processing, never
searched). This guards the contract between them.

Run: python3 tests/test_ocr_raw_retention.py   (no pytest dependency required)
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data

# Redirect every read/write to a throwaway file so the real inventory is never
# touched. data.py reads the module global at call time, so setting it here is
# enough.
_tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
_tmp.write("[]")
_tmp.close()
data.INVENTORY_JSON = _tmp.name

_ok = True


def _check(name, cond):
    global _ok
    print(("PASS" if cond else "FAIL"), "-", name)
    _ok = cond and _ok


def _get(iid):
    return next(x for x in data.inventory() if x["id"] == iid)


def main():
    # 1) A new item defaults ocr_raw to "".
    row = data.add_item("Widget A", "", 1, [], "trimmed searchable text")
    _check("add_item stores trimmed ocr_text", row["ocr_text"] == "trimmed searchable text")
    _check("add_item defaults ocr_raw empty", row.get("ocr_raw", "MISSING") == "")
    iid = row["id"]

    # 2) The background write-back stores BOTH the trimmed copy and the raw scan.
    data.set_ocr_text(iid, "trimmed line one", merge=True,
                      raw="RAWTOKEN full page nav cross-sell reviews footer")
    r = _get(iid)
    _check("set_ocr_text merged trimmed", "trimmed line one" in r["ocr_text"])
    _check("set_ocr_text stored raw", r["ocr_raw"].startswith("RAWTOKEN"))

    # 3) Raw text is kept OUT of the search index; trimmed text is searchable.
    _check("raw text is NOT searchable",
           all(h["id"] != iid for h in data.search("RAWTOKEN")))
    _check("trimmed text IS searchable",
           any(h["id"] == iid for h in data.search("searchable")))

    # 4) A plain form edit (no ocr_raw arg) must NOT wipe the retained raw.
    data.update_item(iid, "Widget A", "new desc", 2, [], "user edited trimmed text")
    r = _get(iid)
    _check("edit updates trimmed ocr_text", r["ocr_text"] == "user edited trimmed text")
    _check("edit preserves ocr_raw", r["ocr_raw"].startswith("RAWTOKEN"))

    # 5) Clearing the trimmed text via the form leaves the raw scan intact.
    data.update_item(iid, "Widget A", "new desc", 2, [], "")
    r = _get(iid)
    _check("clear empties trimmed ocr_text", r["ocr_text"] == "")
    _check("clear preserves ocr_raw", r["ocr_raw"].startswith("RAWTOKEN"))

    # 6) A second scan merges new raw onto the existing raw (deduped).
    data.set_ocr_text(iid, "second trimmed", merge=True, raw="SECONDRAW extra scan")
    r = _get(iid)
    _check("raw merge keeps first raw", "RAWTOKEN" in r["ocr_raw"])
    _check("raw merge adds second raw", "SECONDRAW" in r["ocr_raw"])

    # 7) raw=None leaves the stored raw untouched.
    before = r["ocr_raw"]
    data.set_ocr_text(iid, "third trimmed", merge=True, raw=None)
    _check("raw=None leaves raw untouched", _get(iid)["ocr_raw"] == before)

    # 8) Merges carry raw across combined items — and it still isn't searchable.
    row2 = data.add_item("Widget B", "", 1, [], "b trimmed")
    data.set_ocr_text(row2["id"], "b trimmed", merge=False, raw="BRAW only-on-b")
    preview = data.merge_preview([_get(iid), _get(row2["id"])])
    _check("merge_preview includes both raws",
           "RAWTOKEN" in preview["ocr_raw"] and "BRAW" in preview["ocr_raw"])
    merged = data.merge_group(iid, [row2["id"]])
    _check("merge_group carries raw onto survivor",
           "RAWTOKEN" in merged["ocr_raw"] and "BRAW" in merged["ocr_raw"])
    _check("merge_group raw still not searchable",
           all(h["id"] != iid for h in data.search("BRAW")))

    print("\nRESULT:", "ALL PASS" if _ok else "SOME FAILED")
    return 0 if _ok else 1


if __name__ == "__main__":
    try:
        code = main()
    finally:
        try:
            os.unlink(_tmp.name)
        except OSError:
            pass
    sys.exit(code)
