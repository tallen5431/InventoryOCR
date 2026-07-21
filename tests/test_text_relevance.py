"""Tests for text_relevance.for_index against a real Amazon-listing screenshot OCR.

Run: python3 tests/test_text_relevance.py   (no pytest dependency required)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import text_relevance as tr

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                       "amazon_soldering_screenshot.txt")


def _load():
    with open(FIXTURE, encoding="utf-8") as f:
        return f.read()


def _check(name, cond):
    print(("PASS" if cond else "FAIL"), "-", name)
    return cond


def main():
    raw = _load()
    out = tr.for_index(raw)
    low = out.lower()
    ok = True

    print("\n===== FILTERED OUTPUT =====\n")
    print(out)
    print("\n===== ASSERTIONS =====")

    # --- item-relevant content MUST survive ---
    keep_terms = [
        "adjustable temperature",         # About this item
        "ceramic heating element",        # About this item
        "desoldering pump",               # About / contents
        "solder rosin flux paste",        # About this item contents
        "temperature range",              # spec table (Product description)
        "power consumption",              # spec table
        "heat resistant grip",            # product-description knob section
        "eutectic solder",                # product-description solder blurb
    ]
    for t in keep_terms:
        ok &= _check(f"keeps item text: {t!r}", t in low)

    # --- cross-sell / unrelated products MUST be gone (these cause false hits) ---
    drop_terms = [
        "fiskars",            # completely unrelated sponsored Tree Pruner
        "tree pruner",
        "yihua",              # a different soldering station brand
        "multimeter",         # "Customers also bought" item
        "wep 982",            # cross-sell soldering stations
        "bigstone",           # related-products item
        "lumvelle",           # brands-in-this-category
        "customers also bought",
        "products related to this item",
        "more from frequently bought",
    ]
    for t in drop_terms:
        ok &= _check(f"drops cross-sell: {t!r}", t not in low)

    # --- reviews MUST be gone ---
    review_terms = [
        "reviewed in the united states",
        "verified purchase",
        "people found this helpful",
        "fantastic value",
        "customers say",
        "top reviews",
    ]
    for t in review_terms:
        ok &= _check(f"drops reviews: {t!r}", t not in low)

    # --- navigation / buy-box / footer MUST be gone ---
    chrome_terms = [
        "prime video",
        "whole foods",
        "kindle books",
        "add to cart",
        "in stock",
        "return guarantee",   # footer boilerplate
        "bought in past month",
    ]
    for t in chrome_terms:
        ok &= _check(f"drops chrome: {t!r}", t not in low)

    # --- fallback: a plain (non-retailer) snippet is kept as-is ---
    plain = ("DEWALT DCD771 20V MAX Cordless Drill\n"
             "Chuck size: 1/2 inch\nBattery: 20V lithium ion\nMax torque 300 in-lbs")
    fout = tr.for_index(plain).lower()
    ok &= _check("fallback keeps plain label text (dewalt)", "dewalt" in fout)
    ok &= _check("fallback keeps plain spec (torque)", "torque" in fout)

    # --- empty / whitespace is safe ---
    ok &= _check("empty input -> empty", tr.for_index("") == "")
    ok &= _check("whitespace input -> empty", tr.for_index("   \n  ") == "")

    # --- size sanity: filtered is much smaller than raw ---
    ok &= _check("filtered is smaller than raw",
                 len(out) < 0.6 * len(raw))

    print("\n----- regression cases from adversarial review -----")

    def case(name, text):
        r = tr.for_index(text)
        return r, r.lower()

    # #1/#2 eBay: "Item specifics" is the anchor; cross-sell must drop, specs stay.
    _o, l = case("ebay", """Fluke 117 Electricians True RMS Multimeter
