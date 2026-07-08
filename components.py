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
                        html.Span([html.I(className="bi bi-plus-circle me-2"), "Add / Edit Item"])
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
                            # Datalists power the type-ahead suggestions above.
                            html.Datalist(id="category-datalist"),
                            html.Datalist(id="location-datalist"),

                            dbc.Label("Quantity", className="mt-2"),
                            dbc.Input(id="item-qty", type="number", min=0, step=1, value=1),

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
                            dbc.Row(
                                [
                                    dbc.Col(
                                        dbc.Button(
                                            [html.I(className="bi bi-save me-1"), "Save"],
                                            id="save-button", color="primary", className="w-100 mt-3",
                                        ),
                                        xs=12, sm=12, md=6, lg=6,
                                    ),
                                    dbc.Col(
                                        dbc.Button(
                                            [html.I(className="bi bi-trash me-1"), "Delete"],
                                            id="delete-button", color="danger", className="w-100 mt-3",
                                        ),
                                        xs=6, sm=6, md=3, lg=3,
                                    ),
                                    dbc.Col(
                                        dbc.Button(
                                            [html.I(className="bi bi-x-lg me-1"), "Cancel"],
                                            id="cancel-button", color="secondary", className="w-100 mt-3",
                                        ),
                                        xs=6, sm=6, md=3, lg=3,
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
        {"name": "Image", "id": "image", "presentation": "markdown"},
        {"name": "Name", "id": "name"},
        {"name": "Category", "id": "category", "hideable": True},
        {"name": "Location", "id": "location", "hideable": True},
        {"name": "Qty", "id": "qty", "type": "numeric"},
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
            "padding": "12px 8px",
            "fontSize": 14,
            "whiteSpace": "normal",
            "height": "auto",
            "textAlign": "left",
            "color": "var(--bs-body-color)",
            "backgroundColor": "var(--bs-body-bg)",
            "borderColor": "var(--bs-border-color)",
            "minWidth": "70px",
        },
        style_cell_conditional=[
            {"if": {"column_id": "name"}, "minWidth": "120px", "maxWidth": "220px", "fontWeight": "500"},
            {"if": {"column_id": "category"}, "minWidth": "90px", "maxWidth": "140px"},
            {"if": {"column_id": "location"}, "minWidth": "90px", "maxWidth": "160px"},
            {"if": {"column_id": "description"}, "minWidth": "150px", "maxWidth": "300px", "overflowWrap": "anywhere", "whiteSpace": "pre-wrap"},
            {"if": {"column_id": "ocr_text"}, "minWidth": "150px", "maxWidth": "400px", "overflowWrap": "anywhere", "whiteSpace": "pre-wrap"},
            {"if": {"column_id": "image"}, "width": "120px", "minWidth": "100px", "maxWidth": "160px", "textAlign": "center"},
            {"if": {"column_id": "qty"}, "textAlign": "center", "width": "60px", "minWidth": "60px", "maxWidth": "80px"},
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
