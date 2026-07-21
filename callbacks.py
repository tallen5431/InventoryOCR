from __future__ import annotations
import os, time
from dash import Input, Output, State, ctx, no_update, ALL, MATCH, html, dcc
import dash_bootstrap_components as dbc
from dash.exceptions import PreventUpdate
import data
from utils import (
    save_image, get_thumbnail_url, get_image_url, get_preview_url,
    save_attachment, read_attachment_text,
)
# Pure formatters + component builders shared with the Operations tab
# (ui_helpers is the single home for these; see that module for why the data
# normalizers are deliberately NOT shared).
from ui_helpers import (
    specs_to_text as _specs_to_text, tags_to_text as _tags_to_text,
    fullres_links as _fullres_links, attachment_list as _render_attachments,
    photo_gallery,
)
from config import ASSET_IMAGE_PATH, OCR_TEXT_MAX_CHARS

URL_PREFIX = os.getenv("URL_PREFIX", "/inventory").strip().rstrip("/")
if URL_PREFIX and not URL_PREFIX.startswith("/"):
    URL_PREFIX = "/" + URL_PREFIX

# How much of the description to show inline before truncating (full text + the
# extracted specs live in the row's hover tooltip).
DESC_MAX_CHARS = 90

def _parse_qty(q):
    try:
        n = int(q)
        return n if n >= 0 else 0
    except Exception:
        return 0

def _build_rows(filtered):
    out_rows = []
    for r in filtered:
        row = dict(r)

        # Handle images array (new) or single image_filename (backward compatibility)
        images = row.get("images", [])
        if not images:
            # Check for old single image_filename field
            old_img = row.get("image_filename")
            if old_img:
                images = [old_img]

        # Show primary (first) image thumbnail in table
        if images:
            primary_img = images[0]
            thumb_url = get_thumbnail_url(primary_img)
            img_count = len(images)
            badge = f" ({img_count})" if img_count > 1 else ""
            row["image"] = f"![thumb]({thumb_url}){badge}" if thumb_url else ""
            # For the viewer: previews (fast) + originals (full-res link).
            row["all_previews"] = [get_preview_url(img) for img in images]
            row["all_images"] = [get_image_url(img) for img in images]
        else:
            row["image"] = ""
            row["all_previews"] = []
            row["all_images"] = []

        # Keep organizing fields present for the table (and CSV/native filters)
        row["type"] = (row.get("type") or "").strip()
        row["category"] = (row.get("category") or "").strip()
        row["location"] = (row.get("location") or "").strip()
        row["estimated_value"] = (row.get("estimated_value") or "").strip()

        # Compact "paperwork" indicator: 🧾 = has a purchase record, 📎N = N
        # attached documents. Full details show in the column's hover tooltip.
        atts = r.get("attachments") or []
        has_purchase = any((r.get(k) or "").strip()
                           for k in ("order_number", "purchase_date", "price_paid", "seller"))
        docs_bits = []
        if has_purchase:
            docs_bits.append("🧾")
        if atts:
            docs_bits.append(f"📎{len(atts)}")
        row["docs"] = " ".join(docs_bits)

        # "Added" column: show just the date (YYYY-MM-DD). This form also sorts
        # correctly under the table's native column sort.
        row["added"] = (row.get("created_at") or "")[:10]

        # Server-computed low-stock flag so the table highlight uses a simple,
        # version-proof equality query ({_low} = "low") instead of relying on
        # DataTable "is not blank"-style syntax that its grammar doesn't support.
        row["_low"] = "low" if data.is_low_stock(r) else ""

        # Truncate the description so rows stay compact — the full text (and the
        # extracted specs) are shown in the row's hover tooltip.
        full_desc = (row.get("description") or "").strip()
        if len(full_desc) > DESC_MAX_CHARS:
            cut = full_desc.rfind(" ", 0, DESC_MAX_CHARS)
            cut = cut if cut != -1 else DESC_MAX_CHARS
            row["description"] = full_desc[:cut].rstrip() + "…"
        else:
            row["description"] = full_desc

        full_ocr = (row.get("ocr_text") or "").strip()
        if len(full_ocr) > OCR_TEXT_MAX_CHARS:
            cut = full_ocr.rfind(" ", 0, OCR_TEXT_MAX_CHARS)
            cut = cut if cut != -1 else OCR_TEXT_MAX_CHARS
            display_ocr = full_ocr[:cut].rstrip() + "..."
        else:
            display_ocr = full_ocr
        row["ocr_text"] = display_ocr
        out_rows.append(row)
    return out_rows

def _apply_filters(items, search, filter_cat, filter_loc, filter_type=None, filter_bin=None):
    filtered = data.search(search) if search else items
    if filter_type:
        filtered = [r for r in filtered if (r.get("type") or "").strip() == filter_type]
    if filter_cat:
        filtered = [r for r in filtered if (r.get("category") or "").strip() == filter_cat]
    if filter_loc:
        filtered = [r for r in filtered if (r.get("location") or "").strip() == filter_loc]
    if filter_bin:
        filtered = [r for r in filtered if (r.get("location_code") or "").strip() == filter_bin]
    return filtered


def _apply_sort(rows, sort_by):
    """Order rows for the table. Defaults to newest-added first.

    Items missing a created_at (e.g. no image to derive one from) sort last under
    the date orderings so the dated ones lead.
    """
    sb = sort_by or "date_desc"
    if sb in ("date_desc", "date_asc"):
        desc = sb == "date_desc"
        # Empty created_at should always fall to the bottom, regardless of
        # direction, so pair each row with a "has date" flag for the sort key.
        def key(r):
            c = r.get("created_at") or ""
            return (bool(c), c) if desc else (not bool(c), c)
        return sorted(rows, key=key, reverse=desc)
    if sb in ("name_asc", "name_desc"):
        return sorted(rows, key=lambda r: (r.get("name") or "").lower(),
                      reverse=(sb == "name_desc"))
    if sb in ("qty_asc", "qty_desc"):
        return sorted(rows, key=lambda r: int(r.get("qty") or 0),
                      reverse=(sb == "qty_desc"))
    # Cluster related items together. Type follows the canonical TYPE_GROUPS order
    # (Tools, Components, …); Category/Location go alphabetically. In every case
    # items with no value for that field sink to the bottom, and rows within a
    # group are ordered by name so the cluster reads cleanly.
    if sb == "group_type":
        order = {g: i for i, g in enumerate(data.TYPE_GROUPS)}
        def tkey(r):
            v = (r.get("type") or "").strip()
            rank = order.get(v, len(order) + (1 if v else 2))  # custom types, then empty, last
            return (rank, v.lower(), (r.get("name") or "").lower())
        return sorted(rows, key=tkey)
    if sb in ("group_category", "group_location", "group_bin"):
        field = {"group_category": "category", "group_location": "location",
                 "group_bin": "location_code"}[sb]
        def gkey(r):
            v = (r.get(field) or "").strip()
            return (v == "", v.lower(), (r.get("name") or "").lower())
        return sorted(rows, key=gkey)
    return rows

def _breakdown_list(groups):
    """Render a summary_by() result as a compact list with quantity badges."""
    if not groups:
        return html.Div("Nothing here yet.", className="text-muted small")
    items = []
    for g in groups:
        items.append(
            html.Div(
                [
                    html.Span(g["name"], className="text-truncate me-2"),
                    html.Span(
                        [
                            html.Span(f"{g['qty']}", className="badge bg-primary rounded-pill me-1"),
                            html.Span(f"{g['items']} item{'s' if g['items'] != 1 else ''}", className="text-muted small"),
                        ],
                        className="text-nowrap",
                    ),
                ],
                className="d-flex justify-content-between align-items-center py-1 border-bottom",
            )
        )
    return html.Div(items)

def _render_plan(plan):
    """Render an auto_organize() plan as a readable analysis + preview table."""
    if not plan:
        return html.Div("Nothing to organize yet.", className="text-muted")

    total_items = sum(g.get("items", 0) for g in plan)
    total_val = sum(g.get("value", 0) or 0 for g in plan)

    rows = [
        html.Tr(
            [
                html.Th("Bin"),
                html.Th("Group"),
                html.Th("Items", className="text-end"),
                html.Th("Qty", className="text-end"),
                html.Th("Value", className="text-end"),
            ]
        )
    ]
    for g in plan:
        code_badge = html.Span(
            g.get("location_code", ""),
            className="badge bg-primary" if not g.get("existing") else "badge bg-info text-dark",
        )
        val = g.get("value", 0) or 0
        rows.append(
            html.Tr(
                [
                    html.Td(code_badge),
                    html.Td(g.get("location_name", "") or "—", className="fw-semibold"),
                    html.Td(str(g.get("items", 0)), className="text-end"),
                    html.Td(str(g.get("qty", 0)), className="text-end"),
                    html.Td(f"${val:,.2f}" if val else "—", className="text-end text-success"),
                ]
            )
        )
    return html.Div(
        [
            html.P(
                [
                    "Analysed ", html.Strong(f"{total_items} items"), " into ",
                    html.Strong(f"{len(plan)} bins"),
                    (f" · est. ${total_val:,.2f} total" if total_val else ""),
                    ".",
                ],
                className="mb-1",
            ),
            html.P(
                "Related items are grouped by their name & category (e.g. Toggle + "
                "Slide Switches → “Switches”). Blue bins keep a code they already "
                "had. Apply to stamp these bins onto every item.",
                className="text-muted small",
            ),
            dbc.Table(rows, bordered=False, hover=True, responsive=True, striped=True, className="mb-0"),
        ]
    )

def _render_storage_map(bins):
    """Render data.storage_overview() — every bin with its bags and live counts."""
    if not bins:
        return html.Div(
            "No bins yet — click “Set up bins” to say how many you have, or run Smart Organize.",
            className="text-muted small",
        )
    cards = []
    for b in bins:
        code = b.get("code", "")
        label = code or "Unfiled"
        badge_class = "badge bg-primary" if code else "badge bg-secondary"
        items = b.get("items", 0)
        cap = b.get("capacity", 0)
        over = bool(cap) and items > cap
        usage = f"{items}/{cap}" if cap else f"{items}"
        usage_class = "badge rounded-pill me-1 " + ("bg-danger" if over else "bg-primary")

        # Bags: the ones actually in use (with counts) first, then any planned
        # bags not yet used (as muted outlines).
        used = b.get("used_bags", []) or []            # [(name, count), …]
        used_names = {n.lower() for n, _ in used}
        chips = [
            html.Span(f"{name} · {cnt}",
                      className="badge bg-info-subtle text-dark border border-info-subtle me-1 mb-1")
            for name, cnt in used
        ]
        chips += [
            html.Span(p, className="badge bg-light text-muted border me-1 mb-1")
            for p in (b.get("bags") or []) if p.lower() not in used_names
        ]

        body = []
        if chips:
            body.append(html.Div(chips, className="mt-1"))
        names = b.get("names", []) or []
        if names:
            preview = ", ".join(names[:6]) + ("…" if len(names) > 6 else "")
            body.append(html.Div(preview, className="text-muted small mt-1"))
        elif not chips:
            body.append(html.Div("Empty", className="text-muted small fst-italic mt-1"))

        cards.append(
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(label, className=badge_class + " me-2"),
                            html.Span(b.get("name", "") or "", className="fw-semibold small"),
                            html.Span(
                                [
                                    html.Span(usage, className=usage_class),
                                    html.Span(f"item{'s' if items != 1 else ''}", className="text-muted small"),
                                ],
                                className="ms-auto text-nowrap",
                            ),
                        ],
                        className="d-flex align-items-center",
                    ),
                    *body,
                ],
                className="py-2 border-bottom",
            )
        )
    return html.Div(cards)

def _render_fit(plan):
    """Render a fit_to_containers() plan: per-bin capacity bars + overflow."""
    if not plan or not plan.get("ok"):
        msg = (plan or {}).get("error") or "Add your containers above, then Fit."
        return html.Div(msg, className="text-muted")
    cards = []
    for a in plan.get("assignments", []):
        used, cap = a.get("used", 0), a.get("capacity", 0)
        over = cap and used > cap
        pct = min(100, int(used * 100 / cap)) if cap else 0
        bar = "danger" if over else ("warning" if pct >= 90 else "success")
        contents = ", ".join(f"{g['name']} ({g['count']})" for g in a.get("groups", [])) or "— empty —"
        cards.append(
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(a["code"], className="badge bg-primary me-2"),
                            html.Strong(a["name"]),
                            html.Span(f"{used}/{cap}",
                                      className="ms-auto text-nowrap " + ("text-danger" if over else "text-muted")),
                        ],
                        className="d-flex align-items-center",
                    ),
                    dbc.Progress(value=pct, color=bar, className="my-1", style={"height": "6px"}),
                    html.Div(contents, className="text-muted small"),
                ],
                className="py-2 border-bottom",
            )
        )
    children = [html.Div(cards)]
    overflow = plan.get("overflow_names", [])
    if overflow:
        children.append(
            html.Div(
                [
                    html.I(className="bi bi-exclamation-triangle-fill me-2 text-warning"),
                    html.Strong(f"{len(overflow)} item(s) didn't fit: "),
                    html.Span(", ".join(overflow[:12]) + ("…" if len(overflow) > 12 else "")),
                    html.Div("Add capacity or another container, then Fit again.", className="text-muted small"),
                ],
                className="alert alert-warning mt-2 mb-0 py-2",
            )
        )
    else:
        children.append(
            html.Div(
                [html.I(className="bi bi-check-circle me-2 text-success"), "Everything fits — Apply to save."],
                className="text-success small mt-2",
            )
        )
    return html.Div(children)


def _render_dups(plans):
    """Render detected duplicate groups, each with survivor + rename controls."""
    if not plans:
        return html.Div(
            [html.I(className="bi bi-check-circle me-2 text-success"),
             "No duplicates found at this sensitivity. Try a looser setting to catch near-matches."],
            className="text-muted",
        )

    total_dupes = sum(len(p["merge_ids"]) for p in plans)
    cards = []
    for i, p in enumerate(plans):
        prev = p["preview"]

        # The entries being combined.
        entry_rows = []
        for r in p["items"]:
            entry_rows.append(html.Tr([
                html.Td(r.get("name", "")),
                html.Td(f"×{r.get('qty', 0)}", className="text-end"),
                html.Td(r.get("category") or "—", className="text-muted small"),
                html.Td(r.get("location_code") or r.get("location") or "—", className="text-muted small"),
                html.Td(f"{len(r.get('images') or [])}📷" if r.get("images") else "",
                        className="text-muted small"),
            ]))

        keep_opts = [{"label": f"{r.get('name', '(no name)')} (×{r.get('qty', 0)}"
                               f"{', ' + str(len(r.get('images') or [])) + ' photos' if r.get('images') else ''})",
                      "value": int(r.get("id"))} for r in p["items"]]

        controls = dbc.Row(
            [
                dbc.Col(
                    [dbc.Label("Keep which entry?", className="small mb-1"),
                     dcc.Dropdown(id={"type": "dup-primary", "index": i}, options=keep_opts,
                                  value=p["primary_id"], clearable=False, className="pc-dropdown")],
                    xs=12, sm=6,
                ),
                dbc.Col(
                    [dbc.Label("Name after merge", className="small mb-1"),
                     dbc.Input(id={"type": "dup-name", "index": i}, value=prev["name"], size="sm")],
                    xs=12, sm=6,
                ),
            ],
            className="g-2",
        )

        becomes = html.Div(
            [
                html.I(className="bi bi-arrow-right-circle me-1 text-success"),
                html.Strong("Combined: "),
                html.Span(f"qty {prev['qty']} · {len(prev['images'])} photo(s) · "
                          f"{len(prev['tags'])} tag(s) · {len(prev['specifications'])} spec(s)"),
            ],
            className="small mt-2",
        )
        conflict = html.Div()
        if p["conflicts"]:
            conflict = html.Div(
                [html.I(className="bi bi-exclamation-triangle me-1 text-warning"),
                 "Heads up — " + "; ".join(p["conflicts"]) + " (the kept entry's value is used)."],
                className="small text-warning mt-1",
            )
        cards.append(
            dbc.Card(
                dbc.CardBody(
                    [
                        dbc.Switch(id={"type": "dup-include", "index": i}, value=True,
                                   label=f"Merge these {len(p['item_ids'])} (~{p['match_pct']}% match)",
                                   className="fw-semibold"),
                        dbc.Table(html.Tbody(entry_rows), size="sm", borderless=True,
                                  className="mb-2 align-middle"),
                        controls,
                        becomes,
                        conflict,
                    ]
                ),
                className="mb-2",
            )
        )

    return html.Div([
        html.Div(
            [html.I(className="bi bi-collection me-2"),
             html.Strong(f"Found {len(plans)} group(s)"),
             f" — merging removes up to {total_dupes} duplicate "
             f"entr{'y' if total_dupes == 1 else 'ies'}. Pick the survivor / name per group, "
             "toggle off any to keep separate, then Merge selected."],
            className="alert alert-info py-2",
        ),
        html.Div(cards),
    ])


