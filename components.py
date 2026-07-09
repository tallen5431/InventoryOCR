from __future__ import annotations
from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc
from config import DATATABLE_PAGE_SIZE, TOAST_DURATION, LOW_STOCK_THRESHOLD


def _kpi_card(icon, color, label, value_id):
    return dbc.Col(
        dbc.Card(
            dbc.CardBody(
                [
                    html.Div(
                        [
                            html.I(className=f"bi {icon} me-2 {color}"),
                            html.Span(label, className="kpi-sub"),
                        ],
                        className="d-flex align-items-center",
                    ),
                    html.Div(id=value_id, className=f"kpi-number mt-1 {color}"),
                ]
            ),
            className="h-100 shadow-sm",
        ),
        xs=6,
        sm=6,
        md=3,
        lg=3,
        className="mb-3",
    )


def kpi_bar():
    return dbc.Row(
        [
            _kpi_card("bi-box-seam", "text-primary", "Total Items", "kpi-total"),
            _kpi_card("bi-123", "text-success", "Total Quantity", "kpi-qty"),
            _kpi_card("bi-exclamation-triangle-fill", "text-warning", f"Low Stock (< {LOW_STOCK_THRESHOLD})", "kpi-low"),
            _kpi_card("bi-tags-fill", "text-info", "Categories", "kpi-cat"),
        ],
        className="g-3 mb-2",
    )


