"""Callbacks for the Operations tab (materials + batches).

Everything is namespaced ``op-*`` so it can't collide with the dashboard. The
data model lives in :mod:`operations_data`; photo/document saving and invoice
parsing reuse the exact same helpers the dashboard uses (:mod:`utils`,
:mod:`invoice_parse`), so an invoice attached here fills in vendor/date/total
just like it does on the inventory form.

Output ownership (so Dash's duplicate-output rules are satisfied): each shared
output has exactly ONE owning callback that writes it without
``allow_duplicate``; every other writer sets ``allow_duplicate=True`` and
``prevent_initial_call=True``. See the comments on each callback.
"""
from __future__ import annotations

import csv
import io
import os

from dash import Input, Output, State, ctx, no_update, ALL, html, dcc
import dash_bootstrap_components as dbc
from dash.exceptions import PreventUpdate

import operations_data as od
import invoice_parse
import data  # for the shared, now materials-aware asset pruners
from utils import (
    save_image, save_attachment, read_attachment_text,
    get_thumbnail_url, get_image_url, get_preview_url,
)

# Asset URL base (mirrors utils/callbacks so document links work behind Caddy).
URL_PREFIX = os.getenv("URL_PREFIX", "/inventory").strip().rstrip("/")
if URL_PREFIX and not URL_PREFIX.startswith("/"):
    URL_PREFIX = "/" + URL_PREFIX
ASSET_URL_BASE = f"{URL_PREFIX}/assets" if URL_PREFIX else "/assets"

_ATTACH_ICON = {
    "image": "bi-file-earmark-image", "html": "bi-filetype-html",
    "pdf": "bi-file-earmark-pdf", "other": "bi-file-earmark",
}


# --------------------------------------------------------------------
# Small rendering helpers
# --------------------------------------------------------------------

def _money(v):
    return f"${v:,.2f}" if isinstance(v, (int, float)) else "—"


def _specs_to_text(specs):
    if isinstance(specs, list):
        return "\n".join(str(s) for s in specs if str(s).strip())
    return str(specs or "")


def _tags_to_text(tags):
    if isinstance(tags, list):
        return ", ".join(str(t) for t in tags if str(t).strip())
    return str(tags or "")


def _human_size(n):
    try:
        size = float(n)
    except (TypeError, ValueError):
        return ""
    if size <= 0:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return ""


def _doc_url(filename: str, *, download: bool = False) -> str:
    url = f"{ASSET_URL_BASE}/documents/{filename}"
    return url + "?download=1" if download else url


def _fullres_links(originals):
    """Footer control keeping the full-resolution originals one tap away while
    the viewer shows the fast preview."""
    originals = [u for u in (originals or []) if u]
    if not originals:
        return ""
    if len(originals) == 1:
        return html.A([html.I(className="bi bi-arrows-fullscreen me-1"),
                       "View full resolution"],
                      href=originals[0], target="_blank", rel="noopener noreferrer",
                      className="text-decoration-none")
    links = [html.Span("Full resolution: ", className="text-muted")]
    for i, u in enumerate(originals):
        links.append(html.A(str(i + 1), href=u, target="_blank",
                            rel="noopener noreferrer", className="me-2"))
    return html.Span(links)


def _render_gallery(images, remove_type="op-mat-img-remove"):
    images = images or []
    items = []
    for i, fn in enumerate(images):
        thumb = get_thumbnail_url(fn)
        if not thumb:
            continue
        items.append(
            html.Div(
                [
                    html.Img(src=thumb, className="gallery-thumb"),
                    html.Button("×", id={"type": remove_type, "index": i},
                                className="btn btn-sm btn-danger delete-img-btn",
                                title="Remove photo", n_clicks=0),
                    html.Div(f"Photo {i + 1}", className="text-muted small text-center"),
                ],
                className="gallery-item",
            )
        )
    if not items:
        return html.Div("No photos yet.", className="text-muted small")
    return html.Div(items, className="image-gallery-grid")


def _render_doc_list(atts, remove_type="op-mat-doc-remove"):
    atts = atts or []
    if not atts:
        return html.Div("No documents attached yet.", className="text-muted small")
    rows = []
    for i, a in enumerate(atts):
        fn = a.get("filename", "")
        icon = _ATTACH_ICON.get(a.get("kind", "other"), "bi-file-earmark")
        meta = " · ".join([x for x in [a.get("kind", ""), _human_size(a.get("size"))] if x])
        line = [
            html.I(className=f"bi {icon} me-2 text-secondary"),
            html.A(a.get("original_name") or fn, href=_doc_url(fn), target="_blank",
                   rel="noopener noreferrer", className="text-truncate me-2",
                   style={"maxWidth": "55%"}),
            html.Span(meta, className="text-muted small me-2"),
            html.A(html.I(className="bi bi-download"), href=_doc_url(fn, download=True),
                   className="btn btn-sm btn-outline-secondary py-0 px-1 me-1", title="Download"),
        ]
        if remove_type:
            line.append(
                dbc.Button(html.I(className="bi bi-x-lg"),
                           id={"type": remove_type, "index": i}, color="outline-danger",
                           size="sm", className="py-0 px-1", title="Remove", n_clicks=0)
            )
        rows.append(html.Div(line, className="d-flex align-items-center border rounded px-2 py-1 mb-1"))
    return html.Div(rows)


