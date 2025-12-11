from __future__ import annotations
from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc
from config import DATATABLE_PAGE_SIZE, TOAST_DURATION, LOW_STOCK_THRESHOLD

def kpi_bar():
    return dbc.Row(
        [
            dbc.Col(
                dbc.Card(
                    dbc.CardBody(
                        [
                            html.Div(
                                [
                                    html.I(className="bi bi-box-seam me-2 text-primary"),
                                    html.Span("Total Items", className="kpi-sub"),
                                ]
                            ),
                            html.Div(id="kpi-total", className="kpi-number mt-1 text-primary"),
                        ]
                    ),
                    className="h-100 shadow-sm",
                ),
                md=6,
                className="mb-3",
            ),
            dbc.Col(
                dbc.Card(
                    dbc.CardBody(
                        [
                            html.Div(
                                [
                                    html.I(className="bi bi-exclamation-triangle-fill me-2 text-warning"),
                                    html.Span(f"Low Stock (< {LOW_STOCK_THRESHOLD})", className="kpi-sub"),
                                ]
                            ),
                            html.Div(id="kpi-low", className="kpi-number mt-1 text-warning"),
                        ]
                    ),
                    className="h-100 shadow-sm",
                ),
                md=6,
                className="mb-3",
            ),
        ],
        className="g-3",
    )

def sidebar_form():
    return html.Div(
        [
            dcc.Store(id="editing-id"),
            dbc.Card(
                [
                    dbc.CardHeader("Add / Edit Item"),
                    dbc.CardBody(
                        [
                            dbc.Label("Name"),
                            dbc.Input(id="item-name", debounce=True, placeholder="e.g., Blue Widget"),
                            dbc.Label("Description", className="mt-2"),
                            dbc.Textarea(id="item-desc", placeholder="Optional details…", rows=3),
                            dbc.Label("Quantity", className="mt-2"),
                            dbc.Input(id="item-qty", type="number", min=0, step=1),
                            dbc.Label("Image", className="mt-3"),
                            dcc.Upload(
                                id="image-upload",
                                children=html.Div(["Drag & drop or ", html.A("browse")]),
                                multiple=False,
                                style={
                                    "border": "1px dashed #999",
                                    "padding": "12px",
                                    "textAlign": "center",
                                    "borderRadius": "8px",
                                },
                            ),
                            html.Img(
                                id="image-preview",
                                style={"maxWidth": "100%", "marginTop": "10px", "display": "none"},
                            ),
                            dbc.Row(
                                [
                                    dbc.Col(
                                        dbc.Button(
                                            "Save", id="save-button", color="primary", className="w-100 mt-3"
                                        ),
                                        width=6,
                                    ),
                                    dbc.Col(
                                        dbc.Button(
                                            "Delete", id="delete-button", color="danger", className="w-100 mt-3"
                                        ),
                                        width=3,
                                    ),
                                    dbc.Col(
                                        dbc.Button(
                                            "Cancel", id="cancel-button", color="secondary", className="w-100 mt-3"
                                        ),
                                        width=3,
                                    ),
                                ]
                            ),
                        ]
                    ),
                ],
                className="shadow-sm",
            ),
            dbc.Card(
                [
                    dbc.CardHeader("Search"),
                    dbc.CardBody(dbc.Input(id="search-bar", placeholder="Search name / description / OCR…", debounce=True)),
                ],
                className="mt-3 shadow-sm",
            ),
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

def inventory_table():
    columns = [
        {"name": "", "id": "select", "presentation": "markdown"},
        {"name": "Image", "id": "image", "presentation": "markdown"},
        {"name": "Name", "id": "name"},
        {"name": "Description", "id": "description"},
        {"name": "Qty", "id": "qty", "type": "numeric"},
        {"name": "OCR Text", "id": "ocr_text"},
        {"name": "id", "id": "id", "hideable": True},
        {"name": "image_filename", "id": "image_filename", "hideable": True},
        {"name": "full_src", "id": "full_src", "hideable": True},
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
        },
        style_cell={
            "padding": "10px",
            "fontSize": 15,
            "whiteSpace": "normal",
            "height": "auto",
            "textAlign": "left",
            "color": "var(--bs-body-color)",
            "backgroundColor": "var(--bs-body-bg)",
            "borderColor": "var(--bs-border-color)",
        },
        style_cell_conditional=[
            {"if": {"column_id": "select"}, "textAlign": "center", "width": 70, "minWidth": 70, "maxWidth": 70},
            {"if": {"column_id": "description"}, "maxWidth": 300, "overflowWrap": "anywhere", "whiteSpace": "pre-wrap"},
            {"if": {"column_id": "ocr_text"}, "maxWidth": 500, "overflowWrap": "anywhere", "whiteSpace": "pre-wrap"},
            {"if": {"column_id": "image"}, "maxWidth": 150, "textAlign": "center"},
            {"if": {"column_id": "qty"}, "textAlign": "center", "width": 80},
        ],
        style_data_conditional=[
            {"if": {"row_index": "odd"}, "backgroundColor": "var(--bs-table-striped-bg)"},
        ],
        css=[{"selector": "td div", "rule": "overflow: visible; white-space: normal;"}],
    )
    return html.Div([table])

def detail_panel():
    return html.Div(
        [
            dbc.Modal(
                [
                    dbc.ModalHeader(dbc.ModalTitle(id="image-modal-title")),
                    dbc.ModalBody(html.Img(id="image-modal-img", style={"maxWidth": "100%"})),
                    dbc.ModalFooter(dbc.Button("Close", id="close-image-modal", className="ms-auto", n_clicks=0)),
                ],
                id="image-modal",
                is_open=False,
                size="lg",
                centered=True,
                backdrop="static",
            ),
        ]
    )
