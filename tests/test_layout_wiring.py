"""Cross-checks every callback's component ids against the real layouts.

The app runs with ``suppress_callback_exceptions=True`` — it has to, because
each page's layout is built on demand by ``display_page`` — which means a
callback that references an id no component ever creates simply never fires.
No error, no warning, just a button that does nothing. Nothing else in the
suite builds a layout at all, so that class of mistake was completely
unguarded.

This walks the four page layouts plus the always-mounted shell, collects every
id, and asserts that:

  * no id is declared twice in the same layout (Dash silently misbehaves, and
    the duplicate's callbacks fire against whichever copy the DOM finds first);
  * every id a callback *outputs* to exists in some layout — an Output with no
    component is a dead callback.

Some components are legitimately built inside a callback rather than in a page
layout (modal bodies, the price-writeback bar, generated rows), so an id
missing from the static layouts is not on its own an error. The Output check
therefore also accepts any id constructed anywhere in the source — which still
catches the failure mode that matters: an Output naming an id that no component
constructor uses at all, i.e. a typo or a rename that missed a caller.

Callback *inputs* are not checked; the same dynamic-creation caveat applies and
there is no equally cheap way to distinguish a typo from a dynamic input.

Run: python3 tests/test_layout_wiring.py
"""
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ok = True


def _check(name, cond):
    global _ok
    print(("PASS" if cond else "FAIL"), "-", name)
    _ok = cond and _ok


def _walk_ids(node, out):
    """Collect every string id in a Dash component tree (pattern ids skipped)."""
    cid = getattr(node, "id", None)
    if isinstance(cid, str) and cid:
        out.append(cid)
    children = getattr(node, "children", None)
    if isinstance(children, (list, tuple)):
        for c in children:
            _walk_ids(c, out)
    elif children is not None:
        _walk_ids(children, out)
    return out


def main():
    import app as A

    layouts = {
        "dashboard": A.dashboard_layout(),
        "ocr-lab": A.ocr_lab_layout(),
        "price-compare": A.price_compare_layout(),
        "operations": A.operations_layout(),
        "shell": A.app.layout,
    }

    all_ids = set()
    for page, layout in layouts.items():
        ids = _walk_ids(layout, [])
        dupes = [i for i, n in Counter(ids).items() if n > 1]
        _check(f"{page}: no duplicate component ids", not dupes)
        if dupes:
            print("      duplicates:", sorted(dupes))
        all_ids.update(ids)

    _check("layouts actually built (sanity)", len(all_ids) > 100)

    # Ids constructed anywhere in the source, for components a callback builds
    # at runtime rather than a layout declaring up front.
    constructed = set()
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for fn in os.listdir(repo):
        if not fn.endswith(".py"):
            continue
        with open(os.path.join(repo, fn), encoding="utf-8") as fh:
            for m in re.finditer(r"""id\s*=\s*["']([A-Za-z0-9_-]+)["']""", fh.read()):
                constructed.add(m.group(1))
    known = all_ids | constructed

    # Every callback Output must have a component to write to.
    missing = set()
    for key, spec in A.app.callback_map.items():
        outs = spec.get("output")
        outs = outs if isinstance(outs, (list, tuple)) else [outs]
        for out in outs:
            cid = getattr(out, "component_id", None)
            if isinstance(cid, str) and cid and cid not in known:
                missing.add(cid)
    _check("every callback Output targets a component that exists", not missing)
    if missing:
        print("      outputs with no component anywhere:", sorted(missing))

    # Ids built only at runtime, listed so an unexpected new one is visible.
    dynamic = sorted(
        cid for spec in A.app.callback_map.values()
        for out in ((spec.get("output"),) if not isinstance(spec.get("output"), (list, tuple))
                    else spec["output"])
        for cid in [getattr(out, "component_id", None)]
        if isinstance(cid, str) and cid and cid not in all_ids
    )
    print(f"      ({len(dynamic)} output id(s) built at runtime, not in a static layout)")

    print("\nRESULT:", "ALL PASS" if _ok else "SOME FAILED")
    return 0 if _ok else 1


def test_main():
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
