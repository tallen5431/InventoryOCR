from __future__ import annotations
import os, time
from dash import Input, Output, State, ctx, no_update, ALL
from dash.exceptions import PreventUpdate
import data
from utils import save_image, get_thumbnail_url, get_image_url
from config import LOW_STOCK_THRESHOLD, ASSET_IMAGE_PATH, OCR_TEXT_MAX_CHARS

URL_PREFIX = os.getenv("URL_PREFIX", "/inventory").rstrip("/")
if not URL_PREFIX.startswith("/"):
    URL_PREFIX = "/" + URL_PREFIX
ASSET_URL_BASE = f"{URL_PREFIX}/assets"

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

def register_callbacks(app):
    # ---------- Table & form (single source of truth for table + toast) ----------
    @app.callback(
        [
            Output("inventory-table", "data"),
            Output("inventory-table", "selected_rows"),
            Output("item-name", "value"),
            Output("item-desc", "value"),
            Output("item-qty", "value"),
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
            Input("refresh-seq", "data"),
        ],
        [
            State("item-name", "value"),
            State("item-desc", "value"),
            State("item-qty", "value"),
            State("image-upload", "contents"),
            State("current-images", "data"),
            State("editing-id", "data"),
            State("inventory-table", "data"),
        ],
        prevent_initial_call=False,
    )
    def manage_table(pathname, save_clicks, delete_clicks, sel_rows, cancel_clicks,
                     search, _refresh_seq, name, desc, qty, img_contents, current_images, editing_id, current_rows):
        triggered = (ctx.triggered_id or "")
        toast_open, toast_header, toast_icon, toast_msg = False, "", "info", ""
        next_sel = sel_rows or []
        next_name = next_desc = next_qty = next_editing = next_images = next_upload = no_update

        # Always load latest items
        items = data.inventory()

        # Create / Update
        if triggered == "save-button":
            nm = (name or "").strip()
            if not nm:
                toast_open, toast_header, toast_icon, toast_msg = True, "Missing Name", "warning", "Please enter a name."
            else:
                ds = (desc or "").strip()
                nqty = _parse_qty(qty)

                # Handle multiple image uploads
                img_filenames = current_images or []
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
                        data.update_item(editing_id, nm, ds, nqty, img_filenames, existing_ocr)
                        toast_header, toast_icon, toast_msg = "Item Updated", "success", f'"{nm}" updated.'
                    else:
                        data.add_item(nm, ds, nqty, img_filenames, "")
                        toast_header, toast_icon, toast_msg = "Item Added", "success", f'"{nm}" added.'
                except ValueError as e:
                    toast_header, toast_icon, toast_msg = "Duplicate Name", "danger", str(e)

                toast_open = True
                # clear form
                next_sel, next_name, next_desc, next_qty, next_editing, next_images, next_upload = [], "", "", None, None, [], None
                # refresh items for table build
                items = data.inventory()

        # Delete
        elif triggered == "delete-button":
            if editing_id:
                removed = data.remove_item(editing_id)
                if removed:
                    toast_open, toast_header, toast_icon, toast_msg = True, "Item Deleted", "danger", f'"{removed.get("name","")}" deleted.'
                next_sel, next_name, next_desc, next_qty, next_editing, next_images, next_upload = [], "", "", None, None, [], None
                items = data.inventory()

        # Cancel clears form
        elif triggered == "cancel-button":
            next_sel, next_name, next_desc, next_qty, next_editing, next_images, next_upload = [], "", "", None, None, [], None

        # Selecting a row populates form
        elif triggered == "inventory-table":
            if sel_rows:
                idx = sel_rows[0]
                if isinstance(idx, int) and 0 <= idx < len(current_rows or []):
                    row = (current_rows or [])[idx]
                    next_name, next_desc = row.get("name", ""), row.get("description", "")
                    next_qty, next_editing = row.get("qty", None), row.get("id")
                    # Load images from the actual data
                    actual_row = next((r for r in items if r.get("id") == row.get("id")), {})
                    next_images = actual_row.get("images", [])

        # Filter/search
        filtered = data.search(search) if search else items
        out_rows = _build_rows(filtered)

        return [
            out_rows, next_sel, next_name, next_desc, next_qty, next_editing, next_images, next_upload,
            toast_open, toast_header, toast_icon, toast_msg
        ]

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
        from utils import get_thumbnail_url
        import base64
        from io import BytesIO
        from PIL import Image

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
            return h.Div("No images yet. Drag & drop or click to upload.", className="text-muted small"), img_list

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
        from utils import get_thumbnail_url

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

                gallery_div = h.Div(gallery_items, className="image-gallery-grid") if gallery_items else h.Div("No images yet. Drag & drop or click to upload.", className="text-muted small")

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
        Output("kpi-low", "children"),
        Input("inventory-table", "data"),
        prevent_initial_call=False,
    )
    def update_kpis(rows):
        rows = rows or []
        total = len(rows)
        low = sum(1 for r in rows if (r.get("qty") or 0) < LOW_STOCK_THRESHOLD)
        return total, low

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
        from pathlib import Path

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
                )
        except Exception:
            pass
        return time.time()
