from __future__ import annotations
import os, time
from dash import Input, Output, State, ctx, no_update, ALL, html, dcc
from dash.exceptions import PreventUpdate
import data
from utils import save_image, get_thumbnail_url, get_image_url
from config import LOW_STOCK_THRESHOLD, ASSET_IMAGE_PATH, OCR_TEXT_MAX_CHARS

URL_PREFIX = os.getenv("URL_PREFIX", "/inventory").strip().rstrip("/")
if URL_PREFIX and not URL_PREFIX.startswith("/"):
    URL_PREFIX = "/" + URL_PREFIX
ASSET_URL_BASE = f"{URL_PREFIX}/assets" if URL_PREFIX else "/assets"

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
            # Store all image URLs for modal
            row["all_images"] = [get_image_url(img) for img in images]
        else:
            row["image"] = ""
            row["all_images"] = []

        # Keep organizing fields present for the table (and CSV/native filters)
        row["category"] = (row.get("category") or "").strip()
        row["location"] = (row.get("location") or "").strip()

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

def _identify_footer(res):
    endpoint = (res.get("endpoint", "") or "").replace("/api/generate", "")
    return html.Div(
        ["via ", html.Code(res.get("model", "") or "?"), " @ ", html.Code(endpoint or "?")],
        className="text-muted small mt-3",
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

def _render_identify(res):
    """Read-only rendering of a vision_lookup.identify_item() result."""
    if not res.get("ok"):
        return html.Div(
            [
                html.P(
                    [html.I(className="bi bi-exclamation-triangle me-2"), "Couldn't reach the vision service."],
                    className="fw-bold text-danger",
                ),
                html.P(res.get("error", ""), className="small"),
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
                "⚠️ These are AI estimates read from the photo — double-check before relying on them.",
                className="text-muted small mt-3",
            ),
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
            State("image-upload", "contents"),
            State("current-images", "data"),
            State("editing-id", "data"),
            State("inventory-table", "data"),
        ],
        prevent_initial_call=False,
    )
    def manage_table(pathname, save_clicks, delete_clicks, sel_rows, cancel_clicks,
                     search, filter_cat, filter_loc, _refresh_seq,
                     name, desc, qty, category, location, img_contents,
                     current_images, editing_id, current_rows):
        triggered = (ctx.triggered_id or "")
        # Default toast outputs to no_update: 'inventory-table.selected_rows' is both
        # an Output and an Input here, so resetting the selection after a Save/Delete
        # re-enters this callback. If the toast defaulted to closed, that second pass
        # would immediately hide the success toast, so leave it untouched instead.
        toast_open, toast_header, toast_icon, toast_msg = no_update, no_update, no_update, no_update
        next_sel = sel_rows or []
        next_name = next_desc = next_qty = next_category = next_location = no_update
        next_editing = next_images = next_upload = no_update

        # Always load latest items
        items = data.inventory()

        # Create / Update
        if triggered == "save-button":
            nm = (name or "").strip()
            if not nm:
                toast_open, toast_header, toast_icon, toast_msg = True, "Missing Name", "warning", "Please enter a name."
            else:
                ds = (desc or "").strip()
                cat = (category or "").strip()
                loc = (location or "").strip()
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
                                         category=cat, location=loc)
                        toast_header, toast_icon, toast_msg = "Item Updated", "success", f'"{nm}" updated.'
                    else:
                        data.add_item(nm, ds, nqty, img_filenames, "", category=cat, location=loc)
                        toast_header, toast_icon, toast_msg = "Item Added", "success", f'"{nm}" added.'
                except ValueError as e:
                    toast_header, toast_icon, toast_msg = "Duplicate Name", "danger", str(e)

                toast_open = True
                # clear form (reset qty to 1 for quick repeat entry)
                next_sel = []
                next_name, next_desc, next_qty = "", "", 1
                next_category, next_location = "", ""
                next_editing, next_images, next_upload = None, [], None
                # refresh items for table build
                items = data.inventory()

        # Delete
        elif triggered == "delete-button":
            if editing_id:
                removed = data.remove_item(editing_id)
                if removed:
                    toast_open, toast_header, toast_icon, toast_msg = True, "Item Deleted", "danger", f'"{removed.get("name","")}" deleted.'
                next_sel = []
                next_name, next_desc, next_qty = "", "", 1
                next_category, next_location = "", ""
                next_editing, next_images, next_upload = None, [], None
                items = data.inventory()

        # Cancel clears form
        elif triggered == "cancel-button":
            next_sel = []
            next_name, next_desc, next_qty = "", "", 1
            next_category, next_location = "", ""
            next_editing, next_images, next_upload = None, [], None

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
            next_editing, next_images, next_upload,
            toast_open, toast_header, toast_icon, toast_msg
        ]

    # ---------- Populate filter dropdowns & type-ahead suggestions ----------
    @app.callback(
        Output("filter-category", "options"),
        Output("filter-location", "options"),
        Output("category-datalist", "children"),
        Output("location-datalist", "children"),
        Input("inventory-table", "data"),
        prevent_initial_call=False,
    )
    def refresh_organizers(_table_data):
        # Always derive from the FULL inventory (not the filtered view) so you can
        # switch between filters freely and newly-added values show up immediately.
        all_items = data.inventory()
        cats = data.categories(all_items)
        locs = data.locations(all_items)
        cat_opts = [{"label": c, "value": c} for c in cats]
        loc_opts = [{"label": l, "value": l} for l in locs]
        cat_dl = [html.Option(value=c) for c in cats]
        loc_dl = [html.Option(value=l) for l in locs]
        return cat_opts, loc_opts, cat_dl, loc_dl

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
        writer.writerow(["id", "name", "category", "location", "qty", "description", "ocr_text", "images"])
        for r in rows:
            writer.writerow([
                r.get("id"),
                r.get("name", ""),
                r.get("category", ""),
                r.get("location", ""),
                r.get("qty", 0),
                r.get("description", ""),
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
        State("current-images", "data"),
        State("image-upload", "contents"),
        prevent_initial_call=True,
    )
    def toggle_identify(open_clicks, close_clicks, current_images, upload_contents):
        trig = ctx.triggered_id
        if trig == "close-identify-modal":
            return False, no_update
        if trig != "identify-button":
            raise PreventUpdate
        # Prefer a freshly-taken (unsaved) photo; else the selected item's primary photo.
        pending = None
        if upload_contents:
            pending = upload_contents[0] if isinstance(upload_contents, list) else upload_contents
        primary = (current_images or [None])[0] if current_images else None
        # Include n_clicks so re-clicking on the same photo re-runs the lookup.
        return True, {"pending": pending, "img": primary, "n": open_clicks}

    # ---------- Identify item from photo (run the vision lookup) ----------
    @app.callback(
        Output("identify-body", "children"),
        Input("identify-trigger", "data"),
        prevent_initial_call=True,
    )
    def do_identify(trigger):
        if not trigger:
            raise PreventUpdate
        pending = trigger.get("pending")
        primary = trigger.get("img")

        image = None
        if pending:
            image = pending  # data URL string (freshly-taken, unsaved photo)
        elif primary:
            path = ASSET_IMAGE_PATH / primary
            if path.exists():
                image = path.read_bytes()

        if image is None:
            return html.Div(
                "Select an item that has a photo (or take a new photo) first, then click Identify.",
                className="text-warning",
            )

        import vision_lookup
        res = vision_lookup.identify_item(image)
        return _render_identify(res)

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
