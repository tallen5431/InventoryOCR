"""Tests for Operations material auto-fill + unit-cost derivation.

Covers the two behaviours added to the Operations tab:
  * a saved product page fills a material's name / pack size / unit cost / specs,
    reusing product_import + price_compare (no new parsers);
  * a material derives its own unit cost from total ÷ qty.

The Dash callback itself needs a browser, so this tests the pure pieces it is
built from — the same calls the callback makes — plus the cost helpers.

Run: python3 tests/test_operations_material_parse.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import product_import as pi
import price_compare as pc
import operations_data as od

_ok = True


def _check(name, cond):
    global _ok
    print(("PASS" if cond else "FAIL"), "-", name)
    _ok = cond and _ok


# A product page whose PACK SIZE ("5 Pack") lives past the comma that the short
# display name trims — so qty must be read from the full title, not the name.
PRODUCT_HTML = """<html><head>
<meta property="og:title" content="USB C Cable 6 inch, 5 Pack Fast Charging Braided Cord">
<meta property="og:description" content="Short braided USB-C charging cable, 5 pack.">
<meta property="og:brand" content="Umefly">
<meta property="product:price:amount" content="7.59">
<meta property="product:price:currency" content="USD">
</head><body></body></html>"""


def _fill_from_product(html):
    """Mirror what stage_material_docs computes for a single product page."""
    if pi.extract_listings_from_html(html).get("ok"):
        return None  # a search page — the material form skips product auto-fill
    r = pi.extract_from_html(html, "")
    if not r.get("ok"):
        return None
    d = r.get("data", {})
    qty_src = d.get("source_title") or d.get("name") or ""
    pv = pc.per_unit_value(r.get("price") or d.get("estimated_value") or "",
                           qty_src, d.get("specifications"), d.get("what_it_is") or "")
    return {"name": d.get("name", ""), "brand": r.get("brand", ""), "pv": pv}


def main():
    if not pi._HAS_BS4:
        # extract_from_html's meta path is stdlib, so this still runs; note only.
        print("NOTE - BeautifulSoup missing; spec enrichment limited")

    got = _fill_from_product(PRODUCT_HTML)
    _check("product page parsed", got is not None)
    pv = got["pv"]
    _check("name is the short product name", got["name"] == "USB C Cable 6 inch")
    _check("pack size read from full title (5)", pv["qty"] == 5)
    _check("total price parsed", pv["list_price"] == 7.59)
    _check("unit price = 7.59 / 5", abs(pv["unit_price"] - 1.518) < 1e-6)
    _check("brand available for vendor fill", got["brand"] == "Umefly")

    # A search-results page must NOT auto-fill a single material (ambiguous).
    search = ('<html><body>'
              '<div data-component-type="s-search-result" data-asin="A1">'
              '<h2>Cable 5 Pack</h2><span class="a-price"><span class="a-offscreen">$7</span></span></div>'
              '<div data-component-type="s-search-result" data-asin="A2">'
              '<h2>Cable 10 Pack</h2><span class="a-price"><span class="a-offscreen">$9</span></span></div>'
              '</body></html>')
    _check("search page skipped for material auto-fill",
           _fill_from_product(search) is None)

    # ---- Unit-cost derivation ----
    _check("unit_cost from total ÷ qty",
           od.material_unit_cost({"total_cost": "$7.59", "qty": 5}) == 1.518)
    _check("explicit unit_cost preferred",
           od.material_unit_cost({"unit_cost": "$2.00", "total_cost": "$7.59", "qty": 5}) == 2.0)
    _check("no price → None",
           od.material_unit_cost({"qty": 5}) is None)
    _check("qty 0 with only total → None",
           od.material_unit_cost({"total_cost": "$7.59", "qty": 0}) is None)
    _check("total cost still prefers explicit total",
           od.material_cost({"total_cost": "$7.59", "unit_cost": "$1.00", "qty": 5}) == 7.59)
    _check("total cost falls back to unit × qty",
           od.material_cost({"unit_cost": "$1.50", "qty": 4}) == 6.0)

    print("\nRESULT:", "ALL PASS" if _ok else "SOME FAILED")
    return 0 if _ok else 1


if __name__ == "__main__":
    sys.exit(main())
