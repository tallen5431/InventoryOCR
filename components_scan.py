"""The page a phone lands on after scanning an item's QR label.

Deliberately not the dashboard. Scanning a label answers one question — *where
does this go back?* — usually while standing in front of a shelf holding the
thing. So this is a single tall column, big type, the location as the loudest
element on the page, and the two edits that actually happen at the shelf:
adjust the count, or record that the item now lives somewhere else.

The layout is rebuilt on every navigation (``display_page``), so the item's
current values are baked in at render time and the type-ahead datalists are
filled here rather than by another round trip.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from dash import html, dcc
import dash_bootstrap_components as dbc

import data
from config import URL_PREFIX
from utils import get_preview_url


def _not_found(code: str):
    shown = (code or "").strip() or "—"
    return dbc.Container(
        dbc.Card(
            dbc.CardBody([
                html.Div("🔍", className="scan-hero-icon"),
                html.H4("No item with that code", className="mt-2"),
                html.P([
                    "Nothing in the inventory is labelled ",
                    html.Code(shown, className="scan-code-inline"), ".",
                ], className="text-muted"),
                html.P(
                    "The item may have been deleted, or merged into another entry. "
                    "Search the inventory to find where it went.",
                    className="text-muted small",
                ),
                dbc.Button([html.I(className="bi bi-search me-1"), "Search the inventory"],
                           href=f"{URL_PREFIX}/?q={shown}", color="primary", className="mt-2"),
            ], className="text-center"),
            className="shadow-sm",
        ),
        className="scan-page py-4",
    )


def _location_block(item: Dict[str, Any]):
    """The answer to 'where does this go back?' — the loudest thing on the page."""
    bin_code = (item.get("location_code") or "").strip()
    where = (item.get("location") or "").strip()

    if not bin_code and not where:
        return dbc.Alert(
            [html.I(className="bi bi-question-circle me-2"),
             "No location set for this item yet — set one below."],
            color="warning", className="scan-location scan-location-empty",
        )

    lines = []
    if bin_code:
        lines.append(html.Div(bin_code, className="scan-bin"))
    if where:
        # When a bin code is present the location doubles as the bag /
        # sub-compartment inside it, which is exactly the detail you need at the
        # shelf — so it is shown, smaller, underneath rather than dropped.
        lines.append(html.Div(where, className="scan-where"))
    return html.Div(
        [html.Div([html.I(className="bi bi-geo-alt-fill me-2"), "Goes back in"],
                  className="scan-location-label")] + lines,
        className="scan-location",
    )


def _photo(item: Dict[str, Any]):
    imgs = item.get("images") or []
    if not imgs:
        return None
    url = get_preview_url(imgs[0])
    if not url:
        return None
    return html.Img(src=url, className="scan-photo", alt=item.get("name") or "")


def scan_layout(code: str = ""):
    """Build the scan page for a label ``code``.

    Called with an empty code only to register component ids with Dash's
    validation layout; that path renders the not-found card.
    """
    item: Optional[Dict[str, Any]] = data.item_by_code(code) if code else None
    if not item:
        return _not_found(code)

    qty = int(item.get("qty") or 0)
    photo = _photo(item)
    low = data.is_low_stock(item)

    return dbc.Container(
        [
            # The code the callbacks act on. Read from the layout rather than the
            # URL so a callback can never act on a different item than the one
            # rendered.
            dcc.Store(id="scan-code", data=item.get("code", "")),
            dcc.Store(id="scan-item-id", data=item.get("id")),

            html.Div([
                html.Span(item.get("code", ""), className="scan-code-badge"),
                dbc.Badge("Needs reorder", color="warning", className="ms-2")
                if low else None,
            ], className="text-center mb-2"),

            html.H3(item.get("name") or "Untitled item",
                    className="scan-name text-center mb-1"),
            html.Div((item.get("category") or "").strip(),
                     className="text-muted text-center small mb-3"),

            html.Div(photo, className="text-center mb-3") if photo else None,

            _location_block(item),

            # ---- Count -------------------------------------------------
            dbc.Card(dbc.CardBody([
                html.Div("Quantity", className="text-muted small text-uppercase mb-2"),
                html.Div([
                    # Literal glyphs, not icon-font classes: if the icon CDN is
                    # slow or blocked (a phone on a captive portal, an offline
                    # LAN) an <i class="bi …"> renders as an empty circle with no
                    # affordance at all. These always draw.
                    dbc.Button("\u2212", id="scan-qty-dec",
                               color="secondary", outline=True, className="scan-step-btn",
                               n_clicks=0, title="One fewer"),
                    html.Span(str(qty), id="scan-qty-value", className="scan-qty"),
                    dbc.Button("+", id="scan-qty-inc",
                               color="secondary", outline=True, className="scan-step-btn",
                               n_clicks=0, title="One more"),
                ], className="d-flex align-items-center justify-content-center gap-3"),
            ]), className="shadow-sm mb-3"),

            # ---- Move it -----------------------------------------------
            dbc.Button([html.I(className="bi bi-box-arrow-in-right me-1"), "Change location"],
                       id="scan-move-toggle", color="link", className="p-0 mb-2", n_clicks=0),
            dbc.Collapse(
                dbc.Card(dbc.CardBody([
                    dbc.Label("Location / bag", html_for="scan-location", size="sm"),
                    dbc.Input(id="scan-location", value=item.get("location", ""),
                              list="scan-location-datalist", placeholder="e.g. Garage, Red bag"),
                    dbc.Label("Bin / code", html_for="scan-bin", size="sm", className="mt-2"),
                    dbc.Input(id="scan-bin", value=item.get("location_code", ""),
                              list="scan-bin-datalist", placeholder="e.g. BIN-04"),
                    dbc.Button([html.I(className="bi bi-check-lg me-1"), "Save location"],
                               id="scan-move-save", color="primary", className="mt-3 w-100",
                               n_clicks=0),
                ]), className="shadow-sm"),
                id="scan-move-collapse", is_open=False,
            ),
            # Filled here rather than by a callback — the page is rebuilt per
            # navigation, so these are always current.
            html.Datalist(id="scan-location-datalist",
                          children=[html.Option(value=v) for v in data.locations()]),
            html.Datalist(id="scan-bin-datalist",
                          children=[html.Option(value=v) for v in data.location_codes()]),

            html.Div(id="scan-status", className="small mt-2"),

            html.Hr(className="mt-4"),
            html.Div([
                dbc.Button([html.I(className="bi bi-box-seam me-1"), "Open full item"],
                           href=f"{URL_PREFIX}/?q={item.get('code','')}",
                           color="secondary", outline=True, size="sm"),
                dbc.Button([html.I(className="bi bi-house me-1"), "Inventory"],
                           href=f"{URL_PREFIX}/", color="secondary", outline=True,
                           size="sm", className="ms-2"),
            ], className="text-center pb-4"),
        ],
        className="scan-page py-3",
    )


def label_sheet(labels, *, columns: int = 3):
    """Printable grid of QR labels. ``labels`` come from item_labels.labels_for."""
    if not labels:
        return html.Div("No items to label.", className="text-muted p-3")
    cells = []
    for lab in labels:
        qr = lab.get("qr")
        cells.append(html.Div([
            html.Img(src=qr, className="label-qr") if qr
            else html.Div("no QR", className="label-qr label-qr-missing"),
            html.Div([
                html.Div(lab.get("name") or "", className="label-name"),
                html.Div(lab.get("code") or "", className="label-code"),
            ], className="label-text"),
        ], className="label-cell"))
    # Fixed-width columns rather than 1fr: a label is a physical sticker, so it
    # should be sticker-sized on the page instead of stretching to fill the
    # paper. minmax(0, …) keeps it from overflowing a narrow preview.
    cols = max(1, int(columns))
    return html.Div(cells, className="label-sheet",
                    style={"gridTemplateColumns": f"repeat({cols}, minmax(0, 2.6in))"})
