# Visual search spike

Two throwaway-able tools that answer one question with **your** photos, before
any feature gets built:

> If I point a camera at a part I own, can the app work out where it goes back?

Synthetic tests put the honest odds at roughly **100% for anything with a
printed label on it** and **12–18% for bare, unlabelled parts** — and bare parts
are the case that matters here. That gap is too big to build on a guess, hence
this.

Nothing here is part of the app. It reads your inventory; it never writes to it.

---

## Step 0 — is this even viable for your data? (30 seconds, no photos needed)

```bash
python3 tools/export_photo_set.py --report-only
```

Prints how many items have photos, how many have a bin set, and how many items
share each bin. Copy that output to me and I can tell you a lot before you take
a single picture. **Nothing is copied or uploaded.**

The key number is *items per bin*: a photo search only has to land on the right
**bin**, so the more items share one, the more often a near-miss is still the
right answer.

---

## Step 1 — bundle your logged photos with the entries they belong to

```bash
python3 tools/export_photo_set.py --zip
```

This is the part that keeps photos and entries linked, so nothing has to be
matched up by hand and no photo can be attributed to the wrong item:

```
photo_set/
  manifest.csv        one row per photo: file, code, name, type, category, location, bin, qty
  manifest.json       the same, plus the full item records
  images/0042-1.jpg   every photo, renamed <item code>-<n>
  README.txt
```

Each file is named for the item it came from, so the link survives even if the
manifest is lost.

Useful flags:

| flag | why |
|---|---|
| `--type Components` | only one Type (repeatable) |
| `--category Resistors` | only one Category (repeatable) |
| `--bin BIN-04` | only one bin (repeatable) |
| `--limit 50` | stop after N items |
| `--max-edge 1024` | shrink photos (default; ~10–20× smaller, no effect on matching) |
| `--max-edge 0` | keep originals |

**Start narrow.** `--type Components --limit 40` is a better first run than
everything you own.

---

## Step 2 — take some new photos

Pick ~20 items you can identify by eye. For each, make a folder named with that
item's **code** (the number on its QR label, e.g. `0042`) and put 1–3 *new*
photos in it — shot the way you'd actually use this: in hand, on the bench,
normal lighting.

```
queries/
  0042/  a.jpg  b.jpg
  0107/  a.jpg
  0233/  a.jpg  b.jpg
```

A folder named with the item's **name** works too, and `42` is accepted for
`0042`. Anything unrecognised is reported rather than silently ignored.

Include some deliberately hard ones — two parts that look nearly identical. The
easy cases don't tell us anything.

---

## Step 3 — measure

```bash
python3 tools/visual_spike.py --set photo_set --queries queries
```

You'll get something like:

```
signal    exact top-1   top-5    type  category  BIN top-1  BIN top-5
---------------------------------------------------------------------
orb             31.2%   50.0%   56.2%     37.5%      66.7%     100.0%
hog             43.8%   62.5%  100.0%     56.2%      56.2%      81.2%
colour          50.0%   75.0%  100.0%     87.5%      87.5%     100.0%

confidence gate — accept only matches with >= N geometric inliers:
     N  answers given   of those, right bin
     0           100%                   67%
    20            11%                  100%
```

**`BIN top-1` is the number that decides it.** Above ~85% with a confidence
gate, the feature is worth building; near 50% it isn't, and the answer for bare
parts is a QR sticker on the *bag* instead of the part.

The confidence gate matters as much as the accuracy: a wrong bin is never
noticed, so the system has to be able to say *I don't know* rather than guess.

Worth trying `--crop 0.6` as well — in synthetic tests, tightening the crop
around the object moved bare-part accuracy from 7% to 98%, a bigger effect than
any change of algorithm.

---

## Two ways to get me the results

1. **Keep everything local** — run the commands above and paste me the output
   tables. No photos leave your machine. This is the better option.
2. **Send the bundle** — share `photo_set.zip` plus your `queries/` folder and
   I'll run it, try variations you didn't, and report back.

Either way I'll interpret the numbers and say plainly whether this is worth
building.
