from __future__ import annotations
import os, time
from dash import Input, Output, State, ctx, no_update, ALL, html, dcc
import dash_bootstrap_components as dbc
from dash.exceptions import PreventUpdate
import data
from utils import save_image, get_thumbnail_url, get_image_url
from config import LOW_STOCK_THRESHOLD, ASSET_IMAGE_PATH, OCR_TEXT_MAX_CHARS

URL_PREFIX = os.getenv("URL_PREFIX", "/inventory").strip().rstrip("/")
if URL_PREFIX and not URL_PREFIX.startswith("/"):
    URL_PREFIX = "/" + URL_PREFIX
ASSET_URL_BASE = f"{URL_PREFIX}/assets" if URL_PREFIX else "/assets"

# How much of the description to show inline before truncating (full text + the
# extracted specs live in the row's hover tooltip).
DESC_MAX_CHARS = 90

def _parse_qty(q):
    try:
        n = int(q)
        return n if n >= 0 else 0
    except Exception:
        return 0

def _specs_to_text(specs):
    """Render a stored specifications list as one-per-line text for the textarea."""
    if isinstance(specs, list):
        return "\n".join(str(s) for s in specs if str(s).strip())
    return str(specs or "")

def _tags_to_text(tags):
    """Render a stored tags list as a comma-separated string for the input."""
    if isinstance(tags, list):
        return ", ".join(str(t) for t in tags if str(t).strip())
    return str(tags or "")

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
            # Store all image URLs for modal
            row["all_images"] = [get_image_url(img) for img in images]
        else:
            row["image"] = ""
            row["all_images"] = []

        # Keep organizing fields present for the table (and CSV/native filters)
        row["category"] = (row.get("category") or "").strip()
        row["location"] = (row.get("location") or "").strip()
        row["estimated_value"] = (row.get("estimated_value") or "").strip()

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

def _apply_filters(items, search, filter_cat, filter_loc):
    filtered = data.search(search) if search else items
    if filter_cat:
        filtered = [r for r in filtered if (r.get("category") or "").strip() == filter_cat]
    if filter_loc:
        filtered = [r for r in filtered if (r.get("location") or "").strip() == filter_loc]
    return filtered

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
    """Render data.storage_map() as a compact per-bin list."""
    if not bins:
        return html.Div("No bins yet. Add items and run Smart Organize.", className="text-muted small")
    cards = []
    for b in bins:
        code = b.get("location_code", "")
        label = code or "Unfiled"
        badge_class = "badge bg-primary" if code else "badge bg-secondary"
        names = b.get("names", [])
        preview = ", ".join(names[:6]) + ("…" if len(names) > 6 else "")
        cards.append(
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(label, className=badge_class + " me-2"),
                            html.Span(b.get("location_name", "") or "", className="text-muted small"),
                            html.Span(
                                [
                                    html.Span(f"{b.get('qty', 0)}", className="badge bg-primary rounded-pill me-1"),
                                    html.Span(f"{b.get('items', 0)} item{'s' if b.get('items') != 1 else ''}", className="text-muted small"),
                                ],
                                className="ms-auto text-nowrap",
                            ),
                        ],
                        className="d-flex align-items-center",
                    ),
                    html.Div(preview, className="text-muted small mt-1"),
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
                        " and pull a vision model, e.g. ", html.Code("ollama pull llama3.2-vision"), ".",
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