def sidebar_form():
    return html.Div(
        [
            dcc.Store(id="editing-id"),
            dbc.Card(
                [
                    dbc.CardHeader(
                        html.Div(
                            [
                                html.Span([html.I(className="bi bi-plus-circle me-2"), "Add / Edit Item"]),
                                html.Span(id="form-mode-badge", className="badge bg-secondary ms-2"),
                            ],
                            className="d-flex align-items-center justify-content-between",
                        )
                    ),
                    dbc.CardBody(
                        [
                            dbc.Label("Name"),
                            dbc.Input(id="item-name", debounce=True, placeholder="e.g., Cordless Drill"),

                            dbc.Row(
                                [
                                    dbc.Col(
                                        [
                                            dbc.Label("Category", className="mt-2"),
                                            dbc.Input(
                                                id="item-category",
                                                debounce=True,
                                                placeholder="e.g., Tools",
                                                list="category-datalist",
                                                autoComplete="off",
                                            ),
                                        ],
                                        xs=12, sm=6,
                                    ),
                                    dbc.Col(
                                        [
                                            dbc.Label("Location", className="mt-2"),
                                            dbc.Input(
                                                id="item-location",
                                                debounce=True,
                                                placeholder="e.g., Garage shelf B",
                                                list="location-datalist",
                                                autoComplete="off",
                                            ),
                                        ],
                                        xs=12, sm=6,
                                    ),
                                ],
                                className="g-2",
                            ),

                            dbc.Row(
                                [
                                    dbc.Col(
                                        [
                                            dbc.Label("Quantity", className="mt-2"),
                                            dbc.Input(id="item-qty", type="number", min=0, step=1, value=1),
                                        ],
                                        xs=6,
                                    ),
                                    dbc.Col(
                                        [
                                            dbc.Label(
                                                [html.I(className="bi bi-box2 me-1"), "Bin / code"],
                                                className="mt-2",
                                            ),
                                            dbc.Input(
                                                id="item-location-code",
                                                debounce=True,
                                                placeholder="e.g., BIN-01",
                                                list="location-code-datalist",
                                                autoComplete="off",
                                            ),
                                        ],
                                        xs=6,
                                    ),
                                ],
                                className="g-2",
                            ),

                            # Datalists power the type-ahead suggestions above.
                            html.Datalist(id="category-datalist"),
                            html.Datalist(id="location-datalist"),
                            html.Datalist(id="location-code-datalist"),

                            dbc.Label("Description", className="mt-2"),
                            dbc.Textarea(id="item-desc", placeholder="Optional details…", rows=2),

                            dbc.Label("Photos", className="mt-3"),
                            dcc.Upload(
                                id="image-upload",
                                children=html.Div(
                                    [
                                        html.Div("📷", className="upload-icon"),
                                        html.Div(
                                            [
                                                html.Strong("Take a photo"),
                                                " or ",
                                                html.A("choose from library"),
                                            ]
                                        ),
                                        html.Div(
                                            "Snap items with your phone — multiple photos supported",
                                            className="text-muted small mt-1",
                                        ),
                                    ]
                                ),
                                multiple=True,
                                accept="image/*",
                                className="upload-dropzone",
                            ),
                            html.Div(id="image-gallery", className="mt-2"),
                            dcc.Store(id="current-images", data=[]),

                            # ----- Identify + web search (fast lookup) -----
                            dbc.Row(
                                [
                                    dbc.Col(
                                        dbc.Button(
                                            [html.I(className="bi bi-stars me-1"), "Identify from photo"],
                                            id="identify-button",
                                            color="info",
                                            outline=True,
                                            className="w-100 mt-3",
                                        ),
                                        xs=12, sm=6,
                                    ),
                                    dbc.Col(
                                        html.A(
                                            [html.I(className="bi bi-globe me-1"), "Search the web"],
                                            id="form-web-search",
                                            href="https://www.google.com",
                                            target="_blank",
                                            rel="noopener noreferrer",
                                            className="btn btn-outline-secondary w-100 mt-3 mt-sm-3",
                                        ),
                                        xs=12, sm=6,
                                    ),
                                ],
                                className="g-2",
                            ),
                            html.Div(
                                "Local vision AI suggests what it is; the web button opens Google for the name/specs.",
                                className="text-muted small mt-1",
                            ),
                            dbc.Button(
                                [html.I(className="bi bi-link-45deg me-1"), "Import from a product link / page"],
                                id="open-import",
                                color="link",
                                size="sm",
                                n_clicks=0,
                                className="px-0 mt-1 text-decoration-none",
                            ),

                            # ----- Collapsible catalogue details -----
                            dbc.Button(
                                [html.I(className="bi bi-sliders me-1"), "More details ", html.I(className="bi bi-chevron-down")],
                                id="more-details-toggle",
                                color="link",
                                size="sm",
                                className="px-0 mt-2 text-decoration-none",
                                n_clicks=0,
                            ),
                            dbc.Collapse(
                                html.Div(
                                    [
                                        dbc.Label("Specifications", className="mt-1"),
                                        dbc.Textarea(
                                            id="item-specs",
                                            placeholder="One per line, or comma-separated",
                                            rows=2,
                                        ),
                                        dbc.Row(
                                            [
                                                dbc.Col(
                                                    [
                                                        dbc.Label("Est. value", className="mt-2"),
                                                        dbc.Input(id="item-value", placeholder="e.g., $20–30"),
                                                    ],
                                                    xs=6,
                                                ),
                                                dbc.Col(
                                                    [
                                                        dbc.Label("Dimensions", className="mt-2"),
                                                        dbc.Input(id="item-dims", placeholder="e.g., 30×10 cm"),
                                                    ],
                                                    xs=6,
                                                ),
                                            ],
                                            className="g-2",
                                        ),
                                        dbc.Label("Tags / keywords", className="mt-2"),
                                        dbc.Input(
                                            id="item-tags",
                                            placeholder="comma-separated, e.g. cordless, 18v, dewalt",
                                        ),
                                        dbc.Label("Product link", className="mt-2"),
                                        dbc.Input(id="item-producturl", placeholder="https://…", type="url"),
                                    ]
                                ),
                                id="more-details-collapse",
                                is_open=False,
                            ),

                            # ----- Primary actions -----
                            dbc.Row(
                                [
                                    dbc.Col(
                                        dbc.Button(
                                            [html.I(className="bi bi-save me-1"), "Save"],
                                            id="save-button", color="primary", className="w-100 mt-3",
                                        ),
                                        xs=12, sm=6, md=6, lg=6,
                                    ),
                                    dbc.Col(
                                        dbc.Button(
                                            [html.I(className="bi bi-save2 me-1"), "Save & Next"],
                                            id="save-next-button", color="success", className="w-100 mt-3",
                                            title="Save this item and keep category/location for the next one",
                                        ),
                                        xs=12, sm=6, md=6, lg=6,
                                    ),
                                ],
                                className="g-2",
                            ),
                            dbc.Row(
                                [
                                    dbc.Col(
                                        dbc.Button(
                                            [html.I(className="bi bi-trash me-1"), "Delete"],
                                            id="delete-button", color="outline-danger", outline=True, className="w-100 mt-2",
                                        ),
                                        xs=6,
                                    ),
                                    dbc.Col(
                                        dbc.Button(
                                            [html.I(className="bi bi-x-lg me-1"), "Cancel"],
                                            id="cancel-button", color="outline-secondary", outline=True, className="w-100 mt-2",
                                        ),
                                        xs=6,
                                    ),
                                ],
                                className="g-2",
                            ),
                        ]
                    ),
                ],
                className="shadow-sm",
            ),
            filter_card(),
            dbc.Toast(
                id="action-toast",
                is_open=False,
                header="",
                icon="info",
                duration=TOAST_DURATION,
                children="",
                style={"position": "fixed", "top": 20, "right": 20, "zIndex": 2000},
            ),
        ]
    )


