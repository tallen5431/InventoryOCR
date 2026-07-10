"""Callbacks for the Price Compare page."""
from __future__ import annotations
import base64

from dash import html, dcc, Input, Output, State, no_update, ctx, ALL
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc

import price_compare as pc
import data


# --------------------------------------------------------------------
# Rendering helpers
# --------------------------------------------------------------------

def _money(v, cur="$"):
    return f"{cur}{v:,.2f}" if isinstance(v, (int, float)) else "—"


def _unit_money(v, cur="$"):
    if not isinstance(v, (int, float)):
        return "—"
    # Show enough precision for cheap per-unit prices without trailing noise.
    return f"{cur}{v:.4f}".rstrip("0").rstrip(".") if v < 1 else f"{cur}{v:,.2f}"


def _decode_upload(contents: str) -> str:
    try:
        if contents and "," in contents:
            return base64.b64decode(contents.split(",", 1)[1]).decode("utf-8", "replace")
    except Exception:
        pass
    return ""


def _best_banner(res):
    best = res.get("best")
    n = len([p for p in res.get("products", []) if p.get("unit_price") is not None])
    if not best or n == 0:
        return html.Div()
    cur = best.get("currency", "$")
    parts = [
        html.I(className="bi bi-trophy-fill me-2"),
        html.Strong(f"Best value: {best['name']}"),
        html.Span(
            f"  —  {_unit_money(best['unit_price'], cur)} per {best.get('unit', 'each')}"
            f"  ({_money(best.get('price_value'), cur)} for {best.get('quantity', 1)})",
        ),
    ]
    if best.get("matched_item_name"):
        parts.append(html.Span([" · ", html.I(className="bi bi-box-seam me-1"),
                                 f"you have: {best['matched_item_name']}"], className="ms-1"))
    return html.Div(parts, className="alert alert-success py-2 mb-2")


def _comparison_table(res):
    products = res.get("products", [])
    if not products:
        return html.Div("Upload a few product pages, then Compare.", className="text-muted")

    header = html.Thead(html.Tr([
        html.Th("#"), html.Th("Product"), html.Th("Pack qty", className="text-end"),
        html.Th("Price", className="text-end"), html.Th("Per unit", className="text-end"),
        html.Th("In inventory"), html.Th(""),
    ]))
    rows = []
    for i, p in enumerate(products):
        cur = p.get("currency", "$")
        best = p.get("best")
        name_cell = [html.Div(p["name"], className="fw-semibold"),
                     html.Div(p.get("source", ""), className="text-muted small")]
        matched = (html.Span([html.I(className="bi bi-check-circle-fill me-1"),
                              p["matched_item_name"]], className="text-success small")
                   if p.get("matched_item_name") else html.Span("—", className="text-muted"))
        link = (html.A(html.I(className="bi bi-box-arrow-up-right"), href=p["url"],
                       target="_blank", rel="noopener noreferrer", title="Open listing")
                if p.get("url") else "")
        rank = html.Span("🏆", title="Best price per unit") if best else str(i + 1)
        # Editable pack size — correct a mis-detected count and Recalculate.
        qty_cell = dbc.Input(id={"type": "pc-qty", "index": i}, type="number",
                             min=1, step=1, value=p.get("quantity", 1),
                             size="sm", style={"width": "72px", "display": "inline-block"},
                             className="text-end")
        rows.append(html.Tr(
            [
                html.Td(rank),
                html.Td(name_cell),
                html.Td(qty_cell, className="text-end text-nowrap"),
                html.Td(_money(p.get("price_value"), cur), className="text-end text-nowrap"),
                html.Td(html.Strong(_unit_money(p.get("unit_price"), cur)),
                        className="text-end text-nowrap"),
                html.Td(matched),
                html.Td(link, className="text-end"),
            ],
            className=("table-success" if best else ""),
        ))
    table = dbc.Table([header, html.Tbody(rows)], striped=True, hover=True,
                      responsive=True, className="align-middle pc-compare-table")
    recalc = html.Div(
        dbc.Button([html.I(className="bi bi-arrow-repeat me-1"), "Recalculate after editing pack sizes"],
                   id="pc-recalc", color="outline-secondary", size="sm", n_clicks=0),
        className="mt-1",
    )
    return html.Div([table, recalc])


