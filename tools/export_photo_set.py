#!/usr/bin/env python3
"""Bundle your item photos together with the entry each one belongs to.

Run this on the machine that holds your inventory. It produces one folder (and
optionally one .zip) containing every photo plus a manifest that says which item
each photo came from — so nothing has to be matched up by hand later, and there
is no chance of a photo being attributed to the wrong entry.

    python3 tools/export_photo_set.py
    python3 tools/export_photo_set.py --type Components --max-edge 1024 --zip

What you get:

    photo_set/
      manifest.csv        one row per photo: file, code, name, type, category,
                          location, bin, qty  (open it in a spreadsheet if you like)
      manifest.json       the same thing, plus the full item records
      images/0042-1.jpg   photos, renamed <code>-<n> so the link is visible even
                          if the manifest is lost
      README.txt          what this is and what was included

Nothing is uploaded and nothing in your inventory is modified — this only reads.

Only stdlib is required. Pillow is used if present to downscale (--max-edge),
which usually shrinks the bundle by 10-20x with no effect on matching.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Photos moved out of assets/ into userdata/ in the QR-label release; check both
# so this works on an install that hasn't been restarted since the upgrade.
IMAGE_DIRS = [REPO / "userdata" / "images", REPO / "assets" / "images"]


def find_images_dir(explicit: str | None, required: bool = True) -> Path | None:
    if explicit:
        p = Path(explicit).expanduser()
        if not p.is_dir():
            sys.exit(f"error: --images {p} is not a directory")
        return p
    for p in IMAGE_DIRS:
        if p.is_dir() and any(p.iterdir()):
            return p
    if not required:
        # --report-only still has something useful to say about an inventory whose
        # photo folder is empty or elsewhere: namely that nothing can be found by
        # photo yet. Dying here would withhold exactly that answer.
        return None
    sys.exit("error: couldn't find a photo folder. Pass --images /path/to/images")


def load_inventory(explicit: str | None) -> list:
    p = Path(explicit).expanduser() if explicit else REPO / "inventory.json"
    if not p.is_file():
        sys.exit(f"error: no inventory at {p}. Pass --inventory /path/to/inventory.json")
    try:
        rows = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        sys.exit(f"error: couldn't read {p}: {e}")
    if not isinstance(rows, list):
        sys.exit(f"error: {p} is not a JSON list")
    return [r for r in rows if isinstance(r, dict)]


def downscale(src: Path, dst: Path, max_edge: int) -> bool:
    """Copy src to dst, shrinking the long edge to max_edge. False if Pillow is absent."""
    try:
        from PIL import Image
    except ImportError:
        return False
    try:
        with Image.open(src) as im:
            im.load()
            if max(im.size) > max_edge:
                im.thumbnail((max_edge, max_edge), Image.LANCZOS)
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            im.save(dst.with_suffix(".jpg"), "JPEG", quality=88)
        return True
    except Exception:
        return False


def report(rows, img_dir) -> int:
    """Describe the inventory's readiness for a visual search, changing nothing."""
    from collections import Counter
    total = len(rows)
    withphoto = [r for r in rows if r.get("images")]
    n_photos = sum(len(r["images"]) if isinstance(r.get("images"), list) else 1
                   for r in withphoto)
    on_disk = 0 if img_dir is None else sum(
        1 for r in withphoto
        for fn in (r["images"] if isinstance(r["images"], list) else [r["images"]])
        if (img_dir / str(fn)).is_file())
    withbin = [r for r in withphoto if (r.get("location_code") or "").strip()]
    multi = [r for r in withphoto
             if isinstance(r.get("images"), list) and len(r["images"]) > 1]

    print(f"inventory: {total} items")
    print(f"  with at least one photo : {len(withphoto)} ({len(withphoto)/max(total,1)*100:.0f}%)"
          f"   <- only these can ever be found by photo")
    print(f"  with more than one photo: {len(multi)} ({len(multi)/max(len(withphoto),1)*100:.0f}% "
          f"of photographed items)   <- extra angles measurably improve matching")
    if img_dir is None:
        print("  photo files on disk     : photo folder not found — pass --images <path>")
    else:
        print(f"  photo files on disk     : {on_disk} of {n_photos} referenced")
    print(f"  photographed AND binned : {len(withbin)} "
          f"({len(withbin)/max(len(withphoto),1)*100:.0f}%)   <- the bin is the answer "
          f"a photo search has to produce")

    bins = Counter((r.get("location_code") or "").strip() for r in withbin)
    cats = Counter((r.get("category") or "").strip() or "(none)" for r in withphoto)
    print(f"\n  distinct bins in use: {len(bins)}")
    if bins:
        avg = sum(bins.values()) / len(bins)
        print(f"  items per bin: mean {avg:.1f}, biggest {max(bins.values())}")
        print("  -> a photo search only has to pick the right BIN, so the more items share "
              "a bin,\n     the more often a near-miss still lands on the right answer")
    print("\n  top categories among photographed items:")
    for c, k in cats.most_common(8):
        print(f"    {k:>5}  {c}")
    print("\nNothing was copied. Drop --report-only to build the bundle.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inventory", help="path to inventory.json (default: repo root)")
    ap.add_argument("--images", help="path to the photo folder (default: userdata/images)")
    ap.add_argument("--out", default="photo_set", help="output folder (default: photo_set)")
    ap.add_argument("--type", dest="types", action="append",
                    help="only this Type (repeatable), e.g. --type Components")
    ap.add_argument("--category", dest="categories", action="append",
                    help="only this Category (repeatable)")
    ap.add_argument("--bin", dest="bins", action="append",
                    help="only this bin code (repeatable), e.g. --bin BIN-04")
    ap.add_argument("--limit", type=int, help="stop after this many items")
    ap.add_argument("--max-edge", type=int, default=1024,
                    help="shrink photos to this long edge (0 = originals). Default 1024, "
                         "which is plenty for matching and keeps the bundle small")
    ap.add_argument("--zip", action="store_true", help="also produce photo_set.zip")
    ap.add_argument("--report-only", action="store_true",
                    help="just describe what's in the inventory — copy nothing. Run this "
                         "first to see whether a photo search is viable on your data")
    args = ap.parse_args()

    rows = load_inventory(args.inventory)
    img_dir = find_images_dir(args.images, required=not args.report_only)

    if args.report_only:
        return report(rows, img_dir)

    def keep(r):
        if args.types and (r.get("type") or "").strip() not in args.types:
            return False
        if args.categories and (r.get("category") or "").strip() not in args.categories:
            return False
        if args.bins and (r.get("location_code") or "").strip() not in args.bins:
            return False
        return bool(r.get("images"))

    picked = [r for r in rows if keep(r)]
    picked.sort(key=lambda r: str(r.get("code") or r.get("id") or ""))
    if args.limit:
        picked = picked[:args.limit]

    out = Path(args.out).expanduser()
    if out.exists():
        shutil.rmtree(out)
    (out / "images").mkdir(parents=True)

    manifest, missing, copied = [], [], 0
    for r in picked:
        code = str(r.get("code") or "").strip() or f"id{r.get('id')}"
        imgs = r.get("images") or []
        if isinstance(imgs, str):
            imgs = [imgs]
        for n, fn in enumerate(imgs, 1):
            src = img_dir / str(fn)
            if not src.is_file():
                missing.append(str(fn))
                continue
            stem = f"{code}-{n}"
            dst = out / "images" / f"{stem}{src.suffix.lower()}"
            if args.max_edge and downscale(src, dst, args.max_edge):
                dst = dst.with_suffix(".jpg")
            else:
                shutil.copy2(src, dst)
            copied += 1
            manifest.append({
                "file": f"images/{dst.name}",
                "code": code,
                "item_id": r.get("id"),
                "name": (r.get("name") or "").strip(),
                "type": (r.get("type") or "").strip(),
                "category": (r.get("category") or "").strip(),
                "location": (r.get("location") or "").strip(),
                "bin": (r.get("location_code") or "").strip(),
                "qty": r.get("qty"),
                "original_filename": str(fn),
            })

    with (out / "manifest.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(manifest[0].keys()) if manifest else
                           ["file", "code", "item_id", "name", "type", "category",
                            "location", "bin", "qty", "original_filename"])
        w.writeheader()
        w.writerows(manifest)

    (out / "manifest.json").write_text(json.dumps({
        "photos": manifest,
        "items": [{k: r.get(k) for k in
                   ("id", "code", "alt_codes", "name", "type", "category", "location",
                    "location_code", "qty", "specifications", "tags", "dimensions",
                    "estimated_value", "ocr_fields")}
                  for r in picked],
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    n_items = len({m["code"] for m in manifest})
    (out / "README.txt").write_text(
        "Photo set exported from Inventory Manager.\n\n"
        f"items:  {n_items}\n"
        f"photos: {copied}\n"
        f"photos are named <item code>-<n>, so every file states which entry it\n"
        "belongs to even without the manifest.\n\n"
        "manifest.csv  one row per photo (open in a spreadsheet)\n"
        "manifest.json the same, plus the full item records\n\n"
        "Nothing here modifies your inventory; this export is read-only.\n",
        encoding="utf-8")

    print(f"exported {copied} photos from {n_items} items -> {out}/")
    if missing:
        print(f"  note: {len(missing)} photo file(s) referenced by an item were not found "
              f"on disk and were skipped")
    no_photo = sum(1 for r in rows if not r.get("images"))
    if no_photo:
        print(f"  note: {no_photo} item(s) in the inventory have no photo at all "
              f"(they can't take part in a visual search)")

    if args.zip:
        zp = out.with_suffix(".zip")
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(out.rglob("*")):
                if f.is_file():
                    z.write(f, f.relative_to(out.parent))
        print(f"  wrote {zp} ({zp.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