def filter_card():
    return dbc.Card(
        [
            dbc.CardHeader(
                html.Span([html.I(className="bi bi-funnel me-2"), "Find & Filter"])
            ),
            dbc.CardBody(
                [
                    dbc.Input(
                        id="search-bar",
                        placeholder="Search name, category, location, notes, OCR…",
                        debounce=True,
                    ),
                    dbc.Row(
                        [
                            dbc.Col(
                                dcc.Dropdown(
                                    id="filter-category",
                                    placeholder="All categories",
                                    clearable=True,
                                    options=[],
                                ),
                                xs=12, sm=6, className="mt-2",
                            ),
                            dbc.Col(
                                dcc.Dropdown(
                                    id="filter-location",
                                    placeholder="All locations",
                                    clearable=True,
                                    options=[],
                                ),
                                xs=12, sm=6, className="mt-2",
                            ),
                        ],
                        className="g-2",
                    ),
                    dbc.Button(
                        [html.I(className="bi bi-download me-1"), "Export CSV"],
                        id="export-button",
                        color="outline-secondary",
                        outline=True,
                        size="sm",
                        className="w-100 mt-3",
                    ),
                    dcc.Download(id="download-csv"),
                ]
            ),
        ],
        className="mt-3 shadow-sm",
    )


def inventory_table():
    columns = [
        {"name": "Photo", "id": "image", "presentation": "markdown"},
        {"name": "Name", "id": "name"},
        {"name": "Qty", "id": "qty", "type": "numeric"},
        {"name": "Category", "id": "category", "hideable": True},
        {"name": "Location", "id": "location", "hideable": True},
        {"name": "Bin", "id": "location_code", "hideable": True},
        {"name": "Value", "id": "estimated_value", "hideable": True},
        {"name": "Description", "id": "description", "hideable": True},
        {"name": "OCR Text", "id": "ocr_text", "hideable": True},
        {"name": "id", "id": "id", "hideable": True},
        {"name": "all_images", "id": "all_images", "hideable": True},
    ]
    table = dash_table.DataTable(
        id="inventory-table",
        columns=columns,
        data=[],
        page_size=DATATABLE_PAGE_SIZE,
        row_selectable="single",
        selected_rows=[],
        tooltip_delay=0,
        tooltip_duration=None,
        sort_action="native",
        filter_action="native",
        hidden_columns=["id", "all_images", "ocr_text"],
        style_table={
            "height": "70vh",
            "overflowY": "auto",
            "overflowX": "auto",
            "backgroundColor": "var(--bs-body-bg)",
        },
        style_as_list_view=True,
        style_header={
            "position": "sticky",
            "top": 0,
            "zIndex": 2,
            "backgroundColor": "var(--bs-tertiary-bg)",
            "fontWeight": "700",
            "borderBottom": "1px solid var(--bs-border-color)",
            "padding": "12px 8px",
        },
        style_cell={
            "padding": "14px 12px",
            "fontSize": 14,
            "whiteSpace": "normal",
            "height": "auto",
            "verticalAlign": "middle",
            "textAlign": "left",
            "color": "var(--bs-body-color)",
            "backgroundColor": "var(--bs-body-bg)",
            "borderColor": "var(--bs-border-color)",
            "minWidth": "60px",
        },
        style_cell_conditional=[
            {"if": {"column_id": "name"}, "minWidth": "160px", "maxWidth": "260px", "fontWeight": "600"},
            {"if": {"column_id": "category"}, "minWidth": "90px", "maxWidth": "150px"},
            {"if": {"column_id": "location"}, "minWidth": "90px", "maxWidth": "160px"},
            {"if": {"column_id": "location_code"}, "minWidth": "72px", "maxWidth": "110px", "fontWeight": "600", "textAlign": "center"},
            {"if": {"column_id": "estimated_value"}, "minWidth": "80px", "maxWidth": "120px", "textAlign": "right", "fontWeight": "600", "color": "var(--bs-success)"},
            {"if": {"column_id": "description"}, "minWidth": "160px", "maxWidth": "300px", "overflowWrap": "anywhere", "whiteSpace": "normal"},
            {"if": {"column_id": "ocr_text"}, "minWidth": "150px", "maxWidth": "400px", "overflowWrap": "anywhere", "whiteSpace": "pre-wrap"},
            {"if": {"column_id": "image"}, "width": "88px", "minWidth": "88px", "maxWidth": "96px", "textAlign": "center", "padding": "6px"},
            {"if": {"column_id": "qty"}, "textAlign": "center", "width": "64px", "minWidth": "64px", "maxWidth": "80px", "fontWeight": "600"},
        ],
        style_data_conditional=[
            {"if": {"row_index": "odd"}, "backgroundColor": "var(--bs-table-striped-bg)"},
            {
                "if": {"filter_query": "{qty} < " + str(LOW_STOCK_THRESHOLD), "column_id": "qty"},
                "color": "var(--bs-warning)",
                "fontWeight": "700",
            },
        ],
        css=[
            {"selector": "td div", "rule": "overflow: visible; white-space: normal;"},
            {"selector": ".dash-table-container", "rule": "font-size: 14px;"},
        ],
    )
    return html.Div(
        [
            html.Div(
                html.Span(
                    ["Tap a row to edit · tap a ", html.I(className="bi bi-image"), " thumbnail to view photos"],
                    className="text-muted small",
                ),
                className="mb-2",
            ),
            html.Div([table], className="table-responsive"),
        ]
    )