def _sparkline(points, cur="$"):
    """Tiny inline SVG line of best-unit-price over time (themes via currentColor)."""
    vals = [pt["best_unit_price"] for pt in points if pt.get("best_unit_price") is not None]
    if len(vals) < 2:
        return html.Div()
    w, h, pad = 260, 48, 6
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    n = len(vals)
    coords = []
    for i, v in enumerate(vals):
        x = pad + (w - 2 * pad) * (i / (n - 1))
        y = pad + (h - 2 * pad) * (1 - (v - lo) / rng)  # lower price = higher on chart
        coords.append((x, y))
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    last_x, last_y = coords[-1]
    return html.Div(
        dcc.Markdown(  # inline SVG through markdown keeps it dependency-free
            f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'style="max-width:100%;color:#0d6efd">'
            f'<polyline fill="none" stroke="currentColor" stroke-width="2" points="{pts}"/>'
            f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="3" fill="currentColor"/>'
            f"</svg>",
            dangerously_allow_html=True,
        ),
        className="mb-1",
    )


def _matched_best(products):
    """Best (lowest unit-price) listing per matched inventory item id."""
    best = {}
    for p in products or []:
        mid = p.get("matched_item_id")
        up = p.get("unit_price")
        if mid is None or up is None:
            continue
        cur = best.get(mid)
        if cur is None or up < cur["unit_price"]:
            best[mid] = p
    return best


def _writeback_bar(res):
    """Offer to write the best unit price + link onto matched inventory items."""
    matched = _matched_best(res.get("products", []))
    if not matched:
        return html.Div()
    n = len(matched)
    return dbc.Alert(
        [
            html.I(className="bi bi-box-seam me-2"),
            html.Span(f"{n} of these match item(s) already in your inventory. "),
            dbc.Button([html.I(className="bi bi-tag me-1"),
                        f"Save best price to {n} item{'s' if n != 1 else ''}"],
                       id="pc-writeback-apply", color="success", size="sm", className="ms-2"),
            html.Div(id="pc-writeback-status", className="small mt-1"),
        ],
        color="secondary", className="py-2 mt-2",
    )


def _history_view(search):
    if not search:
        return html.Div("Pick a saved search to see its price history.", className="text-muted")
    series = pc.history_series(search)
    if not series:
        return html.Div("No snapshots yet — save a comparison under this name.", className="text-muted")
    cur = series[-1].get("currency", "$")
    first, last = series[0], series[-1]
    delta = None
    if (first.get("best_unit_price") is not None and last.get("best_unit_price") is not None):
        delta = last["best_unit_price"] - first["best_unit_price"]

    trend = html.Div()
    if delta is not None and len(series) > 1:
        if delta < 0:
            trend = html.Span([html.I(className="bi bi-arrow-down-right me-1"),
                               f"down {_unit_money(abs(delta), cur)} since {first['date']}"],
                              className="text-success")
        elif delta > 0:
            trend = html.Span([html.I(className="bi bi-arrow-up-right me-1"),
                               f"up {_unit_money(delta, cur)} since {first['date']}"],
                              className="text-danger")
        else:
            trend = html.Span("no change", className="text-muted")

    head = html.Thead(html.Tr([
        html.Th("Date"), html.Th("Options", className="text-end"),
        html.Th("Best / unit", className="text-end"), html.Th("Best pick"),
    ]))
    body_rows = []
    for s in reversed(series):  # newest first
        body_rows.append(html.Tr([
            html.Td(s["date"]),
            html.Td(str(s.get("count", 0)), className="text-end"),
            html.Td(html.Strong(_unit_money(s.get("best_unit_price"), s.get("currency", "$"))),
                    className="text-end"),
            html.Td(html.Span(s.get("best_name", ""), className="small")),
        ]))
    return html.Div([
        html.Div([html.Strong(search.get("label", "")),
                  html.Span(f"  ·  {len(series)} run(s)  ·  ", className="text-muted"),
                  trend], className="mb-2"),
        _sparkline(series, cur),
        dbc.Table([head, html.Tbody(body_rows)], striped=True, hover=True,
                  size="sm", responsive=True, className="align-middle"),
    ])


