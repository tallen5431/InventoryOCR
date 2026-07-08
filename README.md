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
- 🔎 **Find fast** — full‑text search across name / category / location / notes /
  OCR text, plus dropdown filters for category and location.
- 📊 **At‑a‑glance** — KPI cards (total items, total quantity, low‑stock count,
  categories) and an **Overview** grouped by location and by category.
- 📤 **Export** — one‑click CSV of your whole inventory.
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
| `PUBLIC_BASE`     | *(unset)*     | Force the external base URL shown on startup |

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
| `components.py` | Dashboard UI (form, filters, KPIs, table, overview, modal) |
| `callbacks.py` | Dashboard behavior (add/edit/delete, filter, KPIs, export) |
| `data.py` | JSON persistence + organizing helpers (categories/locations/summaries) |
| `utils.py` | Image saving, thumbnails, asset URLs |
| `image_processing.py` / `ocr_engine.py` | OCR preprocessing & extraction |
| `components_ocr_lab.py` / `callbacks_ocr_lab.py` | OCR Lab page |
| `config.py` | Paths, theme, thresholds, Tesseract wiring |
