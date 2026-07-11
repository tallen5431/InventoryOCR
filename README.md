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

- 📷 **Phone‑first capture** — on mobile the Photos button lets you **snap a new
  picture or choose an existing photo** from the same chooser; on a desktop it
  opens the file picker. **Add as many photos as you like** — take several shots
  in a row or pick multiple files and they all **stack up** on the item — then
  view them full‑size in a carousel.
- 🗂️ **Organize** — every item has a coarse **Type**, a detailed **Category**,
  and a **Location** (all with type‑ahead suggestions from what you've already
  used), plus a **Quantity**, description, and photos.
- 🏷️ **Type (top‑level grouping)** — a short, stable group for browsing:
  **Tools · Components · Cables & Adapters · Devices · Consumables · Other**.
  Leave it blank and the app **auto‑groups** each item from its name/category
  (so a shelf of scraped listings sorts itself into tools‑with‑tools,
  parts‑with‑parts), while **Category** keeps the specific sub‑label underneath.
  Filter, and sort by Type from the dashboard.
- ⚡ **Fast batch entry** — **Save & Next** stores the item and keeps the
  type / category / location / bin so you can rip through a whole shelf without
  re‑typing where things live.
- 📷 **Quick phone scan** — on your phone, just snap a photo and tap **Save &
  Next**: a blank name **auto‑numbers** (Item 0001, Item 0002 …), so you can bang
  through a pile of items with photos only, then fill in real names/details later
  from a desktop.
- 🔎 **Find fast** — full‑text search across name / type / category / location /
  bin / notes / tags / specs / OCR text (multi‑word = AND), plus dropdown filters
  for type, category, and location (each showing how many items it holds, e.g.
  *Tools (12)*). Sort newest / name / quantity, or **Group by Type / Category /
  Location** to cluster related items together in the list.
- ✅ **Bulk edit & merge** — tick several rows to set their type / category /
  location / bin in one go, **merge them into a single entry** (keeps the richest
  one, adds up the quantities, and combines every photo/spec/tag), or delete them
  together. Merges and bulk deletes offer a one‑click **Undo**.
- 📊 **At‑a‑glance** — KPI cards (total items, total quantity, low‑stock count,
  categories) and an **Overview** with item/quantity totals grouped by **type**,
  by location, and by category.
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
- 💲 **Price Compare** — drop several saved listing `.html` files for the same
  product and the app works out each one's **price per unit** (handling packs of
  many), ranks the best deal, and can **track prices over time** across repeat
  runs. If a listing matches something you own, one click **writes the best unit
  price + link back** onto that item.
- 🧺 **Storage system** — say **how many bins you have** in one step (type a
  number → it generates `BIN-01 … BIN-09`), and give each bin its own **bags**
  (sub-compartments, e.g. *resistors, capacitors, diodes*). The live **Storage
  map** shows every bin — even empty ones — with its bags and how full it is, so
  a keyword search tells you exactly where to look. **Smart Organize** can also
  group like items into labelled bins automatically.
- 🧬 **Merge duplicates** — scanned the same thing twice? **Merge duplicates**
  finds identical / very similar entries, previews the combined item (quantities
  added, photos/specs/tags kept), and merges the ones you pick — while keeping
  genuinely different sizes/models (AA vs 9V, M3 vs M5) apart. A badge on the
  button flags likely duplicates automatically so you don't have to remember to look.
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

## Access it from the internet (optional)

Tailscale already lets you reach the app from anywhere **on your tailnet**. If you
want a *public* URL — reachable from any browser without the Tailscale client —
do it in two parts: **turn on the login**, then **expose it over HTTPS**.

### 1. Turn on the login (required before exposing)

The app ships with **no authentication**, so never put it on the public internet
without this. Set a username and password and the app requires them on every
request:

```bash
export INVENTORY_AUTH_USER="tj"
export INVENTORY_AUTH_PASSWORD="a-long-random-passphrase"
# or the shorthand:  export INVENTORY_AUTH="tj:a-long-random-passphrase"
```