def _undo_alert(msg):
    """A dismissible bar offering to roll back the last destructive change."""
    return dbc.Alert(
        [
            html.I(className="bi bi-arrow-counterclockwise me-2"),
            html.Span(msg + " "),
            dbc.Button([html.I(className="bi bi-arrow-90deg-left me-1"), "Undo"],
                       id="undo-apply", color="warning", size="sm", className="ms-2",
                       n_clicks=0),
        ],
        color="secondary", className="py-2 mb-3 d-flex align-items-center",
        dismissable=True,
    )


def _render_connect(eps):
    """Render the list of access URLs (LAN / Tailscale / localhost) with QR codes."""
    if not eps:
        return html.Div("No network addresses found.", className="text-muted")
    import net_info
    kind_icon = {
        "lan": "bi-hdd-network", "tailscale": "bi-shield-lock",
        "loopback": "bi-pc-display", "other": "bi-globe",
    }
    cols = []
    for e in eps:
        qr = net_info.qr_data_uri(e["url"])
        qr_node = html.Img(src=qr, className="connect-qr mt-2") if qr else html.Div(
            "QR needs the 'qrcode' package.", className="text-muted small mt-2"
        )
        cols.append(
            dbc.Col(
                dbc.Card(
                    dbc.CardBody(
                        [
                            html.Div(
                                [html.I(className=f"bi {kind_icon.get(e['kind'], 'bi-globe')} me-2"),
                                 html.Strong(e["label"])],
                                className="mb-1",
                            ),
                            html.A(
                                e["url"], href=e["url"], target="_blank", rel="noopener noreferrer",
                                className="d-block text-break small",
                            ),
                            html.Div(qr_node, className="text-center"),
                        ]
                    ),
                    className="h-100 shadow-sm text-center",
                ),
                xs=12, sm=6, md=4, className="mb-3",
            )
        )
    return dbc.Row(cols, className="g-3")

def _render_import(res):
    """Render a product_import result (from a URL fetch or pasted/uploaded HTML)."""
    if not res.get("ok"):
        return html.Div(
            [
                html.P(
                    [html.I(className="bi bi-exclamation-triangle me-2"), "Couldn't import that page."],
                    className="fw-bold text-warning",
                ),
                html.P(res.get("error", ""), className="small"),
            ]
        )
    d = res.get("data") or {}

    def _row(icon, label, val):
        if not val:
            return None
        return html.Div(
            [
                html.Div([html.I(className=f"bi {icon} me-2 text-muted"), html.Span(label)], className="text-muted small"),
                html.Div(val, className="mt-1"),
            ],
            className="py-2 border-bottom",
        )

    header = [html.H4(d.get("name", "") or "Product", className="mb-0")]
    if d.get("estimated_value"):
        header.append(html.Span(d["estimated_value"], className="badge bg-success ms-2"))
    body = [html.Div(header, className="d-flex align-items-center flex-wrap mb-2")]

    if res.get("image_url"):
        body.append(
            html.Img(
                src=res["image_url"],
                className="mb-2",
                style={"maxHeight": "140px", "maxWidth": "100%", "objectFit": "contain", "borderRadius": "8px"},
            )
        )

    specs = d.get("specifications") or []
    specs_node = html.Ul([html.Li(s) for s in specs], className="mb-0") if specs else None
    for node in (
        _row("bi-tags", "Category", d.get("category")),
        _row("bi-info-circle", "Description", d.get("what_it_is")),
        _row("bi-list-check", "Specifications", specs_node),
    ):
        if node:
            body.append(node)

    tags = d.get("tags") or []
    if tags:
        body.append(html.Div([html.Span(t, className="badge bg-secondary me-1 mb-1") for t in tags], className="py-2"))

    body.append(
        html.Div(
            ["Imported via ", html.Code(res.get("via", "web")),
             " — use ", html.Strong("Apply to form"), " or ", html.Strong("Apply & Update"), " below."],
            className="text-muted small mt-2",
        )
    )
    return html.Div(body)

def _identify_footer(res):
    endpoint = (res.get("endpoint", "") or "").replace("/api/generate", "")
    return html.Div(
        ["via ", html.Code(res.get("model", "") or "?"), " @ ", html.Code(endpoint or "?")],
        className="text-muted small mt-3",
    )

def _web_search_buttons(links):
    """A row of 'search the web' link-buttons (open in a new tab).

    Google Lens (reverse image search) only appears when the app is reachable on
    a public URL, since Google must be able to fetch the photo. Text/Shopping
    search always work — they run in the user's browser, not from the server.
    """
    links = links or {}
    btns = []
    if links.get("lens"):
        btns.append(
            html.A(
                [html.I(className="bi bi-camera me-1"), "Google Lens (image)"],
                href=links["lens"], target="_blank", rel="noopener",
                className="btn btn-primary btn-sm me-2 mb-2",
            )
        )
    if links.get("text"):
        btns.append(
            html.A(
                [html.I(className="bi bi-google me-1"), "Google search"],
                href=links["text"], target="_blank", rel="noopener",
                className="btn btn-outline-secondary btn-sm me-2 mb-2",
            )
        )
    if links.get("shopping"):
        btns.append(
            html.A(
                [html.I(className="bi bi-bag me-1"), "Shopping / prices"],
                href=links["shopping"], target="_blank", rel="noopener",
                className="btn btn-outline-secondary btn-sm me-2 mb-2",
            )
        )
    if not btns:
        return html.Div()

    note = None
    if not links.get("lens_available"):
        note = html.Div(
            [
                html.I(className="bi bi-info-circle me-1"),
                "Tip: for reverse image search, right-click the photo and choose ",
                html.Em("“Search image with Google Lens”"),
                ". Enable Lens-by-link by serving this app on a public URL "
                "(Tailscale Funnel or PUBLIC_BASE).",
            ],
            className="text-muted small mt-1",
        )
    return html.Div(
        [
            html.Div([html.I(className="bi bi-globe me-2"), html.Strong("Look it up on the web")], className="mb-2"),
            html.Div(btns, className="d-flex flex-wrap"),
            note or html.Div(),
        ],
        className="py-2",
    )

def _identify_row(icon, label, value_node):
    return html.Div(
        [
            html.Div(
                [html.I(className=f"bi {icon} me-2 text-muted"), html.Span(label)],
                className="text-muted small",
            ),
            html.Div(value_node, className="mt-1"),
        ],
        className="py-2 border-bottom",
    )

def _render_web_match(web):
    """Render a web_detect.detect_web() result (reverse-image match)."""
    if not web:
        return html.Div()
    if not web.get("ok"):
        # Configured but failed — a small muted note; local result still shows.
        if web.get("configured") is False:
            return html.Div()
        return html.Div(
            [html.I(className="bi bi-cloud-slash me-1"),
             f"Web match unavailable: {web.get('error', 'unknown error')}"],
            className="text-muted small mb-2",
        )
    best = (web.get("best_guess") or "").strip()
    entities = web.get("entities") or []
    pages = web.get("pages") or []

    children = [
        html.Div(
            [html.I(className="bi bi-globe2 me-2"),
             html.Strong("Best web match"),
             html.Span(f"  ·  {web.get('provider', '')}", className="text-muted small")],
            className="mb-1",
        )
    ]
    if best:
        children.append(html.Div(best, className="fs-5 fw-semibold"))
        children.append(
            html.Div("This becomes the item name when you Apply.", className="text-muted small mb-2")
        )
    else:
        children.append(html.Div("No confident product name from the image.", className="text-muted small mb-2"))

    if entities:
        children.append(
            html.Div(
                [html.Span(e, className="badge bg-secondary me-1 mb-1") for e in entities[:8]],
                className="mb-2",
            )
        )
    if pages:
        children.append(html.Div([html.I(className="bi bi-link-45deg me-1"), "Matching pages:"], className="small text-muted"))
        children.append(
            html.Ul(
                [
                    html.Li(
                        html.A(p["title"][:90], href=p["url"], target="_blank", rel="noopener noreferrer")
                    )
                    for p in pages[:5]
                ],
                className="mb-0 small",
            )
        )
    return html.Div(children, className="p-2 mb-3 rounded border")


def _render_identify(res, links=None):
    """Read-only rendering of a vision_lookup.identify_item() result."""
    if not res.get("ok"):
        return html.Div(
            [
                html.P(
                    [html.I(className="bi bi-exclamation-triangle me-2"), "Couldn't reach the vision service."],
                    className="fw-bold text-danger",
                ),
                html.P(res.get("error", ""), className="small"),
                # Even when the local model is down, the web search still works.
                _web_search_buttons(links) if links else html.Div(),
                html.Hr(),
                html.P(["Endpoint: ", html.Code(res.get("endpoint", "") or "—")], className="small mb-1"),
                html.P(["Model: ", html.Code(res.get("model", "") or "—")], className="small mb-1"),
                html.P(
                    [
                        "Tip: set ", html.Code("OLLAMA_HOST"), " / ", html.Code("OLLAMA_VISION_MODEL"),
                        " and pull a vision model, e.g. ", html.Code("ollama pull llava:13b"), ".",
                    ],
                    className="small text-muted",
                ),
            ]
        )

    data = res.get("data")
    if not isinstance(data, dict):
        return html.Div(
            [
                html.P("Here's what the model returned (couldn't parse it as structured data):", className="fw-bold"),
                html.Pre(res.get("raw", "") or "(empty)", style={"whiteSpace": "pre-wrap"}),
                _identify_footer(res),
            ]
        )

    def _txt(v):
        return "" if v is None else str(v).strip()

    def _disp(v):
        t = _txt(v)
        return "—" if (not t or t.lower() == "unknown") else t

    name = _txt(data.get("name")) or "Unidentified item"
    conf = _txt(data.get("confidence")).lower()
    conf_color = {"high": "success", "medium": "warning", "low": "danger"}.get(conf, "secondary")

    rows = [
        _identify_row("bi-info-circle", "What it is", _disp(data.get("what_it_is"))),
        _identify_row("bi-tags", "Category", _disp(data.get("category"))),
    ]

    specs = data.get("specifications")
    if isinstance(specs, list) and any(_txt(s) for s in specs):
        specs_node = html.Ul([html.Li(_txt(s)) for s in specs if _txt(s)], className="mb-0")
    else:
        specs_node = _disp(specs if isinstance(specs, str) else None)
    rows.append(_identify_row("bi-list-check", "Specifications", specs_node))
    rows.append(_identify_row("bi-cash-coin", "Estimated value", _disp(data.get("estimated_value"))))
    rows.append(_identify_row("bi-rulers", "Dimensions", _disp(data.get("dimensions"))))

    header = [html.H4(name, className="mb-0")]
    if conf:
        header.append(html.Span(conf.capitalize(), className=f"badge bg-{conf_color} ms-2"))

    return html.Div(
        [
            html.Div(header, className="d-flex align-items-center mb-3"),
            html.Div(rows),
            html.Div(
                "⚠️ These are AI estimates read from the photo — double-check before relying on them. "
                "Use “Apply to item” below to copy them into the form.",
                className="text-muted small mt-3",
            ),
            html.Hr(),
            _web_search_buttons(links) if links else html.Div(),
            _identify_footer(res),
        ]
    )

def _container_row(i, c):
    """One editable container row: Name + Bags + a remove button (capacity is
    carried in a hidden field so it survives without cluttering the row)."""
    c = c or {}
    return dbc.Row(
        [
            dbc.Col(dbc.Input(id={"type": "cont-name", "index": i}, value=c.get("name", ""),
                              placeholder="Name — drawer, tote, box, bag…", size="sm"),
                    xs=12, sm=6),
            dbc.Col(dbc.Input(id={"type": "cont-bags", "index": i},
                              value=", ".join(c.get("bags") or []),
                              placeholder="bags inside (comma-separated)", size="sm"),
                    xs=10, sm=5),
            dbc.Col(dbc.Button(html.I(className="bi bi-x-lg"),
                               id={"type": "cont-remove", "index": i},
                               color="link", size="sm", title="Remove this container",
                               className="text-danger px-1"),
                    xs=2, sm=1, className="text-end"),
            dbc.Input(id={"type": "cont-slots", "index": i}, type="number",
                      value=(c.get("capacity") or 25), style={"display": "none"}),
        ],
        className="g-1 mb-1 align-items-center",
    )


def _raw_rows(names, bags, slots):
    """Rebuild the on-screen container rows (blank rows kept, aligned to what the
    user sees) so add/remove/generate operate on the exact visible list. Codes
    are derived later, at save time."""
    n = max(len(names or []), len(bags or []), len(slots or []))
    out = []
    for i in range(n):
        nm = (names[i] if names and i < len(names) else "") or ""
        bg = (bags[i] if bags and i < len(bags) else "") or ""
        raw_cap = slots[i] if slots and i < len(slots) else None
        try:
            cap = int(raw_cap) if raw_cap not in (None, "") else 25
        except (TypeError, ValueError):
            cap = 25
        out.append({"name": nm, "bags": data._clean_bags(bg), "capacity": max(1, cap)})
    return out


def _qa_photo_gallery(photos):
    """Read-with-remove thumbnail strip for the Quick Add photo step."""
    return photo_gallery(photos, "qa-photo-remove")


def _batch_preview(photos):
    """Thumbnail strip + count for the batch-add modal, each removable."""
    photos = photos or []
    if not photos:
        return html.Div("No photos yet — add some above.", className="text-muted small")
    n = len(photos)
    header = html.Div(
        [html.Strong(f"{n} photo{'s' if n != 1 else ''}"),
         html.Span(f" → {n} item{'s' if n != 1 else ''} will be created", className="text-muted")],
        className="small mb-1",
    )
    return html.Div([header, photo_gallery(photos, "batch-photo-remove", labels=False)])


def _qa_apply_parsed(d, cur_name, cur_cat, cur_value, cur_extra, cur_src):
    """Fold a vision/import result into the wizard's review fields.

    Only fills blanks, so running Identify and then importing a page (or the
    reverse) never clobbers something already found or typed. Specs / dims / tags
    / url / description ride along in the ``extra`` store.
    """
    d = d or {}

    def _s(v):
        t = "" if v is None else str(v).strip()
        return "" if t.lower() == "unknown" else t

    name = (cur_name or "").strip() or _s(d.get("name"))
    category = (cur_cat or "").strip() or _s(d.get("category"))
    value = (cur_value or "").strip() or _s(d.get("estimated_value"))
    extra = dict(cur_extra or {})

    specs = d.get("specifications")
    specs_text = _specs_to_text(specs) if isinstance(specs, list) else _s(specs)
    if specs_text and not (extra.get("specifications") or "").strip():
        extra["specifications"] = specs_text
    dims = _s(d.get("dimensions"))
    if dims and not (extra.get("dimensions") or "").strip():
        extra["dimensions"] = dims
    tags = d.get("tags")
    tags_text = _tags_to_text(tags) if isinstance(tags, list) else _s(tags)
    if tags_text and not (extra.get("tags") or "").strip():
        extra["tags"] = tags_text
    url = _s(d.get("product_url"))
    if url and not (extra.get("product_url") or "").strip():
        extra["product_url"] = url
    what = _s(d.get("what_it_is"))
    if what and what.lower() not in (extra.get("description") or "").lower():
        extra["description"] = ((extra.get("description") or "") + "\n" + what).strip()

    src = (cur_src or "").strip() or _s(d.get("source_title"))
    return name, category, value, extra, src


def _per_unit_adjust(d):
    """For a multi-pack listing, swap the whole-pack estimated_value for the
    per-unit price and keep the pack total as a spec note (reuses Price Compare's
    pack detection). Mutates and returns the data dict. Never raises."""
    try:
        import price_compare
        pu = price_compare.per_unit_value(d.get("estimated_value", ""), d.get("name", ""),
                                          d.get("specifications"), d.get("what_it_is", ""))
        if pu["unit_price"] is not None and 1 < pu["qty"] <= 2000:
            d["estimated_value"] = f"{pu['currency']}{pu['unit_price']:.2f}"
            specs = list(d.get("specifications") or [])
            if pu["formatted"] and pu["formatted"] not in specs:
                specs.insert(0, pu["formatted"])
            d["specifications"] = specs
    except Exception:
        pass
    return d


