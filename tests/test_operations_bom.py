"""Tests for the batch bill-of-materials cost model.

A batch's cost per produced unit is the sum of each assigned material's
per-unit cost × how many that unit consumes (qty_per_unit). One purchased pack
feeds many units, so no order needs re-entering per unit.

Run: python3 tests/test_operations_bom.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
# Point both operations stores at throwaway files BEFORE importing the module,
# and rebind the module-level paths it captured at import.
_mat = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False); _mat.write("[]"); _mat.close()
_bat = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False); _bat.write("[]"); _bat.close()
config.MATERIALS_JSON = _mat.name
config.BATCHES_JSON = _bat.name

import operations_data as od
od.MATERIALS_JSON = _mat.name
od.BATCHES_JSON = _bat.name

_ok = True


def _check(name, cond):
    global _ok
    print(("PASS" if cond else "FAIL"), "-", name)
    _ok = cond and _ok


def main():
    # A pack of 20 cables for $12.99 → $0.65 each; one unit uses 1.
    cable = od.add_material("USB C Cable 20-Pack", qty=20, total_cost="$12.99")
    # A pack of 100 foam sheets for $10.90 → $0.109 each; one unit uses 2.
    foam = od.add_material("Foam Sheets 100-Pack", qty=100, total_cost="$10.90")
    # A board pack: 1 board yields 4 coasters → 0.25 board per unit, $1.52 each.
    board = od.add_material("PCB Boards", qty=50, total_cost="$75.92")

    _check("unit cost derived from total ÷ qty", abs(od.material_unit_cost(cable) - 0.6495) < 1e-6)

    batch = od.add_batch("Coaster Run", units_produced=200)
    od.set_materials_batch([cable["id"], foam["id"], board["id"]], batch["id"])

    # Default qty_per_unit is 1 for each until set.
    r0 = od.batch_rollup(od.get_batch(batch["id"]))
    _check("defaults to 1 per unit",
           all(od.material_qty_per_unit(m) == 1.0 for m in r0["materials"]))

    # Set the bill of materials: 1 cable, 2 foam, 0.25 board per produced unit.
    od.update_material(cable["id"], qty_per_unit=1)
    od.update_material(foam["id"], qty_per_unit=2)
    od.update_material(board["id"], qty_per_unit=0.25)

    r = od.batch_rollup(od.get_batch(batch["id"]))
    foam = od.get_material(foam["id"])    # re-read after the qty_per_unit update
    board = od.get_material(board["id"])
    # per-unit: 0.6495*1 + 0.109*2 + 1.5184*0.25 = 0.6495 + 0.218 + 0.3796 = 1.2471
    _check("per-material build cost (foam ×2)",
           abs(od.material_per_build_cost(foam) - 0.218) < 1e-6)
    _check("board fractional per-unit (0.25)",
           abs(od.material_per_build_cost(board) - 0.3796) < 1e-6)
    _check("cost/unit sums the bill of materials",
           abs(r["cost_per_unit"] - 1.2471) < 1e-3)
    _check("run cost = cost/unit × units",
           abs(r["run_cost"] - round(r["cost_per_unit"] * 200, 2)) < 1e-6)
    _check("purchased cost = what the packs cost",
           abs(r["purchased_cost"] - round(12.99 + 10.90 + 75.92, 2)) < 1e-6)
    _check("run cost is far below buying a pack per unit",
           r["run_cost"] < r["purchased_cost"] * 3)

    # A material with no price contributes nothing but doesn't break the sum.
    tape = od.add_material("Mystery Tape", qty=1)
    od.set_materials_batch([tape["id"]], batch["id"])
    od.update_material(tape["id"], qty_per_unit=3)
    r2 = od.batch_rollup(od.get_batch(batch["id"]))
    _check("priceless material skipped in cost/unit",
           abs(r2["cost_per_unit"] - r["cost_per_unit"]) < 1e-6)

    # No units produced → run cost unknown, cost/unit still shown.
    b2 = od.add_batch("Prototype")  # units_produced 0
    od.set_materials_batch([cable["id"]], b2["id"])
    od.update_material(cable["id"], qty_per_unit=1)
    r3 = od.batch_rollup(od.get_batch(b2["id"]))
    _check("cost/unit without units", r3["cost_per_unit"] is not None)
    _check("run cost None without units", r3["run_cost"] is None)

    print("\nRESULT:", "ALL PASS" if _ok else "SOME FAILED")
    return 0 if _ok else 1


if __name__ == "__main__":
    try:
        code = main()
    finally:
        for f in (_mat.name, _bat.name):
            try:
                os.unlink(f)
            except OSError:
                pass
    sys.exit(code)