Item specifics
Condition: New
Brand: Fluke
Model: 117
MPN: FLUKE-117
Type: Digital Multimeter
People who viewed this item also viewed
Fluke 115 Compact True RMS Multimeter
Klein Tools MM600 Auto Ranging Multimeter
Fluke 101 Basic Digital Multimeter""")
    ok &= _check("eBay keeps item specifics (mpn)", "mpn" in l and "fluke-117" in l)
    ok &= _check("eBay keeps spec (digital multimeter)", "digital multimeter" in l)
    ok &= _check("eBay drops cross-sell (klein tools)", "klein tools" not in l)
    ok &= _check("eBay drops cross-sell (fluke 115)", "fluke 115" not in l)

    # #6 Walmart: "Customer ratings & reviews" header must switch to drop.
    _o, l = case("walmart", """BLACK+DECKER LDX120C 20V MAX Cordless Drill
About this item
20V MAX lithium-ion battery for long run time
11 position clutch prevents stripping
Specifications
Chuck Size: 3/8 in
Battery Type: Lithium Ion
Customer ratings & reviews
4.5 out of 5 stars 1203 reviews
Write a review
Works great for hanging pictures and furniture
Similar items you might like
DEWALT 20V MAX Cordless Drill
CRAFTSMAN V20 Cordless Drill""")
    ok &= _check("Walmart keeps spec (chuck size)", "chuck size" in l)
    ok &= _check("Walmart drops reviews (works great)", "works great" not in l)
    ok &= _check("Walmart drops similar item (dewalt)", "dewalt" not in l)
    ok &= _check("Walmart drops similar item (craftsman)", "craftsman" not in l)

    # #3 A leading DROP header must NOT empty a legit item's text.
    _o, l = case("lead-sponsored", """Sponsored
Anker 737 Power Bank (PowerCore 24K)
24000mAh 3-Port Portable Charger with 140W Output
Compatible with iPhone 15, MacBook, Dell XPS
Model A1289, black""")
    ok &= _check("leading 'Sponsored' keeps item (24000mah)", "24000mah" in l)
    ok &= _check("leading 'Sponsored' keeps model", "a1289" in l)

    _o, l = case("lead-important", """IMPORTANT INFORMATION
Contains natural rubber latex which may cause allergic reactions.
Nitrile examination gloves, powder-free, box of 100.
Model RX-40, size large.
Manufactured by MediGlove, lot 22981.""")
    ok &= _check("leading 'IMPORTANT INFORMATION' keeps item (nitrile)", "nitrile" in l)
    ok &= _check("leading 'IMPORTANT INFORMATION' keeps model (rx-40)", "rx-40" in l)

    # #7 A mid-page shelf label must not truncate the specs below it (fallback).
    _o, l = case("mid-sponsored", """Sponsored
Model AX55 v2
Processor 1.5GHz triple-core CPU
Memory 256MB RAM
Dimensions 260 x 135 x 38 mm
Weight 0.5 kg""")
    ok &= _check("mid-page shelf label keeps specs (triple-core)", "triple-core" in l)
    ok &= _check("mid-page shelf label keeps specs (256mb ram)", "256mb ram" in l)

    # #5 A short line merely containing a drop marker must not flip to drop.
    _o, l = case("contained-marker", """About this item
Great value from the brand
Torque 300 in-lbs adjustable metal chuck
Includes lithium battery and charger""")
    ok &= _check("contained 'from the brand' keeps following specs (torque)",
                 "torque 300" in l)
    ok &= _check("contained 'from the brand' keeps following specs (lithium)",
                 "lithium battery" in l)

    # #8 Accented spec lines must survive (NFKD fold + apostrophe intra-word).
    o8, l8 = case("accents", """Caractéristiques
Référence: XT-4021
Numéro de série imprimé sous l'appareil
Réglé à l'usine""")
    ok &= _check("accented line survives (réglé à l'usine)", "réglé à l" in l8)
    ok &= _check("accented ref survives (xt-4021)", "xt-4021" in l8)

    print("\nRESULT:", "ALL PASS" if ok else "SOME FAILED")
    print(f"(raw {len(raw)} chars -> filtered {len(out)} chars)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