def _build_mat_rows(mats, name_map):
    """Materials -> DataTable rows (photo markdown, batch label, cost columns)."""
    out = []
    for m in mats:
        images = m.get("images") or []
        thumb = get_thumbnail_url(images[0]) if images else ""
        badge = f" ({len(images)})" if len(images) > 1 else ""
        cost = od.material_cost(m)
        bid = m.get("batch_id")
        out.append({
            "id": m.get("id"),
            "image": f"![thumb]({thumb}){badge}" if thumb else "",
            "all_previews": [get_preview_url(i) for i in images],
            "all_images": [get_image_url(i) for i in images],
            "name": m.get("name", ""),
            "material_type": m.get("material_type", ""),
            "batch": name_map.get(bid, "") if bid is not None else "",
            "qty": m.get("qty", 0),
            "unit_cost": m.get("unit_cost", "") or "—",
            "total_display": _money(cost),
            "vendor": m.get("vendor", ""),
            "purchase_date": m.get("purchase_date", ""),
            "docs": f"📎 {len(m.get('attachments') or [])}" if m.get("attachments") else "",
        })
    return out


def _mat_tooltips(mats):
    tips = []
    for m in mats:
        parts = []
        if m.get("description"):
            parts.append(m["description"])
        specs = m.get("specifications") or []
        if specs:
            parts.append("**Specs:** " + "; ".join(specs))
        text = "\n\n".join(parts) or m.get("name", "")
        tips.append({"name": {"value": text, "type": "markdown"}})
    return tips


# --------------------------------------------------------------------
# Batch cards (Batches tab)
# --------------------------------------------------------------------

def _batch_card(rollup, mat_options):
    b = rollup["batch"]
    bid = b.get("id")
    total = rollup["total_cost"]
    units = rollup["units_produced"]
    per_unit = rollup["cost_per_unit"]

    # Cost headline
    metrics = dbc.Row(
        [
            dbc.Col(html.Div([html.Div(_money(total), className="fw-bold fs-5 text-success"),
                              html.Div("materials cost", className="text-muted small")]), xs=4),
            dbc.Col(html.Div([html.Div(str(units) if units else "—", className="fw-bold fs-5"),
                              html.Div("units made", className="text-muted small")]), xs=4),
            dbc.Col(html.Div([html.Div(_money(per_unit) if per_unit is not None else "—",
                                       className="fw-bold fs-5 text-warning"),
                              html.Div("cost / unit", className="text-muted small")]), xs=4),
        ],
        className="text-center g-2 my-2",
    )

    # Assigned materials
    mats = rollup["materials"]
    if mats:
        mat_rows = [
            html.Tr([
                html.Td(m.get("name", "")),
                html.Td(m.get("material_type", ""), className="text-muted small"),
                html.Td(str(m.get("qty", 0)), className="text-center"),
                html.Td(_money(od.material_cost(m)), className="text-end"),
                html.Td(
                    dbc.Button(html.I(className="bi bi-x-lg"),
                               id={"type": "op-batch-remove-mat", "index": m.get("id")},
                               color="outline-danger", size="sm", className="py-0 px-1",
                               title="Remove from batch", n_clicks=0),
                    className="text-end",
                ),
            ])
            for m in mats
        ]
        mat_table = dbc.Table(
            [html.Thead(html.Tr([html.Th("Material"), html.Th("Type"),
                                 html.Th("Qty", className="text-center"),
                                 html.Th("Cost", className="text-end"), html.Th("")])),
             html.Tbody(mat_rows)],
            size="sm", striped=True, hover=True, responsive=True, className="align-middle mb-2",
        )
    else:
        mat_table = html.Div("No materials assigned yet — add some below.",
                             className="text-muted small mb-2")

    # Add-materials control
    adder = dbc.Row(
        [
            dbc.Col(
                dcc.Dropdown(id={"type": "op-batch-addsel", "index": bid},
                             options=mat_options, multi=True,
                             placeholder="Add materials to this batch…",
                             className="op-dropdown"),
                xs=12, sm=9,
            ),
            dbc.Col(
                dbc.Button([html.I(className="bi bi-plus-lg me-1"), "Add"],
                           id={"type": "op-batch-addbtn", "index": bid},
                           color="success", size="sm", className="w-100", n_clicks=0),
                xs=12, sm=3, className="mt-2 mt-sm-0",
            ),
        ],
        className="g-2",
    )

    header = html.Div(
        [
            html.Div(
                [html.Strong(b.get("name", "")),
                 html.Span(f"  ·  {b.get('product','')}" if b.get("product") else "",
                           className="text-muted"),
                 html.Span(f"  ·  {b.get('date','')}" if b.get("date") else "",
                           className="text-muted small")],
            ),
            html.Div(
                [
                    dbc.Button(html.I(className="bi bi-pencil"),
                               id={"type": "op-batch-edit", "index": bid},
                               color="outline-secondary", size="sm", className="py-0 px-2 me-1",
                               title="Edit batch", n_clicks=0),
                    dbc.Button(html.I(className="bi bi-trash"),
                               id={"type": "op-batch-del", "index": bid},
                               color="outline-danger", size="sm", className="py-0 px-2",
                               title="Delete batch", n_clicks=0),
                ],
                className="text-nowrap",
            ),
        ],
        className="d-flex align-items-center justify-content-between",
    )

    body = [metrics, mat_table, adder]
    if b.get("notes"):
        body.insert(0, html.Div(b["notes"], className="text-muted small mb-2"))

    return dbc.Card(
        [dbc.CardHeader(header), dbc.CardBody(body)],
        className="mb-3 shadow-sm",
    )


