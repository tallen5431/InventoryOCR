"""Tests for text_extract.extract — structured fields pulled from OCR text.

Precision matters most here: a false UPC or a sentence mistaken for a "field"
pollutes the search index it feeds, so these assert both that real fields are
found AND that ordinary prose / bad barcodes are rejected.

Run: python3 tests/test_text_extract.py   (no pytest dependency required)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import text_extract as te

_ok = True


def _check(name, cond):
    global _ok
    print(("PASS" if cond else "FAIL"), "-", name)
    _ok = cond and _ok


def main():
    page = """About this item
Brand: DeWalt
Item model number: DCD771C2
Voltage: 20 V
Color: Yellow / Black
This is great value from the brand you trust
UPC 885911475013
ASIN B00ET5VMTU
Capacity 5000mAh
"""
    got = te.extract(page)
    _check("brand detected", "Brand: DeWalt" in got)
    _check("model detected", "Model: DCD771C2" in got)
    _check("voltage detected", any(g.startswith("Voltage:") for g in got))
    _check("valid UPC detected", "UPC: 885911475013" in got)
    _check("ASIN detected", "ASIN: B00ET5VMTU" in got)
    _check("capacity detected", any("mah" in g.lower() for g in got))
    _check("prose 'from the brand' NOT a field",
           not any(g.lower().startswith("brand: this") for g in got))

    # Checksum gating: a 12-digit run with a bad check digit must be rejected.
    _check("bad-checksum barcode rejected",
           not any("885911475010" in g for g in te.extract("UPC 885911475010")))
    # EAN-13 with an internal hyphen in the label must not be sliced at it.
    _check("EAN-13 label parsed whole",
           "EAN: 4006381333931" in te.extract("EAN-13: 4006381333931"))
    # A barcode OCR'd with spaces still normalises to clean digits.
    _check("spaced barcode canonicalised",
           "UPC: 885911475013" in te.extract("UPC: 8 85911 47501 3"))

    # Single-valued labels keep only the first hit; identifiers may repeat.
    multi = te.extract("Brand: Acme\nBrand: Acme Corp\nUPC 885911475013\nASIN B00ET5VMTU")
    _check("single-valued label deduped",
           len([g for g in multi if g.startswith("Brand:")]) == 1)

    # Pure prose / empty yields nothing.
    _check("prose yields no fields",
           te.extract("just some ordinary words with no structured data here") == [])
    _check("empty yields no fields", te.extract("") == [])

    # An unspaced hyphen (Wi-Fi) is not treated as a separator.
    _check("hyphenated word not split",
           not any(g.startswith("Wi:") for g in te.extract("Wi-Fi: 802.11ac")))

    print("\nRESULT:", "ALL PASS" if _ok else "SOME FAILED")
    return 0 if _ok else 1


if __name__ == "__main__":
    sys.exit(main())
