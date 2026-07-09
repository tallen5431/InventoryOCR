# 📦 Inventory Manager (InventoryOCR)

Snap photos with your phone to **organize, categorize, and count** your
stuff — what each item is, **where** it lives, **how many** you have, and any
notes. A mobile‑friendly [Dash](https://dash.plotly.com/) web app with optional
OCR text extraction from labels and boxes.

![built with Dash + Bootstrap](https://img.shields.io/badge/built%20with-Dash%20%2B%20Bootstrap-0d6efd)

## Why

Managing physical stuff — tools, pantry, parts, supplies, gear across rooms and
bins — is tedious. This app makes it a 15‑second loop from your phone:

> **Take a photo → give it a category & location → set a quantity → Save.**

Then search, filter, and see totals by location and category whenever you need
to find something or restock.

## Features

- 📷 **Phone‑first capture** — the Photos field opens your camera on mobile
  (`accept="image/*"`); attach multiple photos per item, preview before saving,
  and view them full‑size in a carousel.
- 🗂️ **Organize** — every item has a **Category** and **Location** (with
  type‑ahead suggestions from what you've already used), a **Quantity**, a
  description, and photos.
- ⚡ **Fast batch entry** — **Save & Next** stores the item and keeps the
  category / location / bin so you can rip through a whole shelf without
  re‑typing where things live.
- 🔎 **Find fast** — full‑text search across name / category / location / bin /
  notes / tags / specs / OCR text (multi‑word = AND), plus dropdown filters for
  category and location.
- 📊 **At‑a‑glance** — KPI cards (total items, total quantity, low‑stock count,
  categories) and an **Overview** grouped by location and by category.
- 📤 **Export** — one‑click CSV of your whole inventory (including bin, specs,
  value, dimensions, tags, and product link).
- 🔎 **Identify from photo** — send an item's photo to a local vision AI
  (Ollama) to suggest what it is, its specifications, an estimated value,
  dimensions, and search keywords. **Apply to item** copies those into the form
  in one click.
- 🌐 **Look it up on the web** — open a **Google Lens** reverse‑image search
  (when the app is on a public URL) or a plain **Google / Shopping** search for
  the item's name and specs. Handy when local models can't nail an exact product.
- 🧺 **Storage system** — give items a short **bin / location code**, or run
  **Smart Organize** to group like items into labelled bins automatically. A live
  **Storage map** shows what lives in each bin so a keyword search tells you
  exactly where to look.
- 🧪 **OCR Lab** — experiment with preprocessing and pull text off images when
  Tesseract is installed.
- 🌗 **Dark/light theme**, responsive layout tuned for phones and tablets.
- 🔌 **Proxy‑aware** — serve at the root (`/`) standalone, or under a path
  (e.g. `/inventory`) behind a reverse proxy.

## Quick start

```bash
# 1. Install dependencies (creates .venv on first run)
./Start.sh
```

`Start.sh` creates a virtual environment, installs `requirements.txt`, and
launches the app with [waitress](https://docs.pylonsproject.org/projects/waitress/).
Then open the URL it prints (default <http://localhost:8001>).

Manual run:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

## Configuration

All settings are environment variables:

| Variable          | Default       | Purpose |
| ----------------- | ------------- | ------- |
| `HOST`            | `0.0.0.0`     | Bind address |
| `PORT`            | `8001`        | Port to listen on |
| `URL_PREFIX`      | `/inventory`  | Path prefix. **Set to empty** (`URL_PREFIX=`) to serve at the site root. |
| `INVENTORY_THEME` | `dark`        | `dark` or `light` default theme |
| `PUBLIC_BASE`     | *(unset)*     | Public base URL of the app. Also enables the **Google Lens by‑image** button (Google must be able to fetch the photo). |
| `TAILSCALE_FUNNEL_BASE` | *(unset)* | Public [Tailscale Funnel](https://tailscale.com/kb/1223/funnel) base (e.g. `https://host.tailnet.ts.net`). Alternative to `PUBLIC_BASE` for enabling Lens. |
| `OLLAMA_HOST`     | `http://100.98.112.1:11434` | Ollama server for "Identify from photo" (a trailing `/v1` is accepted). |
| `OLLAMA_VISION_MODEL` | `llama3.2-vision` | Vision model used for identification. Pull it first. |
| `VISION_TIMEOUT`  | `60`          | Identify request timeout, in seconds |
| `GOOGLE_VISION_API_KEY` | *(unset)* | Enables **automatic reverse‑image detection** (Lens‑style) during Identify. When set, the photo is sent to Google Cloud Vision on click; unset = fully local. |
| `WEB_DETECT_TIMEOUT` | `30`       | Reverse‑image request timeout, in seconds |
| `WEB_DETECT_MAX_RESULTS` | `8`    | Max web entities / matching pages to keep |

Serve at the root (e.g. when accessed directly at `http://host:8001/`):

```bash
URL_PREFIX= PORT=8001 ./Start.sh
```

Serve under a path behind a reverse proxy:

```bash
URL_PREFIX=/inventory PORT=8001 ./Start.sh
```

## OCR (optional)

Text extraction uses [Tesseract](https://github.com/tesseract-ocr/tesseract) via
`pytesseract`. Install the system binary to enable it:

```bash
# Debian/Ubuntu
sudo apt-get install -y tesseract-ocr
```

On Windows you can drop a `Tesseract-OCR/` folder (with `tesseract.exe` and
`tessdata/`) next to the app and it will be picked up automatically. Without
Tesseract the inventory features all work — OCR simply returns empty text.

## Identify items from a photo (optional)

Click **🔎 Identify from photo** to have a local vision AI look at an item's
photo and suggest what it is, its specifications, an estimated value, and
dimensions. It works on the currently-selected item's photo, or on a photo you
just took (before saving). Results are **read-only** — nothing is written back
to the item; you copy over anything useful yourself.

It talks to an [Ollama](https://ollama.com) server using a vision-capable model
— by default the same local/Tailscale endpoint the rest of the stack uses. The
photo never leaves your network unless `OLLAMA_HOST` points somewhere remote.

Set it up:

```bash
# On the machine running Ollama, pull a vision model:
ollama pull llama3.2-vision       # or: qwen2.5vl, llava, moondream, …

# Point the app at your Ollama server (defaults shown):
export OLLAMA_HOST=http://100.98.112.1:11434
export OLLAMA_VISION_MODEL=llama3.2-vision
```

> ⚠️ Estimated values and specs are the model's best guess from the photo —
> treat them as a starting point, not an appraisal.

## Automatic reverse‑image identification (Lens‑style)

Local vision models describe an item well but often miss the *exact* product.
Set **`GOOGLE_VISION_API_KEY`** and the Identify button does a real reverse‑image
lookup automatically — no manual search or copy‑paste:

1. Your local model runs as usual (category, estimated value, dimensions, specs).
2. In parallel, the photo is sent to **Google Cloud Vision — Web Detection**,
   which returns the accurate **product name**, keyword entities, and links to
   matching pages.
3. The two are merged — the reverse‑image match wins the **name**, its keywords
   become **tags**, the top matching page becomes the **product link**, and your
   local model keeps category/value/size. **Apply to item** drops it all into the
   form.

Why Vision (and not Google Lens / SerpApi)? It accepts the photo **bytes
directly**, so it works on a **private LAN** without exposing the app on a public
URL. Nothing is sent anywhere unless the key is set *and* you press Identify.

Setup:
```
# 1. In Google Cloud, create a project, enable the "Cloud Vision API",
#    and make an API key (Vision Web Detection has a free monthly tier).
# 2. Point the app at it (e.g. in the manager card's env, or your shell):
export GOOGLE_VISION_API_KEY=AIza...your-key...
```
No key? Identify stays exactly as before — fully local, plus the manual web
buttons below.

## Look it up on the web (manual)

The Identify panel and the form's **🌐 Search the web** button also give you two
browser‑powered lookups that run in *your* browser (so they work on any network):

- **Google / Shopping search** — always available. Opens a normal Google search
  for the item's name + specs in a new tab. Runs in *your* browser, so it works
  on any network.
- **Google Lens (reverse image)** — appears when the app is reachable on a public
  URL, because Google's servers must be able to fetch the photo. Set
  `PUBLIC_BASE` or `TAILSCALE_FUNNEL_BASE` to enable it. Otherwise, right‑click
  the photo in the modal and choose **“Search image with Google Lens”** — the
  browser uploads the image directly and it works even on a private LAN.

Whatever you learn, click **Apply to item** on an AI result (or just type into
the form) and **Save** to record the name, category, specs, value, dimensions,
tags, and a product link.

## Storage & retrieval — find where you put things

The whole point of scanning your stuff is being able to find it later. Two pieces
make that fast:

1. **Bins / location codes.** Each item can carry a short code (e.g. `BIN-01`,
   `SHELF-A3`) alongside its human location. Type it in the **Bin / code** field,
   or let the app assign one.
2. **Smart Organize.** Click **Smart Organize** in the Storage map card to
   generate a plan that groups *like items together* — one bin per category — and
   assigns each a bin code. Review the plan, then **Apply plan** to stamp those
   bin labels onto every item at once. Existing codes are preserved, so re‑running
   it is safe and stable.

The **Storage map** card then shows what physically lives in each bin. To find
something later, just search a keyword (name, tag, spec, category…) — the results
show the item **and its bin**, so you know exactly which box to open.

A good workflow for a big scan‑in:

> Snap → *Identify* / *Search web* → *Apply* → set quantity → **Save & Next**
> (category/location stay put) … repeat for the shelf, then **Smart Organize**
> once at the end to bin everything.

## Data & storage

- Items are stored in `inventory.json` (created automatically).
- Photos and thumbnails are saved under `assets/images/` and
  `assets/thumbnails/`.
- These are git‑ignored so your data stays local and survives app updates.

Old data files are migrated automatically: a legacy single `image_filename`
becomes the `images` list, and items without a category/location just show up as
Uncategorized / Unassigned until you set them.

## Using it with the HTTP Server Manager

This app ships as a bundled card in
[`tallen5431/HTTP_Server`](https://github.com/tallen5431/HTTP_Server)
(`examples/inventory-ocr`). The manager clones this repo, runs it with
`URL_PREFIX=` so it serves at the root, and gives you a one‑click **Open** link.

## Project layout

| File | Role |
| ---- | ---- |
| `app.py` | Dash app shell, routing, theme, asset routes, server entrypoint |
| `components.py` | Dashboard UI (form, filters, KPIs, table, overview, modals, storage map) |
| `callbacks.py` | Dashboard behavior (add/edit/delete, filter, KPIs, identify, web search, organize, export) |
| `data.py` | JSON persistence + organizing/storage helpers (categories, locations, bins, Smart Organize) |
| `vision_lookup.py` | Ollama vision client for "Identify from photo" |
| `web_detect.py` | Automatic reverse‑image detection (Google Vision Web Detection) |
| `web_search.py` | Google Lens / Google / Shopping search URL builders |
| `utils.py` | Image saving, thumbnails, asset URLs |
| `image_processing.py` / `ocr_engine.py` | OCR preprocessing & extraction |
| `components_ocr_lab.py` / `callbacks_ocr_lab.py` | OCR Lab page |
| `config.py` | Paths, theme, thresholds, Tesseract wiring |
