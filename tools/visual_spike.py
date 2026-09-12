#!/usr/bin/env python3
"""Measure whether photo search could actually find your items. Real photos only.

This answers one question before any feature gets built: if you point a camera at
a part you own, can software work out which entry it is — or at least which bin
it goes back in?

    # 1. bundle your logged photos with the entry each belongs to
    python3 tools/export_photo_set.py --zip

    # 2. take NEW photos of ~20 items you can identify, one folder per item,
    #    the folder named with that item's code (the number on its QR label):
    #      queries/0042/a.jpg
    #      queries/0042/b.jpg
    #      queries/0107/a.jpg
    #    (a folder named with the item's NAME works too)

    # 3. measure
    python3 tools/visual_spike.py --set photo_set --queries queries

Four things get reported, in increasing order of how much they matter:

  exact item   — is the #1 candidate the right entry?
  type/category— did it at least work out what kind of thing this is?
  BIN          — does the #1 candidate live in the right bin? This is the one
                 that decides the feature, because "where does this go back"
                 is answered correctly whenever the bin is right, even if the
                 specific entry is wrong.
  confidence   — can it tell a confident match from a guess? Without this a
                 wrong answer is indistinguishable from a right one, and a part
                 goes back in the wrong bin unnoticed.

Needs only what the app already requires: opencv, numpy, Pillow.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

try:
    import cv2
    import numpy as np
except ImportError as _e:                                       # pragma: no cover
    import sys as _sys
    _sys.exit(
        f"error: {_e.name} isn't available to this Python.\n\n"
        "This needs the same interpreter the app runs on, which has opencv and\n"
        "numpy installed. Use the project's virtualenv:\n\n"
        "    Linux/macOS:  .venv/bin/python tools/visual_spike.py ...\n"
        "    Windows:      .venv\\Scripts\\python.exe tools\\visual_spike.py ...\n\n"
        "If there's no .venv yet, run ./Start.sh (or Start.bat) once to create it.")

EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


# ----------------------------------------------------------------- loading

def load_set(root: Path):
    """Read an export_photo_set bundle, or a raw inventory.json + images folder."""
    man = root / "manifest.json"
    if man.is_file():
        blob = json.loads(man.read_text(encoding="utf-8"))
        photos = [{**p, "path": root / p["file"]} for p in blob.get("photos", [])]
        return [p for p in photos if p["path"].is_file()]

    inv = root / "inventory.json"
    imgs = next((d for d in (root / "images", root / "userdata" / "images",
                             root / "assets" / "images") if d.is_dir()), None)
    if not inv.is_file() or imgs is None:
        sys.exit(f"error: {root} is neither an export bundle (manifest.json) nor an "
                 f"inventory.json + images/ folder")
    out = []
    for r in json.loads(inv.read_text(encoding="utf-8")):
        if not isinstance(r, dict):
            continue
        files = r.get("images") or []
        if isinstance(files, str):
            files = [files]
        for fn in files:
            p = imgs / str(fn)
            if p.is_file():
                out.append({"path": p, "code": str(r.get("code") or f"id{r.get('id')}"),
                            "item_id": r.get("id"), "name": (r.get("name") or "").strip(),
                            "type": (r.get("type") or "").strip(),
                            "category": (r.get("category") or "").strip(),
                            "bin": (r.get("location_code") or "").strip()})
    return out


def load_queries(root: Path, gallery):
    """Each subfolder names the item it depicts: by code, or by name."""
    by_code = {p["code"].lower(): p["code"] for p in gallery}
    by_name = {p["name"].lower(): p["code"] for p in gallery if p["name"]}
    out, unmatched = [], []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        key = d.name.strip().lower()
        code = by_code.get(key) or by_code.get(key.lstrip("#").lstrip("0") or key) or by_name.get(key)
        if code is None:
            # tolerate "0042" vs "42"
            digits = key.lstrip("#").lstrip("0")
            code = next((c for c in by_code.values() if c.lstrip("0") == digits), None)
        files = [f for f in sorted(d.iterdir()) if f.suffix.lower() in EXTS]
        if code is None:
            unmatched.append((d.name, len(files)))
            continue
        for f in files:
            out.append({"path": f, "code": code})
    return out, unmatched


def read(path: Path, max_edge=900):
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        return None
    if max(img.shape[:2]) > max_edge:
        s = max_edge / max(img.shape[:2])
        img = cv2.resize(img, (int(img.shape[1] * s), int(img.shape[0] * s)),
                         interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def centre_crop(img, frac):
    if frac >= 1.0:
        return img
    h, w = img.shape[:2]
    ch, cw = int(h * frac), int(w * frac)
    y, x = (h - ch) // 2, (w - cw) // 2
    return img[y:y + ch, x:x + cw]


# ------------------------------------------------------------- descriptors

_ORB = cv2.ORB_create(nfeatures=1500, scaleFactor=1.2, nlevels=8, fastThreshold=12)


def orb_desc(img):
    g = cv2.resize(cv2.cvtColor(img, cv2.COLOR_RGB2GRAY), (512, 512),
                   interpolation=cv2.INTER_AREA)
    kp, des = _ORB.detectAndCompute(g, None)
    return (np.float32([k.pt for k in kp]) if kp else np.zeros((0, 2), np.float32),
            des if des is not None else np.zeros((0, 32), np.uint8))


def orb_inliers(q, g):
    """Geometrically verified match count — also serves as the confidence score."""
    (qp, qd), (gp, gd) = q, g
    if len(qd) < 8 or len(gd) < 8:
        return 0
    try:
        pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(qd, gd, k=2)
    except cv2.error:
        return 0
    good = [m for m, n in (p for p in pairs if len(p) == 2) if m.distance < 0.75 * n.distance]
    if len(good) < 8:
        return 0
    src = np.float32([qp[m.queryIdx] for m in good]).reshape(-1, 1, 2)
    dst = np.float32([gp[m.trainIdx] for m in good]).reshape(-1, 1, 2)
    _H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    return int(mask.sum()) if mask is not None else 0


def hog_vec(img, cells=8, bins=9):
    g = cv2.resize(cv2.cvtColor(img, cv2.COLOR_RGB2GRAY), (64, 64)).astype(np.float32)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    mag, ang = np.hypot(gx, gy), np.rad2deg(np.arctan2(gy, gx)) % 180.0
    b = np.minimum((ang / (180.0 / bins)).astype(int), bins - 1)
    cs = 64 // cells
    out = np.zeros((cells, cells, bins), np.float32)
    for cy in range(cells):
        for cx in range(cells):
            sl = (slice(cy * cs, (cy + 1) * cs), slice(cx * cs, (cx + 1) * cs))
            h = np.bincount(b[sl].ravel(), weights=mag[sl].ravel(),
                            minlength=bins).astype(np.float32)
            out[cy, cx] = h / (np.linalg.norm(h) + 1e-6)
    v = out.ravel()
    return v / (np.linalg.norm(v) + 1e-9)


def colour_vec(img):
    hsv = cv2.cvtColor(cv2.resize(img, (96, 96)), cv2.COLOR_RGB2HSV).astype(np.float32)
    f = []
    for c in range(3):
        ch = hsv[..., c].ravel()
        f += [ch.mean() / 255, ch.std() / 255,
              float(np.cbrt(((ch - ch.mean()) ** 3).mean())) / 255]
    h, w = img.shape[:2]
    f.append(h / max(w, 1) / 4.0)
    v = np.array(f, np.float32)
    return v / (np.linalg.norm(v) + 1e-9)


def cos(a, b):
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


# ----------------------------------------------------------------- report

def pct(a, b):
    return f"{a / b * 100:5.1f}%" if b else "    -"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", default="photo_set", help="export bundle, or a folder with "
                                                       "inventory.json + images/")
    ap.add_argument("--queries", default="queries", help="folder of <item>/photo.jpg")
    ap.add_argument("--crop", type=float, default=1.0,
                    help="centre-crop the query to this fraction (e.g. 0.6). Cropping "
                         "mattered enormously in synthetic tests — worth trying 1.0 and 0.6")
    args = ap.parse_args()

    gallery = load_set(Path(args.set).expanduser())
    if not gallery:
        sys.exit("error: no gallery photos found")
    qroot = Path(args.queries).expanduser()
    if not qroot.is_dir():
        sys.exit(f"error: no queries folder at {qroot}")
    queries, unmatched = load_queries(qroot, gallery)

    meta = {}
    for p in gallery:
        meta.setdefault(p["code"], p)
    per_item = defaultdict(int)
    for p in gallery:
        per_item[p["code"]] += 1

    print(f"gallery : {len(gallery)} photos over {len(per_item)} items "
          f"({np.mean(list(per_item.values())):.1f} photos/item)")
    print(f"queries : {len(queries)} photos over {len({q['code'] for q in queries})} items")
    if unmatched:
        print("  !! these query folders matched no item — rename them to the item's code:")
        for name, k in unmatched:
            print(f"     {name!r} ({k} photos)")
    bins_known = sum(1 for c in per_item if (meta[c].get('bin') or '').strip())
    print(f"  {bins_known}/{len(per_item)} gallery items have a bin set "
          f"(bin accuracy is only meaningful for those)\n")
    if not queries:
        sys.exit("error: no usable query photos")

    print("indexing…", end="", flush=True)
    t0 = time.perf_counter()
    g_orb = [orb_desc(read(p["path"])) for p in gallery]
    g_hog = [hog_vec(read(p["path"])) for p in gallery]
    g_col = [colour_vec(read(p["path"])) for p in gallery]
    t_idx = time.perf_counter() - t0
    print(f" {t_idx:.1f}s ({t_idx / len(gallery) * 1000:.0f} ms/photo)\n")

    methods = ("orb", "hog", "colour")
    hit = {m: defaultdict(int) for m in methods}
    lat = defaultdict(list)
    gate = []                      # (inliers, correct_bin) for the confidence curve

    for q in queries:
        img = read(q["path"])
        if img is None:
            continue
        img = centre_crop(img, args.crop)
        truth = q["code"]
        tmeta = meta[truth]

        t = time.perf_counter()
        qo = orb_desc(img)
        s_orb = np.array([orb_inliers(qo, g) for g in g_orb], float)
        lat["orb"].append(time.perf_counter() - t)
        s_hog = np.array([cos(hog_vec(img), g) for g in g_hog])
        s_col = np.array([cos(colour_vec(img), g) for g in g_col])

        for m, s in (("orb", s_orb), ("hog", s_hog), ("colour", s_col)):
            # collapse photo-level scores to item level (best photo wins)
            best = defaultdict(lambda: -1e9)
            for p, sc in zip(gallery, s):
                best[p["code"]] = max(best[p["code"]], sc)
            ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)
            h = hit[m]
            h["n"] += 1
            if m == "orb" and ranked[0][1] <= 0:
                h["declined"] += 1
                continue
            top = [c for c, _ in ranked[:5]]
            if top[0] == truth:
                h["exact1"] += 1
            if truth in top:
                h["exact5"] += 1
            if meta[top[0]].get("type") and meta[top[0]]["type"] == tmeta.get("type"):
                h["type1"] += 1
            if meta[top[0]].get("category") and meta[top[0]]["category"] == tmeta.get("category"):
                h["cat1"] += 1
            tb = (tmeta.get("bin") or "").strip()
            if tb:
                h["bin_n"] += 1
                if (meta[top[0]].get("bin") or "").strip() == tb:
                    h["bin1"] += 1
                if any((meta[c].get("bin") or "").strip() == tb for c in top):
                    h["bin5"] += 1
            if m == "orb":
                gate.append((ranked[0][1], (meta[top[0]].get("bin") or "").strip() == tb and bool(tb)))

    hdr = (f"{'signal':8} {'exact top-1':>12} {'top-5':>7} {'type':>7} {'category':>9} "
           f"{'BIN top-1':>10} {'BIN top-5':>10}")
    print(hdr); print("-" * len(hdr))
    for m in methods:
        h = hit[m]
        n, bn = h["n"], h.get("bin_n", 0)
        print(f"{m:8} {pct(h['exact1'], n):>12} {pct(h['exact5'], n):>7} "
              f"{pct(h['type1'], n):>7} {pct(h['cat1'], n):>9} "
              f"{pct(h.get('bin1', 0), bn):>10} {pct(h.get('bin5', 0), bn):>10}")
    n_items = len(per_item)
    print(f"\nchance: exact top-1 {100 / n_items:.1f}%, top-5 {min(100, 500 / n_items):.1f}%")
    if hit["orb"].get("declined"):
        print(f"ORB declined to answer on {hit['orb']['declined']}/{hit['orb']['n']} queries "
              f"(no geometrically consistent match — a safe failure)")
    print(f"query latency: ORB {np.median(lat['orb']) * 1000:.0f} ms median "
          f"over {len(gallery)} photos")

    if gate:
        print("\nconfidence gate — accept only matches with >= N geometric inliers:")
        print(f"  {'N':>4} {'answers given':>14} {'of those, right bin':>21}")
        for thr in (0, 8, 12, 20, 30, 50):
            kept = [(s, ok) for s, ok in gate if s >= thr]
            if not kept:
                continue
            right = sum(1 for _s, ok in kept if ok)
            print(f"  {thr:>4} {len(kept) / len(gate) * 100:>13.0f}% "
                  f"{right / len(kept) * 100:>20.0f}%")
    print("\nWhat to look at: BIN top-1 is the number that decides the feature. Above ~85% "
          "with a confidence gate, this is worth building; near 50% it is not.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