def _render_batch_list():
    bats = od.batches()
    mats = od.materials()
    if not bats:
        return dbc.Alert(
            [html.I(className="bi bi-info-circle me-2"),
             "No batches yet. Create one above, then assign the materials you ordered "
             "for it — here you'll see its total cost and cost per unit."],
            color="secondary", className="py-2",
        )
    # Options for the per-card "add materials" dropdown: every material, labelled
    # with where it currently sits so you can move one between batches.
    name_map = od.batch_name_map(bats)

    def _opt_label(m):
        bid = m.get("batch_id")
        where = f"in: {name_map.get(bid)}" if bid is not None else "unassigned"
        cost = od.material_cost(m)
        cost_s = f" · {_money(cost)}" if cost is not None else ""
        return f"{m.get('name','')} ({where}{cost_s})"

    mat_options = [{"label": _opt_label(m), "value": m.get("id")} for m in mats]
    cards = [_batch_card(od.batch_rollup(b, mats), mat_options) for b in bats]
    return html.Div(cards)


# ====================================================================
# Registration
# ====================================================================

def register_operations_callbacks(app):

    # ---------------- Materials: table + KPIs (OWNER of table.data) ----------
    @app.callback(
        Output("op-mat-table", "data"),
        Output("op-mat-table", "tooltip_data"),
        Output("op-kpi-materials", "children"),
        Output("op-kpi-spend", "children"),
        Output("op-kpi-batches", "children"),
        Output("op-kpi-perunit", "children"),
        Input("op-refresh", "data"),
        Input("op-mat-search", "value"),
        Input("op-mat-filter-type", "value"),
        Input("op-mat-filter-batch", "value"),
        Input("url", "pathname"),
        prevent_initial_call=False,
    )
    def render_materials(_refresh, search, ftype, fbatch, _path):
        mats = od.materials()
        name_map = od.batch_name_map()

        rows = od.search_materials(search, mats)
        if ftype:
            rows = [m for m in rows if m.get("material_type") == ftype]
        if fbatch is not None:
            if fbatch == -1:  # sentinel: unassigned only
                rows = [m for m in rows if m.get("batch_id") is None]
            else:
                rows = [m for m in rows if m.get("batch_id") == fbatch]

        s = od.stats()
        return (
            _build_mat_rows(rows, name_map),
            _mat_tooltips(rows),
            str(s["materials"]),
            _money(s["spend"]),
            str(s["batches"]),
            _money(s["avg_cost_per_unit"]) if s["avg_cost_per_unit"] is not None else "—",
        )

    # ---------------- Dropdown options + datalists (OWNER) -------------------
    @app.callback(
        Output("op-mat-type-datalist", "children"),
        Output("op-mat-vendor-datalist", "children"),
        Output("op-mat-filter-type", "options"),
        Output("op-mat-filter-batch", "options"),
        Output("op-mat-batch", "options"),
        Output("op-mat-bulk-batch", "options"),
        Input("op-refresh", "data"),
        Input("url", "pathname"),
        prevent_initial_call=False,
    )
    def populate_options(_refresh, _path):
        mats = od.materials()
        bats = od.batches()
        types = od.material_types(mats)
        vends = od.vendors(mats)
        batch_opts = od.batch_options(bats)
        type_opts = [{"label": t, "value": t} for t in types]
        # Filter dropdown gets an extra "unassigned" pseudo-option (sentinel -1).
        filter_batch_opts = [{"label": "⚠ Unassigned", "value": -1}] + batch_opts
        return (
            [html.Option(value=t) for t in types],
            [html.Option(value=v) for v in vends],
            type_opts,
            filter_batch_opts,
            batch_opts,
            batch_opts,
        )

    # ---------------- Material form: staged photos (OWNER of images) ---------
    @app.callback(
        Output("op-mat-images", "data"),
        Output("op-mat-gallery", "children"),
        Output("op-mat-image-upload", "contents"),
        Input("op-mat-image-upload", "contents"),
        Input({"type": "op-mat-img-remove", "index": ALL}, "n_clicks"),
        State("op-mat-image-upload", "filename"),
        State("op-mat-images", "data"),
        prevent_initial_call=True,
    )
    def stage_material_photos(contents, remove_clicks, filenames, current):
        current = list(current or [])
        trig = ctx.triggered_id
        # Remove a staged photo
        if isinstance(trig, dict) and trig.get("type") == "op-mat-img-remove":
            # Only act on a real click (added buttons fire with n_clicks=0/None).
            if not any(remove_clicks or []):
                raise PreventUpdate
            idx = trig.get("index")
            if isinstance(idx, int) and 0 <= idx < len(current):
                current.pop(idx)
            return current, _render_gallery(current), no_update
        # New upload(s)
        if not contents:
            raise PreventUpdate
        conts = contents if isinstance(contents, list) else [contents]
        names = filenames if isinstance(filenames, list) else [filenames]
        for c, fn in zip(conts, names):
            if not c:
                continue
            try:
                info = save_image(c, base_name=(fn or "material"))
                current.append(info["filename"])
            except Exception:
                continue
        # Reset the upload so re-picking the same file fires again.
        return current, _render_gallery(current), None

    # ---------------- Material form: documents + invoice parse --------------
    # OWNS attachments/doc-list/doc-status/doc-upload.contents. Auto-fills
    # vendor/date/total/order as allow_duplicate (manage_material owns those).
    @app.callback(
        Output("op-mat-attachments", "data"),
        Output("op-mat-doc-list", "children"),
        Output("op-mat-doc-status", "children"),
        Output("op-mat-doc-upload", "contents"),
        Output("op-mat-vendor", "value", allow_duplicate=True),
        Output("op-mat-date", "value", allow_duplicate=True),
        Output("op-mat-total-cost", "value", allow_duplicate=True),
        Output("op-mat-order", "value", allow_duplicate=True),
        Input("op-mat-doc-upload", "contents"),
        Input({"type": "op-mat-doc-remove", "index": ALL}, "n_clicks"),
        State("op-mat-doc-upload", "filename"),
        State("op-mat-attachments", "data"),
        State("op-mat-vendor", "value"),
        State("op-mat-date", "value"),
        State("op-mat-total-cost", "value"),
        State("op-mat-order", "value"),
        prevent_initial_call=True,
    )
    def stage_material_docs(contents, remove_clicks, filenames, current,
                            cur_vendor, cur_date, cur_total, cur_order):
        current = list(current or [])
        trig = ctx.triggered_id
        NOFILL = (no_update, no_update, no_update, no_update)

        if isinstance(trig, dict) and trig.get("type") == "op-mat-doc-remove":
            if not any(remove_clicks or []):
                raise PreventUpdate
            idx = trig.get("index")
            if isinstance(idx, int) and 0 <= idx < len(current):
                current.pop(idx)
            return (current, _render_doc_list(current), "", no_update, *NOFILL)

        if not contents:
            raise PreventUpdate
        conts = contents if isinstance(contents, list) else [contents]
        names = filenames if isinstance(filenames, list) else [filenames]

        parsed_all = {}
        added = 0
        for c, fn in zip(conts, names):
            if not c:
                continue
            try:
                meta = save_attachment(c, fn or "attachment")
            except Exception:
                continue
            current.append(meta)
            added += 1
            # Best-effort: read the invoice/receipt text and pull purchase fields.
            try:
                text = read_attachment_text(meta["filename"])
                if text:
                    got = invoice_parse.extract_purchase(text)
                    for k, v in got.items():
                        if k != "found" and v and not parsed_all.get(k):
                            parsed_all[k] = v
            except Exception:
                pass

        # Only fill fields the user left blank — never clobber typed values.
        def _fill(cur, key):
            return parsed_all.get(key) if (not (cur or "").strip() and parsed_all.get(key)) else no_update

        new_vendor = _fill(cur_vendor, "seller")
        new_date = _fill(cur_date, "purchase_date")
        new_total = _fill(cur_total, "price_paid")
        new_order = _fill(cur_order, "order_number")

        filled = [k for k, val in (("vendor", new_vendor), ("date", new_date),
                                   ("total", new_total), ("order#", new_order))
                  if val is not no_update]
        status = html.Span(
            [html.I(className="bi bi-check-circle me-1"),
             f"Attached {added} file(s)." + (f" Read: {', '.join(filled)}." if filled else "")],
            className="text-success",
        )
        return (current, _render_doc_list(current), status, None,
                new_vendor, new_date, new_total, new_order)

    # ---------------- Material form + table lifecycle (BIG owner) -----------
    @app.callback(
        Output("op-mat-table", "selected_rows"),
        Output("op-mat-name", "value"),
        Output("op-mat-type", "value"),
        Output("op-mat-vendor", "value"),
        Output("op-mat-batch", "value"),
        Output("op-mat-new-batch", "value"),
        Output("op-mat-qty", "value"),
        Output("op-mat-unit-cost", "value"),
        Output("op-mat-total-cost", "value"),
        Output("op-mat-order", "value"),
        Output("op-mat-date", "value"),
        Output("op-mat-desc", "value"),
        Output("op-mat-specs", "value"),
        Output("op-mat-tags", "value"),
        Output("op-mat-images", "data", allow_duplicate=True),
        Output("op-mat-gallery", "children", allow_duplicate=True),
        Output("op-mat-attachments", "data", allow_duplicate=True),
        Output("op-mat-doc-list", "children", allow_duplicate=True),
        Output("op-mat-image-upload", "contents", allow_duplicate=True),
        Output("op-mat-doc-upload", "contents", allow_duplicate=True),
        Output("op-editing-mat", "data"),
        Output("op-mat-form-collapse", "is_open"),
        Output("op-mat-form-badge", "children"),
        Output("op-mat-delete", "disabled"),
        Output("op-refresh", "data"),
        Output("op-toast", "is_open"),
        Output("op-toast", "header"),
        Output("op-toast", "icon"),
        Output("op-toast", "children"),
        Input("op-mat-add-toggle", "n_clicks"),
        Input("op-mat-save", "n_clicks"),
        Input("op-mat-delete", "n_clicks"),
        Input("op-mat-cancel", "n_clicks"),
        Input("op-mat-table", "selected_rows"),
        State("op-mat-table", "data"),
        State("op-editing-mat", "data"),
        State("op-mat-form-collapse", "is_open"),
        State("op-mat-name", "value"),
        State("op-mat-type", "value"),
        State("op-mat-vendor", "value"),
        State("op-mat-batch", "value"),
        State("op-mat-new-batch", "value"),
        State("op-mat-qty", "value"),
        State("op-mat-unit-cost", "value"),
        State("op-mat-total-cost", "value"),
        State("op-mat-order", "value"),
        State("op-mat-date", "value"),
        State("op-mat-desc", "value"),
        State("op-mat-specs", "value"),
        State("op-mat-tags", "value"),
        State("op-mat-images", "data"),
        State("op-mat-attachments", "data"),
        prevent_initial_call=True,
    )
    def manage_material(add_n, save_n, del_n, cancel_n, sel_rows, table_data,
                        editing_id, form_open, name, mtype, vendor, batch_val, new_batch,
                        qty, unit_cost, total_cost, order, pdate, desc, specs, tags,
                        images, attachments):
        trig = ctx.triggered_id

        # Defaults: leave everything untouched (selected_rows re-enters this
        # callback, so a blanket reset would flicker the toast/form).
        NU = no_update
        out = {
            "sel": NU, "name": NU, "type": NU, "vendor": NU, "batch": NU, "newbatch": NU,
            "qty": NU, "unit": NU, "total": NU, "order": NU, "date": NU, "desc": NU,
            "specs": NU, "tags": NU, "images": NU, "gallery": NU, "atts": NU,
            "doclist": NU, "imgup": NU, "docup": NU, "editing": NU, "open": NU,
            "badge": NU, "del_disabled": NU, "refresh": NU,
            "toast_open": NU, "toast_hdr": NU, "toast_icon": NU, "toast_msg": NU,
        }

        def _clear(keep_group=False):
            out["sel"] = []
            out["name"] = ""
            if not keep_group:
                out["type"] = ""
                out["batch"] = None
            out["vendor"] = "" if not keep_group else NU
            out["newbatch"] = ""
            out["qty"] = 1
            out["unit"], out["total"], out["order"], out["date"] = "", "", "", ""
            out["desc"], out["specs"], out["tags"] = "", "", ""
            out["images"], out["gallery"] = [], _render_gallery([])
            out["atts"], out["doclist"] = [], _render_doc_list([])
            out["imgup"], out["docup"] = None, None
            out["editing"] = None
            out["del_disabled"] = True
            out["badge"] = "New"

        def _bump():
            # Distinct token each time so downstream reload callbacks always fire.
            out["refresh"] = (save_n or 0) + (del_n or 0) + (add_n or 0) + 1

        def _toast(hdr, icon, msg):
            out["toast_open"], out["toast_hdr"], out["toast_icon"], out["toast_msg"] = \
                True, hdr, icon, msg

        # ---- Add: open a clean form ----
        if trig == "op-mat-add-toggle":
            if form_open:
                out["open"] = False
            else:
                _clear()
                out["open"] = True
            return _pack(out)

        # ---- Cancel: close + reclaim any orphaned staged assets ----
        if trig == "op-mat-cancel":
            _clear()
            out["open"] = False
            _safe_prune()
            return _pack(out)

        # ---- Delete ----
        if trig == "op-mat-delete":
            if editing_id:
                removed = od.remove_material(editing_id)
                if removed:
                    _toast("Material deleted", "danger", f'"{removed.get("name","")}" removed.')
                _clear()
                out["open"] = False
                _safe_prune()
                _bump()
            return _pack(out)

        # ---- Save (create or update) ----
        if trig == "op-mat-save":
            nm = (name or "").strip()
            has_photo = bool(images)
            if not nm and not has_photo and not editing_id:
                _toast("Add a name or photo", "warning", "Type a name or add a photo first.")
                return _pack(out)
            # Resolve batch: a typed new-batch name wins and is created on the fly.
            bid = od._safe_id(batch_val)
            nb = (new_batch or "").strip()
            if nb:
                created = od.find_or_create_batch(nb)
                if created:
                    bid = created.get("id")
            common = dict(
                material_type=mtype, batch_id=bid, vendor=vendor, qty=qty,
                unit_cost=unit_cost, total_cost=total_cost, order_number=order,
                purchase_date=pdate, description=desc, specifications=specs, tags=tags,
                images=list(images or []), attachments=list(attachments or []),
            )
            try:
                if editing_id:
                    # Omit name when blank so the existing name is preserved (_KEEP).
                    if nm:
                        common["name"] = nm
                    od.update_material(editing_id, **common)
                    _toast("Material updated", "success", f'"{nm or "Material"}" saved.')
                else:
                    created = od.add_material(name=nm, **common)
                    _toast("Material added", "success", f'"{created.get("name")}" added.')
            except Exception as e:  # pragma: no cover - defensive
                _toast("Couldn't save", "danger", str(e))
                return _pack(out)
            # Keep type + batch sticky so a run of materials for one batch is fast.
            _clear(keep_group=True)
            out["open"] = True
            _bump()
            return _pack(out)

        # ---- Row selection: 1 -> load for edit; 2+ -> leave form (bulk bar) ----
        if trig == "op-mat-table":
            if sel_rows and len(sel_rows) == 1:
                idx = sel_rows[0]
                trows = table_data or []
                if isinstance(idx, int) and 0 <= idx < len(trows):
                    rid = trows[idx].get("id")
                    m = od.get_material(rid) or {}
                    out.update({
                        "name": m.get("name", ""), "type": m.get("material_type", ""),
                        "vendor": m.get("vendor", ""), "batch": m.get("batch_id"),
                        "newbatch": "", "qty": m.get("qty", 1),
                        "unit": m.get("unit_cost", ""), "total": m.get("total_cost", ""),
                        "order": m.get("order_number", ""), "date": m.get("purchase_date", ""),
                        "desc": m.get("description", ""),
                        "specs": _specs_to_text(m.get("specifications", [])),
                        "tags": _tags_to_text(m.get("tags", [])),
                        "images": list(m.get("images", [])),
                        "gallery": _render_gallery(m.get("images", [])),
                        "atts": list(m.get("attachments", [])),
                        "doclist": _render_doc_list(m.get("attachments", [])),
                        "imgup": None, "docup": None,
                        "editing": rid, "open": True, "badge": "Editing",
                        "del_disabled": False,
                    })
            return _pack(out)

        return _pack(out)

    # ---------------- Bulk assign / unassign / delete ----------------------
    @app.callback(
        Output("op-refresh", "data", allow_duplicate=True),
        Output("op-mat-table", "selected_rows", allow_duplicate=True),
        Output("op-toast", "is_open", allow_duplicate=True),
        Output("op-toast", "header", allow_duplicate=True),
        Output("op-toast", "icon", allow_duplicate=True),
        Output("op-toast", "children", allow_duplicate=True),
        Input("op-mat-bulk-apply", "n_clicks"),
        Input("op-mat-bulk-unassign", "n_clicks"),
        Input("op-mat-bulk-delete", "n_clicks"),
        State("op-mat-table", "selected_rows"),
        State("op-mat-table", "data"),
        State("op-mat-bulk-batch", "value"),
        prevent_initial_call=True,
    )
    def bulk_actions(apply_n, unassign_n, delete_n, sel_rows, table_data, bulk_batch):
        trig = ctx.triggered_id
        trows = table_data or []
        ids = [trows[i].get("id") for i in (sel_rows or [])
               if isinstance(i, int) and 0 <= i < len(trows)]
        ids = [i for i in ids if i is not None]
        if not ids:
            raise PreventUpdate
        token = (apply_n or 0) + (unassign_n or 0) + (delete_n or 0) + 1
        if trig == "op-mat-bulk-apply":
            if bulk_batch is None:
                return no_update, no_update, True, "Pick a batch", "warning", \
                    "Choose a batch to assign to."
            n = od.set_materials_batch(ids, bulk_batch)
            name = od.batch_name_map().get(od._safe_id(bulk_batch), "batch")
            return token, [], True, "Assigned", "success", f'{n} material(s) → "{name}".'
        if trig == "op-mat-bulk-unassign":
            n = od.set_materials_batch(ids, None)
            return token, [], True, "Unassigned", "secondary", f"{n} material(s) unassigned."
        if trig == "op-mat-bulk-delete":
            for i in ids:
                od.remove_material(i)
            _safe_prune()
            return token, [], True, "Deleted", "danger", f"{len(ids)} material(s) deleted."
        raise PreventUpdate

    # ---------------- Bulk bar visibility ----------------------------------
    @app.callback(
        Output("op-mat-bulk-collapse", "is_open"),
        Output("op-mat-bulk-label", "children"),
        Input("op-mat-table", "selected_rows"),
        prevent_initial_call=True,
    )
    def toggle_bulk_bar(sel_rows):
        n = len(sel_rows or [])
        if n >= 2:
            return True, f"{n} selected"
        return False, ""

    # ---------------- Photo modal (open from table) ------------------------
    @app.callback(
        Output("op-image-modal", "is_open"),
        Output("op-image-modal-title", "children"),
        Output("op-image-carousel", "items"),
        Output("op-image-modal-fullres", "children"),
        Input("op-mat-table", "active_cell"),
        State("op-mat-table", "data"),
        prevent_initial_call=True,
    )
    def open_image_modal(cell, rows):
        if not cell or cell.get("column_id") != "image":
            raise PreventUpdate
        row = None
        rid = cell.get("row_id")
        if rid is not None:
            row = next((r for r in (rows or []) if str(r.get("id")) == str(rid)), None)
        else:
            i = cell.get("row")
            if i is not None and 0 <= i < len(rows or []):
                row = rows[i]
        if not row:
            raise PreventUpdate
        previews = row.get("all_previews") or row.get("all_images") or []
        originals = row.get("all_images") or []
        if not previews:
            raise PreventUpdate
        items = [{"key": str(i), "src": u,
                  "img_style": {"maxHeight": "70vh", "objectFit": "contain"}}
                 for i, u in enumerate(previews)]
        return True, row.get("name", ""), items, _fullres_links(originals)

    @app.callback(
        Output("op-image-modal", "is_open", allow_duplicate=True),
        Input("op-close-image-modal", "n_clicks"),
        prevent_initial_call=True,
    )
    def close_image_modal(_n):
        return False

    # ---------------- CSV export -------------------------------------------
    @app.callback(
        Output("op-mat-download", "data"),
        Input("op-mat-export", "n_clicks"),
        prevent_initial_call=True,
    )
    def export_csv(_n):
        mats = od.materials()
        name_map = od.batch_name_map()
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id", "name", "type", "batch", "vendor", "qty", "unit_cost",
                    "total_cost", "computed_cost", "order_number", "purchase_date",
                    "description", "specifications", "tags", "created_at"])
        for m in mats:
            bid = m.get("batch_id")
            w.writerow([
                m.get("id"), m.get("name", ""), m.get("material_type", ""),
                name_map.get(bid, "") if bid is not None else "", m.get("vendor", ""),
                m.get("qty", 0), m.get("unit_cost", ""), m.get("total_cost", ""),
                od.material_cost(m) if od.material_cost(m) is not None else "",
                m.get("order_number", ""), m.get("purchase_date", ""),
                m.get("description", ""), "; ".join(m.get("specifications") or []),
                ", ".join(m.get("tags") or []), m.get("created_at", ""),
            ])
        return dcc.send_string(buf.getvalue(), "materials.csv")

    # ====================  BATCHES  ====================================

    # ---------------- Render batch cards (OWNER) ---------------------------
    @app.callback(
        Output("op-batch-list", "children"),
        Input("op-refresh", "data"),
        Input("op-tabs", "active_tab"),
        Input("url", "pathname"),
        prevent_initial_call=False,
    )
    def render_batches(_refresh, _tab, _path):
        return _render_batch_list()

    # ---------------- Batch form: create / edit / cancel -------------------
    @app.callback(
        Output("op-batch-name", "value"),
        Output("op-batch-product", "value"),
        Output("op-batch-units", "value"),
        Output("op-batch-date", "value"),
        Output("op-batch-notes", "value"),
        Output("op-editing-batch", "data"),
        Output("op-batch-form-badge", "children"),
        Output("op-refresh", "data", allow_duplicate=True),
        Output("op-toast", "is_open", allow_duplicate=True),
        Output("op-toast", "header", allow_duplicate=True),
        Output("op-toast", "icon", allow_duplicate=True),
        Output("op-toast", "children", allow_duplicate=True),
        Input("op-batch-save", "n_clicks"),
        Input("op-batch-cancel", "n_clicks"),
        Input({"type": "op-batch-edit", "index": ALL}, "n_clicks"),
        State("op-editing-batch", "data"),
        State("op-batch-name", "value"),
        State("op-batch-product", "value"),
        State("op-batch-units", "value"),
        State("op-batch-date", "value"),
        State("op-batch-notes", "value"),
        prevent_initial_call=True,
    )
    def manage_batch(save_n, cancel_n, edit_clicks, editing_id,
                     name, product, units, date, notes):
        trig = ctx.triggered_id
        blank = ("", "", None, "", "", None, "New")

        # Edit button on a card -> load that batch into the form.
        if isinstance(trig, dict) and trig.get("type") == "op-batch-edit":
            if not any(edit_clicks or []):
                raise PreventUpdate
            b = od.get_batch(trig.get("index")) or {}
            return (b.get("name", ""), b.get("product", ""), b.get("units_produced", 0),
                    b.get("date", ""), b.get("notes", ""), b.get("id"), "Editing",
                    no_update, no_update, no_update, no_update, no_update)

        if trig == "op-batch-cancel":
            return (*blank, no_update, no_update, no_update, no_update, no_update)

        if trig == "op-batch-save":
            nm = (name or "").strip()
            if not nm:
                return (no_update,) * 7 + (no_update, True, "Name required", "warning",
                                           "Give the batch a name.")
            token = (save_n or 0) + 1
            if editing_id:
                od.update_batch(editing_id, name=nm, product=product,
                                units_produced=units, date=date, notes=notes)
                msg = f'Batch "{nm}" updated.'
            else:
                od.add_batch(nm, product=product, units_produced=units, date=date, notes=notes)
                msg = f'Batch "{nm}" created.'
            return (*blank, token, True, "Saved", "success", msg)

        raise PreventUpdate

    # ---------------- Batch delete -----------------------------------------
    @app.callback(
        Output("op-refresh", "data", allow_duplicate=True),
        Output("op-toast", "is_open", allow_duplicate=True),
        Output("op-toast", "header", allow_duplicate=True),
        Output("op-toast", "icon", allow_duplicate=True),
        Output("op-toast", "children", allow_duplicate=True),
        Input({"type": "op-batch-del", "index": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def delete_batch(clicks):
        trig = ctx.triggered_id
        if not isinstance(trig, dict) or not any(clicks or []):
            raise PreventUpdate
        removed = od.remove_batch(trig.get("index"))
        if not removed:
            raise PreventUpdate
        token = sum(c or 0 for c in clicks) + 1
        return (token, True, "Batch deleted", "danger",
                f'"{removed.get("name","")}" deleted — its materials were unassigned.')

    # ---------------- Remove a material from its batch ---------------------
    @app.callback(
        Output("op-refresh", "data", allow_duplicate=True),
        Output("op-toast", "is_open", allow_duplicate=True),
        Output("op-toast", "header", allow_duplicate=True),
        Output("op-toast", "icon", allow_duplicate=True),
        Output("op-toast", "children", allow_duplicate=True),
        Input({"type": "op-batch-remove-mat", "index": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def remove_from_batch(clicks):
        trig = ctx.triggered_id
        if not isinstance(trig, dict) or not any(clicks or []):
            raise PreventUpdate
        n = od.set_materials_batch([trig.get("index")], None)
        if not n:
            raise PreventUpdate
        token = sum(c or 0 for c in clicks) + 1
        return token, True, "Removed", "secondary", "Material removed from batch."

    # ---------------- Add materials to a batch -----------------------------
    @app.callback(
        Output("op-refresh", "data", allow_duplicate=True),
        Output("op-toast", "is_open", allow_duplicate=True),
        Output("op-toast", "header", allow_duplicate=True),
        Output("op-toast", "icon", allow_duplicate=True),
        Output("op-toast", "children", allow_duplicate=True),
        Input({"type": "op-batch-addbtn", "index": ALL}, "n_clicks"),
        State({"type": "op-batch-addsel", "index": ALL}, "value"),
        State({"type": "op-batch-addsel", "index": ALL}, "id"),
        prevent_initial_call=True,
    )
    def add_to_batch(clicks, sel_values, sel_ids):
        trig = ctx.triggered_id
        if not isinstance(trig, dict) or not any(clicks or []):
            raise PreventUpdate
        bid = trig.get("index")
        # Find the multiselect value that belongs to the clicked card.
        chosen = []
        for val, cid in zip(sel_values or [], sel_ids or []):
            if isinstance(cid, dict) and cid.get("index") == bid:
                chosen = val or []
                break
        chosen = [c for c in chosen if c is not None]
        if not chosen:
            return no_update, True, "Nothing selected", "warning", \
                "Pick materials to add first."
        n = od.set_materials_batch(chosen, bid)
        token = sum(c or 0 for c in clicks) + 1
        name = od.batch_name_map().get(od._safe_id(bid), "batch")
        return token, True, "Added", "success", f'{n} material(s) → "{name}".'


# --------------------------------------------------------------------
# Module-level utilities used above
# --------------------------------------------------------------------

# The output order of ``manage_material``'s return, matching its Output list.
_MANAGE_KEYS = [
    "sel", "name", "type", "vendor", "batch", "newbatch", "qty", "unit", "total",
    "order", "date", "desc", "specs", "tags", "images", "gallery", "atts",
    "doclist", "imgup", "docup", "editing", "open", "badge", "del_disabled",
    "refresh", "toast_open", "toast_hdr", "toast_icon", "toast_msg",
]


def _pack(out: dict):
    return [out[k] for k in _MANAGE_KEYS]


def _safe_prune():
    """Reclaim orphaned shared assets after a delete/cancel. Never raises."""
    try:
        data.prune_unreferenced_images()
        data.prune_unreferenced_documents()
    except Exception:
        pass
