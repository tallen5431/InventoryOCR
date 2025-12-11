from __future__ import annotations
import os, time
from dash import Input, Output, State, ctx, no_update
from dash.exceptions import PreventUpdate
import data
from utils import save_image, get_thumbnail_url
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
        row["select"] = "🔘"

        # Always recompute thumbnail URL so we pick up the correct /inventory prefix
        image_filename = row.get("image_filename")
        thumb_url = get_thumbnail_url(image_filename)
        row["image"] = f"![thumb]({thumb_url})" if thumb_url else ""

        # Full-size image URL uses the same /inventory/assets/... base
        if image_filename:
            row["full_src"] = f"{ASSET_URL_BASE}/images/{image_filename}"
        else:
            row["full_src"] = ""

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
            State("editing-id", "data"),
            State("inventory-table", "data"),
        ],
        prevent_initial_call=False,
    )
    def manage_table(pathname, save_clicks, delete_clicks, sel_rows, cancel_clicks,
                     search, _refresh_seq, name, desc, qty, img, editing_id, current_rows):
        triggered = (ctx.triggered_id or "")
        toast_open, toast_header, toast_icon, toast_msg = False, "", "info", ""
        next_sel = sel_rows or []
        next_name = next_desc = next_qty = next_editing = no_update

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

                # keep current image if not uploading a new one
                img_fname = None
                if img:
                    saved = save_image(img, ASSET_IMAGE_PATH, base_name=nm)
                    img_fname = saved["filename"]
                elif editing_id:
                    existing = next((r for r in (current_rows or []) if r.get("id") == editing_id), None)
                    img_fname = (existing or {}).get("image_filename")

                try:
                    if editing_id:
                        # preserve existing ocr_text if not part of this form
                        existing_row = next((r for r in items if r.get("id") == editing_id), {})
                        existing_ocr = existing_row.get("ocr_text", "")
                        data.update_item(editing_id, nm, ds, nqty, img_fname, existing_ocr)
                        toast_header, toast_icon, toast_msg = "Item Updated", "success", f"“{nm}” updated."
                    else:
                        data.add_item(nm, ds, nqty, img_fname, "")
                        toast_header, toast_icon, toast_msg = "Item Added", "success", f"“{nm}” added."
                except ValueError as e:
                    toast_header, toast_icon, toast_msg = "Duplicate Name", "danger", str(e)

                toast_open = True
                # clear form
                next_sel, next_name, next_desc, next_qty, next_editing = [], "", "", None, None
                # refresh items for table build
                items = data.inventory()

        # Delete
        elif triggered == "delete-button":
            if editing_id:
                removed = data.remove_item(editing_id)
                if removed:
                    toast_open, toast_header, toast_icon, toast_msg = True, "Item Deleted", "danger", f"“{removed.get('name','')}” deleted."
                next_sel, next_name, next_desc, next_qty, next_editing = [], "", "", None, None
                items = data.inventory()

        # Cancel clears form
        elif triggered == "cancel-button":
            next_sel, next_name, next_desc, next_qty, next_editing = [], "", "", None, None

        # Selecting a row populates form
        elif triggered == "inventory-table":
            if sel_rows:
                idx = sel_rows[0]
                if isinstance(idx, int) and 0 <= idx < len(current_rows or []):
                    row = (current_rows or [])[idx]
                    next_name, next_desc = row.get("name", ""), row.get("description", "")
                    next_qty, next_editing = row.get("qty", None), row.get("id")

        # Filter/search
        filtered = data.search(search) if search else items
        out_rows = _build_rows(filtered)

        return [
            out_rows, next_sel, next_name, next_desc, next_qty, next_editing,
            toast_open, toast_header, toast_icon, toast_msg
        ]

    # ---------- Image preview (upload -> preview + bridge) ----------
    @app.callback(
        Output("image-preview", "src"),
        Output("image-preview", "style"),
        Output("image-contents", "data"),
        Input("image-upload", "contents"),
        prevent_initial_call=False,
    )
    def preview_image(contents):
        if not contents:
            raise PreventUpdate
        return contents, {"maxWidth": "100%", "marginTop": "10px", "display": "block"}, contents

    # ---------- Full image modal ----------
    @app.callback(
        Output("image-modal", "is_open"),
        Output("image-modal-title", "children"),
        Output("image-modal-img", "src"),
        Input("inventory-table", "active_cell"),
        State("inventory-table", "data"),
        State("image-modal", "is_open"),
        prevent_initial_call=True,
    )
    def open_image_modal(cell, rows, is_open):
        if not cell or cell.get("column_id") != "image":
            raise PreventUpdate
        ridx = cell.get("row")
        if ridx is None or ridx >= len(rows or []):
            raise PreventUpdate
        row = (rows or [])[ridx]
        src = row.get("full_src") or ""
        if not src:
            raise PreventUpdate
        return True, row.get("name", ""), src

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
                    image_filename=match.get("image_filename"),
                    ocr_text=(text or ""),
                )
        except Exception:
            pass
        return time.time()