def _tile_details(r):
    """Expanded detail panel for a gallery tile: photos (tap to enlarge), the
    catalogue fields, specs, documents (in-app viewable), and an Edit button."""
    iid = r.get("id")
    imgs = r.get("images") or []
    photo_strip = html.Div(
        [html.Img(src=get_thumbnail_url(f), className="gallery-detail-thumb",
                  id={"type": "gallery-photo", "item": iid, "idx": j}, n_clicks=0,
                  title="View full-size")
         for j, f in enumerate(imgs) if get_thumbnail_url(f)],
        className="d-flex flex-wrap gap-2 mb-2",
    ) if imgs else None

    fields = []

    def _fld(label, val):
        val = ("" if val is None else str(val)).strip()
        if val:
            fields.append(html.Div([html.Span(f"{label}: ", className="text-muted"),
                                    html.Span(val)], className="small"))
    _fld("Type", r.get("type"))
    _fld("Category", r.get("category"))
    _fld("Location", r.get("location"))
    _fld("Bin", r.get("location_code"))
    _fld("Value", r.get("estimated_value"))
    _fld("Reorder at", r.get("reorder_at"))
    _fld("Tags", ", ".join(r.get("tags") or []))

    body = [
        html.Div(
            [html.Strong(r.get("name", "") or "(unnamed)"),
             dbc.Button([html.I(className="bi bi-pencil me-1"), "Edit"],
                        id={"type": "gallery-edit", "index": iid}, color="primary",
                        size="sm", className="ms-auto", n_clicks=0)],
            className="d-flex align-items-center mb-2",
        ),
    ]
    if photo_strip is not None:
        body.append(photo_strip)
    desc = (r.get("description") or "").strip()
    if desc:
        body.append(html.Div(desc, className="mb-2"))
    if fields:
        body.append(html.Div(fields, className="mb-2"))
    specs = r.get("specifications") or []
    if specs:
        body.append(html.Div(
            [html.Div("Specs", className="text-muted small")]
            + [html.Div(f"• {s}", className="small") for s in specs], className="mb-2"))
    atts = r.get("attachments") or []
    if atts:
        body.append(html.Div([html.Div("Documents", className="text-muted small mb-1"),
                              _render_attachments(atts, remove_type=None)]))
    return dbc.Card(dbc.CardBody(body), className="gallery-detail")


def _build_gallery(items, open_id):
    """Responsive grid of photo tiles; the one whose id == open_id renders an
    expanded, full-width detail panel right after it (tap-to-expand-in-place)."""
    if not items:
        return html.Div([html.I(className="bi bi-search me-2"),
                         "No items match your search / filters."],
                        className="text-muted p-4 text-center")
    cols = []
    for r in items:
        iid = r.get("id")
        imgs = r.get("images") or []
        thumb = get_preview_url(imgs[0]) if imgs else ""
        expanded = iid is not None and iid == open_id
        img_el = (html.Img(src=thumb, className="gallery-tile-img")
                  if thumb else html.Div("📦", className="gallery-tile-noimg"))
        meta = [html.Span(f"×{r.get('qty', 0)}", className="badge bg-secondary me-1")]
        loc = (r.get("location") or "").strip() or (r.get("location_code") or "").strip()
        if loc:
            meta.append(html.Span([html.I(className="bi bi-geo-alt me-1"), loc],
                                  className="text-muted"))
        head = [img_el]
        if len(imgs) > 1:
            head.append(html.Span([str(len(imgs)), html.I(className="bi bi-images ms-1")],
                                  className="gallery-tile-photocount"))
        tile = dbc.Button(
            dbc.Card(
                [html.Div(head, className="position-relative"),
                 dbc.CardBody(
                     [html.Div(r.get("name", "") or "(unnamed)", className="gallery-tile-name"),
                      html.Div(meta, className="gallery-tile-meta mt-1")],
                     className="p-2")],
                className="gallery-tile h-100" + (" expanded" if expanded else ""),
            ),
            id={"type": "gallery-tile", "index": iid}, n_clicks=0,
            color="link", className="p-0 w-100 text-decoration-none text-start",
        )
        cols.append(dbc.Col(tile, xs=6, sm=4, md=3, lg=2, className="mb-2"))
        if expanded:
            cols.append(dbc.Col(_tile_details(r), xs=12, className="mb-2"))
    return dbc.Row(cols, className="g-2")