(In the HTTP Server Manager, add these to the program's **env** so they persist.)
Leave them unset and auth stays **off** — unchanged for LAN use. `/healthz` stays
open (no credentials) so a tunnel or uptime monitor can probe it. Basic Auth sends
the password on each request, so only expose the app **over HTTPS** — both options
below give you that.

### 2. Expose it over HTTPS — pick one

**Tailscale Funnel (easiest — you already run Tailscale).** Publishes the local
port on a public `https://<machine>.<tailnet>.ts.net` URL with automatic TLS and
**no router ports opened**. Enable Funnel for the node in your tailnet's ACLs
once, then:

```bash
sudo tailscale funnel 8001        # serve the app publicly over HTTPS
tailscale funnel status           # shows the public URL
```

**Cloudflare Tunnel (add your own domain + SSO).** `cloudflared` dials out to
Cloudflare (again, no open ports) and serves the app at your domain; pair it with
**Cloudflare Access** for real SSO/2FA in front:

```bash
cloudflared tunnel --url http://localhost:8001   # quick throwaway *.trycloudflare.com URL
```

> ⚠️ **Don't** expose the **HTTP Server Manager** (port 3000) — only the app
> (8001). And avoid raw router port‑forwarding: it publishes your home IP, has no
> TLS, and AT&T CGNAT often blocks it. The tunnels above are safer and simpler.

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

## Compare prices — find the best deal per unit

The **💲 Price Compare** page (in the top nav) answers a different question:
*of all the listings I found for this thing, which is actually the cheapest?* —
without trawling tabs by hand.

1. Open a few listings for the **same kind of product** and **Save Page As**
   (`.html`) each one.
2. Drop them all on the **Product pages** dropzone and hit **Compare prices**.
3. Each page is scraped for its name and price, its **pack size** is detected
   (e.g. `150PCS`, `24 Pack`, `Pack of 6`, `x500`, `Qty: 50`), and the
   **price per unit** is worked out — so a 48‑pack at \$22.99 correctly beats an
   8‑pack at \$7.49. The table ranks cheapest‑per‑unit first and 🏆 marks the
   winner. If a listing matches something already in your inventory, it says so.
4. Detection got a pack size wrong? The **Pack qty** cells are editable — fix a
   number and hit **Recalculate** to re‑price and re‑rank.

**Track prices over time.** Give the comparison a name (e.g. *AA Batteries*) and
**Save** — it's stored as a dated snapshot in `price_compare.json`. Re‑run the
same name later (new listings, new prices) and each run adds a snapshot, so the
**Tracked searches** panel shows the best unit price over time with a little
trend line — handy for knowing when a price is actually a good one.

**Write it back to your inventory.** If any compared listing matches an item you
already have, a bar appears offering to **save the best unit price** (and the
listing link) straight onto that item — so the value in your catalogue reflects
the best deal you found.

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

3. **Set up bins (with bags).** Smart Organize invents as many bins as it needs —
   but in real life you have a *fixed* set of drawers, totes and shelves. Click
   **Set up bins** (next to Smart Organize):

   - **How many bins do you have?** Type a number, an optional code **prefix**
     (default `BIN`) and **slots** each, then **Generate** — it creates
     `BIN-01 … BIN-09` for you. Existing bins are kept, so it's additive.
   - **Name your bins & their bags.** Fine-tune in the editor, one bin per line as
     `CODE | Name | slots | bag1, bag2, bag3`. The **bags** are the separate bags
     of material inside a bin, for example:

   ```
   BIN-01 | Small parts drawer | 20 | resistors, capacitors, diodes
   BIN-02 | Cables tote        | 40 | usb, ribbon, power
   SHELF-01 | Workshop shelf   | 30
   ```

   The **Storage map** then lists every bin — even empty ones — with its bags and
   how full it is; bags you've actually filled show a live item count. (Set an
   item's **Location** to a bag name and its **Bin** to the bin code — both offer
   type-ahead suggestions from what you've defined.)

   *Slots* is how many **different items** a container should hold. **Save
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
> (category/location stay put) … repeat for the shelf, then **Merge duplicates**
> to combine anything entered twice, then **Smart Organize** once at the end to
> bin everything.

## Clean up duplicates

When you scan fast, the same item lands in the list more than once — sometimes
under slightly different names (*AA Battery* / *AA Batteries*), sometimes with the
count split across entries. **Merge duplicates** (in the Storage map card) fixes
that:

1. Open it — it **scans right away** (at the *Similar* level). Change the
   sensitivity — **Identical only**, **Similar** (recommended), or **Loosely
   similar** — and **Scan** again if you like.
2. Each group shows the entries it will combine. **Choose which entry survives**
   (its name is offered, and picking a survivor sets that field to its name) and
   **rename** the result if you want; the quantities are **added up** and every
   photo, spec and tag is kept.
3. Toggle off any group you'd rather leave alone, then **Merge selected**.

Changed your mind? An **Undo** bar appears after a merge (and after a bulk
delete) — one click rolls it straight back.

It's deliberately careful about *size/model* differences: **AA vs 9V**, **M3 vs
M5**, or two listings with different part numbers are held apart even when the
rest of the name matches, so a quick clean‑up never collapses things that aren't
actually the same. Matching happens on the item name, tags and category — nothing
leaves your machine.

You don't have to remember to check: the **Merge duplicates** button shows a
badge with the number of likely duplicate groups whenever some are detected.

> **Bulk edit tip:** after a scan, tick several rows in the table to reveal the
> bulk bar — set their category / location / bin at once, or delete them
> together. Ticking a single row still opens it in the edit form as usual.

## Data & storage

- Items are stored in `inventory.json` (created automatically).
- Your storage containers (for **Fit to my bins**) are stored in
  `containers.json`.
- **Price Compare** history is stored in `price_compare.json`.
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
| `data.py` | JSON persistence + organizing/storage helpers (categories, locations, bins, Smart Organize, Fit to my bins, Merge duplicates) |
| `vision_lookup.py` | Ollama vision client for "Identify from photo" |
| `web_detect.py` | Automatic web lookup (SerpApi / Google Vision), pluggable |
| `web_search.py` | Google Lens / Google / Shopping search URL builders |
| `product_import.py` | Extract product details from a page URL or pasted/saved HTML (JSON‑LD / OG) |
| `price_compare.py` | Price‑per‑unit comparison across saved listings + price‑over‑time history |
| `net_info.py` | Enumerates reachable URLs (LAN / Tailscale) + QR codes for the Connect panel |
| `utils.py` | Image saving, thumbnails, asset URLs |
| `image_processing.py` / `ocr_engine.py` | OCR preprocessing & extraction |
| `components_ocr_lab.py` / `callbacks_ocr_lab.py` | OCR Lab page |
| `components_price_compare.py` / `callbacks_price_compare.py` | Price Compare page |
| `config.py` | Paths, theme, thresholds, Tesseract wiring |
