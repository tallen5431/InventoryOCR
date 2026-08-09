"""Callbacks for the "Print QR labels" modal.

Kept out of callbacks.py — that file is already 3800 lines, and label printing
is a self-contained feature with its own module (item_labels) behind it.
"""
from __future__ import annotations

import os

from dash import html, Input, Output, State, ctx, no_update
from dash.exceptions import PreventUpdate

import data
import item_labels
from components_scan import label_sheet

# Cap on one print run. A sheet is a data URI per label, and a few hundred SVGs
# is already several MB of layout for the browser to lay out and paginate — well
# past the point where anyone is peeling that many stickers in one sitting.
MAX_LABELS = 200


def _port() -> int:
    try:
        return int(os.environ.get("PORT", 8001) or 8001)
    except (TypeError, ValueError):
        return 8001


def register_label_callbacks(app):

    # ---------- Open / close, and fill the address picker ----------------
    @app.callback(
        Output("qr-labels-modal", "is_open"),
        Output("qr-base", "options"),
        Output("qr-base", "value"),
        Input("open-qr-labels", "n_clicks"),
        Input("qr-labels-close", "n_clicks"),
        State("qr-base", "value"),
        prevent_initial_call=True,
    )
    def toggle_labels(open_n, close_n, current_base):
        trig = ctx.triggered_id
        if trig == "qr-labels-close":
            return False, no_update, no_update
        if trig != "open-qr-labels":
            raise PreventUpdate
        scheme = os.environ.get("SCHEME", "http")
        opts = item_labels.base_options(_port(), scheme)
        options = [{"label": f"{o['label']} — {o['base']}", "value": o["base"]} for o in opts]
        # Keep the operator's previous choice if it is still a valid address;
        # otherwise fall back to the most durable one available.
        keep = current_base if any(o["base"] == current_base for o in opts) else None
        return True, options, keep or (opts[0]["base"] if opts else None)

    @app.callback(
        Output("qr-base-note", "children"),
        Input("qr-base", "value"),
        prevent_initial_call=False,
    )
    def base_note(base):
        if not base:
            return ""
        scheme = os.environ.get("SCHEME", "http")
        for o in item_labels.base_options(_port(), scheme):
            if o["base"] == base:
                # A LAN or loopback address will stop resolving the moment the
                # machine's IP changes, which silently kills every label already
                # stuck on a bin — worth a warning colour, not just a note.
                if o["kind"] in ("lan", "loopback"):
                    return html.Span(
                        [html.I(className="bi bi-exclamation-triangle me-1"), o["note"]],
                        className="text-warning")
                return o["note"]
        return ""

    # ---------- Build the sheet ------------------------------------------
    @app.callback(
        Output("qr-labels-preview", "children"),
        Output("qr-labels-count", "children"),
        Output("qr-labels-status", "children"),
        Input("qr-labels-modal", "is_open"),
        Input("qr-scope", "value"),
        Input("qr-base", "value"),
        Input("qr-columns", "value"),
        State("inventory-table", "derived_virtual_data"),
        State("inventory-table", "derived_virtual_selected_rows"),
        prevent_initial_call=True,
    )
    def build_sheet(is_open, scope, base, columns, table_rows, selected):
        if not is_open:
            raise PreventUpdate
        if not item_labels.qr_available():
            return (html.Div(), "", html.Span(
                [html.I(className="bi bi-exclamation-triangle me-1"),
                 "QR codes need the 'qrcode' package — install it with "
                 "pip install -r requirements.txt, then reopen this window."],
                className="text-warning"))

        table_rows = table_rows or []
        if scope == "selected":
            picked = [table_rows[i] for i in (selected or []) if 0 <= i < len(table_rows)]
            if not picked:
                return (html.Div(), "", html.Span(
                    "Tick some rows in the table first, or switch to "
                    "“Everything matching the current filters”.",
                    className="text-muted"))
        else:
            picked = table_rows

        # The table rows are display projections; re-read the real records so a
        # label can never be built from a stale or trimmed value.
        by_code = {r.get("code"): r for r in data.inventory() if r.get("code")}
        rows = [by_code[c] for c in
                [str(p.get("code") or "") for p in picked] if c in by_code]

        note = ""
        if len(rows) > MAX_LABELS:
            note = html.Span(
                [html.I(className="bi bi-info-circle me-1"),
                 f"Showing the first {MAX_LABELS} of {len(rows)} — print these, "
                 "then narrow the filters for the rest."],
                className="text-muted")
            rows = rows[:MAX_LABELS]

        if not rows:
            return (html.Div(), "", html.Span("Nothing to label.", className="text-muted"))

        labels = item_labels.labels_for(rows, base or "")
        try:
            cols = int(columns or 3)
        except (TypeError, ValueError):
            cols = 3
        count = f"{len(labels)} label{'s' if len(labels) != 1 else ''}"
        return label_sheet(labels, columns=cols), count, note

    # ---------- Print -----------------------------------------------------
    # Clientside: the browser's own print dialog is the only way to reach a
    # printer, and the @media print rules in custom.css hide everything except
    # the sheet.
    app.clientside_callback(
        """
        function(n) {
            // Let Dash finish painting the sheet before handing off to the
            // browser's print dialog, or the first page can come out blank.
            if (n) { setTimeout(function () { window.print(); }, 150); }
            return "";
        }
        """,
        Output("qr-print-sink", "children"),
        Input("qr-labels-print", "n_clicks"),
        prevent_initial_call=True,
    )
