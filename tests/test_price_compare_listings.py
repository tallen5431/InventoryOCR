"""Tests for multi-listing (search results) handling in Price Compare.

A saved *search results* page holds many listings; the analyzer must expand each
into its own comparable product (catching per-card pack sizes), while a single
product-detail page — even one carrying a sponsored carousel — stays one product.

Run: python3 tests/test_price_compare_listings.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import product_import as pi
import price_compare as pc

_ok = True


def _check(name, cond):
    global _ok
    print(("PASS" if cond else "FAIL"), "-", name)
    _ok = cond and _ok


def _card(asin, title, price, list_price=None):
    strike = (f'<span class="a-price a-text-price"><span class="a-offscreen">'
              f'{list_price}</span></span>' if list_price else "")
    return f'''
    <div data-component-type="s-search-result" data-asin="{asin}">
      <h2><a class="a-link-normal" href="/dp/{asin}/ref=sr_1_1"><span>{title}</span></a></h2>
      {strike}
      <span class="a-price"><span class="a-offscreen">{price}</span></span>
      <img class="s-image" src="https://img/{asin}.jpg"/>
    </div>'''


SEARCH_HTML = "<html><body>" + "".join([
    _card("B00000AAA1", "USB C Cable, 10 Pack Fast Charging 6in", "$8.99", list_price="$14.99"),
    _card("B00000AAA2", "USB C Cable, 5 Pack Braided 6 inch", "$7.59"),
    _card("B00000AAA3", "USB C Cable Single 6 inch Premium", "$6.29"),
    # Duplicate ASIN (Amazon repeats sponsored + organic) — must collapse to one.
    _card("B00000AAA1", "USB C Cable 10-Pack (sponsored copy)", "$8.99"),
]) + "</body></html>"

# A product-detail page that also embeds a sponsored results carousel. The
# #productTitle tell must keep it a SINGLE product, not a results page.
PRODUCT_HTML = ("<html><body>"
                '<span id="productTitle">Widget USB C Cable 3-Pack 6 inch</span>'
                + _card("B0CAROUS1", "Unrelated 20 Pack Carousel Item", "$99.00")
                + _card("B0CAROUS2", "Another 20 Pack Carousel Item", "$88.00")
                + "</body></html>")


def main():
    if not pi._HAS_BS4:
        print("SKIP - BeautifulSoup not available; listing extraction is a no-op")
        return 0

    # 1) The search page expands into one product per unique listing.
    listings = pi.extract_listings_from_html(SEARCH_HTML)
    _check("search page detected as listing", listings["ok"] is True)
    _check("duplicate ASIN collapsed (3 unique)", len(listings["products"]) == 3)

    res = pc.analyze_htmls([("search.html", SEARCH_HTML)])
    prods = res["products"]
    _check("three comparable products", len(prods) == 3)

    by_asin = {p["name"][:20]: p for p in prods}
    ten = next(p for p in prods if p["quantity"] == 10)
    five = next(p for p in prods if p["quantity"] == 5)
    one = next(p for p in prods if p["quantity"] == 1)
    _check("10-pack qty detected", ten["quantity"] == 10)
    _check("10-pack unit price = 8.99/10", abs(ten["unit_price"] - 0.899) < 1e-6)
    _check("5-pack qty detected", five["quantity"] == 5)
    _check("single item qty 1", one["quantity"] == 1)
    _check("live price beats struck-through list price",
           ten["price_value"] == 8.99)
    _check("best value is the 10-pack (lowest per-unit)",
           res["best"] is not None and res["best"]["quantity"] == 10)
    _check("canonical /dp/ url built", "/dp/B00000AAA1" in ten.get("url", ""))

    # 2) A product page with a carousel stays ONE product (guard via #productTitle).
    guard = pi.extract_listings_from_html(PRODUCT_HTML)
    _check("product page NOT treated as listing", guard["ok"] is False)
    single = pc.analyze_htmls([("product.html", PRODUCT_HTML)])
    _check("product page yields exactly one product", len(single["products"]) == 1)
    _check("single product keeps its own 3-pack size",
           single["products"][0]["quantity"] == 3)

    print("\nRESULT:", "ALL PASS" if _ok else "SOME FAILED")
    return 0 if _ok else 1


if __name__ == "__main__":
    sys.exit(main())