def register_callbacks(app):
    # ---------- Table & form (single source of truth for table + toast) ----------
    @app.callback(
        [
            Output("inventory-table", "data"),
            Output("inventory-table", "selected_rows"),
            Output("item-name", "value"),
            Output("item-desc", "value"),
            Output("item-qty", "value"),
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
            Input("filter-category", "value"),
            Input("filter-location", "value"),
            Input("refresh-seq", "data"),
        ],
        [
            State("item-name", "value"),
            State("item-desc", "value"),
            State("item-qty", "value"),
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
        ],
        prevent_initial_call=False,
    )
    def manage_table(pathname, save_clicks, save_next_clicks, delete_clicks, sel_rows, cancel_clicks,
                     search, filter_cat, filter_loc, _refresh_seq,
                     name, desc, qty, category, location, location_code,
                     specs, value, dims, tags, producturl, img_contents,
                     current_images, editing_id, current_rows):
        triggered = (ctx.triggered_id or "")
        # Default toast outputs to no_update: 'inventory-table.selected_rows' is both
        # an Output and an Input here, so resetting the selection after a Save/Delete
        # re-enters this callback. If the toast defaulted to closed, that second pass
        # would immediately hide the success toast, so leave it untouched instead.
        toast_open, toast_header, toast_icon, toast_msg = no_update, no_update, no_update, no_update
        next_sel = sel_rows or []
        next_name = next_desc = next_qty = next_category = next_location = no_update
        next_code = next_specs = next_value = next_dims = next_tags = next_url = no_update
        next_editing = next_images = next_upload = no_update

        def _clear_form(keep_location=False):
            """Reset the form. When keep_location, the category/location/bin stay so
            you can scan a run of similar items without re-typing where they live."""
            nonlocal next_name, next_desc, next_qty, next_category, next_location
            nonlocal next_code, next_specs, next_value, next_dims, next_tags, next_url
            nonlocal next_editing, next_images, next_upload, next_sel
            next_sel = []
            next_name, next_desc, next_qty = "", "", 1
            next_specs, next_value, next_dims, next_tags, next_url = "", "", "", "", ""
            if not keep_location:
                next_category, next_location, next_code = "", "", ""
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
                loc = (location or "").strip()
                code = (location_code or "").strip()
                nqty = _parse_qty(qty)

                # Handle multiple image uploads
                img_filenames = list(current_images or [])
                if img_contents:
                    # Support both single and multiple uploads
                    if isinstance(img_contents, list):
                        for img_content in img_contents:
                            saved = save_image(img_content, ASSET_IMAGE_PATH, base_name=nm)
                            img_filenames.append(saved["filename"])
                    else:
                        saved = save_image(img_contents, ASSET_IMAGE_PATH, base_name=nm)
                        img_filenames.append(saved["filename"])

                try:
                    if editing_id:
                        # preserve existing ocr_text if not part of this form
                        existing_row = next((r for r in items if r.get("id") == editing_id), {})
                        existing_ocr = existing_row.get("ocr_text", "")
                        data.update_item(editing_id, nm, ds, nqty, img_filenames, existing_ocr,
                                         category=cat, location=loc, location_code=code,
                                         specifications=specs, estimated_value=value,
                                         dimensions=dims, tags=tags, product_url=producturl)
                        toast_header, toast_icon, toast_msg = "Item Updated", "success", f'"{nm}" updated.'
                    else:
                        data.add_item(nm, ds, nqty, img_filenames, "", category=cat, location=loc,
                                      location_code=code, specifications=specs, estimated_value=value,
                                      dimensions=dims, tags=tags, product_url=producturl)
                        toast_header, toast_icon, toast_msg = "Item Added", "success", f'"{nm}" added.'
                except ValueError as e:
                    toast_header, toast_icon, toast_msg = "Duplicate Name", "danger", str(e)

                toast_open = True
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
                items = data.inventory()

        # Cancel clears form
        elif triggered == "cancel-button":
            _clear_form()

        # Selecting a row populates form
        elif triggered == "inventory-table":
            if sel_rows:
                idx = sel_rows[0]
                if isinstance(idx, int) and 0 <= idx < len(current_rows or []):
                    row = (current_rows or [])[idx]
                    # Load the authoritative record from disk
                    actual_row = next((r for r in items if r.get("id") == row.get("id")), {})
                    next_name = actual_row.get("name", row.get("name", ""))
                    next_desc = actual_row.get("description", row.get("description", ""))
                    next_qty = actual_row.get("qty", row.get("qty", None))
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

        # Search / filter change: drop the stale selection highlight (the edit form
        # and editing-id are intentionally left as-is).
        elif triggered in ("search-bar", "filter-category", "filter-location"):
            next_sel = []

        # Filter/search
        filtered = _apply_filters(items, search, filter_cat, filter_loc)
        out_rows = _build_rows(filtered)

        return [
            out_rows, next_sel, next_name, next_desc, next_qty, next_category, next_location,
            next_code, next_specs, next_value, next_dims, next_tags, next_url,
            next_editing, next_images, next_upload,
            toast_open, toast_header, toast_icon, toast_msg
        ]

    # ---------- Populate filter dropdowns & type-ahead suggestions ----------
    @app.callback(
        Output("filter-category", "options"),
        Output("filter-location", "options"),
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
        cats = data.categories(all_items)
        locs = data.locations(all_items)
        codes = data.location_codes(all_items)
        cat_opts = [{"label": c, "value": c} for c in cats]
        loc_opts = [{"label": l, "value": l} for l in locs]
        cat_dl = [html.Option(value=c) for c in cats]
        loc_dl = [html.Option(value=l) for l in locs]
        code_dl = [html.Option(value=c) for c in codes]
        return cat_opts, loc_opts, cat_dl, loc_dl, code_dl

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
            # Same rich tooltip on the columns you're most likely to hover.
            tips.append({"name": cell, "description": cell, "estimated_value": cell})
        return tips

    # ---------- Image gallery display ----------
    @app.callback(
        Output("image-gallery", "children"),
        Output("current-images", "data", allow_duplicate=True),
        Input("current-images", "data"),
        Input("image-upload", "contents"),
        State("image-upload", "filename"),
        State("current-images", "data"),
        prevent_initial_call='initial_duplicate',
    )
    def update_image_gallery(current_imgs, upload_contents, upload_filenames, existing_imgs):
        from dash import html as h

        # Start with existing images
        img_list = existing_imgs or []
        preview_data = []  # For showing upload previews before save

        # If this was triggered by upload, process the uploads for preview
        if ctx.triggered_id == "image-upload" and upload_contents:
            # Support both single and multiple uploads
            uploads = upload_contents if isinstance(upload_contents, list) else [upload_contents]
            filenames = upload_filenames if isinstance(upload_filenames, list) else [upload_filenames]

            for content, filename in zip(uploads, filenames):
                if content:
                    # Store the upload data for preview (don't save to disk yet)
                    preview_data.append({
                        'content': content,
                        'filename': filename,
                        'is_preview': True
                    })

        # Create gallery of thumbnails with delete buttons
        gallery_items = []

        # Show existing saved images
        for i, img_filename in enumerate(img_list):
            thumb_url = get_thumbnail_url(img_filename)
            if thumb_url:
                gallery_items.append(
                    h.Div(
                        [
                            h.Img(src=thumb_url, className="gallery-thumb"),
                            h.Button(
                                "×",
                                id={"type": "delete-image", "index": i},
                                className="btn btn-sm btn-danger delete-img-btn",
                                title="Remove image",
                                n_clicks=0,
                            ),
                            h.Div(f"Image {i+1}", className="text-muted small text-center"),
                        ],
                        className="gallery-item",
                    )
                )

        # Show upload previews
        for j, preview in enumerate(preview_data):
            gallery_items.append(
                h.Div(
                    [
                        h.Img(src=preview['content'], className="gallery-thumb", style={'maxHeight': '150px', 'maxWidth': '150px', 'objectFit': 'contain'}),
                        h.Div(f"New: {preview['filename']}", className="text-muted small text-center"),
                    ],
                    className="gallery-item",
                    style={'border': '2px dashed #28a745'}
                )
            )

        if not gallery_items:
            return h.Div("No photos yet. Take a photo or upload to get started.", className="text-muted small"), img_list

        return h.Div(gallery_items, className="image-gallery-grid"), img_list

    # ---------- Remove image from gallery ----------
    @app.callback(
        Output("current-images", "data", allow_duplicate=True),
        Output("image-gallery", "children", allow_duplicate=True),
        Input({"type": "delete-image", "index": ALL}, "n_clicks"),
        State("current-images", "data"),
        prevent_initial_call=True,
    )
    def remove_image_from_gallery(n_clicks_list, current_imgs):
        from dash import html as h

        if not ctx.triggered or not current_imgs:
            raise PreventUpdate

        # Check if any delete button was actually clicked
        if not n_clicks_list or all(clicks is None or clicks == 0 for clicks in n_clicks_list):
            raise PreventUpdate

        # Find which button was clicked
        triggered_id = ctx.triggered_id
        if triggered_id and isinstance(triggered_id, dict):
            index = triggered_id.get("index")
            if index is not None and 0 <= index < len(current_imgs):
                # Remove the image at the specified index
                updated_imgs = current_imgs.copy()
                del updated_imgs[index]

                # Rebuild gallery with updated list
                gallery_items = []
                for i, img_filename in enumerate(updated_imgs):
                    thumb_url = get_thumbnail_url(img_filename)
                    if thumb_url:
                        gallery_items.append(
                            h.Div(
                                [
                                    h.Img(src=thumb_url, className="gallery-thumb"),
                                    h.Button(
                                        "×",
                                        id={"type": "delete-image", "index": i},
                                        className="btn btn-sm btn-danger delete-img-btn",
                                        title="Remove image",
                                        n_clicks=0,
                                    ),
                                    h.Div(f"Image {i+1}", className="text-muted small text-center"),
                                ],
                                className="gallery-item",
                            )
                        )

                gallery_div = h.Div(gallery_items, className="image-gallery-grid") if gallery_items else h.Div("No photos yet. Take a photo or upload to get started.", className="text-muted small")

                return updated_imgs, gallery_div

        raise PreventUpdate

    # ---------- Full image modal ----------
    @app.callback(
        Output("image-modal", "is_open"),
        Output("image-modal-title", "children"),
        Output("image-carousel", "items"),
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
        all_images = row.get("all_images", [])
        if not all_images:
            raise PreventUpdate

        # Create carousel items
        carousel_items = [
            {
                "key": str(i),
                "src": img_url,
                "img_style": {"maxHeight": "70vh", "objectFit": "contain"},
            }
            for i, img_url in enumerate(all_images)
        ]

        return True, row.get("name", ""), carousel_items

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
        Input("inventory-table", "data"),
        prevent_initial_call=False,
    )
    def update_kpis(rows):
        rows = rows or []
        total = len(rows)
        total_qty = sum(int(r.get("qty") or 0) for r in rows)
        low = sum(1 for r in rows if (int(r.get("qty") or 0)) < LOW_STOCK_THRESHOLD)
        cats = len({(r.get("category") or "").strip() for r in rows if (r.get("category") or "").strip()})
        return total, total_qty, low, cats

    # ---------- Overview breakdown (by location / category) ----------
    @app.callback(
        Output("breakdown-location", "children"),
        Output("breakdown-category", "children"),
        Input("inventory-table", "data"),
        prevent_initial_call=False,
    )
    def update_breakdown(rows):
        rows = rows or []
        by_loc = data.summary_by("location", rows)
        by_cat = data.summary_by("category", rows)
        return _breakdown_list(by_loc), _breakdown_list(by_cat)

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
            "id", "name", "category", "location", "bin", "qty", "description",
            "specifications", "estimated_value", "dimensions", "tags",
            "product_url", "ocr_text", "images",
        ])
        for r in rows:
            writer.writerow([
                r.get("id"),
                r.get("name", ""),
                r.get("category", ""),
                r.get("location", ""),
                r.get("location_code", ""),
                r.get("qty", 0),
                r.get("description", ""),
                " | ".join(r.get("specifications", []) or []),
                r.get("estimated_value", ""),
                r.get("dimensions", ""),
                ", ".join(r.get("tags", []) or []),
                r.get("product_url", ""),
                (r.get("ocr_text", "") or "").replace("\n", " ").strip(),
                "; ".join(r.get("images", []) or []),
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
        qty = _parse_qty(cur_qty)
        images = list(cur_imgs or [])
        loc = (cur_loc or "").strip()
        code = (cur_code or "").strip()

        try:
            if editing_id:
                existing = next((r for r in data.inventory() if r.get("id") == editing_id), {})
                data.update_item(
                    editing_id, name, desc, qty, images, existing.get("ocr_text", ""),
                    category=category, location=loc, location_code=code,
                    specifications=specs_text, estimated_value=value, dimensions=dims,
                    tags=tags_text, product_url=url,
                )
                saved_id = editing_id
                header, msg = "Item Updated", f'"{name}" updated from the lookup.'
            else:
                row = data.add_item(
                    name, desc, qty, images, "", category=category, location=loc,
                    location_code=code, specifications=specs_text, estimated_value=value,
                    dimensions=dims, tags=tags_text, product_url=url,
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

        body = _render_import(res)
        if res.get("ok"):
            return body, {"data": res.get("data")}
        # Keep any prior good result on failure so Apply still has something.
        return body, no_update

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
        return _render_storage_map(data.storage_map())

    # ---------- Storage bins: open editor (load current containers) ----------
    @app.callback(
        Output("bins-modal", "is_open"),
        Output("containers-text", "value"),
        Input("open-bins", "n_clicks"),
        prevent_initial_call=True,
    )
    def open_bins(n):
        if not n:
            raise PreventUpdate
        return True, data.containers_to_text()

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
        Output("containers-text", "value", allow_duplicate=True),
        Input("save-containers", "n_clicks"),
        State("containers-text", "value"),
        prevent_initial_call=True,
    )
    def save_bins(n, text):
        if not n:
            raise PreventUpdate
        conts = data.save_containers(data.parse_containers_text(text))
        msg = html.Span(
            [html.I(className="bi bi-check-circle me-1"), f"Saved {len(conts)} bin{'s' if len(conts) != 1 else ''}."],
            className="text-success",
        )
        return msg, data.containers_to_text(conts)

    # ---------- Storage bins: fit items into the containers ----------
    @app.callback(
        Output("fit-result", "children"),
        Output("fit-plan", "data"),
        Output("containers-text", "value", allow_duplicate=True),
        Output("bins-status", "children", allow_duplicate=True),
        Input("fit-bins", "n_clicks"),
        State("containers-text", "value"),
        prevent_initial_call=True,
    )
    def do_fit(n, text):
        if not n:
            raise PreventUpdate
        conts = data.save_containers(data.parse_containers_text(text))
        if not conts:
            return (html.Div("Add at least one container above (CODE | Name | capacity), then Fit.",
                             className="text-warning"),
                    None, no_update, no_update)
        plan = data.fit_to_containers(conts=conts)
        return _render_fit(plan), plan, data.containers_to_text(conts), ""

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
