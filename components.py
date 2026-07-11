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
            _kpi_card("bi-exclamation-triangle-fill", "text-warning", "Needs Reorder", "kpi-low"),
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
                            dbc.Input(id="item-name", debounce=True,
                                      placeholder="e.g., Cordless Drill — or leave blank to auto-number"),
                            html.Div(
                                [html.I(className="bi bi-phone me-1"),
                                 "Quick scan on your phone: snap a photo and tap Save & Next — a blank "
                                 "name auto-numbers (Item 0001). Fill in the details later from a desktop."],
                                className="text-muted small mt-1",
                            ),

                            dbc.Row(
                                dbc.Col(
                                    [
                                        dbc.Label("Type", className="mt-2"),
                                        dbc.Input(
                                            id="item-type",
                                            debounce=True,
                                            placeholder="Tools, Components, Cables & Adapters…",
                                            list="type-datalist",
                                            autoComplete="off",
                                        ),
                                        html.Div(
                                            "Top-level group for browsing. Leave blank to auto-group "
                                            "from the name/category.",
                                            className="text-muted", style={"fontSize": "0.75rem"},
                                        ),
                                    ],
                                    xs=12,
                                ),
                                className="g-2",
                            ),

                            dbc.Row(
                                [
                                    dbc.Col(
                                        [
                                            dbc.Label("Category", className="mt-2"),
                                            dbc.Input(
                                                id="item-category",
                                                debounce=True,
                                                placeholder="e.g., Sockets, USB Cables",
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
                                                [html.I(className="bi bi-bell me-1"), "Reorder at"],
                                                className="mt-2",
                                            ),
                                            dbc.Input(id="item-reorder", type="number", min=0, step=1,
                                                      placeholder="—"),
                                            html.Div(
                                                "Flag as low stock when quantity reaches this. Blank = never.",
                                                className="text-muted", style={"fontSize": "0.72rem"},
                                            ),
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
                            html.Datalist(id="type-datalist"),
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
                                                html.Strong("Take photos"),
                                                " or ",
                                                html.A("choose files"),
                                            ]
                                        ),
                                        html.Div(
                                            "Add as many as you like — snap several shots or pick multiple "
                                            "files, and they stack up on this item. On a phone you can also "
                                            "pick an existing photo; on a computer it opens the file picker.",
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
        ]
    )


def action_toast():
    """The success/error toast. Mounted at the top level (never inside a
    collapsible section) so it always shows, whatever's expanded."""
    return dbc.Toast(
        id="action-toast",
        is_open=False,
        header="",
        icon="info",
        duration=TOAST_DURATION,
        children="",
        style={"position": "fixed", "top": 20, "right": 20, "zIndex": 2000},
    )


def search_box():
    """Always-visible search input for the toolbar."""
    return dbc.InputGroup(
        [
            dbc.InputGroupText(html.I(className="bi bi-search")),
            dbc.Input(
                id="search-bar",
                placeholder="Search name, type, category, bin, notes…",
                debounce=True,
            ),
        ]
    )


def _toggle_button(label, icon, btn_id):
    return dbc.Button(
        [html.I(className=f"bi {icon} me-1"), label],
        id=btn_id, color="light", size="sm", n_clicks=0, className="border",
    )


def dashboard_toolbar():
    """Primary action + always-visible search + expand toggles for the cards."""
    return dbc.Row(
        [
            dbc.Col(
                dbc.Button(
                    [html.I(className="bi bi-plus-lg me-1"), "Add item"],
                    id="toggle-add", color="primary", n_clicks=0, className="w-100",
                ),
                xs=12, sm="auto",
            ),
            dbc.Col(search_box(), xs=12, sm=True),
            dbc.Col(
                dbc.ButtonGroup(
                    [
                        _toggle_button("Filter & sort", "bi-funnel", "toggle-filter"),
                        _toggle_button("Overview", "bi-diagram-3", "toggle-overview"),
                        _toggle_button("Storage", "bi-boxes", "toggle-storage"),
                    ]
                ),
                xs=12, sm="auto",
            ),
        ],
        className="g-2 align-items-center mb-2",
    )


def filter_card():
    return dbc.Card(
        [
            dbc.CardHeader(
                html.Span([html.I(className="bi bi-funnel me-2"), "Find & Filter"])
            ),
            dbc.CardBody(
                [
                    dbc.Row(
                        [
                            dbc.Col(
                                dcc.Dropdown(
                                    id="filter-type",
                                    placeholder="All types",
                                    clearable=True,
                                    options=[],
                                ),
                                xs=12, sm=4, className="mt-2",
                            ),
                            dbc.Col(
                                dcc.Dropdown(
                                    id="filter-category",
                                    placeholder="All categories",
                                    clearable=True,
                                    options=[],
                                ),
                                xs=12, sm=4, className="mt-2",
                            ),
                            dbc.Col(
                                dcc.Dropdown(
                                    id="filter-location",
                                    placeholder="All locations",
                                    clearable=True,
                                    options=[],
                                ),
                                xs=12, sm=4, className="mt-2",
                            ),
                        ],
                        className="g-2",
                    ),
                    dbc.Row(
                        dbc.Col(
                            dcc.Dropdown(
                                id="sort-by",
                                clearable=False,
                                options=[
                                    {"label": "🕑 Newest first", "value": "date_desc"},
                                    {"label": "🕑 Oldest first", "value": "date_asc"},
                                    {"label": "🔤 Name (A–Z)", "value": "name_asc"},
                                    {"label": "🔤 Name (Z–A)", "value": "name_desc"},
                                    {"label": "🔢 Qty (high → low)", "value": "qty_desc"},
                                    {"label": "🔢 Qty (low → high)", "value": "qty_asc"},
                                    {"label": "🗂 Group by Type", "value": "group_type"},
                                    {"label": "🗂 Group by Category", "value": "group_category"},
                                    {"label": "🗂 Group by Location", "value": "group_location"},
                                ],
                                value="date_desc",
                            ),
                            xs=12, className="mt-2",
                        ),
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
        {"name": "Reorder at", "id": "reorder_at", "type": "numeric", "hideable": True},
        {"name": "Added", "id": "added", "hideable": True},
        {"name": "Type", "id": "type", "hideable": True},
        {"name": "Category", "id": "category", "hideable": True},
        {"name": "Location", "id": "location", "hideable": True},
        {"name": "Bin", "id": "location_code", "hideable": True},
        {"name": "Value", "id": "estimated_value", "hideable": True},
        {"name": "Description", "id": "description", "hideable": True},
        {"name": "OCR Text", "id": "ocr_text", "hideable": True},
        {"name": "id", "id": "id", "hideable": True},
        {"name": "all_images", "id": "all_images", "hideable": True},
        {"name": "_low", "id": "_low"},  # server-computed low-stock flag (hidden)
    ]
    table = dash_table.DataTable(
        id="inventory-table",
        columns=columns,
        data=[],
        page_size=DATATABLE_PAGE_SIZE,
        row_selectable="multi",
        selected_rows=[],
        tooltip_delay=0,
        tooltip_duration=None,
        sort_action="native",
        # No per-column filter row — the Find & Filter card (search + Type /
        # Category / Location dropdowns) covers it without the extra clutter.
        filter_action="none",
        # Description is long; it's shown in full in the row's hover tooltip, so
        # keep it out of the default view. Re-show any of these via Toggle Columns.
        hidden_columns=["id", "all_images", "ocr_text", "description", "reorder_at", "_low"],
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
            {"if": {"column_id": "type"}, "minWidth": "96px", "maxWidth": "150px", "fontWeight": "600"},
            {"if": {"column_id": "category"}, "minWidth": "90px", "maxWidth": "150px"},
            {"if": {"column_id": "location"}, "minWidth": "90px", "maxWidth": "160px"},
            {"if": {"column_id": "location_code"}, "minWidth": "72px", "maxWidth": "110px", "fontWeight": "600", "textAlign": "center"},
            {"if": {"column_id": "estimated_value"}, "minWidth": "80px", "maxWidth": "120px", "textAlign": "right", "fontWeight": "600", "color": "var(--bs-success)"},
            {"if": {"column_id": "description"}, "minWidth": "160px", "maxWidth": "300px", "overflowWrap": "anywhere", "whiteSpace": "normal"},
            {"if": {"column_id": "ocr_text"}, "minWidth": "150px", "maxWidth": "400px", "overflowWrap": "anywhere", "whiteSpace": "pre-wrap"},
            {"if": {"column_id": "image"}, "width": "88px", "minWidth": "88px", "maxWidth": "96px", "textAlign": "center", "padding": "6px"},
            {"if": {"column_id": "qty"}, "textAlign": "center", "width": "64px", "minWidth": "64px", "maxWidth": "80px", "fontWeight": "600"},
            {"if": {"column_id": "added"}, "width": "104px", "minWidth": "96px", "maxWidth": "120px", "textAlign": "center", "whiteSpace": "nowrap", "color": "var(--bs-secondary-color)"},
        ],
        style_data_conditional=[
            {"if": {"row_index": "odd"}, "backgroundColor": "var(--bs-table-striped-bg)"},
            {
                # Highlight the qty of items at/below their own reorder point.
                # Uses a server-computed flag ({_low}) for a robust equality query.
                "if": {"filter_query": '{_low} = "low"', "column_id": "qty"},
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
                    ["Tick one row to edit · tick several to bulk-edit · tap a ",
                     html.I(className="bi bi-image"), " thumbnail to view photos"],
                    className="text-muted small",
                ),
                className="mb-2",
            ),
            _bulk_bar(),
            html.Div([table], className="table-responsive"),
        ]
    )


def _bulk_bar():
    """Actions that appear when 2+ rows are ticked: set fields, merge, or delete."""
    return dbc.Card(
        dbc.CardBody(
            [
                html.Div(
                    [html.I(className="bi bi-check2-square me-2"),
                     html.Strong(id="bulk-count"), " selected"],
                    className="mb-2 small",
                ),

                # --- Set the same field(s) on every selected row ---
                html.Div("Set on all, then Apply:", className="text-muted small mb-1"),
                dbc.Row(
                    [
                        dbc.Col(dbc.Input(id="bulk-type", placeholder="Type",
                                          size="sm", list="type-datalist"), xs=6, sm=4, md=3),
                        dbc.Col(dbc.Input(id="bulk-category", placeholder="Category",
                                          size="sm", list="category-datalist"), xs=6, sm=4, md=3),
                        dbc.Col(dbc.Input(id="bulk-location", placeholder="Location",
                                          size="sm", list="location-datalist"), xs=6, sm=4, md=2),
                        dbc.Col(dbc.Input(id="bulk-code", placeholder="Bin / code",
                                          size="sm", list="location-code-datalist"), xs=6, sm=6, md=2),
                        dbc.Col(
                            dbc.Button([html.I(className="bi bi-check2 me-1"), "Apply"],
                                       id="bulk-apply", color="primary", size="sm", className="w-100"),
                            xs=12, sm=6, md=2,
                        ),
                    ],
                    className="g-2 align-items-center",
                ),

                html.Hr(className="my-2"),

                # --- Combine or remove the selected rows ---
                html.Div("Do this with the selected rows:", className="text-muted small mb-1"),
                dbc.Row(
                    [
                        dbc.Col(
                            dbc.Button([html.I(className="bi bi-union me-1"), "Merge into one"],
                                       id="bulk-merge", color="info", size="sm", className="w-100"),
                            xs=12, sm=4,
                        ),
                        dbc.Col(
                            dbc.Button([html.I(className="bi bi-trash me-1"), "Delete"],
                                       id="bulk-delete", color="outline-danger", size="sm", className="w-100"),
                            xs=6, sm=4,
                        ),
                        dbc.Col(
                            dbc.Button("Clear selection", id="bulk-clear", color="link", size="sm",
                                       className="w-100 text-muted"),
                            xs=6, sm=4,
                        ),
                    ],
                    className="g-2 align-items-center",
                ),
                html.Div(
                    "Merge keeps the richest entry, adds up the quantities, and combines "
                    "every photo, spec and tag. One-click Undo after.",
                    className="text-muted mt-1", style={"fontSize": "0.75rem"},
                ),
            ]
        ),
        id="bulk-bar",
        className="mb-2 border-primary",
        style={"display": "none"},
    )


def breakdown_card():
    """Compact 'where is everything' overview: totals grouped by type, location & category."""
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
                                html.H6([html.I(className="bi bi-collection me-1"), "By Type"], className="text-muted"),
                                html.Div(id="breakdown-type"),
                            ],
                            xs=12, md=4, className="mb-3 mb-md-0",
                        ),
                        dbc.Col(
                            [
                                html.H6([html.I(className="bi bi-geo-alt me-1"), "By Location"], className="text-muted"),
                                html.Div(id="breakdown-location"),
                            ],
                            xs=12, md=4, className="mb-3 mb-md-0",
                        ),
                        dbc.Col(
                            [
                                html.H6([html.I(className="bi bi-tags me-1"), "By Category"], className="text-muted"),
                                html.Div(id="breakdown-category"),
                            ],
                            xs=12, md=4,
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
                        html.Div(
                            [
                                dbc.Button(
                                    [html.I(className="bi bi-magic me-1"), "Smart Organize"],
                                    id="organize-button",
                                    color="primary",
                                    size="sm",
                                    n_clicks=0,
                                    title="Group like items into auto-created bins",
                                ),
                                dbc.Button(
                                    [html.I(className="bi bi-box-seam me-1"), "Set up bins"],
                                    id="open-bins",
                                    color="secondary",
                                    size="sm",
                                    n_clicks=0,
                                    title="Say how many bins you have, name their bags, and pack items into them",
                                ),
                                dbc.Button(
                                    [html.I(className="bi bi-layers me-1"), "Merge duplicates",
                                     html.Span(id="dup-count-badge", className="ms-1")],
                                    id="open-dups",
                                    color="secondary",
                                    size="sm",
                                    n_clicks=0,
                                    title="Find identical / very similar items and combine them",
                                ),
                            ],
                            className="d-flex flex-wrap gap-2",
                        ),
                    ],
                    className="d-flex align-items-center justify-content-between",
                )
            ),
            dbc.CardBody(
                [
                    html.Div(
                        "Set up how many bins you have and the bags inside each one, then see "
                        "what's stored where. Smart Organize can also auto-group related items "
                        "into labelled bins for you.",
                        className="text-muted small mb-2",
                    ),
                    html.Div(id="storage-map"),
                ]
            ),
        ],
        className="mt-4 shadow-sm",
    )


