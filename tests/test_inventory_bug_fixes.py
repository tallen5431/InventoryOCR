"""Regression tests for the Inventory Manager / import / OCR bug fixes.

These lock in the behaviour changes made after a codebase review that used the
user's real exported inventory to surface data-quality bugs:

  * hand tools no longer fall through Type classification to "Other";
  * a stray non-canonical Type (e.g. "Label Printer") is normalised on load;
  * Merge duplicates never auto-merges different sizes that share a code
    (M3x10 vs M3x16), and keeps the searchable source_title;
  * item_value recovers a pack total in any currency, not just "$";
  * auto_organize clusters singular/plural category variants together;
  * product-import price/name/spec/image extraction fixes;
  * invoice order-number vs date, and Total vs Total-Due/$0.00;
  * price-per-unit handles "N+M Pcs" bonus packs;
  * text_relevance keeps pipe-delimited spec rows and real "Quantity: N" lines.

No Tesseract or network needed. Run: python3 tests/test_inventory_bug_fixes.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data
import product_import as pi
import invoice_parse as ip
import price_compare as pc
import text_relevance as tr

_ok = True


def _check(name, cond):
    global _ok
    print(("PASS" if cond else "FAIL"), "-", name)
    _ok = cond and _ok


# ---------------------------------------------------------------------------
# Type classification + normalisation
# ---------------------------------------------------------------------------
def test_type_classification():
    def t(name):
        return data._classify_type({"name": name, "category": "", "tags": []})

    for nm in ("Precision Tweezers Set 6PCS", "WGGE 8-inch Wire Stripper",
               "Side Cutting Nippers Wire Cutters", "RB3000 Deburring Tool",
               "Commercial Electric Digital Multi-Meter", "Soldering Iron Kit"):
        _check(f"'{nm[:28]}' -> Tools", t(nm) == "Tools")

    # Must NOT drag non-tools into Tools.
    _check("resistor -> Components", t("Chanzon 100pcs 4.7K ohm Resistor") == "Components")
    _check("ethernet cable -> Cables", t("Cat6 Ethernet Cable 1FT") == "Cables & Adapters")
    _check("cable ties -> Consumables", t("HMROPE 60PCS Fastening Cable Ties") == "Consumables")
    _check("cooler backpack -> Other", t("Tenot Cooler Backpack 33 Cans") == "Other")


def test_type_normalised_on_load():
    saved = data._load
    try:
        data._load = lambda: [
            {"id": 1, "name": "Core Innovations Bluetooth Label Maker", "type": "Label Printer"},
            {"id": 2, "name": "Something", "type": "Tools"},  # canonical stays
        ]
        rows = {r["id"]: r for r in data.inventory()}
        _check("non-canonical 'Label Printer' normalised",
               rows[1]["type"] in data.TYPE_GROUPS and rows[1]["type"] != "Label Printer")
        _check("canonical 'Tools' preserved", rows[2]["type"] == "Tools")
    finally:
        data._load = saved


# ---------------------------------------------------------------------------
# Merge duplicates: size guard + source_title
# ---------------------------------------------------------------------------
def test_merge_size_guard():
    bal = data.DUP_LEVELS["balanced"]

    def sim(a, b, ca="", cb=""):
        return data.item_similarity({"name": a, "category": ca},
                                    {"name": b, "category": cb})

    s = sim("M3 x 10mm Socket Head Screw", "M3 x 16mm Socket Head Screw", "Screws", "Screws")
    _check("M3x10 vs M3x16 below auto-merge tier", s < bal)
    s2 = sim("AA Battery", "9V Battery", "Batteries", "Batteries")
    _check("AA vs 9V below auto-merge tier", s2 < bal)
    s3 = sim("600 Pcs M3 Screws Kit", "600 Pcs M3 Screws Kit")
    _check("identical names still auto-merge", s3 >= bal)


def test_merge_keeps_source_title():
    primary = {"id": 1, "name": "Pliers", "source_title": "", "qty": 1}
    dup = {"id": 2, "name": "Pliers",
           "source_title": "WORKPRO 6-inch Long Nose Pliers", "qty": 1}
    merged = data.merge_preview([primary, dup], primary=primary)
    _check("merge_preview surfaces a source_title key", "source_title" in merged)
    _check("merged source_title kept from the duplicate",
           merged.get("source_title") == "WORKPRO 6-inch Long Nose Pliers")


# ---------------------------------------------------------------------------
# item_value: currency-agnostic pack total
# ---------------------------------------------------------------------------
def test_pack_value_any_currency():
    usd = data.item_value({"estimated_value": "$0.03",
                           "specifications": ["$0.03 each (pack of 300 @ $7.99)"]})
    _check("USD pack total recovered ($7.99)", usd == 7.99)
    eur = data.item_value({"estimated_value": "€0.05",
                           "specifications": ["€0.05 each (pack of 300 @ €13.99)"]})
    _check("EUR pack total recovered (13.99)", eur == 13.99)
    # A spec line with a bare "@ 250V" must NOT be recovered as a pack price:
    # the item's value should stay its estimated_value, not the 250 in the spec.
    volts = data.item_value({"estimated_value": "$5.00",
                             "specifications": ["Input voltage @ 250V"]})
    _check("'@ 250V' spec not mistaken for a pack price", volts == 5.00)


def test_auto_organize_singular_plural():
    rows = [
        {"id": 1, "name": "Toggle Switch A", "category": "Toggle Switch", "qty": 1},
        {"id": 2, "name": "Slide Switch B", "category": "Slide Switches", "qty": 1},
        {"id": 3, "name": "Lone Widget", "category": "Gizmos", "qty": 1},
    ]
    plan = data.auto_organize(rows)
    groups = {tuple(sorted(g["item_ids"])) for g in plan}
    _check("singular+plural switch categories cluster", (1, 2) in groups)


# ---------------------------------------------------------------------------
# product_import
# ---------------------------------------------------------------------------
def test_short_name_thousands_comma():
    nm = pi._short_name("Precision Resistor Kit 1,000 Pcs 1% Metal Film Through Hole")
    _check("thousands comma not truncated", "1,000" in nm and nm.endswith("Hole"))
    cut = pi._short_name("Widget Model X, Blue, Large, Pack of 3")
    _check("real ', ' list separator still cuts", cut == "Widget Model X")


def test_isolate_specs_late_dimensions():
    pairs = [(f"Spec{i}", f"val{i}") for i in range(20)]
    pairs.append(("Product Dimensions", "3 x 4 x 5 inches"))
    specs, dims = pi._isolate_specs(pairs)
    _check("dimensions captured past the 15-spec cap", dims == "3 x 4 x 5 inches")
    _check("spec list still capped at 15", len(specs) == 15)


def test_jsonld_image_list_of_objects():
    block = ('{"@type":"Product","name":"Foo",'
             '"image":[{"@type":"ImageObject","url":"https://x/y.jpg"}]}')
    prod = pi._product_from_jsonld([block])
    _check("image list-of-ImageObjects yields the URL",
           prod and prod.get("image_url") == "https://x/y.jpg")


def test_amazon_price_skips_strikethrough():
    if not getattr(pi, "_HAS_BS4", False):
        print("SKIP - bs4 unavailable; strikethrough-price test")
        return
    html = ('<html><body>'
            '<span class="a-price a-text-price"><span class="a-offscreen">$12.99</span></span>'
            '<span class="a-price"><span class="a-offscreen">$7.99</span></span>'
            '</body></html>')
    enr = pi._enrich_with_bs4(html)
    _check("live price beats struck-through list price", enr.get("price") == "$7.99")


# ---------------------------------------------------------------------------
# invoice_parse
# ---------------------------------------------------------------------------
def test_invoice_order_vs_date():
    _check("bare date after label is not the order id",
           ip._find_order("Invoice 2026-06-14 thank you") == "")
    _check("real order id still found",
           ip._find_order("Order # 112-4472839-1234567 shipped") == "112-4472839-1234567")


def test_invoice_total_due_zero():
    txt = "Subtotal: $20.00\nTax: $3.98\nTotal: $23.98\nTotal Due: $0.00"
    _check("plain Total beats Total Due $0.00", ip._find_total(txt) == "$23.98")
    _check("lone Total Due still read", ip._find_total("Total Due: $15.00") == "$15.00")


# ---------------------------------------------------------------------------
# price_compare
# ---------------------------------------------------------------------------
def test_bonus_pack_quantity():
    qty, _ = pc.detect_quantity("FFVRVSS 300+6Pcs M2 M3 Brass Threaded Inserts")
    _check("'300+6Pcs' detected as 306", qty == 306)
    pu = pc.per_unit_value("$7.99", "FFVRVSS 300+6Pcs Threaded Inserts")
    _check("per-unit divides by 306, not 6", pu["qty"] == 306)


# ---------------------------------------------------------------------------
# text_relevance
# ---------------------------------------------------------------------------
def test_text_relevance_specs_survive():
    out = tr.for_index("Input | 5V | 2A\nQuantity: 600 pieces\nBuy now\nQuantity")
    lines = [ln.strip().lower() for ln in out.splitlines()]
    _check("pipe-delimited spec row kept", "5V" in out and "2A" in out)
    _check("'Quantity: 600 pieces' spec kept", "600" in out)
    _check("bare 'Quantity' selector dropped", "quantity" not in lines)


# ---------------------------------------------------------------------------
# OCR auto-naming (fill a placeholder name from a confident OCR line)
# ---------------------------------------------------------------------------
def test_is_placeholder_name():
    for nm in ("", "   ", "Item 0007", "item0007", "ITEM 12"):
        _check(f"placeholder: {nm!r}", data.is_placeholder_name(nm) is True)
    for nm in ("WINSINN Blower Fan", "Micro USB to USB-A", "Duct Tape"):
        _check(f"real name kept: {nm!r}", data.is_placeholder_name(nm) is False)


def test_best_title_from_ocr():
    name = tr.best_title("| ( BO79BPS9Qé& WINSINN 5015 24V DC Blower Fan j | Made in China")
    _check("clean product line -> name", "Blower Fan" in name and "WINSINN" in name)
    _check("ASIN code dropped from name", "BO79BPS9" not in name)
    # Garbled OCR soup must NOT produce a name (conservative abstain).
    for soup in ("we wwe oewwe © we owwew ewww dw weeee Ol line a8 seas i",
                 "ISR rece is", "Prat", "a ie Meee", "re pee Pe Rens ee"):
        _check(f"soup abstains: {soup[:18]!r}", tr.best_title(soup) == "")


def main():
    test_type_classification()
    test_type_normalised_on_load()
    test_merge_size_guard()
    test_merge_keeps_source_title()
    test_pack_value_any_currency()
    test_auto_organize_singular_plural()
    test_short_name_thousands_comma()
    test_isolate_specs_late_dimensions()
    test_jsonld_image_list_of_objects()
    test_amazon_price_skips_strikethrough()
    test_invoice_order_vs_date()
    test_invoice_total_due_zero()
    test_bonus_pack_quantity()
    test_text_relevance_specs_survive()
    test_is_placeholder_name()
    test_best_title_from_ocr()
    print("\nRESULT:", "ALL PASS" if _ok else "FAILURES ABOVE")
    return 0 if _ok else 1


if __name__ == "__main__":
    sys.exit(main())