def breakdown_card():
    """Compact 'where is everything' overview: totals grouped by location & category."""
    return dbc.Card(
        [
            dbc.CardHeader(
                html.Span([html.I(className="bi bi-diagram-3 me-2"), "Overview"])
            ),
            dbc.CardBody(
                dbc.Row(
                    [
                        dbc.Col(
                            [
                                html.H6([html.I(className="bi bi-geo-alt me-1"), "By Location"], className="text-muted"),
                                html.Div(id="breakdown-location"),
                            ],
                            xs=12, md=6, className="mb-3 mb-md-0",
                        ),
                        dbc.Col(
                            [
                                html.H6([html.I(className="bi bi-tags me-1"), "By Category"], className="text-muted"),
                                html.Div(id="breakdown-category"),
                            ],
                            xs=12, md=6,
                        ),
                    ],
                    className="g-3",
                )
            ),
        ],
        className="mt-4 shadow-sm",
    )


def identify_modal():
    """Panel showing what the vision AI + web lookup found for an item's photo."""
    return html.Div(
        [
            dcc.Store(id="identify-trigger"),
            # Holds the parsed identify result so "Apply to item" can copy it
            # into the edit form.
            dcc.Store(id="identify-result"),
            dbc.Modal(
                [
                    dbc.ModalHeader(
                        dbc.ModalTitle([html.I(className="bi bi-search me-2"), "Item lookup"])
                    ),
                    dbc.ModalBody(
                        [
                            # --- Import from a product listing (upload .html — most reliable — or URL) ---
                            html.Div(
                                [
                                    html.Div(
                                        [html.I(className="bi bi-link-45deg me-2"),
                                         html.Strong("Found it online? Import from the listing")],
                                        className="mb-2",
                                    ),
                                    # Primary, reliable path: upload the saved page.
                                    dcc.Upload(
                                        id="import-html-upload",
                                        children=html.Div(
                                            [
                                                html.Div("⬆️", className="upload-icon"),
                                                html.Div(html.Strong("Upload the saved .html listing")),
                                                html.Div(
                                                    "Save the page (Ctrl+S) then drop it here — name, price & specs fill in automatically. Never gets blocked.",
                                                    className="text-muted small mt-1",
                                                ),
                                            ]
                                        ),
                                        accept=".html,.htm,text/html",
                                        className="upload-dropzone",
                                    ),
                                    # Secondary: fetch a URL directly (works on many non-Amazon sites).
                                    dbc.InputGroup(
                                        [
                                            dbc.Input(
                                                id="import-url",
                                                placeholder="…or paste a product URL (Amazon, eBay, Home Depot…)",
                                                type="url",
                                            ),
                                            dbc.Button(
                                                [html.I(className="bi bi-download me-1"), "Fetch"],
                                                id="import-fetch", color="secondary", n_clicks=0,
                                            ),
                                        ],
                                        className="mt-2",
                                    ),
                                    dbc.Button(
                                        "or paste the HTML source instead",
                                        id="import-html-toggle",
                                        color="link", size="sm", n_clicks=0,
                                        className="px-0 mt-1 text-decoration-none",
                                    ),
                                    dbc.Collapse(
                                        html.Div(
                                            [
                                                dbc.Textarea(
                                                    id="import-html",
                                                    placeholder="Paste the listing page's HTML source here…",
                                                    rows=4, className="mt-1",
                                                ),
                                                dbc.Button(
                                                    [html.I(className="bi bi-magic me-1"), "Extract from pasted HTML"],
                                                    id="import-extract", color="secondary",
                                                    n_clicks=0, className="w-100 mt-1",
                                                ),
                                            ]
                                        ),
                                        id="import-html-collapse", is_open=False,
                                    ),
                                ],
                                className="mb-2",
                            ),
                            html.Hr(),
                            dcc.Loading(html.Div(id="identify-body"), type="default"),
                        ]
                    ),
                    dbc.ModalFooter(
                        [
                            html.Div(
                                [
                                    dbc.Button(
                                        [html.I(className="bi bi-pencil-square me-1"), "Apply to form"],
                                        id="apply-identify",
                                        color="primary",
                                        outline=True,
                                        n_clicks=0,
                                        title="Fill the form with these details so you can review, then Save.",
                                        className="me-2",
                                    ),
                                    dbc.Button(
                                        [html.I(className="bi bi-check2-circle me-1"), "Apply & Update"],
                                        id="apply-identify-save",
                                        color="primary",
                                        n_clicks=0,
                                        title="Write these details straight onto the item and save.",
                                    ),
                                ],
                                className="d-flex flex-wrap gap-2",
                            ),
                            dbc.Button("Close", id="close-identify-modal", color="secondary", n_clicks=0),
                        ],
                        className="justify-content-between",
                    ),
                ],
                id="identify-modal",
                is_open=False,
                size="lg",
                centered=True,
                scrollable=True,
            ),
        ]
    )