def bins_modal():
    """Define real containers (with capacities) and pack items into them."""
    return html.Div(
        [
            dcc.Store(id="fit-plan"),
            dbc.Modal(
                [
                    dbc.ModalHeader(
                        dbc.ModalTitle([html.I(className="bi bi-box-seam me-2"), "Storage bins & auto-fit"])
                    ),
                    dbc.ModalBody(
                        [
                            # --- Step 1: how many bins do you have? ---
                            html.Div(
                                [html.I(className="bi bi-1-circle me-2"),
                                 html.Strong("How many bins do you have?")],
                                className="mb-1",
                            ),
                            dbc.Row(
                                [
                                    dbc.Col(
                                        dbc.InputGroup([
                                            dbc.InputGroupText("Bins"),
                                            dbc.Input(id="bin-count", type="number", min=1,
                                                      max=200, step=1, placeholder="9"),
                                        ]),
                                        xs=6, sm=3,
                                    ),
                                    dbc.Col(
                                        dbc.InputGroup([
                                            dbc.InputGroupText("Prefix"),
                                            dbc.Input(id="bin-prefix", value="BIN"),
                                        ]),
                                        xs=6, sm=3,
                                    ),
                                    dbc.Col(
                                        dbc.InputGroup([
                                            dbc.InputGroupText("Slots"),
                                            dbc.Input(id="bin-capacity", type="number", min=1,
                                                      step=1, value=25),
                                        ]),
                                        xs=6, sm=3,
                                    ),
                                    dbc.Col(
                                        dbc.Button(
                                            [html.I(className="bi bi-plus-square me-1"), "Generate"],
                                            id="generate-bins", color="primary", outline=True,
                                            n_clicks=0, className="w-100",
                                        ),
                                        xs=6, sm=3,
                                    ),
                                ],
                                className="g-2",
                            ),
                            html.Div(
                                "Creates rows like BIN-01 … BIN-09 below. Existing bins are kept — "
                                "then add bag names to any bin.",
                                className="text-muted small mt-1 mb-2",
                            ),
                            html.Hr(className="my-2"),
                            # --- Step 2: fine-tune, incl. bags per bin ---
                            html.Div(
                                [html.I(className="bi bi-2-circle me-2"),
                                 html.Strong("Name your bins & their bags")],
                                className="mb-1",
                            ),
                            html.Div(
                                [
                                    "One bin per line —  ",
                                    html.Code("CODE | Name | slots | bag1, bag2, bag3"),
                                    ".  Name, slots and bags are optional; bags are the "
                                    "separate bags of stuff inside that bin.",
                                ],
                                className="text-muted small mb-1",
                            ),
                            dbc.Textarea(
                                id="containers-text",
                                rows=6,
                                placeholder=("BIN-01 | Small parts drawer | 20 | resistors, capacitors, diodes\n"
                                             "BIN-02 | Cables tote | 40 | usb, ribbon, power\n"
                                             "SHELF-01 | Workshop shelf | 30"),
                            ),
                            dbc.Row(
                                [
                                    dbc.Col(
                                        dbc.Button(
                                            [html.I(className="bi bi-save me-1"), "Save bins"],
                                            id="save-containers", color="secondary",
                                            n_clicks=0, className="w-100 mt-2",
                                        ),
                                        xs=12, sm=6,
                                    ),
                                    dbc.Col(
                                        dbc.Button(
                                            [html.I(className="bi bi-box-seam me-1"), "Fit items into bins"],
                                            id="fit-bins", color="primary",
                                            n_clicks=0, className="w-100 mt-2",
                                        ),
                                        xs=12, sm=6,
                                    ),
                                ],
                                className="g-2",
                            ),
                            html.Div(id="bins-status", className="small mt-1"),
                            html.Hr(),
                            dcc.Loading(html.Div(id="fit-result"), type="default"),
                        ]
                    ),
                    dbc.ModalFooter(
                        [
                            dbc.Button(
                                [html.I(className="bi bi-check2-circle me-1"), "Apply fit"],
                                id="apply-fit", color="success", n_clicks=0,
                            ),
                            dbc.Button("Close", id="close-bins-modal", color="secondary", n_clicks=0),
                        ],
                        className="justify-content-between",
                    ),
                ],
                id="bins-modal",
                is_open=False,
                size="lg",
                centered=True,
                scrollable=True,
            ),
        ]
    )


