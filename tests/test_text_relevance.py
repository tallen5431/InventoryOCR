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

    print("\nRESULT:", "ALL PASS" if ok else "SOME FAILED")
    print(f"(raw {len(raw)} chars -> filtered {len(out)} chars)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