# --------------------------------------------------------------------
# Callback registration
# --------------------------------------------------------------------

def register_price_compare_callbacks(app):

    # ---- Show which files are staged before compare ----
    @app.callback(
        Output("pc-filelist", "children"),
        Input("pc-upload", "filename"),
        prevent_initial_call=True,
    )
    def show_files(filenames):
        names = filenames if isinstance(filenames, list) else ([filenames] if filenames else [])
        names = [n for n in names if n]
        if not names:
            return ""
        return html.Span([html.I(className="bi bi-paperclip me-1"),
                          f"{len(names)} file(s): " + ", ".join(names[:6]) +
                          ("…" if len(names) > 6 else "")], className="text-muted")

    # ---- Run the comparison ----
    @app.callback(
        Output("pc-results", "data"),
        Output("pc-table", "children"),
        Output("pc-best", "children"),
        Output("pc-errors", "children"),
        Output("pc-status", "children"),
        Output("pc-name", "value"),
        Output("pc-writeback", "children"),
        Input("pc-compare", "n_clicks"),
        State("pc-upload", "contents"),
        State("pc-upload", "filename"),
        State("pc-name", "value"),
        prevent_initial_call=True,
    )
    def do_compare(n, contents, filenames, current_name):
        if not n:
            raise PreventUpdate
        contents = contents if isinstance(contents, list) else ([contents] if contents else [])
        filenames = filenames if isinstance(filenames, list) else ([filenames] if filenames else [])
        if not contents:
            return no_update, no_update, no_update, no_update, \
                html.Span("Drop at least one .html file first.", className="text-warning"), \
                no_update, no_update

        files = []
        for c, fn in zip(contents, filenames):
            text = _decode_upload(c)
            if text.strip():
                files.append((fn or "page.html", text))

        if not files:
            return no_update, no_update, no_update, no_update, \
                html.Span("Couldn't read those files.", className="text-warning"), \
                no_update, no_update

        res = pc.analyze_htmls(files)
        errbox = html.Div()
        if res["errors"]:
            errbox = dbc.Alert(
                [html.Strong(f"{len(res['errors'])} page(s) couldn't be read:"),
                 html.Ul([html.Li(f"{e['source']}: {e['error']}") for e in res["errors"]],
                         className="mb-0 mt-1 small")],
                color="warning", className="py-2",
            )
        ok = len(res["products"])
        status = html.Span([html.I(className="bi bi-check-circle me-1"),
                            f"Compared {ok} product(s)."], className="text-success")
        name = (current_name or "").strip() or pc.suggest_label(res["products"])
        return res, _comparison_table(res), _best_banner(res), errbox, status, name, _writeback_bar(res)

    # ---- Recompute after the user corrects a pack size ----
    @app.callback(
        Output("pc-results", "data", allow_duplicate=True),
        Output("pc-table", "children", allow_duplicate=True),
        Output("pc-best", "children", allow_duplicate=True),
        Output("pc-writeback", "children", allow_duplicate=True),
        Input("pc-recalc", "n_clicks"),
        State({"type": "pc-qty", "index": ALL}, "value"),
        State("pc-results", "data"),
        prevent_initial_call=True,
    )
    def recalc(n, qtys, results):
        if not n or not results:
            raise PreventUpdate
        products = results.get("products", [])
        # Map each pack-size input back to its product by index.
        qmap = {s["id"]["index"]: s.get("value") for s in (ctx.states_list[0] or [])}
        for i, p in enumerate(products):
            q = qmap.get(i)
            try:
                q = int(q)
            except (TypeError, ValueError):
                q = p.get("quantity", 1)
            q = max(1, q)
            p["quantity"] = q
            pv = p.get("price_value")
            p["unit_price"] = round(pv / q, 4) if pv is not None else None
        ranked = pc._rank(products)
        res = {**results, "products": ranked,
               "best": next((p for p in ranked if p.get("best")), None)}
        return res, _comparison_table(res), _best_banner(res), _writeback_bar(res)

    # ---- Save the current comparison as a dated snapshot ----
    @app.callback(
        Output("pc-save-status", "children"),
        Output("pc-saved-refresh", "data"),
        Input("pc-save", "n_clicks"),
        State("pc-name", "value"),
        State("pc-results", "data"),
        prevent_initial_call=True,
    )
    def save_snapshot(n, name, results):
        if not n:
            raise PreventUpdate
        products = (results or {}).get("products", [])
        if not products:
            return html.Span("Run a comparison before saving.", className="text-warning"), no_update
        search = pc.save_snapshot(name or "", products)
        runs = len(search.get("snapshots", []))
        msg = html.Span([html.I(className="bi bi-check-circle me-1"),
                         f'Saved to "{search["label"]}" ({runs} run{"s" if runs != 1 else ""}).'],
                        className="text-success")
        return msg, search["id"]

    # ---- Write the best price + link back onto matched inventory items ----
    @app.callback(
        Output("pc-writeback-status", "children"),
        Input("pc-writeback-apply", "n_clicks"),
        State("pc-results", "data"),
        prevent_initial_call=True,
    )
    def apply_writeback(n, results):
        if not n:
            raise PreventUpdate
        matched = _matched_best((results or {}).get("products", []))
        if not matched:
            return html.Span("No matched items to update.", className="text-warning")
        updated = 0
        for mid, p in matched.items():
            val = _unit_money(p.get("unit_price"), p.get("currency", "$"))
            url = (p.get("url") or "").strip() or None
            if data.update_item_fields(mid, estimated_value=val, product_url=url) is not None:
                updated += 1
        return html.Span([html.I(className="bi bi-check-circle me-1"),
                          f"Updated {updated} item{'s' if updated != 1 else ''} with best unit price."],
                         className="text-success")

    # ---- Populate / refresh the saved-search dropdown ----
    @app.callback(
        Output("pc-saved-select", "options"),
        Output("pc-saved-select", "value"),
        Input("pc-saved-refresh", "data"),
        Input("url", "pathname"),
        State("pc-saved-select", "value"),
        prevent_initial_call=False,
    )
    def refresh_saved(refresh_id, _path, current):
        opts = pc.label_options()
        # Prefer a just-saved search, else keep the current selection if still valid.
        valid = {o["value"] for o in opts}
        if ctx.triggered_id == "pc-saved-refresh" and refresh_id in valid:
            return opts, refresh_id
        value = current if current in valid else (opts[0]["value"] if opts else None)
        return opts, value

    # ---- Render the selected search's price history ----
    @app.callback(
        Output("pc-history", "children"),
        Input("pc-saved-select", "value"),
        prevent_initial_call=False,
    )
    def show_history(sid):
        if not sid:
            return html.Div("Save a comparison to start tracking prices over time.",
                            className="text-muted")
        return _history_view(pc.get_search(sid))

    # ---- Delete a tracked search ----
    @app.callback(
        Output("pc-saved-refresh", "data", allow_duplicate=True),
        Output("pc-save-status", "children", allow_duplicate=True),
        Input("pc-delete", "n_clicks"),
        State("pc-saved-select", "value"),
        prevent_initial_call=True,
    )
    def delete_saved(n, sid):
        if not n or not sid:
            raise PreventUpdate
        pc.delete_search(sid)
        # Return a distinct token so refresh_saved re-reads and picks a new default.
        return f"deleted:{sid}", html.Span("Deleted.", className="text-muted")