def connect_modal():
    """Shows every address the app is reachable at (LAN, Tailscale, localhost)."""
    return html.Div(
        [
            dbc.Modal(
                [
                    dbc.ModalHeader(
                        dbc.ModalTitle([html.I(className="bi bi-phone me-2"), "Open on another device"])
                    ),
                    dbc.ModalBody(
                        [
                            html.P(
                                "This app is reachable at every address below — pick your local "
                                "network for speed, or Tailscale from anywhere. Scan a QR with "
                                "your phone's camera to open it there.",
                                className="text-muted small",
                            ),
                            dcc.Loading(html.Div(id="connect-body"), type="default"),
                        ]
                    ),
                    dbc.ModalFooter(dbc.Button("Close", id="close-connect-modal", className="ms-auto", n_clicks=0)),
                ],
                id="connect-modal",
                is_open=False,
                size="lg",
                centered=True,
                scrollable=True,
            ),
        ]
    )


def organize_card():
    """Storage system: Smart Organize + a live 'what's in each bin' map."""
    return dbc.Card(
        [
            dbc.CardHeader(
                html.Div(
                    [
                        html.Span([html.I(className="bi bi-boxes me-2"), "Storage map"]),
                        dbc.Button(
                            [html.I(className="bi bi-magic me-1"), "Smart Organize"],
                            id="organize-button",
                            color="primary",
                            size="sm",
                            n_clicks=0,
                        ),
                    ],
                    className="d-flex align-items-center justify-content-between",
                )
            ),
            dbc.CardBody(
                [
                    html.Div(
                        "Smart Organize analyses every item's name & category and groups related "
                        "things into labelled bins (e.g. all your switches together). Then a keyword "
                        "search tells you which bin something lives in.",
                        className="text-muted small mb-2",
                    ),
                    html.Div(id="storage-map"),
                ]
            ),
        ],
        className="mt-4 shadow-sm",
    )


