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
- 📷 **Quick phone scan** — on your phone, just snap a photo and tap **Save &
  Next**: a blank name **auto‑numbers** (Item 0001, Item 0002 …), so you can bang
  through a pile of items with photos only, then fill in real names/details later
  from a desktop.
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
- 🔗 **Import from a product page** — found it online? Paste the product URL (or,
  when a store blocks bots, paste/upload the page's HTML) and the app reads the
  embedded product data (name, price, brand, specs) and fills the item for you.
- 🧺 **Storage system** — give items a short **bin / location code**, or run
  **Smart Organize** to group like items into labelled bins automatically. A live
  **Storage map** shows what lives in each bin so a keyword search tells you
  exactly where to look.
- 📱 **Connect panel** — the navbar **Connect** button lists every address the app
  is reachable at (local network, Tailscale, localhost) with **QR codes**, so you
  can scan it open on your phone.
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
| `SERPAPI_KEY`     | *(unset)*     | **Free web lookup** during Identify (SerpApi — 100/mo, no credit card). Real product name, tags, links, and price. |
| `GOOGLE_VISION_API_KEY` | *(unset)* | Alternative web lookup (Google Vision reverse‑image; free tier needs billing on). |
| `WEB_DETECT_PROVIDER` | `auto`   | `auto` (serpapi if its key is set, else google_vision, else off), or force `serpapi` / `google_vision` / `none`. |
| `WEB_DETECT_TIMEOUT` | `30`       | Web‑lookup request timeout, in seconds |
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

## Automatic web identification (free)

Local vision models describe an item well but often miss the *exact* product.
Configure a web‑lookup provider and the Identify button grounds the result in
real web data automatically — no manual search or copy‑paste:

1. Your local model runs as usual (category, dimensions, specs, a first guess).
2. In parallel, a web lookup returns the accurate **product name**, keyword
   tags, links to matching pages, and — when available — a **real price**.
3. The two are merged: the web match wins the **name** and **price**, entities
   become **tags**, the top page becomes the **product link**, and your local
   model keeps category/dimensions/specs. **Apply to item** drops it all into
   the form.

### Provider options

- **SerpApi — free, recommended.** Free tier is **100 searches/month with no
  credit card**. Returns product names *and* real prices. Sign up at
  [serpapi.com](https://serpapi.com), copy your key, and set:
  ```
  export SERPAPI_KEY=your-serpapi-key
  ```
  It uses Google Lens (reverse image) when the photo is reachable on a public
  URL (`PUBLIC_BASE` / `TAILSCALE_FUNNEL_BASE`), and otherwise a Google search
  grounded on your local model's guess — so it works even on a private LAN.

- **Google Cloud Vision — reverse image from bytes.** Free tier is 1000/month
  but requires enabling billing (a card). Accepts the photo bytes directly, so
  no public URL is needed:
  ```
  export GOOGLE_VISION_API_KEY=AIza...your-key...
  ```

`WEB_DETECT_PROVIDER` selects the back‑end (`auto` by default: SerpApi if its key
is set, else Vision, else off). **No key at all?** Identify stays fully local,
plus the manual web‑search buttons below. Nothing is sent anywhere unless a
provider is configured *and* you press Identify.

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

Two ways to keep a result:

- **Apply to form** — fills the form with the details so you can tweak, then
  **Save**. Best when you want to review first.
- **Apply & Update** — writes the details straight onto the item (or adds a new
  one) in a single click. Fastest during a big scan-in.

Either way the name, category, specs, value, dimensions, tags, and product link
are recorded.

## Open on another device (Connect panel)

The app binds every network interface, so it's reachable **at the same time** on
localhost, your LAN IP, and your Tailscale IP. Click **Connect** in the navbar to
see all of them as clickable links with **QR codes** — scan the local‑network one
for speed, or the Tailscale one to reach it from anywhere. (QR codes need the
optional `qrcode` package from `requirements.txt`; without it you still get the
links.)

## Import from a product page (Amazon, eBay & co.)

When visual search lands you on a real product page, pull its details straight
into the item. Open **Item lookup** (the Identify panel, or the form's *Import
from a product link* button):

- **Most reliable: upload the saved `.html`.** On the listing press **Ctrl+S** to
  save the page, then drop the file on the **Upload the saved .html** box — name,
  price, and specs fill in automatically, and it never gets blocked. (You can also
  paste the HTML source instead.)
- **Or paste a URL → Fetch.** The app fetches the page directly — works on many
  manufacturer/retailer sites; big stores (Amazon) block bots, so use the upload.

The parser reads the structured data pages embed — **JSON‑LD**, **Open Graph**,
Amazon **detail/feature bullets & spec tables**, and **eBay item specifics** — and
puts each value in the right field: product name, **real price**, image, a short
**category** (from the breadcrumb), **dimensions** pulled into their own field,
and the **helpful specs** isolated (noise like *Best Sellers Rank*, *Customer
Reviews*, and placeholders like *“Does not apply”* are dropped).

Then **Apply to form** (to review) or **Apply & Update** (one click) records it.
The importer only reads embedded structured data — no login or account scraping —
and URL fetches are limited to public hosts.

## Storage & retrieval — find where you put things

The whole point of scanning your stuff is being able to find it later. Two pieces
make that fast:

1. **Bins / location codes.** Each item can carry a short code (e.g. `BIN-01`,
   `SHELF-A3`) alongside its human location. Type it in the **Bin / code** field,
   or let the app assign one.
2. **Smart Organize.** Click **Smart Organize** in the Storage map card to
   **analyse every item** and generate a plan that groups *related things
   together*. It reads each item's name and category and clusters ones that share
   a type word — so "Toggle Switches" and "Slide Switches" land in one **Switches**
   bin, while unrelated things stay apart; anything with no match falls back to its
   category or a **Miscellaneous** bin. The preview shows each bin's item count,
   quantity, and total estimated value. Review it, then **Apply plan** to stamp the
   bin labels onto every item at once. Existing codes are preserved, so re‑running
   after you scan more items is safe and stable.

3. **Fit to my bins.** Smart Organize invents as many bins as it needs — but in
   real life you have a *fixed* set of drawers, totes and shelves. Click
   **Fit to my bins** (next to Smart Organize) to describe the containers you
   actually own and let the app pack everything into them. In the editor, list
   one container per line as `CODE | Name | capacity`, for example:

   ```
   A1 | Small parts drawer | 20
   B1 | Garage tote        | 50
   SHELF | Workshop shelf   | 30
   ```

   *Capacity* is how many **different items** a container should hold. **Save
   bins** remembers them (in `containers.json`); **Fit items into bins** runs a
   bin‑packing pass that keeps related items together (the same Switches /
   Resistors groups as Smart Organize), drops each group into the tightest
   container it fits, and splits a group across containers only when it must. The
   result shows a capacity bar for every bin and warns you about anything that
   **didn't fit** — so you know when you need one more tote. **Apply fit** stamps
   the chosen bin code and name onto every placed item at once. Re‑running is
   safe: it re‑fits from your current inventory each time.

The **Storage map** card then shows what physically lives in each bin. To find
something later, just search a keyword (name, tag, spec, category…) — the results
show the item **and its bin**, so you know exactly which box to open.

A good workflow for a big scan‑in:

> Snap → *Identify* / *Search web* → *Apply* → set quantity → **Save & Next**
> (category/location stay put) … repeat for the shelf, then **Smart Organize**
> once at the end to bin everything.

## Data & storage

- Items are stored in `inventory.json` (created automatically).
- Your storage containers (for **Fit to my bins**) are stored in
  `containers.json`.
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
| `data.py` | JSON persistence + organizing/storage helpers (categories, locations, bins, Smart Organize, Fit to my bins) |
| `vision_lookup.py` | Ollama vision client for "Identify from photo" |
| `web_detect.py` | Automatic web lookup (SerpApi / Google Vision), pluggable |
| `web_search.py` | Google Lens / Google / Shopping search URL builders |
| `product_import.py` | Extract product details from a page URL or pasted/saved HTML (JSON‑LD / OG) |
| `net_info.py` | Enumerates reachable URLs (LAN / Tailscale) + QR codes for the Connect panel |
| `utils.py` | Image saving, thumbnails, asset URLs |
| `image_processing.py` / `ocr_engine.py` | OCR preprocessing & extraction |
| `components_ocr_lab.py` / `callbacks_ocr_lab.py` | OCR Lab page |
| `config.py` | Paths, theme, thresholds, Tesseract wiring |