def duplicates_modal():
    """Find identical / very similar items and combine them into one."""
    return html.Div(
        [
            dcc.Store(id="dups-plan"),  # scanned groups, for the apply step
            dbc.Modal(
                [
                    dbc.ModalHeader(
                        dbc.ModalTitle([html.I(className="bi bi-layers me-2"), "Merge duplicate items"])
                    ),
                    dbc.ModalBody(
                        [
                            html.Div(
                                "Scanned a pile of stuff and entered the same thing twice? This finds "
                                "identical or very similar entries and combines them — adding up the "
                                "quantities and keeping every photo, spec and tag.",
                                className="text-muted small mb-2",
                            ),
                            dbc.Row(
                                [
                                    dbc.Col(
                                        [
                                            dbc.Label("How alike is 'a duplicate'?", className="small mb-1"),
                                            dbc.RadioItems(
                                                id="dups-level",
                                                options=[
                                                    {"label": " Identical only", "value": "identical"},
                                                    {"label": " Similar (recommended)", "value": "balanced"},
                                                    {"label": " Loosely similar", "value": "loose"},
                                                ],
                                                value="balanced",
                                                inline=True,
                                            ),
                                            html.Div(
                                                "Loosely similar also groups same-kind items that differ only "
                                                "by size or model — e.g. a 1/4\" drive and a 7mm socket — so you "
                                                "can decide whether to combine them.",
                                                className="text-muted mt-1",
                                                style={"fontSize": "0.78rem"},
                                            ),
                                        ],
                                        xs=12, sm=8,
                                    ),
                                    dbc.Col(
                                        dbc.Button(
                                            [html.I(className="bi bi-search me-1"), "Scan"],
                                            id="dups-scan", color="primary",
                                            n_clicks=0, className="w-100 mt-2 mt-sm-4",
                                        ),
                                        xs=12, sm=4,
                                    ),
                                ],
                                className="g-2 align-items-start",
                            ),
                            html.Div(id="dups-status", className="small mt-2"),
                            html.Hr(),
                            dcc.Loading(html.Div(id="dups-result"), type="default"),
                        ]
                    ),
                    dbc.ModalFooter(
                        [
                            dbc.Button(
                                [html.I(className="bi bi-check2-all me-1"), "Merge selected"],
                                id="dups-apply", color="success", n_clicks=0,
                            ),
                            dbc.Button("Close", id="close-dups-modal", color="secondary", n_clicks=0),
                        ],
                        className="justify-content-between",
                    ),
                ],
                id="dups-modal",
                is_open=False,
                size="lg",
                centered=True,
                scrollable=True,
            ),
        ]
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