def organize_modal():
    """Preview + apply the auto-generated storage plan."""
    return html.Div(
        [
            dcc.Store(id="organize-plan"),
            dbc.Modal(
                [
                    dbc.ModalHeader(
                        dbc.ModalTitle([html.I(className="bi bi-magic me-2"), "Smart Organize"])
                    ),
                    dbc.ModalBody(html.Div(id="organize-body")),
                    dbc.ModalFooter(
                        [
                            dbc.Button(
                                [html.I(className="bi bi-check2-circle me-1"), "Apply plan"],
                                id="apply-organize",
                                color="success",
                                n_clicks=0,
                            ),
                            dbc.Button("Cancel", id="close-organize-modal", color="secondary", n_clicks=0),
                        ],
                        className="justify-content-between",
                    ),
                ],
                id="organize-modal",
                is_open=False,
                size="lg",
                centered=True,
                scrollable=True,
            ),
        ]
    )


def detail_panel():
    return html.Div(
        [
            dbc.Modal(
                [
                    dbc.ModalHeader(dbc.ModalTitle(id="image-modal-title")),
                    dbc.ModalBody(
                        dbc.Carousel(
                            id="image-carousel",
                            items=[],
                            controls=True,
                            indicators=True,
                            interval=None,
                            ride=False,
                        )
                    ),
                    dbc.ModalFooter(dbc.Button("Close", id="close-image-modal", className="ms-auto", n_clicks=0)),
                ],
                id="image-modal",
                is_open=False,
                size="xl",
                centered=True,
                backdrop="static",
            ),
        ]
    )