def register_callbacks(app):
    # ---------- Large-photo mode: toggle a body class (clientside, no round-trip) ----------
    # Bigger table thumbnails so you can visually confirm a search hit without
    # opening the full image. Toggling a class on <body> survives table re-renders
    # (the DataTable's data changes, but body doesn't), and the CSS in custom.css
    # keys off body.large-thumbs.
    app.clientside_callback(
        """
        function(on) {
            try { document.body.classList.toggle('large-thumbs', !!on); } catch (e) {}
            return '';
        }
        """,
        Output("large-thumbs-sink", "children"),
        Input("large-thumbs", "value"),
    )

    # ---------- Gallery view: swap table <-> tile grid (clientside body class) ----------
    app.clientside_callback(
        """
        function(on) {
            try { document.body.classList.toggle('gallery-mode', !!on); } catch (e) {}
            return '';
        }
        """,
        Output("gallery-mode-sink", "children"),
        Input("gallery-view", "value"),
    )

    # ---------- Gallery: build the tiles (shares the table's search/filter/sort) ----------
    @app.callback(
        Output("inventory-gallery", "children"),
        Input("gallery-view", "value"),
        Input("search-bar", "value"),
        Input("filter-type", "value"),
        Input("filter-category", "value"),
        Input("filter-location", "value"),
        Input("filter-bin", "value"),
        Input("sort-by", "value"),
        Input("refresh-seq", "data"),
        Input("gallery-open-id", "data"),
        prevent_initial_call=False,
    )
    def render_gallery(is_gallery, search, ftype, fcat, floc, fbin, sort_by, _refresh, open_id):
        # Only build tiles while the gallery is showing — no wasted work in table
        # mode. prevent_initial_call=False so a persisted "Gallery on" builds on load.
        if not is_gallery:
            raise PreventUpdate
        filtered = _apply_filters(data.inventory(), search, fcat, floc, ftype, fbin)
        filtered = _apply_sort(filtered, sort_by)
        return _build_gallery(filtered, open_id)

    # ---------- Gallery: tap a tile to expand its details in place ----------
    @app.callback(
        Output("gallery-open-id", "data"),
        Input({"type": "gallery-tile", "index": ALL}, "n_clicks"),
        State("gallery-open-id", "data"),
        prevent_initial_call=True,
    )
    def gallery_toggle_tile(clicks, open_id):
        if not any(clicks or []):
            raise PreventUpdate
        iid = (ctx.triggered_id or {}).get("index")
        return None if iid == open_id else iid   # tap the open tile again to collapse

    # ---------- Gallery: "Edit" loads the item into the form (via row selection) ----------
    @app.callback(
        Output("inventory-table", "selected_rows", allow_duplicate=True),
        Input({"type": "gallery-edit", "index": ALL}, "n_clicks"),
        State("search-bar", "value"),
        State("filter-type", "value"),
        State("filter-category", "value"),
        State("filter-location", "value"),
        State("filter-bin", "value"),
        State("sort-by", "value"),
        prevent_initial_call=True,
    )
    def gallery_edit(clicks, search, ftype, fcat, floc, fbin, sort_by):
        if not any(clicks or []):
            raise PreventUpdate
        iid = (ctx.triggered_id or {}).get("index")
        # Same filter+sort order as the table, so the item's position == its
        # selected_rows index; selecting it makes manage_table load the form.
        filtered = _apply_sort(_apply_filters(data.inventory(), search, fcat, floc, ftype, fbin),
                               sort_by)
        idx = next((i for i, r in enumerate(filtered) if r.get("id") == iid), None)
        if idx is None:
            raise PreventUpdate
        return [idx]

    # ---------- Gallery: tap a photo → open the full-image modal ----------
    @app.callback(
        Output("image-modal", "is_open", allow_duplicate=True),
        Output("image-modal-title", "children", allow_duplicate=True),
        Output("image-carousel", "items", allow_duplicate=True),
        Output("image-modal-fullres", "children", allow_duplicate=True),
        Input({"type": "gallery-photo", "item": ALL, "idx": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def gallery_open_photos(clicks):
        if not any(clicks or []):
            raise PreventUpdate
        iid = (ctx.triggered_id or {}).get("item")
        row = next((r for r in data.inventory() if r.get("id") == iid), None)
        imgs = (row or {}).get("images") or []
        if not imgs:
            raise PreventUpdate
        items = [{"key": str(i), "src": get_preview_url(f),
                  "img_style": {"maxHeight": "70vh", "objectFit": "contain"}}
                 for i, f in enumerate(imgs)]
        return True, row.get("name", ""), items, _fullres_links([get_image_url(f) for f in imgs])

    # ---------- Table & form (single source of truth for table + toast) ----------
    @app.callback(
        [
            Output("inventory-table", "data"),
            Output("inventory-table", "selected_rows"),
            Output("item-name", "value"),
            Output("item-desc", "value"),
            Output("item-qty", "value"),
            Output("item-reorder", "value"),
            Output("item-type", "value"),
            Output("item-category", "value"),
            Output("item-location", "value"),
            Output("item-location-code", "value"),
            Output("item-specs", "value"),
            Output("item-value", "value"),
            Output("item-dims", "value"),
            Output("item-tags", "value"),
            Output("item-producturl", "value"),
            Output("editing-id", "data"),
            Output("current-images", "data"),
            Output("image-upload", "contents"),
            Output("action-toast", "is_open"),
            Output("action-toast", "header"),
            Output("action-toast", "icon"),
            Output("action-toast", "children"),
        ],
        [
            Input("url", "pathname"),               # ensures initial population
            Input("save-button", "n_clicks"),
            Input("save-next-button", "n_clicks"),
            Input("delete-button", "n_clicks"),
            Input("inventory-table", "selected_rows"),
            Input("cancel-button", "n_clicks"),
            Input("search-bar", "value"),
            Input("filter-type", "value"),
            Input("filter-category", "value"),
            Input("filter-location", "value"),
            Input("filter-bin", "value"),
            Input("sort-by", "value"),
            Input("refresh-seq", "data"),
        ],
        [
            State("item-name", "value"),
            State("item-desc", "value"),
            State("item-qty", "value"),
            State("item-reorder", "value"),
            State("item-type", "value"),
            State("item-category", "value"),
            State("item-location", "value"),
            State("item-location-code", "value"),
            State("item-specs", "value"),
            State("item-value", "value"),
            State("item-dims", "value"),
            State("item-tags", "value"),
            State("item-producturl", "value"),
            State("image-upload", "contents"),
            State("current-images", "data"),
            State("editing-id", "data"),
            State("inventory-table", "data"),
            State("item-order-number", "value"),
            State("item-purchase-date", "value"),
            State("item-price-paid", "value"),
            State("item-seller", "value"),
            State("current-attachments", "data"),
        ],
        prevent_initial_call=False,
    )
    def manage_table(pathname, save_clicks, save_next_clicks, delete_clicks, sel_rows, cancel_clicks,
                     search, filter_type, filter_cat, filter_loc, filter_bin, sort_by, _refresh_seq,
                     name, desc, qty, reorder, item_type, category, location, location_code,
                     specs, value, dims, tags, producturl, img_contents,
                     current_images, editing_id, current_rows,
                     order_number, purchase_date, price_paid, seller, current_attachments):
        triggered = (ctx.triggered_id or "")
        # Default toast outputs to no_update: 'inventory-table.selected_rows' is both
        # an Output and an Input here, so resetting the selection after a Save/Delete
        # re-enters this callback. If the toast defaulted to closed, that second pass
        # would immediately hide the success toast, so leave it untouched instead.
        toast_open, toast_header, toast_icon, toast_msg = no_update, no_update, no_update, no_update
        next_sel = sel_rows or []
        next_name = next_desc = next_qty = next_type = next_category = next_location = no_update
        next_code = next_specs = next_value = next_dims = next_tags = next_url = no_update
        next_editing = next_images = next_upload = next_reorder = no_update

        def _clear_form(keep_location=False):
            """Reset the form. When keep_location, the type/category/location/bin stay
            so you can scan a run of similar items without re-typing where they live."""
            nonlocal next_name, next_desc, next_qty, next_type, next_category, next_location
            nonlocal next_code, next_specs, next_value, next_dims, next_tags, next_url
            nonlocal next_editing, next_images, next_upload, next_sel, next_reorder
            next_sel = []
            next_name, next_desc, next_qty = "", "", 1
            next_reorder = None
            next_specs, next_value, next_dims, next_tags, next_url = "", "", "", "", ""
            if not keep_location:
                next_type, next_category, next_location, next_code = "", "", "", ""
            next_editing, next_images, next_upload = None, [], None

        # Always load latest items
        items = data.inventory()

        # Create / Update (Save and Save & Next share the write path)
        if triggered in ("save-button", "save-next-button"):
            nm = (name or "").strip()
            has_photo = bool(img_contents) or bool(current_images)
            # Quick phone capture: if there's a photo but no name, auto-number it
            # (Item 0001, Item 0002 …) so you can snap-and-save without typing and
            # fill in the real details later from a desktop.
            if not nm and has_photo and not editing_id:
                nm = data.next_auto_name()
            if not nm:
                toast_open, toast_header, toast_icon, toast_msg = (
                    True, "Add a photo or name", "warning",
                    "Take a photo (it'll auto-number) or type a name first.",
                )
            else:
                ds = (desc or "").strip()
                cat = (category or "").strip()
                typ = (item_type or "").strip()
                loc = (location or "").strip()
                code = (location_code or "").strip()
                nqty = _parse_qty(qty)

                # Photos were saved and appended to current-images as they were
                # taken/chosen (so multiple snaps and file picks accumulate), so we
                # just persist that set here — no re-saving of a pending upload.
                img_filenames = list(current_images or [])
                # Purchase record + attached documents from the form's collapsible.
                p_order = (order_number or "").strip()
                p_date = (purchase_date or "").strip()
                p_price = (price_paid or "").strip()
                p_seller = (seller or "").strip()
                atts = list(current_attachments or [])

                saved_ok = True
                try:
                    if editing_id:
                        # preserve existing ocr_text if not part of this form
                        existing_row = next((r for r in items if r.get("id") == editing_id), {})
                        existing_ocr = existing_row.get("ocr_text", "")
                        data.update_item(editing_id, nm, ds, nqty, img_filenames, existing_ocr,
                                         category=cat, location=loc, location_code=code,
                                         specifications=specs, estimated_value=value,
                                         dimensions=dims, tags=tags, product_url=producturl,
                                         item_type=typ, reorder_at=reorder,
                                         attachments=atts, order_number=p_order,
                                         purchase_date=p_date, price_paid=p_price, seller=p_seller)
                        toast_header, toast_icon, toast_msg = "Item Updated", "success", f'"{nm}" updated.'
                    else:
                        data.add_item(nm, ds, nqty, img_filenames, "", category=cat, location=loc,
                                      location_code=code, specifications=specs, estimated_value=value,
                                      dimensions=dims, tags=tags, product_url=producturl,
                                      item_type=typ, reorder_at=reorder,
                                      attachments=atts, order_number=p_order,
                                      purchase_date=p_date, price_paid=p_price, seller=p_seller)
                        toast_header, toast_icon, toast_msg = "Item Added", "success", f'"{nm}" added.'
                except ValueError as e:
                    # Save failed (duplicate name, or the edited item vanished).
                    # Keep the form and any staged photos/attachments intact so the
                    # user can fix the name and retry — don't clear on failure.
                    saved_ok = False
                    hdr = "Duplicate Name" if "already exists" in str(e).lower() else "Couldn't Save"
                    toast_header, toast_icon, toast_msg = hdr, "danger", str(e)

                toast_open = True
                if saved_ok:
                    # Save & Next keeps where-it-lives sticky for rapid batch scanning.
                    _clear_form(keep_location=(triggered == "save-next-button"))
                    # refresh items for table build
                    items = data.inventory()

        # Delete
        elif triggered == "delete-button":
            if editing_id:
                removed = data.remove_item(editing_id)
                if removed:
                    toast_open, toast_header, toast_icon, toast_msg = True, "Item Deleted", "danger", f'"{removed.get("name","")}" deleted.'
                _clear_form()
                data.prune_unreferenced_images()  # reclaim the deleted item's photos
                data.prune_unreferenced_documents()  # …and its attachments
                items = data.inventory()

        # Cancel clears form (and reclaims any just-taken photos that weren't saved)
        elif triggered == "cancel-button":
            _clear_form()
            data.prune_unreferenced_images()
            data.prune_unreferenced_documents()

        # Selecting a single row populates the form for editing. When 2+ rows are
        # ticked the user is bulk-editing, so leave the form alone (the bulk bar
        # handles it) and don't load anything.
        elif triggered == "inventory-table":
            if sel_rows and len(sel_rows) == 1:
                idx = sel_rows[0]
                if isinstance(idx, int) and 0 <= idx < len(current_rows or []):
                    row = (current_rows or [])[idx]
                    # Load the authoritative record from disk
                    actual_row = next((r for r in items if r.get("id") == row.get("id")), {})
                    next_name = actual_row.get("name", row.get("name", ""))
                    next_desc = actual_row.get("description", row.get("description", ""))
                    next_qty = actual_row.get("qty", row.get("qty", None))
                    next_reorder = actual_row.get("reorder_at")
                    next_type = actual_row.get("type", "")
                    next_category = actual_row.get("category", "")
                    next_location = actual_row.get("location", "")
                    next_code = actual_row.get("location_code", "")
                    next_specs = _specs_to_text(actual_row.get("specifications", []))
                    next_value = actual_row.get("estimated_value", "")
                    next_dims = actual_row.get("dimensions", "")
                    next_tags = _tags_to_text(actual_row.get("tags", []))
                    next_url = actual_row.get("product_url", "")
                    next_editing = row.get("id")
                    next_images = actual_row.get("images", [])
                    # Discard any pending (unsaved) upload so it isn't attached to
                    # the item we just switched to.
                    next_upload = None

        # Search / filter / sort change: drop the stale selection highlight (the
        # edit form and editing-id are intentionally left as-is).
        elif triggered in ("search-bar", "filter-type", "filter-category", "filter-location",
                           "filter-bin", "sort-by"):
            next_sel = []

        # Filter/search, then order for display.
        filtered = _apply_filters(items, search, filter_cat, filter_loc, filter_type, filter_bin)
        filtered = _apply_sort(filtered, sort_by)
        out_rows = _build_rows(filtered)

        return [
            out_rows, next_sel, next_name, next_desc, next_qty, next_reorder, next_type,
            next_category, next_location,
            next_code, next_specs, next_value, next_dims, next_tags, next_url,
            next_editing, next_images, next_upload,
            toast_open, toast_header, toast_icon, toast_msg
        ]

    # ---------- Collapsible dashboard sections (expand-for-detail cards) ----------
    @app.callback(
        Output("collapse-add", "is_open"),
        Input("toggle-add", "n_clicks"),
        Input("editing-id", "data"),
        State("collapse-add", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_add_section(_n, editing_id, is_open):
        # Picking a row for editing auto-opens the form; the Add-item button flips
        # it. Clearing the selection (editing_id -> None) leaves it as-is.
        if ctx.triggered_id == "editing-id":
            if editing_id:
                return True
            raise PreventUpdate
        return not is_open

    @app.callback(
        Output("collapse-filter", "is_open"),
        Input("toggle-filter", "n_clicks"),
        State("collapse-filter", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_filter_section(_n, is_open):
        return not is_open

    @app.callback(
        Output("collapse-overview", "is_open"),
        Input("toggle-overview", "n_clicks"),
        State("collapse-overview", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_overview_section(_n, is_open):
        return not is_open

    @app.callback(
        Output("collapse-storage", "is_open"),
        Input("toggle-storage", "n_clicks"),
        State("collapse-storage", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_storage_section(_n, is_open):
        return not is_open

    # ---------- Populate filter dropdowns & type-ahead suggestions ----------
    @app.callback(
        Output("filter-type", "options"),
        Output("filter-category", "options"),
        Output("filter-location", "options"),
        Output("filter-bin", "options"),
        Output("type-datalist", "children"),
        Output("category-datalist", "children"),
        Output("location-datalist", "children"),
        Output("location-code-datalist", "children"),
        Input("inventory-table", "data"),
        prevent_initial_call=False,
    )
    def refresh_organizers(_table_data):
        # Always derive from the FULL inventory (not the filtered view) so you can
        # switch between filters freely and newly-added values show up immediately.
        all_items = data.inventory()
        present_types = data.types(all_items)
        cats = data.categories(all_items)
        locs = data.locations(all_items)
        codes = data.location_codes(all_items)
        # Item counts per value so the filter dropdowns read "Tools (12)" — a quick
        # sense of how big each group is without opening it.
        type_n = {g["name"]: g["items"] for g in data.summary_by("type", all_items)}
        cat_n = {g["name"]: g["items"] for g in data.summary_by("category", all_items)}
        loc_n = {g["name"]: g["items"] for g in data.summary_by("location", all_items)}
        code_n = {g["name"]: g["items"] for g in data.summary_by("location_code", all_items)}
        type_opts = [{"label": f"{t} ({type_n.get(t, 0)})", "value": t} for t in present_types]
        cat_opts = [{"label": f"{c} ({cat_n.get(c, 0)})", "value": c} for c in cats]
        loc_opts = [{"label": f"{l} ({loc_n.get(l, 0)})", "value": l} for l in locs]
        bin_opts = [{"label": f"{c} ({code_n.get(c, 0)})", "value": c} for c in codes]
        # Datalist suggestions for Type: always offer the canonical groups, plus
        # any custom values already in use, so the form nudges toward consistency.
        type_choices = list(data.TYPE_GROUPS) + [t for t in present_types if t not in data.TYPE_GROUPS]
        type_dl = [html.Option(value=t) for t in type_choices]
        cat_dl = [html.Option(value=c) for c in cats]
        # Location type-ahead also offers the bag names defined on your bins, so a
        # bag can be used as an item's sub-location without retyping it.
        conts = data.containers()
        bag_names = []
        for c in conts:
            bag_names += (c.get("bags") or [])
        loc_choices = list(dict.fromkeys(list(locs) + bag_names))
        # Bin/code type-ahead offers every defined bin code too.
        code_choices = list(dict.fromkeys(list(codes) + [c["code"] for c in conts]))
        loc_dl = [html.Option(value=l) for l in loc_choices]
        code_dl = [html.Option(value=c) for c in code_choices]
        return (type_opts, cat_opts, loc_opts, bin_opts,
                type_dl, cat_dl, loc_dl, code_dl)

    # ---------- Rich hover tooltips (full extracted details per row) ----------
    @app.callback(
        Output("inventory-table", "tooltip_data"),
        Input("inventory-table", "data"),
        prevent_initial_call=False,
    )
    def build_tooltips(rows):
        full = {r.get("id"): r for r in data.inventory()}
        tips = []
        for row in rows or []:
            item = full.get(row.get("id"), {})
            parts = []
            if item.get("estimated_value"):
                parts.append(f"**Value:** {item['estimated_value']}")
            if item.get("dimensions") and item["dimensions"].lower() != "unknown":
                parts.append(f"**Dimensions:** {item['dimensions']}")
            specs = item.get("specifications") or []
            if specs:
                parts.append("**Specs:**\n" + "\n".join(f"- {s}" for s in specs[:18]))
            tags = item.get("tags") or []
            if tags:
                parts.append("**Tags:** " + ", ".join(tags))
            desc = (item.get("description") or "").strip()
            if desc:
                parts.append(f"**Notes:** {desc}")
            if item.get("product_url"):
                parts.append(f"[Open product page]({item['product_url']})")
            md = "\n\n".join(parts) or "_No extra details yet._"
            cell = {"value": md, "type": "markdown"}

            # Docs column tooltip: the purchase record + the attached files.
            dparts = []
            purchase = []
            if item.get("seller"):
                purchase.append(f"**Seller:** {item['seller']}")
            if item.get("order_number"):
                purchase.append(f"**Order #:** {item['order_number']}")
            if item.get("purchase_date"):
                purchase.append(f"**Date:** {item['purchase_date']}")
            if item.get("price_paid"):
                purchase.append(f"**Paid:** {item['price_paid']}")
            if purchase:
                dparts.append("\n".join(purchase))
            atts = item.get("attachments") or []
            if atts:
                names = "\n".join(f"- {a.get('original_name') or a.get('filename')}" for a in atts[:12])
                dparts.append(f"**Documents ({len(atts)}):**\n{names}")
            docs_md = "\n\n".join(dparts) or "_No documents or purchase info yet._"
            docs_cell = {"value": docs_md, "type": "markdown"}

            # Same rich tooltip on the columns you're most likely to hover.
            tips.append({"name": cell, "description": cell, "estimated_value": cell,
                         "docs": docs_cell})
        return tips

    def _render_gallery(img_list):
        """Thumbnails for the current photo set, each with a remove (×) button."""
        from dash import html as h
        items = []
        for i, img_filename in enumerate(img_list or []):
            thumb_url = get_thumbnail_url(img_filename)
            if not thumb_url:
                continue
            items.append(
                h.Div(
                    [
                        h.Img(src=thumb_url, className="gallery-thumb"),
                        h.Button(
                            "×",
                            id={"type": "delete-image", "index": i},
                            className="btn btn-sm btn-danger delete-img-btn",
                            title="Remove photo",
                            n_clicks=0,
                        ),
                        h.Div(f"Photo {i + 1}", className="text-muted small text-center"),
                    ],
                    className="gallery-item",
                )
            )
        if not items:
            return h.Div(
                "No photos yet. Take a photo or choose files — add as many as you like.",
                className="text-muted small",
            )
        return h.Div(items, className="image-gallery-grid")

    # ---------- Image gallery display ----------
    # Each capture/selection is saved and appended immediately, so repeated camera
    # snaps and file picks ACCUMULATE (the browser replaces the file input's
    # contents on every use, so holding a single "pending" one would lose the
    # earlier shots). The input is cleared after each add to arm the next capture.
    @app.callback(
        Output("image-gallery", "children"),
        Output("current-images", "data", allow_duplicate=True),
        Output("image-upload", "contents", allow_duplicate=True),
        Output("image-upload-cam", "contents", allow_duplicate=True),
        Input("current-images", "data"),
        Input("image-upload", "contents"),
        Input("image-upload-cam", "contents"),
        State("image-upload", "filename"),
        State("image-upload-cam", "filename"),
        State("current-images", "data"),
        State("item-name", "value"),
        prevent_initial_call='initial_duplicate',
    )
    def update_image_gallery(current_imgs, upload_contents, cam_contents,
                             upload_filenames, cam_filenames, existing_imgs, item_name):
        # Two sibling uploads feed this: the dropzone ("Choose photos") and the
        # camera button ("Take a photo"). Whichever fired, save & append its
        # shots so repeated snaps and picks accumulate, then clear that input.
        img_list = list(existing_imgs or [])
        out_imgs = no_update       # only rewrite the store when we actually add photos
        clear_choose = no_update
        clear_cam = no_update

        trig = ctx.triggered_id
        contents = None
        if trig == "image-upload" and upload_contents:
            contents, clear_choose = upload_contents, None
        elif trig == "image-upload-cam" and cam_contents:
            contents, clear_cam = cam_contents, None

        if contents is not None:
            uploads = contents if isinstance(contents, list) else [contents]
            base = (item_name or "").strip() or "photo"
            for content in uploads:
                if not content:
                    continue
                try:
                    saved = save_image(content, ASSET_IMAGE_PATH, base_name=base)
                    img_list.append(saved["filename"])
                except Exception:
                    # Skip anything that isn't a decodable image rather than break the form.
                    continue
            out_imgs = img_list

        return _render_gallery(img_list), out_imgs, clear_choose, clear_cam

    # ---------- Remove image from gallery ----------
    # Only updates the store; the gallery re-renders from its current-images Input.
    @app.callback(
        Output("current-images", "data", allow_duplicate=True),
        Input({"type": "delete-image", "index": ALL}, "n_clicks"),
        State("current-images", "data"),
        prevent_initial_call=True,
    )
    def remove_image_from_gallery(n_clicks_list, current_imgs):
        if not ctx.triggered or not current_imgs:
            raise PreventUpdate

        # Check if any delete button was actually clicked
        if not n_clicks_list or all(clicks is None or clicks == 0 for clicks in n_clicks_list):
            raise PreventUpdate

        triggered_id = ctx.triggered_id
        if triggered_id and isinstance(triggered_id, dict):
            index = triggered_id.get("index")
            if index is not None and 0 <= index < len(current_imgs):
                updated_imgs = current_imgs.copy()
                del updated_imgs[index]
                return updated_imgs

        raise PreventUpdate

    # ---------- Full image modal ----------
    @app.callback(
        Output("image-modal", "is_open"),
        Output("image-modal-title", "children"),
        Output("image-carousel", "items"),
        Output("image-modal-fullres", "children"),
        Input("inventory-table", "active_cell"),
        State("inventory-table", "data"),
        State("image-modal", "is_open"),
        prevent_initial_call=True,
    )
    def open_image_modal(cell, rows, is_open):
        if not cell or cell.get("column_id") != "image":
            raise PreventUpdate
        row_id = cell.get("row_id")
        if row_id is not None:
            row = next((r for r in (rows or []) if str(r.get("id")) == str(row_id)), None)
        else:
            ridx = cell.get("row")
            if ridx is None or ridx >= len(rows or []):
                raise PreventUpdate
            row = (rows or [])[ridx]
        if row is None:
            raise PreventUpdate
        # The viewer loads the fast preview; the originals stay one tap away.
        previews = row.get("all_previews") or row.get("all_images", [])
        originals = row.get("all_images", [])
        if not previews:
            raise PreventUpdate

        carousel_items = [
            {
                "key": str(i),
                "src": img_url,
                "img_style": {"maxHeight": "70vh", "objectFit": "contain"},
            }
            for i, img_url in enumerate(previews)
        ]

        return True, row.get("name", ""), carousel_items, _fullres_links(originals)

    @app.callback(
        Output("image-modal", "is_open", allow_duplicate=True),
        Input("close-image-modal", "n_clicks"),
        State("image-modal", "is_open"),
        prevent_initial_call=True,
    )
    def close_image(n, is_open):
        if not n:
            raise PreventUpdate
        return False

    # ---------- KPIs ----------
    @app.callback(
        Output("kpi-total", "children"),
        Output("kpi-qty", "children"),
        Output("kpi-low", "children"),
        Output("kpi-cat", "children"),
        Output("kpi-value", "children"),
        Input("inventory-table", "data"),
        prevent_initial_call=False,
    )
    def update_kpis(rows):
        rows = rows or []
        total = len(rows)
        total_qty = sum(int(r.get("qty") or 0) for r in rows)
        low = sum(1 for r in rows if data.is_low_stock(r))
        cats = len({(r.get("category") or "").strip() for r in rows if (r.get("category") or "").strip()})
        total_value = data._sum_group_value(rows)
        value_str = f"${total_value:,.0f}" if total_value else "—"
        return total, total_qty, low, cats, value_str

    # ---------- Overview breakdown (by type / location / category) ----------
    @app.callback(
        Output("breakdown-type", "children"),
        Output("breakdown-location", "children"),
        Output("breakdown-category", "children"),
        Input("inventory-table", "data"),
        prevent_initial_call=False,
    )
    def update_breakdown(rows):
        rows = rows or []
        by_type = data.summary_by("type", rows)
        by_loc = data.summary_by("location", rows)
        by_cat = data.summary_by("category", rows)
        return _breakdown_list(by_type), _breakdown_list(by_loc), _breakdown_list(by_cat)

    # ---------- Export inventory to CSV ----------
    @app.callback(
        Output("download-csv", "data"),
        Input("export-button", "n_clicks"),
        prevent_initial_call=True,
    )
    def export_csv(n):
        if not n:
            raise PreventUpdate
        import csv, io

        rows = data.inventory()
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "id", "name", "type", "category", "location", "bin", "qty", "reorder_at",
            "added", "description",
            "specifications", "estimated_value", "dimensions", "tags",
            "product_url", "ocr_text", "images",
            # Purchase record (for later spend analysis) + attachments.
            "seller", "order_number", "purchase_date", "price_paid",
            "attachment_count", "attachments",
        ])
        for r in rows:
            ra = r.get("reorder_at")
            atts = r.get("attachments") or []
            writer.writerow([
                r.get("id"),
                r.get("name", ""),
                r.get("type", ""),
                r.get("category", ""),
                r.get("location", ""),
                r.get("location_code", ""),
                r.get("qty", 0),
                "" if ra is None else ra,
                r.get("created_at", ""),
                r.get("description", ""),
                " | ".join(r.get("specifications", []) or []),
                r.get("estimated_value", ""),
                r.get("dimensions", ""),
                ", ".join(r.get("tags", []) or []),
                r.get("product_url", ""),
                (r.get("ocr_text", "") or "").replace("\n", " ").strip(),
                "; ".join(r.get("images", []) or []),
                r.get("seller", ""),
                r.get("order_number", ""),
                r.get("purchase_date", ""),
                r.get("price_paid", ""),
                len(atts),
                "; ".join(a.get("original_name") or a.get("filename") or "" for a in atts),
            ])
        return dcc.send_string(buf.getvalue(), "inventory.csv")

    # ---------- Identify item from photo (open modal + kick off lookup) ----------
    @app.callback(
        Output("identify-modal", "is_open"),
        Output("identify-trigger", "data"),
        Input("identify-button", "n_clicks"),
        Input("close-identify-modal", "n_clicks"),
        Input("apply-identify", "n_clicks"),
        State("current-images", "data"),
        State("image-upload", "contents"),
        State("item-name", "value"),
        State("item-category", "value"),
        prevent_initial_call=True,
    )
    def toggle_identify(open_clicks, close_clicks, apply_clicks,
                        current_images, upload_contents, typed_name, typed_cat):
        trig = ctx.triggered_id
        # Applying or closing dismisses the modal.
        if trig in ("close-identify-modal", "apply-identify"):
            return False, no_update
        if trig != "identify-button":
            raise PreventUpdate
        # Prefer a freshly-taken (unsaved) photo; else the selected item's primary photo.
        pending = None
        if upload_contents:
            pending = upload_contents[0] if isinstance(upload_contents, list) else upload_contents
        primary = (current_images or [None])[0] if current_images else None
        # Include n_clicks so re-clicking on the same photo re-runs the lookup.
        return True, {
            "pending": pending,
            "img": primary,
            "typed_name": (typed_name or "").strip(),
            "typed_cat": (typed_cat or "").strip(),
            "n": open_clicks,
        }

    # ---------- Identify item from photo (run the vision lookup) ----------
    @app.callback(
        Output("identify-body", "children"),
        Output("identify-result", "data"),
        Input("identify-trigger", "data"),
        prevent_initial_call=True,
    )
    def do_identify(trigger):
        if not trigger:
            raise PreventUpdate
        import web_search

        pending = trigger.get("pending")
        primary = trigger.get("img")
        typed_name = (trigger.get("typed_name") or "").strip()
        typed_cat = (trigger.get("typed_cat") or "").strip()

        image = None
        if pending:
            image = pending  # data URL string (freshly-taken, unsaved photo)
        elif primary:
            path = ASSET_IMAGE_PATH / primary
            if path.exists():
                image = path.read_bytes()

        if image is None:
            # No photo — still offer a web text search for whatever name is typed.
            if typed_name:
                links = web_search.links_for(typed_name, None, None)
                body = html.Div(
                    [
                        html.P("No photo to analyse, but you can still search the web:", className="mb-2"),
                        _web_search_buttons(links),
                    ]
                )
                store = {"data": None, "typed_name": typed_name, "typed_cat": typed_cat}
                return body, store
            return html.Div(
                "Select an item that has a photo (or take a new photo) first, then click Identify.",
                className="text-warning",
            ), no_update

        import vision_lookup, web_detect
        res = vision_lookup.identify_item(image)
        parsed = res.get("data") if isinstance(res.get("data"), dict) else None

        # Automatic web lookup when a provider is configured; otherwise fully
        # local. Only runs on click. SerpApi uses a public image URL (Lens) when
        # available, else a Google search on the local model's best guess;
        # Google Vision uses the image bytes directly.
        local_query = ""
        if parsed:
            local_query = str(parsed.get("search_query") or parsed.get("name") or "").strip()
        if not local_query:
            local_query = typed_name
        img_public = web_search.public_image_url(primary)  # "" if no public base
        web = (
            web_detect.detect_web(image, query=local_query, image_url=img_public)
            if web_detect.is_configured() else None
        )

        # Merge: web reverse-image match wins the name; local model keeps
        # category/value/dimensions/specs; entities fold into tags.
        merged = web_detect.merge_into(parsed, web)
        merged = merged if merged else parsed

        # Best web-search query for the manual buttons.
        name_for_search = ""
        specs_for_search = None
        source = merged or parsed
        if source:
            name_for_search = str(source.get("name") or "").strip()
            sq = str(source.get("search_query") or "").strip()
            specs_for_search = source.get("specifications")
            if sq:
                name_for_search, specs_for_search = sq, None
        if web and web.get("ok") and web.get("best_guess"):
            name_for_search = web["best_guess"]
            specs_for_search = None
        query_name = name_for_search or typed_name

        links = web_search.links_for(query_name, specs_for_search, primary)

        # Show the reverse-image match (if any) above the local-AI details.
        res_display = dict(res)
        if isinstance(merged, dict):
            res_display["data"] = merged
        body = html.Div([_render_web_match(web), _render_identify(res_display, links)])

        # Payload the "Apply to item" button copies into the form.
        store = {
            "data": merged if isinstance(merged, dict) else parsed,
            "typed_name": typed_name,
            "typed_cat": typed_cat,
            "product_url": (merged or {}).get("product_url", "") if isinstance(merged, dict) else "",
        }
        return body, store

    # ---------- Apply identify result into the edit form ----------
    @app.callback(
        Output("item-name", "value", allow_duplicate=True),
        Output("item-category", "value", allow_duplicate=True),
        Output("item-desc", "value", allow_duplicate=True),
        Output("item-specs", "value", allow_duplicate=True),
        Output("item-value", "value", allow_duplicate=True),
        Output("item-dims", "value", allow_duplicate=True),
        Output("item-tags", "value", allow_duplicate=True),
        Output("item-producturl", "value", allow_duplicate=True),
        Output("more-details-collapse", "is_open", allow_duplicate=True),
        Output("action-toast", "is_open", allow_duplicate=True),
        Output("action-toast", "header", allow_duplicate=True),
        Output("action-toast", "icon", allow_duplicate=True),
        Output("action-toast", "children", allow_duplicate=True),
        Input("apply-identify", "n_clicks"),
        State("identify-result", "data"),
        State("item-name", "value"),
        State("item-category", "value"),
        State("item-desc", "value"),
        State("item-producturl", "value"),
        prevent_initial_call=True,
    )
    def apply_identify(n, result, cur_name, cur_cat, cur_desc, cur_url):
        if not n or not result:
            raise PreventUpdate
        d = result.get("data") if isinstance(result, dict) else None
        if not isinstance(d, dict):
            # Nothing structured to apply (e.g. vision failed) — tell the user.
            return (no_update,) * 9 + (True, "Nothing to apply", "warning",
                                       "The lookup didn't return structured details.")

        def _s(v):
            t = "" if v is None else str(v).strip()
            return "" if t.lower() == "unknown" else t

        name = _s(d.get("name")) or (cur_name or "")
        category = _s(d.get("category")) or (cur_cat or "")
        # Fold the AI description into any existing notes without clobbering them.
        what = _s(d.get("what_it_is"))
        desc = (cur_desc or "").strip()
        if what and what.lower() not in desc.lower():
            desc = (desc + "\n" + what).strip() if desc else what

        specs = d.get("specifications")
        specs_text = _specs_to_text(specs) if isinstance(specs, list) else _s(specs)
        value = _s(d.get("estimated_value"))
        dims = _s(d.get("dimensions"))
        tags = d.get("tags")
        tags_text = _tags_to_text(tags) if isinstance(tags, list) else _s(tags)
        # Only fill the product link if the lookup found one and the user hasn't set it.
        url = _s(d.get("product_url")) or (cur_url or "")

        return (
            name, category, desc, specs_text, value, dims, tags_text, url,
            True,  # open the details section so the applied fields are visible
            True, "Applied", "success", "Lookup details copied into the form — review and Save.",
        )

    # ---------- Apply identify result AND save straight onto the item ----------
    @app.callback(
        Output("item-name", "value", allow_duplicate=True),
        Output("item-category", "value", allow_duplicate=True),
        Output("item-desc", "value", allow_duplicate=True),
        Output("item-specs", "value", allow_duplicate=True),
        Output("item-value", "value", allow_duplicate=True),
        Output("item-dims", "value", allow_duplicate=True),
        Output("item-tags", "value", allow_duplicate=True),
        Output("item-producturl", "value", allow_duplicate=True),
        Output("editing-id", "data", allow_duplicate=True),
        Output("identify-modal", "is_open", allow_duplicate=True),
        Output("refresh-seq", "data", allow_duplicate=True),
        Output("action-toast", "is_open", allow_duplicate=True),
        Output("action-toast", "header", allow_duplicate=True),
        Output("action-toast", "icon", allow_duplicate=True),
        Output("action-toast", "children", allow_duplicate=True),
        Input("apply-identify-save", "n_clicks"),
        State("identify-result", "data"),
        State("editing-id", "data"),
        State("item-name", "value"),
        State("item-desc", "value"),
        State("item-qty", "value"),
        State("item-category", "value"),
        State("item-location", "value"),
        State("item-location-code", "value"),
        State("current-images", "data"),
        prevent_initial_call=True,
    )
    def apply_and_save(n, result, editing_id, cur_name, cur_desc, cur_qty,
                       cur_cat, cur_loc, cur_code, cur_imgs):
        if not n or not result:
            raise PreventUpdate
        d = result.get("data") if isinstance(result, dict) else None
        if not isinstance(d, dict):
            return (no_update,) * 11 + (True, "Nothing to apply", "warning",
                                        "The lookup didn't return structured details.")

        def _s(v):
            t = "" if v is None else str(v).strip()
            return "" if t.lower() == "unknown" else t

        name = _s(d.get("name")) or (cur_name or "").strip()
        if not name:
            return (no_update,) * 11 + (True, "Missing name", "warning",
                                        "Nothing to name this item — type a name first.")
        category = _s(d.get("category")) or (cur_cat or "").strip()
        what = _s(d.get("what_it_is"))
        desc = (cur_desc or "").strip()
        if what and what.lower() not in desc.lower():
            desc = (desc + "\n" + what).strip() if desc else what
        specs = d.get("specifications")
        specs_text = _specs_to_text(specs) if isinstance(specs, list) else _s(specs)
        value = _s(d.get("estimated_value"))
        dims = _s(d.get("dimensions"))
        tags = d.get("tags")
        tags_text = _tags_to_text(tags) if isinstance(tags, list) else _s(tags)
        url = _s(d.get("product_url"))
        src_title = _s(d.get("source_title"))
        qty = _parse_qty(cur_qty)
        images = list(cur_imgs or [])
        loc = (cur_loc or "").strip()
        code = (cur_code or "").strip()

        try:
            if editing_id:
                existing = next((r for r in data.inventory() if r.get("id") == editing_id), {})
                # Merge, don't clobber: keep the item's stored value for any field
                # the lookup didn't supply, so applying a partial result (e.g. a
                # vision match that only knows the name) never wipes details you
                # already had. The form outputs below reflect these merged values.
                specs_text = specs_text or _specs_to_text(existing.get("specifications") or [])
                value = value or (existing.get("estimated_value") or "")
                dims = dims or (existing.get("dimensions") or "")
                tags_text = tags_text or _tags_to_text(existing.get("tags") or [])
                url = url or (existing.get("product_url") or "")
                data.update_item(
                    editing_id, name, desc, qty, images, existing.get("ocr_text", ""),
                    category=category, location=loc, location_code=code,
                    specifications=specs_text, estimated_value=value, dimensions=dims,
                    tags=tags_text, product_url=url,
                    # Only set when the lookup carried one, so we never wipe an
                    # existing source title with a blank.
                    **({"source_title": src_title} if src_title else {}),
                )
                saved_id = editing_id
                header, msg = "Item Updated", f'"{name}" updated from the lookup.'
            else:
                row = data.add_item(
                    name, desc, qty, images, "", category=category, location=loc,
                    location_code=code, specifications=specs_text, estimated_value=value,
                    dimensions=dims, tags=tags_text, product_url=url, source_title=src_title,
                )
                saved_id = row.get("id")
                header, msg = "Item Added", f'"{name}" added from the lookup.'
        except ValueError as e:
            # Duplicate name (add path) — keep the modal open so they can fix it.
            return (no_update,) * 11 + (True, "Duplicate Name", "danger", str(e))

        return (
            name, category, desc, specs_text, value, dims, tags_text, url,
            saved_id, False, time.time(),
            True, header, "success", msg,
        )

    # ---------- Connect: show every URL this app is reachable at ----------
    @app.callback(
        Output("connect-modal", "is_open"),
        Output("connect-body", "children"),
        Input("open-connect", "n_clicks"),
        Input("close-connect-modal", "n_clicks"),
        prevent_initial_call=True,
    )
    def toggle_connect(open_n, close_n):
        trig = ctx.triggered_id
        if trig == "close-connect-modal":
            return False, no_update
        if trig != "open-connect":
            raise PreventUpdate
        import net_info
        port = int(os.environ.get("PORT", 8001) or 8001)
        scheme = os.environ.get("SCHEME", "http")
        eps = net_info.access_endpoints(port, URL_PREFIX, scheme)
        return True, _render_connect(eps)

    # ---------- Import: toggle the paste-HTML area ----------
    @app.callback(
        Output("import-html-collapse", "is_open"),
        Input("import-html-toggle", "n_clicks"),
        State("import-html-collapse", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_import_html(n, is_open):
        if not n:
            raise PreventUpdate
        return not is_open

    # ---------- Import: open the lookup hub from the form ----------
    @app.callback(
        Output("identify-modal", "is_open", allow_duplicate=True),
        Output("identify-body", "children", allow_duplicate=True),
        Input("open-import", "n_clicks"),
        prevent_initial_call=True,
    )
    def open_import(n):
        if not n:
            raise PreventUpdate
        hint = html.Div(
            [
                html.I(className="bi bi-arrow-up-circle me-2"),
                "Paste a product link (or the page's HTML) above and Fetch / Extract — "
                "or take a photo and use Identify.",
            ],
            className="text-muted",
        )
        return True, hint

    # ---------- Import: fetch a URL or parse pasted/uploaded HTML ----------
    @app.callback(
        Output("identify-body", "children", allow_duplicate=True),
        Output("identify-result", "data", allow_duplicate=True),
        Input("import-fetch", "n_clicks"),
        Input("import-extract", "n_clicks"),
        Input("import-html-upload", "contents"),
        State("import-url", "value"),
        State("import-html", "value"),
        prevent_initial_call=True,
    )
    def do_import(fetch_n, extract_n, upload_contents, url, html_text):
        import product_import, base64
        trig = ctx.triggered_id

        if trig == "import-fetch":
            if not (url or "").strip():
                raise PreventUpdate
            res = product_import.import_product(url=url or "")
        elif trig == "import-extract":
            if not (html_text or "").strip():
                raise PreventUpdate
            res = product_import.import_product(url=url or "", html_text=html_text or "")
        elif trig == "import-html-upload":
            if not upload_contents:
                raise PreventUpdate
            text = ""
            try:
                if "," in upload_contents:
                    text = base64.b64decode(upload_contents.split(",", 1)[1]).decode("utf-8", "replace")
            except Exception:
                text = ""
            res = (product_import.import_product(url=url or "", html_text=text)
                   if text.strip() else {"ok": False, "error": "Couldn't read that file."})
        else:
            raise PreventUpdate

        # Multi-pack listings quote the whole-pack price; record the per-unit value
        # instead so an item's "value" reflects one piece. Reuses Price Compare's
        # pack detection. The full-pack price is kept as a note in the specs.
        if res.get("ok"):
            try:
                import price_compare
                d = res.get("data") or {}
                pu = price_compare.per_unit_value(
                    d.get("estimated_value", ""), d.get("name", ""),
                    d.get("specifications"), d.get("what_it_is", ""))
                if pu["unit_price"] is not None and 1 < pu["qty"] <= 2000:
                    d["estimated_value"] = f"{pu['currency']}{pu['unit_price']:.2f}"
                    note = pu["formatted"]
                    specs = list(d.get("specifications") or [])
                    if note and note not in specs:
                        specs.insert(0, note)
                    d["specifications"] = specs
                    res["data"] = d
            except Exception:
                pass

        body = _render_import(res)
        if res.get("ok"):
            return body, {"data": res.get("data")}
        # Keep any prior good result on failure so Apply still has something.
        return body, no_update

    # ======================================================================
    # Quick Add — guided capture: ① photo → ② documents → ③ review & save
    # ======================================================================

    # ---------- Quick Add: open + reset to a clean slate ----------
    @app.callback(
        Output("qa-modal", "is_open"),
        Output("qa-photos", "data"),
        Output("qa-attachments", "data"),
        Output("qa-source-title", "data"),
        Output("qa-extra", "data"),
        Output("qa-identify-status", "children"),
        Output("qa-import-status", "children"),
        Output("qa-attach-status", "children"),
        Output("qa-import-url", "value"),
        Output("qa-name", "value"),
        Output("qa-qty", "value"),
        Output("qa-category", "value"),
        Output("qa-location", "value"),
        Output("qa-code", "value"),
        Output("qa-value", "value"),
        Output("qa-price", "value"),
        Output("qa-order", "value"),
        Output("qa-seller", "value"),
        Output("qa-date", "value"),
        Input("open-quick-add", "n_clicks"),
        prevent_initial_call=True,
    )
    def open_quick_add(n):
        if not n:
            raise PreventUpdate
        return (True, [], [], "", {}, "", "", "", "",
                "", 1, "", "", "", "", "", "", "", "")

    # ---------- Quick Add: close (reclaim any staged, unsaved files) ----------
    @app.callback(
        Output("qa-modal", "is_open", allow_duplicate=True),
        Input("qa-close", "n_clicks"),
        prevent_initial_call=True,
    )
    def close_quick_add(n):
        if not n:
            raise PreventUpdate
        data.prune_unreferenced_images()
        data.prune_unreferenced_documents()
        return False

    # ---------- Quick Add: photo upload (choose or camera) → save & accumulate ----------
    @app.callback(
        Output("qa-photos", "data", allow_duplicate=True),
        Output("qa-photo-upload", "contents"),
        Output("qa-photo-cam", "contents"),
        Input("qa-photo-upload", "contents"),
        Input("qa-photo-cam", "contents"),
        State("qa-photo-upload", "filename"),
        State("qa-photo-cam", "filename"),
        State("qa-photos", "data"),
        State("qa-name", "value"),
        prevent_initial_call=True,
    )
    def qa_add_photos(contents, cam_contents, filenames, cam_filenames, photos, name):
        trig = ctx.triggered_id
        clear_choose = clear_cam = no_update
        payload = None
        if trig == "qa-photo-upload" and contents:
            payload, clear_choose = contents, None
        elif trig == "qa-photo-cam" and cam_contents:
            payload, clear_cam = cam_contents, None
        if payload is None:
            raise PreventUpdate
        uploads = payload if isinstance(payload, list) else [payload]
        base = (name or "").strip() or "photo"
        out = list(photos or [])
        for c in uploads:
            if not c:
                continue
            try:
                out.append(save_image(c, ASSET_IMAGE_PATH, base_name=base)["filename"])
            except Exception:
                continue
        return out, clear_choose, clear_cam

    # ---------- Quick Add: render the photo strip ----------
    @app.callback(
        Output("qa-photo-gallery", "children"),
        Input("qa-photos", "data"),
        prevent_initial_call=False,
    )
    def qa_render_gallery(photos):
        return _qa_photo_gallery(photos)

    # ---------- Quick Add: remove a staged photo ----------
    @app.callback(
        Output("qa-photos", "data", allow_duplicate=True),
        Input({"type": "qa-photo-remove", "index": ALL}, "n_clicks"),
        State("qa-photos", "data"),
        prevent_initial_call=True,
    )
    def qa_remove_photo(clicks, photos):
        if not photos or not clicks or all(not c for c in clicks):
            raise PreventUpdate
        trig = ctx.triggered_id
        if isinstance(trig, dict):
            i = trig.get("index")
            if isinstance(i, int) and 0 <= i < len(photos):
                out = list(photos)
                del out[i]
                return out
        raise PreventUpdate

    # ---------- Quick Add: Identify from the first photo ----------
    @app.callback(
        Output("qa-name", "value", allow_duplicate=True),
        Output("qa-category", "value", allow_duplicate=True),
        Output("qa-value", "value", allow_duplicate=True),
        Output("qa-extra", "data", allow_duplicate=True),
        Output("qa-source-title", "data", allow_duplicate=True),
        Output("qa-identify-status", "children", allow_duplicate=True),
        Input("qa-identify", "n_clicks"),
        State("qa-photos", "data"),
        State("qa-name", "value"),
        State("qa-category", "value"),
        State("qa-value", "value"),
        State("qa-extra", "data"),
        State("qa-source-title", "data"),
        prevent_initial_call=True,
    )
    def qa_do_identify(n, photos, cur_name, cur_cat, cur_value, cur_extra, cur_src):
        if not n:
            raise PreventUpdate
        if not photos:
            return (no_update,) * 5 + (
                html.Span("Add a photo first, then Identify.", className="text-warning"),)
        primary = photos[0]
        path = ASSET_IMAGE_PATH / primary
        if not path.exists():
            return (no_update,) * 5 + (
                html.Span("Couldn't read that photo.", className="text-danger"),)
        import vision_lookup, web_detect, web_search
        image = path.read_bytes()
        res = vision_lookup.identify_item(image)
        parsed = res.get("data") if isinstance(res.get("data"), dict) else None
        local_query = ""
        if parsed:
            local_query = str(parsed.get("search_query") or parsed.get("name") or "").strip()
        web = (web_detect.detect_web(image, query=local_query,
                                     image_url=web_search.public_image_url(primary))
               if web_detect.is_configured() else None)
        merged = web_detect.merge_into(parsed, web) or parsed
        if not isinstance(merged, dict):
            return (no_update,) * 5 + (
                html.Span("No details recognised — you can type a name below.",
                          className="text-muted"),)
        name, category, value, extra, src = _qa_apply_parsed(
            merged, cur_name, cur_cat, cur_value, cur_extra, cur_src)
        status = html.Span([html.I(className="bi bi-check-circle text-success me-1"),
                            f'Suggested: "{name or "—"}". Review in step 3.'])
        return name, category, value, extra, src, status

    # ---------- Quick Add: import a product page by URL (files go through the
    # single "attach anything" upload below, which also reads product pages) ----
    @app.callback(
        Output("qa-name", "value", allow_duplicate=True),
        Output("qa-category", "value", allow_duplicate=True),
        Output("qa-value", "value", allow_duplicate=True),
        Output("qa-extra", "data", allow_duplicate=True),
        Output("qa-source-title", "data", allow_duplicate=True),
        Output("qa-import-status", "children", allow_duplicate=True),
        Input("qa-import-fetch", "n_clicks"),
        State("qa-import-url", "value"),
        State("qa-name", "value"),
        State("qa-category", "value"),
        State("qa-value", "value"),
        State("qa-extra", "data"),
        State("qa-source-title", "data"),
        prevent_initial_call=True,
    )
    def qa_import(fetch_n, url, cur_name, cur_cat, cur_value, cur_extra, cur_src):
        import product_import
        if not (url or "").strip():
            raise PreventUpdate
        res = product_import.import_product(url=url or "")
        if not res.get("ok"):
            return (no_update,) * 5 + (
                html.Span(res.get("error", "Import failed."), className="text-warning"),)
        d = _per_unit_adjust(res.get("data") or {})
        name, category, value, extra, src = _qa_apply_parsed(
            d, cur_name, cur_cat, cur_value, cur_extra, cur_src)
        status = html.Span([html.I(className="bi bi-check-circle text-success me-1"),
                            f'Imported: "{name or "—"}" ({res.get("via", "page")}).'])
        return name, category, value, extra, src, status

    # ---------- Quick Add: THE single "attach anything" upload ----------
    # Saves every file and auto-parses the useful ones: a saved product page
    # (HTML) fills name/category/value/specs; an invoice (image or HTML) fills
    # order #/date/price/seller. Only blanks are filled, so a value you typed or
    # a previous parse found is never overwritten.
    @app.callback(
        Output("qa-attachments", "data", allow_duplicate=True),
        Output("qa-attach-upload", "contents"),
        Output("qa-order", "value", allow_duplicate=True),
        Output("qa-date", "value", allow_duplicate=True),
        Output("qa-price", "value", allow_duplicate=True),
        Output("qa-seller", "value", allow_duplicate=True),
        Output("qa-attach-status", "children", allow_duplicate=True),
        Output("qa-name", "value", allow_duplicate=True),
        Output("qa-category", "value", allow_duplicate=True),
        Output("qa-value", "value", allow_duplicate=True),
        Output("qa-extra", "data", allow_duplicate=True),
        Output("qa-source-title", "data", allow_duplicate=True),
        Input("qa-attach-upload", "contents"),
        State("qa-attach-upload", "filename"),
        State("qa-attachments", "data"),
        State("qa-order", "value"),
        State("qa-date", "value"),
        State("qa-price", "value"),
        State("qa-seller", "value"),
        State("qa-name", "value"),
        State("qa-category", "value"),
        State("qa-value", "value"),
        State("qa-extra", "data"),
        State("qa-source-title", "data"),
        prevent_initial_call=True,
    )
    def qa_attach(contents, filenames, current, cur_order, cur_date, cur_price, cur_seller,
                  cur_name, cur_cat, cur_value, cur_extra, cur_src):
        if not contents:
            raise PreventUpdate
        import invoice_parse, product_import, base64
        uploads = contents if isinstance(contents, list) else [contents]
        names = filenames if isinstance(filenames, list) else [filenames]
        atts = list(current or [])
        saved = []
        html_text = None
        for c, fn in zip(uploads, names):
            if not c:
                continue
            try:
                meta = save_attachment(c, fn or "attachment")
            except Exception:
                continue
            atts.append(meta)
            saved.append(meta)
            # Grab the first HTML file's text so we can read it as a product page.
            if meta.get("kind") == "html" and html_text is None:
                try:
                    if "," in c:
                        html_text = base64.b64decode(c.split(",", 1)[1]).decode("utf-8", "replace")
                except Exception:
                    html_text = None

        if not saved:
            return (no_update, None, no_update, no_update, no_update, no_update,
                    html.Span("That file couldn't be read.", className="text-warning"),
                    no_update, no_update, no_update, no_update, no_update)

        # ---- Product details from a saved listing page (HTML) ----
        name_o = cat_o = val_o = extra_o = src_o = no_update
        prod_ok = False
        if html_text and html_text.strip():
            res = product_import.import_product(html_text=html_text)
            if res.get("ok"):
                d = _per_unit_adjust(res.get("data") or {})
                name_o, cat_o, val_o, extra_o, src_o = _qa_apply_parsed(
                    d, cur_name, cur_cat, cur_value, cur_extra, cur_src)
                prod_ok = True

        # ---- Purchase details from the most-recent parseable doc ----
        order = (cur_order or "").strip()
        pdate = (cur_date or "").strip()
        price = (cur_price or "").strip()
        seller = (cur_seller or "").strip()
        read_n = 0
        for meta in reversed(saved):
            if meta.get("kind") not in ("image", "html"):
                continue
            text = read_attachment_text(meta["filename"])
            if not text.strip():
                continue
            found = invoice_parse.extract_purchase(text)
            order = order or found.get("order_number", "")
            pdate = pdate or found.get("purchase_date", "")
            price = price or found.get("price_paid", "")
            seller = seller or found.get("seller", "")
            read_n = len(found.get("found", []))
            break

        nm = len(saved)
        bits = [f"Attached {nm} file{'s' if nm != 1 else ''}"]
        if prod_ok:
            bits.append("read the listing")
        if read_n:
            bits.append(f"{read_n} purchase field{'s' if read_n != 1 else ''}")
        if prod_ok or read_n:
            status = html.Span([html.I(className="bi bi-magic text-success me-1"),
                                " · ".join(bits) + " — check step 3."])
        else:
            status = html.Span(f"Attached {nm} document{'s' if nm != 1 else ''}.",
                               className="text-muted")
        return (atts, None, order, pdate, price, seller, status,
                name_o, cat_o, val_o, extra_o, src_o)

    # ---------- Quick Add: render the attachment list ----------
    @app.callback(
        Output("qa-attach-list", "children"),
        Input("qa-attachments", "data"),
        prevent_initial_call=False,
    )
    def qa_render_attach(atts):
        return _render_attachments(atts, remove_type="qa-attach-remove")

    # ---------- Quick Add: remove a staged attachment ----------
    @app.callback(
        Output("qa-attachments", "data", allow_duplicate=True),
        Input({"type": "qa-attach-remove", "index": ALL}, "n_clicks"),
        State("qa-attachments", "data"),
        prevent_initial_call=True,
    )
    def qa_remove_attach(clicks, atts):
        if not atts or not clicks or all(not c for c in clicks):
            raise PreventUpdate
        trig = ctx.triggered_id
        if isinstance(trig, dict):
            i = trig.get("index")
            if isinstance(i, int) and 0 <= i < len(atts):
                out = list(atts)
                del out[i]
                return out
        raise PreventUpdate

    # ---------- Quick Add: save the assembled item ----------
    @app.callback(
        Output("qa-modal", "is_open", allow_duplicate=True),
        Output("refresh-seq", "data", allow_duplicate=True),
        Output("action-toast", "is_open", allow_duplicate=True),
        Output("action-toast", "header", allow_duplicate=True),
        Output("action-toast", "icon", allow_duplicate=True),
        Output("action-toast", "children", allow_duplicate=True),
        Input("qa-save", "n_clicks"),
        State("qa-name", "value"),
        State("qa-qty", "value"),
        State("qa-category", "value"),
        State("qa-location", "value"),
        State("qa-code", "value"),
        State("qa-value", "value"),
        State("qa-price", "value"),
        State("qa-order", "value"),
        State("qa-seller", "value"),
        State("qa-date", "value"),
        State("qa-extra", "data"),
        State("qa-source-title", "data"),
        State("qa-photos", "data"),
        State("qa-attachments", "data"),
        prevent_initial_call=True,
    )
    def qa_save(n, name, qty, category, location, code, value, price, order, seller, pdate,
                extra, src, photos, atts):
        if not n:
            raise PreventUpdate
        photos = list(photos or [])
        nm = (name or "").strip()
        # Same quick-capture rule as the form: a blank name with a photo auto-numbers.
        if not nm and photos:
            nm = data.next_auto_name()
        if not nm:
            return (no_update, no_update, True, "Add a photo or name", "warning",
                    "Take a photo (it'll auto-number) or type a name first.")
        extra = extra or {}
        try:
            data.add_item(
                nm, extra.get("description", ""), _parse_qty(qty), photos, "",
                category=(category or "").strip(), location=(location or "").strip(),
                location_code=(code or "").strip(),
                specifications=extra.get("specifications", ""),
                estimated_value=(value or "").strip(),
                dimensions=extra.get("dimensions", ""),
                tags=extra.get("tags", ""),
                product_url=extra.get("product_url", ""),
                source_title=(src or "").strip(),
                attachments=list(atts or []),
                order_number=(order or "").strip(),
                purchase_date=(pdate or "").strip(),
                price_paid=(price or "").strip(),
                seller=(seller or "").strip(),
            )
        except ValueError as e:
            return (no_update, no_update, True, "Duplicate Name", "danger", str(e))
        return (False, time.time(), True, "Item Added", "success",
                f'"{nm}" added from Quick Add.')

    # ======================================================================
    # Batch add — one item per photo, generic names, fast list populate
    # ======================================================================

    # ---------- Batch: open + reset ----------
    @app.callback(
        Output("batch-modal", "is_open"),
        Output("batch-photos", "data"),
        Input("open-batch-add", "n_clicks"),
        prevent_initial_call=True,
    )
    def open_batch_add(n):
        if not n:
            raise PreventUpdate
        return True, []

    # ---------- Batch: close (reclaim staged photos) ----------
    @app.callback(
        Output("batch-modal", "is_open", allow_duplicate=True),
        Input("batch-close", "n_clicks"),
        prevent_initial_call=True,
    )
    def close_batch_add(n):
        if not n:
            raise PreventUpdate
        data.prune_unreferenced_images()
        return False

    # ---------- Batch: upload photos → stage them ----------
    @app.callback(
        Output("batch-photos", "data", allow_duplicate=True),
        Output("batch-upload", "contents"),
        Input("batch-upload", "contents"),
        State("batch-upload", "filename"),
        State("batch-photos", "data"),
        prevent_initial_call=True,
    )
    def batch_upload(contents, filenames, photos):
        if not contents:
            raise PreventUpdate
        uploads = contents if isinstance(contents, list) else [contents]
        out = list(photos or [])
        for c in uploads:
            if not c:
                continue
            try:
                out.append(save_image(c, ASSET_IMAGE_PATH, base_name="item")["filename"])
            except Exception:
                continue
        return out, None

    # ---------- Batch: render the preview ----------
    @app.callback(
        Output("batch-preview", "children"),
        Input("batch-photos", "data"),
        prevent_initial_call=False,
    )
    def batch_render_preview(photos):
        return _batch_preview(photos)

    # ---------- Batch: remove a staged photo ----------
    @app.callback(
        Output("batch-photos", "data", allow_duplicate=True),
        Input({"type": "batch-photo-remove", "index": ALL}, "n_clicks"),
        State("batch-photos", "data"),
        prevent_initial_call=True,
    )
    def batch_remove_photo(clicks, photos):
        if not photos or not clicks or all(not c for c in clicks):
            raise PreventUpdate
        trig = ctx.triggered_id
        if isinstance(trig, dict):
            i = trig.get("index")
            if isinstance(i, int) and 0 <= i < len(photos):
                out = list(photos)
                del out[i]
                return out
        raise PreventUpdate

    # ---------- Batch: create one item per photo ----------
    @app.callback(
        Output("batch-modal", "is_open", allow_duplicate=True),
        Output("batch-photos", "data", allow_duplicate=True),
        Output("refresh-seq", "data", allow_duplicate=True),
        Output("action-toast", "is_open", allow_duplicate=True),
        Output("action-toast", "header", allow_duplicate=True),
        Output("action-toast", "icon", allow_duplicate=True),
        Output("action-toast", "children", allow_duplicate=True),
        Input("batch-create", "n_clicks"),
        State("batch-photos", "data"),
        prevent_initial_call=True,
    )
    def batch_create(n, photos):
        if not n:
            raise PreventUpdate
        photos = [p for p in (photos or []) if p]
        if not photos:
            return (no_update, no_update, no_update, True, "No photos", "warning",
                    "Add some photos first — each becomes its own item.")
        created = data.add_photo_items(photos)
        c = len(created)
        first = created[0]["name"] if created else ""
        last = created[-1]["name"] if created else ""
        rng = first if c == 1 else f"{first}–{last}"
        return (False, [], time.time(), True, "Items created", "success",
                f"Created {c} item{'s' if c != 1 else ''} ({rng}). "
                f"Rename them anytime; Merge combines any that are the same thing.")

    # ---------- Form: "Search the web" link tracks the typed name ----------
    @app.callback(
        Output("form-web-search", "href"),
        Input("item-name", "value"),
        Input("item-category", "value"),
        Input("item-tags", "value"),
        prevent_initial_call=False,
    )
    def update_web_search_link(name, category, tags):
        import web_search
        query = web_search.build_query(name or "", tags or "", category or "")
        return web_search.google_text_url(query) if query else "https://www.google.com"

    # ---------- Form: collapse toggle for "More details" ----------
    @app.callback(
        Output("more-details-collapse", "is_open"),
        Input("more-details-toggle", "n_clicks"),
        State("more-details-collapse", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_more_details(n, is_open):
        if not n:
            raise PreventUpdate
        return not is_open

    # ---------- Form: collapse toggle for "Purchase & documents" ----------
    @app.callback(
        Output("purchase-docs-collapse", "is_open"),
        Input("purchase-docs-toggle", "n_clicks"),
        State("purchase-docs-collapse", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_purchase_docs(n, is_open):
        if not n:
            raise PreventUpdate
        return not is_open

    # ---------- Form: load purchase fields + attachments for the selected item ----------
    # Keyed on editing-id so it fires whenever the form switches items (row select),
    # clears (Save/Cancel set editing-id to None), or a lookup saves a new item.
    @app.callback(
        Output("item-order-number", "value"),
        Output("item-purchase-date", "value"),
        Output("item-price-paid", "value"),
        Output("item-seller", "value"),
        Output("current-attachments", "data"),
        Input("editing-id", "data"),
        prevent_initial_call=False,
    )
    def load_purchase_fields(editing_id):
        if not editing_id:
            return "", "", "", "", []
        row = next((r for r in data.inventory() if r.get("id") == editing_id), None)
        if not row:
            return "", "", "", "", []
        return (
            row.get("order_number", ""),
            row.get("purchase_date", ""),
            row.get("price_paid", ""),
            row.get("seller", ""),
            row.get("attachments", []) or [],
        )

    # ---------- Form: render the attachment list ----------
    @app.callback(
        Output("attach-list", "children"),
        Input("current-attachments", "data"),
        prevent_initial_call=False,
    )
    def render_attach_list(atts):
        return _render_attachments(atts)

    # ---------- Form: THE single "attach anything" upload ----------
    # One control for every file. A saved product page (HTML) fills in
    # name/category/value/specs/dimensions/tags/link; an invoice (image or HTML)
    # fills order #/date/price/seller. Only blank fields are filled, so nothing
    # you already typed is overwritten. Every file is kept as a record.
    @app.callback(
        Output("current-attachments", "data", allow_duplicate=True),
        Output("attach-upload", "contents"),
        Output("item-order-number", "value", allow_duplicate=True),
        Output("item-purchase-date", "value", allow_duplicate=True),
        Output("item-price-paid", "value", allow_duplicate=True),
        Output("item-seller", "value", allow_duplicate=True),
        Output("action-toast", "is_open", allow_duplicate=True),
        Output("action-toast", "header", allow_duplicate=True),
        Output("action-toast", "icon", allow_duplicate=True),
        Output("action-toast", "children", allow_duplicate=True),
        Output("item-name", "value", allow_duplicate=True),
        Output("item-category", "value", allow_duplicate=True),
        Output("item-value", "value", allow_duplicate=True),
        Output("item-specs", "value", allow_duplicate=True),
        Output("item-dims", "value", allow_duplicate=True),
        Output("item-tags", "value", allow_duplicate=True),
        Output("item-producturl", "value", allow_duplicate=True),
        Input("attach-upload", "contents"),
        State("attach-upload", "filename"),
        State("current-attachments", "data"),
        State("item-order-number", "value"),
        State("item-purchase-date", "value"),
        State("item-price-paid", "value"),
        State("item-seller", "value"),
        State("item-name", "value"),
        State("item-category", "value"),
        State("item-value", "value"),
        State("item-specs", "value"),
        State("item-dims", "value"),
        State("item-tags", "value"),
        State("item-producturl", "value"),
        prevent_initial_call=True,
    )
    def add_attachment(contents, filenames, current, cur_order, cur_date, cur_price, cur_seller,
                       cur_name, cur_cat, cur_value, cur_specs, cur_dims, cur_tags, cur_url):
        if not contents:
            raise PreventUpdate
        import invoice_parse, product_import, base64

        uploads = contents if isinstance(contents, list) else [contents]
        names = filenames if isinstance(filenames, list) else [filenames]
        atts = list(current or [])

        saved_meta = []
        html_text = None
        for content, fname in zip(uploads, names):
            if not content:
                continue
            try:
                meta = save_attachment(content, fname or "attachment")
            except Exception:
                continue
            atts.append(meta)
            saved_meta.append(meta)
            if meta.get("kind") == "html" and html_text is None:
                try:
                    if "," in content:
                        html_text = base64.b64decode(content.split(",", 1)[1]).decode("utf-8", "replace")
                except Exception:
                    html_text = None

        NF = no_update  # unfilled catalogue outputs
        if not saved_meta:
            return (no_update, None, no_update, no_update, no_update, no_update,
                    True, "Couldn't attach", "warning", "That file couldn't be read.",
                    NF, NF, NF, NF, NF, NF, NF)

        # ---- Product details from a saved listing page (HTML) — blanks only ----
        def _s(v):
            t = "" if v is None else str(v).strip()
            return "" if t.lower() == "unknown" else t
        name_o = cat_o = val_o = specs_o = dims_o = tags_o = url_o = no_update
        prod_ok = False
        if html_text and html_text.strip():
            res = product_import.import_product(html_text=html_text)
            if res.get("ok"):
                d = _per_unit_adjust(res.get("data") or {})
                if not (cur_name or "").strip() and _s(d.get("name")):
                    name_o = _s(d.get("name"))
                if not (cur_cat or "").strip() and _s(d.get("category")):
                    cat_o = _s(d.get("category"))
                if not (cur_value or "").strip() and _s(d.get("estimated_value")):
                    val_o = _s(d.get("estimated_value"))
                sp = d.get("specifications")
                sp_txt = _specs_to_text(sp) if isinstance(sp, list) else _s(sp)
                if not (cur_specs or "").strip() and sp_txt:
                    specs_o = sp_txt
                if not (cur_dims or "").strip() and _s(d.get("dimensions")):
                    dims_o = _s(d.get("dimensions"))
                tg = d.get("tags")
                tg_txt = _tags_to_text(tg) if isinstance(tg, list) else _s(tg)
                if not (cur_tags or "").strip() and tg_txt:
                    tags_o = tg_txt
                if not (cur_url or "").strip() and _s(d.get("product_url")):
                    url_o = _s(d.get("product_url"))
                prod_ok = True

        # ---- Purchase details from the most recent parseable document ----
        order = (cur_order or "").strip()
        pdate = (cur_date or "").strip()
        price = (cur_price or "").strip()
        seller = (cur_seller or "").strip()
        read_n = 0
        for meta in reversed(saved_meta):
            if meta.get("kind") not in ("image", "html"):
                continue
            text = read_attachment_text(meta["filename"])
            if not text.strip():
                continue
            found = invoice_parse.extract_purchase(text)
            order = order or found.get("order_number", "")
            pdate = pdate or found.get("purchase_date", "")
            price = price or found.get("price_paid", "")
            seller = seller or found.get("seller", "")
            read_n = len(found.get("found", []))
            break  # only parse the single most-recent parseable doc

        n = len(saved_meta)
        bits = [f"Added {n} document{'s' if n != 1 else ''}"]
        if prod_ok:
            bits.append("read the listing")
        if read_n:
            bits.append(f"{read_n} purchase field{'s' if read_n != 1 else ''}")
        header = "Attached + auto-filled" if (prod_ok or read_n) else "Attached"
        msg = " · ".join(bits) + (" — review, then Save." if (prod_ok or read_n) else ".")
        return (atts, None, order, pdate, price, seller, True, header, "success", msg,
                name_o, cat_o, val_o, specs_o, dims_o, tags_o, url_o)

    # ---------- Form: remove one attachment from the pending set ----------
    @app.callback(
        Output("current-attachments", "data", allow_duplicate=True),
        Input({"type": "attach-remove", "index": ALL}, "n_clicks"),
        State("current-attachments", "data"),
        prevent_initial_call=True,
    )
    def remove_attachment(n_clicks_list, current):
        if not current or not n_clicks_list:
            raise PreventUpdate
        if all(not c for c in n_clicks_list):
            raise PreventUpdate
        trig = ctx.triggered_id
        if isinstance(trig, dict):
            idx = trig.get("index")
            if isinstance(idx, int) and 0 <= idx < len(current):
                out = list(current)
                del out[idx]
                return out
        raise PreventUpdate

    # ---------- Form: Add vs Edit badge ----------
    @app.callback(
        Output("form-mode-badge", "children"),
        Output("form-mode-badge", "className"),
        Input("editing-id", "data"),
        prevent_initial_call=False,
    )
    def update_form_mode(editing_id):
        if editing_id:
            return "Editing", "badge bg-warning text-dark ms-2"
        return "New item", "badge bg-secondary ms-2"

    # ---------- Storage: Smart Organize (preview plan) ----------
    @app.callback(
        Output("organize-modal", "is_open"),
        Output("organize-body", "children"),
        Output("organize-plan", "data"),
        Input("organize-button", "n_clicks"),
        prevent_initial_call=True,
    )
    def open_organize(n):
        if not n:
            raise PreventUpdate
        rows = data.inventory()
        if not rows:
            return True, html.Div("No items yet — add a few, then organize.", className="text-muted"), []
        plan = data.auto_organize(rows)
        return True, _render_plan(plan), plan

    @app.callback(
        Output("organize-modal", "is_open", allow_duplicate=True),
        Input("close-organize-modal", "n_clicks"),
        prevent_initial_call=True,
    )
    def close_organize(n):
        if not n:
            raise PreventUpdate
        return False

    # ---------- Storage: apply the plan ----------
    @app.callback(
        Output("organize-modal", "is_open", allow_duplicate=True),
        Output("refresh-seq", "data", allow_duplicate=True),
        Output("action-toast", "is_open", allow_duplicate=True),
        Output("action-toast", "header", allow_duplicate=True),
        Output("action-toast", "icon", allow_duplicate=True),
        Output("action-toast", "children", allow_duplicate=True),
        Input("apply-organize", "n_clicks"),
        State("organize-plan", "data"),
        prevent_initial_call=True,
    )
    def apply_organize(n, plan):
        if not n:
            raise PreventUpdate
        if not plan:
            return False, no_update, True, "Nothing to organize", "warning", "There was no plan to apply."
        count = data.apply_organization(plan)
        bins = len(plan)
        return (
            False, time.time(),
            True, "Organized", "success",
            f"Assigned {count} item{'s' if count != 1 else ''} across {bins} bin{'s' if bins != 1 else ''}.",
        )

    # ---------- Storage: live 'what is in each bin' map ----------
    @app.callback(
        Output("storage-map", "children"),
        Input("inventory-table", "data"),
        prevent_initial_call=False,
    )
    def render_storage_map(_table_data):
        # storage_overview() merges the defined bins (with their bags) and the
        # live counts, so empty bins you've set up still show on the map.
        return _render_storage_map(data.storage_overview())

    # ---------- Storage bins: open editor (load current containers) ----------
    @app.callback(
        Output("bins-modal", "is_open"),
        Output("containers-store", "data"),
        Input("open-bins", "n_clicks"),
        prevent_initial_call=True,
    )
    def open_bins(n):
        if not n:
            raise PreventUpdate
        return True, data.containers()

    # ---------- Storage bins: render the editable container rows ----------
    @app.callback(
        Output("containers-list", "children"),
        Input("containers-store", "data"),
        prevent_initial_call=False,
    )
    def render_container_rows(conts):
        conts = conts or []
        rows = [_container_row(i, c) for i, c in enumerate(conts)]
        if not rows:
            rows = [html.Div("No containers yet — click “Add container” or generate a set below.",
                             className="text-muted small py-2")]
        return rows

    # ---------- Storage bins: add a row / remove a row / generate a set ----------
    @app.callback(
        Output("containers-store", "data", allow_duplicate=True),
        Output("bins-status", "children", allow_duplicate=True),
        Input("add-container", "n_clicks"),
        Input({"type": "cont-remove", "index": ALL}, "n_clicks"),
        Input("generate-bins", "n_clicks"),
        State({"type": "cont-name", "index": ALL}, "value"),
        State({"type": "cont-bags", "index": ALL}, "value"),
        State({"type": "cont-slots", "index": ALL}, "value"),
        State("bin-count", "value"),
        State("bin-prefix", "value"),
        prevent_initial_call=True,
    )
    def edit_container_rows(_add, remove_clicks, _gen, names, bags, slots, count, prefix):
        rows = _raw_rows(names, bags, slots)   # exactly what's on screen right now
        trig = ctx.triggered_id
        status = no_update
        if trig == "add-container":
            rows.append({"name": "", "bags": [], "capacity": 25})
        elif trig == "generate-bins":
            if not count:
                return no_update, html.Span("Enter how many first.", className="text-warning")
            rows += [{"name": c["name"], "bags": c["bags"], "capacity": c["capacity"]}
                     for c in data.make_bins(count, prefix or "Bin", 25)]
            status = html.Span([html.I(className="bi bi-check-circle me-1"),
                                f"Added {int(count)}."], className="text-success")
        elif isinstance(trig, dict) and trig.get("type") == "cont-remove":
            idx = trig.get("index")
            # Guard the spurious fire when a freshly-mounted remove button reports
            # n_clicks; only act on a real click (its n_clicks is truthy).
            if (idx is not None and idx < len(remove_clicks)
                    and remove_clicks[idx] and idx < len(rows)):
                rows.pop(idx)
            else:
                raise PreventUpdate
        else:
            raise PreventUpdate
        return rows, status

    @app.callback(
        Output("bins-modal", "is_open", allow_duplicate=True),
        Input("close-bins-modal", "n_clicks"),
        prevent_initial_call=True,
    )
    def close_bins(n):
        if not n:
            raise PreventUpdate
        return False

    # ---------- Storage bins: save the container definitions ----------
    @app.callback(
        Output("bins-status", "children"),
        Output("containers-store", "data", allow_duplicate=True),
        Output("refresh-seq", "data", allow_duplicate=True),
        Input("save-containers", "n_clicks"),
        State({"type": "cont-name", "index": ALL}, "value"),
        State({"type": "cont-bags", "index": ALL}, "value"),
        State({"type": "cont-slots", "index": ALL}, "value"),
        prevent_initial_call=True,
    )
    def save_bins(n, names, bags, slots):
        if not n:
            raise PreventUpdate
        conts = data.save_containers(data.containers_from_rows(names, bags, slots))
        total_bags = sum(len(c.get("bags") or []) for c in conts)
        bag_note = f" with {total_bags} bag{'s' if total_bags != 1 else ''}" if total_bags else ""
        msg = html.Span(
            [html.I(className="bi bi-check-circle me-1"),
             f"Saved {len(conts)} container{'s' if len(conts) != 1 else ''}{bag_note}."],
            className="text-success",
        )
        # Return the saved (deduped, coded) list to the store, and bump refresh-seq
        # so the storage map re-renders.
        return msg, conts, time.time()

    # ---------- Storage bins: fit items into the containers ----------
    @app.callback(
        Output("fit-result", "children"),
        Output("fit-plan", "data"),
        Output("bins-status", "children", allow_duplicate=True),
        Input("fit-bins", "n_clicks"),
        State({"type": "cont-name", "index": ALL}, "value"),
        State({"type": "cont-bags", "index": ALL}, "value"),
        State({"type": "cont-slots", "index": ALL}, "value"),
        prevent_initial_call=True,
    )
    def do_fit(n, names, bags, slots):
        if not n:
            raise PreventUpdate
        conts = data.save_containers(data.containers_from_rows(names, bags, slots))
        if not conts:
            return (html.Div("Add at least one container first.", className="text-warning"),
                    None, no_update)
        plan = data.fit_to_containers(conts=conts)
        return _render_fit(plan), plan, ""

    # ---------- Storage bins: apply the fit onto every item ----------
    @app.callback(
        Output("bins-modal", "is_open", allow_duplicate=True),
        Output("refresh-seq", "data", allow_duplicate=True),
        Output("action-toast", "is_open", allow_duplicate=True),
        Output("action-toast", "header", allow_duplicate=True),
        Output("action-toast", "icon", allow_duplicate=True),
        Output("action-toast", "children", allow_duplicate=True),
        Input("apply-fit", "n_clicks"),
        State("fit-plan", "data"),
        prevent_initial_call=True,
    )
    def apply_fit_cb(n, plan):
        if not n:
            raise PreventUpdate
        if not plan or not plan.get("assignments"):
            return no_update, no_update, True, "Nothing to apply", "warning", "Run Fit first."
        count = data.apply_fit(plan)
        overflow = len(plan.get("overflow", []))
        msg = f"Placed {count} item{'s' if count != 1 else ''} into bins."
        if overflow:
            msg += f" {overflow} didn't fit."
        return False, time.time(), True, "Bins updated", ("warning" if overflow else "success"), msg

    def _scan_and_render(level):
        """Run a duplicate scan and return (result view, plan store, status)."""
        plans = data.find_duplicate_groups(level=level or "balanced")
        plan_store = [{"item_ids": p["item_ids"]} for p in plans]
        status = html.Span([html.I(className="bi bi-check-circle me-1"),
                            f"Scanned {len(data.inventory())} items."], className="text-muted")
        return _render_dups(plans), plan_store, status

    # ---------- Duplicates: open the modal + auto-scan ----------
    @app.callback(
        Output("dups-modal", "is_open"),
        Output("dups-result", "children"),
        Output("dups-plan", "data"),
        Output("dups-status", "children"),
        Input("open-dups", "n_clicks"),
        State("dups-level", "value"),
        prevent_initial_call=True,
    )
    def open_dups(n, level):
        if not n:
            raise PreventUpdate
        view, plan, status = _scan_and_render(level or "balanced")
        return True, view, plan, status

    @app.callback(
        Output("dups-modal", "is_open", allow_duplicate=True),
        Input("close-dups-modal", "n_clicks"),
        prevent_initial_call=True,
    )
    def close_dups(n):
        if not n:
            raise PreventUpdate
        return False

    # ---------- Duplicates: re-scan (e.g. after changing sensitivity) ----------
    @app.callback(
        Output("dups-result", "children", allow_duplicate=True),
        Output("dups-plan", "data", allow_duplicate=True),
        Output("dups-status", "children", allow_duplicate=True),
        Input("dups-scan", "n_clicks"),
        State("dups-level", "value"),
        prevent_initial_call=True,
    )
    def do_scan(n, level):
        if not n:
            raise PreventUpdate
        return _scan_and_render(level)

    # ---------- Duplicates: keep the rename field in step with the survivor ----------
    @app.callback(
        Output({"type": "dup-name", "index": MATCH}, "value"),
        Input({"type": "dup-primary", "index": MATCH}, "value"),
        State("dups-plan", "data"),
        prevent_initial_call=True,
    )
    def sync_dup_name(primary_id, plan):
        idx = (ctx.triggered_id or {}).get("index")
        if primary_id is None or plan is None or idx is None or idx >= len(plan):
            raise PreventUpdate
        by_id = {int(r.get("id")): r for r in data.inventory()}
        row = by_id.get(int(primary_id))
        return row.get("name", "") if row else no_update

    # ---------- Duplicates: merge the selected groups ----------
    @app.callback(
        Output("dups-modal", "is_open", allow_duplicate=True),
        Output("refresh-seq", "data", allow_duplicate=True),
        Output("dups-result", "children", allow_duplicate=True),
        Output("dups-plan", "data", allow_duplicate=True),
        Output("undo-bar", "children", allow_duplicate=True),
        Output("action-toast", "is_open", allow_duplicate=True),
        Output("action-toast", "header", allow_duplicate=True),
        Output("action-toast", "icon", allow_duplicate=True),
        Output("action-toast", "children", allow_duplicate=True),
        Input("dups-apply", "n_clicks"),
        State({"type": "dup-include", "index": ALL}, "value"),
        State({"type": "dup-primary", "index": ALL}, "value"),
        State({"type": "dup-name", "index": ALL}, "value"),
        State("dups-plan", "data"),
        prevent_initial_call=True,
    )
    def apply_dups(n, includes, primaries, names, plan):
        if not n:
            raise PreventUpdate
        if not plan:
            return (no_update,) * 5 + (True, "Nothing to merge", "warning",
                                       "Scan for duplicates first.")
        # Map pattern-matched control values back to their group index.
        inc = {s["id"]["index"]: s.get("value") for s in (ctx.states_list[0] or [])}
        pri = {s["id"]["index"]: s.get("value") for s in (ctx.states_list[1] or [])}
        nam = {s["id"]["index"]: s.get("value") for s in (ctx.states_list[2] or [])}

        jobs = []
        for i, grp in enumerate(plan):
            if not inc.get(i, True):
                continue
            item_ids = [int(x) for x in grp.get("item_ids", [])]
            if len(item_ids) < 2:
                continue
            primary_id = pri.get(i) or item_ids[0]
            primary_id = int(primary_id)
            merge_ids = [x for x in item_ids if x != primary_id]
            name = (nam.get(i) or "").strip()
            jobs.append((primary_id, merge_ids, {"name": name} if name else None))

        if not jobs:
            return (no_update,) * 5 + (True, "Nothing selected", "warning",
                                       "Toggle on at least one group to merge.")

        data.snapshot_inventory()  # enable one-click undo
        groups = removed = 0
        for primary_id, merge_ids, overrides in jobs:
            if data.merge_group(primary_id, merge_ids, overrides) is not None and merge_ids:
                groups += 1
                removed += len(merge_ids)
        data.commit_undo()  # checkpoint so undo can detect later edits
        msg = (f"Merged {groups} group(s), removing {removed} duplicate "
               f"entr{'y' if removed == 1 else 'ies'}.")
        undo = _undo_alert(msg)
        return (False, time.time(), "", None, undo, True, "Duplicates merged", "success", msg)

    # ---------- Auto-flag duplicates: badge on the Merge button ----------
    @app.callback(
        Output("dup-count-badge", "children"),
        Input("refresh-seq", "data"),
        Input("url", "pathname"),
        prevent_initial_call=False,
    )
    def dup_badge(_seq, _path):
        try:
            n = len(data.find_duplicate_groups(level="balanced"))
        except Exception:
            n = 0
        if not n:
            return ""
        return dbc.Badge(str(n), color="warning", pill=True, className="ms-1",
                         title=f"{n} likely duplicate group(s) — click to review")

    # ---------- Bulk edit: show the bar + count when 2+ rows ticked ----------
    @app.callback(
        Output("bulk-bar", "style"),
        Output("bulk-count", "children"),
        Input("inventory-table", "selected_rows"),
        prevent_initial_call=True,
    )
    def bulk_bar(sel_rows):
        n = len(sel_rows or [])
        if n >= 2:
            return {"display": "block"}, f"{n} items selected"
        return {"display": "none"}, ""

    def _selected_ids(sel_rows, rows):
        ids = []
        for i in (sel_rows or []):
            if isinstance(i, int) and 0 <= i < len(rows or []):
                rid = (rows[i] or {}).get("id")
                if rid is not None:
                    ids.append(int(rid))
        return ids

    # ---------- Bulk edit: apply category / location / bin ----------
    @app.callback(
        Output("refresh-seq", "data", allow_duplicate=True),
        Output("inventory-table", "selected_rows", allow_duplicate=True),
        Output("bulk-type", "value"),
        Output("bulk-category", "value"),
        Output("bulk-location", "value"),
        Output("bulk-code", "value"),
        Output("action-toast", "is_open", allow_duplicate=True),
        Output("action-toast", "header", allow_duplicate=True),
        Output("action-toast", "icon", allow_duplicate=True),
        Output("action-toast", "children", allow_duplicate=True),
        Input("bulk-apply", "n_clicks"),
        State("inventory-table", "selected_rows"),
        State("inventory-table", "data"),
        State("bulk-type", "value"),
        State("bulk-category", "value"),
        State("bulk-location", "value"),
        State("bulk-code", "value"),
        prevent_initial_call=True,
    )
    def bulk_apply(n, sel_rows, rows, typ, cat, loc, code):
        if not n:
            raise PreventUpdate
        ids = _selected_ids(sel_rows, rows)
        # Only patch fields the user actually filled in (blank = leave as-is).
        typ = typ.strip() if isinstance(typ, str) and typ.strip() else None
        cat = cat.strip() if isinstance(cat, str) and cat.strip() else None
        loc = loc.strip() if isinstance(loc, str) and loc.strip() else None
        code = code.strip() if isinstance(code, str) and code.strip() else None
        if not ids:
            return (no_update, no_update, no_update, no_update, no_update, no_update,
                    True, "Nothing selected", "warning", "Tick some rows first.")
        if typ is None and cat is None and loc is None and code is None:
            return (no_update, no_update, no_update, no_update, no_update, no_update,
                    True, "Nothing to set", "warning", "Fill in Type, Category, Location or Bin first.")
        changed = data.bulk_set_fields(ids, category=cat, location=loc, location_code=code, item_type=typ)
        return (time.time(), [], "", "", "", "", True, "Bulk update",
                "success", f"Updated {changed} item{'s' if changed != 1 else ''}.")

    # ---------- Bulk edit: delete the selected items ----------
    @app.callback(
        Output("refresh-seq", "data", allow_duplicate=True),
        Output("inventory-table", "selected_rows", allow_duplicate=True),
        Output("undo-bar", "children", allow_duplicate=True),
        Output("action-toast", "is_open", allow_duplicate=True),
        Output("action-toast", "header", allow_duplicate=True),
        Output("action-toast", "icon", allow_duplicate=True),
        Output("action-toast", "children", allow_duplicate=True),
        Input("bulk-delete", "n_clicks"),
        State("inventory-table", "selected_rows"),
        State("inventory-table", "data"),
        prevent_initial_call=True,
    )
    def bulk_delete(n, sel_rows, rows):
        if not n:
            raise PreventUpdate
        ids = _selected_ids(sel_rows, rows)
        if not ids:
            return (no_update, no_update, no_update, True, "Nothing selected", "warning",
                    "Tick some rows first.")
        data.snapshot_inventory()  # enable one-click undo
        removed = data.bulk_remove(ids)
        data.commit_undo()  # checkpoint so undo can detect later edits
        msg = f"Removed {removed} item{'s' if removed != 1 else ''}."
        return (time.time(), [], _undo_alert(msg), True, "Deleted", "success", msg)

    # ---------- Bulk edit: merge the selected rows into one ----------
    @app.callback(
        Output("refresh-seq", "data", allow_duplicate=True),
        Output("inventory-table", "selected_rows", allow_duplicate=True),
        Output("undo-bar", "children", allow_duplicate=True),
        Output("action-toast", "is_open", allow_duplicate=True),
        Output("action-toast", "header", allow_duplicate=True),
        Output("action-toast", "icon", allow_duplicate=True),
        Output("action-toast", "children", allow_duplicate=True),
        Input("bulk-merge", "n_clicks"),
        State("inventory-table", "selected_rows"),
        State("inventory-table", "data"),
        prevent_initial_call=True,
    )
    def bulk_merge(n, sel_rows, rows):
        if not n:
            raise PreventUpdate
        ids = _selected_ids(sel_rows, rows)
        if len(ids) < 2:
            return (no_update, no_update, no_update, True, "Pick at least two",
                    "warning", "Tick two or more rows to merge them into one.")

        inv = data.inventory()
        by_id = {int(r["id"]): r for r in inv}
        items = [by_id[i] for i in ids if i in by_id]
        if len(items) < 2:
            return (no_update, no_update, no_update, True, "Nothing to merge",
                    "warning", "Couldn't find the selected rows — refresh and retry.")

        # Auto-pick the richest entry as the survivor (same rule the duplicate
        # finder uses); everything else folds into it.
        preview = data.merge_preview(items)
        primary_id = int(preview["_primary_id"])
        merge_ids = [i for i in ids if i != primary_id]

        data.snapshot_inventory()  # enable one-click undo
        result = data.merge_group(primary_id, merge_ids)
        data.commit_undo()

        if result is None:
            return (no_update, no_update, no_update, True, "Merge failed",
                    "danger", "Could not merge the selected rows.")
        name = result.get("name", "")
        msg = f'Merged {len(merge_ids) + 1} items into "{name}".'
        return (time.time(), [], _undo_alert(msg), True, "Merged", "success", msg)

    # ---------- Undo the last merge / bulk delete ----------
    @app.callback(
        Output("refresh-seq", "data", allow_duplicate=True),
        Output("undo-bar", "children", allow_duplicate=True),
        Output("action-toast", "is_open", allow_duplicate=True),
        Output("action-toast", "header", allow_duplicate=True),
        Output("action-toast", "icon", allow_duplicate=True),
        Output("action-toast", "children", allow_duplicate=True),
        Input("undo-apply", "n_clicks"),
        prevent_initial_call=True,
    )
    def undo_last(n):
        if not n:
            raise PreventUpdate
        status = data.restore_inventory()
        if status == "restored":
            return (time.time(), "", True, "Undone", "success", "Restored the items from before.")
        if status == "stale":
            return (no_update, "", True, "Can't undo", "warning",
                    "The inventory changed since — undo was cancelled to avoid losing that.")
        return (no_update, "", True, "Nothing to undo", "warning", "No recent change to undo.")

    # ---------- Bulk edit: clear the selection ----------
    @app.callback(
        Output("inventory-table", "selected_rows", allow_duplicate=True),
        Input("bulk-clear", "n_clicks"),
        prevent_initial_call=True,
    )
    def bulk_clear(n):
        if not n:
            raise PreventUpdate
        return []

    # ---------- Load selected item image into OCR Lab ----------
    @app.callback(
        Output("ocr-target", "data"),
        Output("image-contents", "data"),
        Input("inventory-table", "selected_rows"),
        State("inventory-table", "data"),
        prevent_initial_call=True,
    )
    def load_image_to_ocr_lab(selected_rows, table_data):
        import base64

        if not selected_rows or not table_data:
            raise PreventUpdate

        # Get the selected row
        row_idx = selected_rows[0]
        if row_idx >= len(table_data):
            raise PreventUpdate

        row = table_data[row_idx]
        item_id = row.get("id")

        if not item_id:
            raise PreventUpdate

        # Set ocr-target with item_id
        ocr_target = {"item_id": item_id}

        # Load the first image if it exists
        all_items = data.inventory()
        item = next((r for r in all_items if r.get("id") == item_id), None)

        if not item:
            return ocr_target, no_update

        images = item.get("images", [])
        if not images:
            return ocr_target, no_update

        # Load the first image file and convert to data URL
        first_image = images[0]
        image_path = ASSET_IMAGE_PATH / first_image

        if not image_path.exists():
            return ocr_target, no_update

        try:
            # Read image and convert to base64 data URL
            image_bytes = image_path.read_bytes()
            b64_str = base64.b64encode(image_bytes).decode('utf-8')

            # Determine mime type from extension
            ext = image_path.suffix.lower()
            if ext in ['.jpg', '.jpeg']:
                mime = 'image/jpeg'
            elif ext == '.png':
                mime = 'image/png'
            elif ext == '.webp':
                mime = 'image/webp'
            else:
                mime = 'image/png'

            data_url = f"data:{mime};base64,{b64_str}"
            return ocr_target, data_url
        except Exception:
            return ocr_target, no_update

    # ---------- OCR Lab → table (NO duplicate Outputs anymore) ----------
    @app.callback(
        Output("refresh-seq", "data"),
        Input("ocr-result", "data"),
        prevent_initial_call=True,
    )
    def apply_ocr_result(res):
        if not res:
            raise PreventUpdate
        item_id = (res or {}).get("item_id")
        text = (res or {}).get("text", "")
        if not item_id:
            return time.time()  # still refresh table
        try:
            all_items = data.inventory()
            match = next((r for r in all_items if r.get("id") == item_id), None)
            if match:
                data.update_item(
                    item_id=item_id,
                    name=match.get("name", ""),
                    description=match.get("description", ""),
                    qty=match.get("qty", 0),
                    images=match.get("images", []),
                    ocr_text=(text or ""),
                    category=match.get("category", ""),
                    location=match.get("location", ""),
                )
        except Exception:
            pass
        return time.time()
