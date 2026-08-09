"""Callbacks for the scanned-label page (``/i/<code>``).

Two edits, both the kind you make standing at a shelf: correct the count, or
record that the item now lives somewhere else. Everything else on that page is
a link back into the full app.

Each callback acts on the code stored *in the rendered layout*, not on the URL,
so a stale browser tab can never write to whatever item the address bar happens
to show now.
"""
from __future__ import annotations

from dash import html, Input, Output, State, ctx, no_update
from dash.exceptions import PreventUpdate

import data


def _status(ok: bool, message: str):
    icon = "bi-check-circle-fill" if ok else "bi-exclamation-triangle-fill"
    tone = "text-success" if ok else "text-danger"
    return html.Span([html.I(className=f"bi {icon} me-1"), message], className=tone)


def register_scan_callbacks(app):

    # ---------- Quantity: one fewer / one more --------------------------
    @app.callback(
        Output("scan-qty-value", "children"),
        Output("scan-status", "children"),
        Input("scan-qty-dec", "n_clicks"),
        Input("scan-qty-inc", "n_clicks"),
        State("scan-code", "data"),
        State("scan-qty-value", "children"),
        prevent_initial_call=True,
    )
    def step_qty(dec, inc, code, shown):
        trig = ctx.triggered_id
        if trig not in ("scan-qty-dec", "scan-qty-inc"):
            raise PreventUpdate
        # Re-read rather than trusting the number on screen: the page may have
        # been open for hours, or another device may have changed it.
        item = data.item_by_code(code)
        if not item:
            return no_update, _status(False, "That item no longer exists.")
        step = 1 if trig == "scan-qty-inc" else -1
        new_qty = max(0, int(item.get("qty") or 0) + step)
        if new_qty == int(item.get("qty") or 0):
            # Already at zero and going down — say so rather than silently no-op.
            return str(new_qty), _status(False, "Already at zero.")
        saved = data.update_item_fields(item["id"], qty=new_qty)
        if saved is None:
            return no_update, _status(False, "Couldn't save — the item may have been deleted.")
        note = " — that's at or below its reorder point" if data.is_low_stock(saved) else ""
        return str(saved.get("qty", new_qty)), _status(True, f"Saved: {saved.get('qty')}{note}.")

    # ---------- Reveal the move form ------------------------------------
    @app.callback(
        Output("scan-move-collapse", "is_open"),
        Input("scan-move-toggle", "n_clicks"),
        State("scan-move-collapse", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_move(n, is_open):
        if not n:
            raise PreventUpdate
        return not is_open

    # ---------- Record a new home ---------------------------------------
    @app.callback(
        Output("scan-status", "children", allow_duplicate=True),
        Output("scan-move-collapse", "is_open", allow_duplicate=True),
        Input("scan-move-save", "n_clicks"),
        State("scan-code", "data"),
        State("scan-location", "value"),
        State("scan-bin", "value"),
        prevent_initial_call=True,
    )
    def save_location(n, code, location, bin_code):
        if not n:
            raise PreventUpdate
        item = data.item_by_code(code)
        if not item:
            return _status(False, "That item no longer exists."), no_update
        loc = (location or "").strip()
        bc = (bin_code or "").strip()
        if not loc and not bc:
            return _status(False, "Enter a location or a bin code first."), no_update
        # update_item_fields ignores None, which would make clearing a field
        # impossible — pass "" explicitly so a blank really does blank it.
        saved = data.update_item_fields(item["id"], location=loc, location_code=bc)
        if saved is None:
            return _status(False, "Couldn't save — the item may have been deleted."), no_update
        where = " · ".join(x for x in (bc, loc) if x)
        return _status(True, f"Moved to {where}."), False
