"""Operations tab — track the **materials** you buy to run the business and the
production **batches** they roll up into (cost per unit included).

This view deliberately mirrors the dashboard's look and reuses its patterns:
the same photo/document upload dropzones, the same DataTable styling, the same
KPI cards. Everything here is namespaced ``op-*`` so it never collides with the
inventory dashboard's component ids. All the heavy lifting (saving photos,
attaching invoices, parsing them, the cost model) lives in
:mod:`operations_data`, :mod:`utils` and :mod:`invoice_parse`.
"""
from __future__ import annotations

from dash import dash_table, dcc, html
import dash_bootstrap_components as dbc

from config import DATATABLE_PAGE_SIZE


# --------------------------------------------------------------------
# KPI bar
# --------------------------------------------------------------------

def _kpi_card(icon, color, label, value_id):
    return dbc.Col(
        dbc.Card(
            dbc.CardBody(
                [
                    html.Div(
                        [html.I(className=f"bi {icon} me-2 {color}"),
                         html.Span(label, className="kpi-sub")],
                        className="d-flex align-items-center",
                    ),
                    html.Div(id=value_id, className=f"kpi-number mt-1 {color}"),
                ]
            ),
            className="h-100 shadow-sm",
        ),
        xs=6, sm=6, md=3, lg=3, className="mb-3",
    )


def _op_kpi_bar():
    return dbc.Row(
        [
            _kpi_card("bi-boxes", "text-primary", "Materials", "op-kpi-materials"),
            _kpi_card("bi-cash-stack", "text-success", "Total Spend", "op-kpi-spend"),
            _kpi_card("bi-collection", "text-info", "Batches", "op-kpi-batches"),
            _kpi_card("bi-cash-coin", "text-warning", "Avg Cost / Unit", "op-kpi-perunit"),
        ],
        className="g-3 mb-2",
    )


# --------------------------------------------------------------------
# Materials — add / edit form
# --------------------------------------------------------------------

def _material_form():
    return dbc.Collapse(
        dbc.Card(
            [
                dbc.CardHeader(
                    html.Div(
                        [
                            html.Span([html.I(className="bi bi-plus-circle me-2"),
                                       "Add / Edit Material"]),
                            html.Span(id="op-mat-form-badge",
                                      className="badge bg-secondary ms-2"),
                        ],
                        className="d-flex align-items-center justify-content-between",
                    )
                ),
                dbc.CardBody(
                    [
                        dbc.Label("Name"),
                        dbc.Input(id="op-mat-name", debounce=True,
                                  placeholder="e.g., 12×18 Birch Plywood — or leave blank to auto-number"),
                        html.Div(
                            [html.I(className="bi bi-phone me-1"),
                             "Snap a photo and Save — a blank name auto-numbers "
                             "(Material 0001). Fill in details later."],
                            className="text-muted small mt-1",
                        ),

                        dbc.Row(
                            [
                                dbc.Col(
                                    [
                                        dbc.Label("Type", className="mt-2"),
                                        dbc.Input(id="op-mat-type", debounce=True,
                                                  placeholder="Boards, Packaging, Shipping, Marketing…",
                                                  list="op-mat-type-datalist", autoComplete="off"),
                                    ],
                                    xs=12, sm=6,
                                ),
                                dbc.Col(
                                    [
                                        dbc.Label("Vendor / supplier", className="mt-2"),
                                        dbc.Input(id="op-mat-vendor", debounce=True,
                                                  placeholder="e.g., Home Depot",
                                                  list="op-mat-vendor-datalist", autoComplete="off"),
                                    ],
                                    xs=12, sm=6,
                                ),
                            ],
                            className="g-2",
                        ),

                        # ----- Batch assignment -----
                        dbc.Label([html.I(className="bi bi-collection me-1"),
                                   "Order for batch"], className="mt-3"),
                        dbc.Row(
                            [
                                dbc.Col(
                                    dcc.Dropdown(
                                        id="op-mat-batch",
                                        placeholder="— Unassigned —",
                                        options=[], value=None,
                                        clearable=True, className="op-dropdown",
                                    ),
                                    xs=12, sm=7,
                                ),
                                dbc.Col(
                                    dbc.Input(id="op-mat-new-batch", debounce=True,
                                              placeholder="…or type a new batch name"),
                                    xs=12, sm=5, className="mt-2 mt-sm-0",
                                ),
                            ],
                            className="g-2",
                        ),
                        html.Div(
                            "Group everything you bought for one production run so its cost adds up.",
                            className="text-muted small mt-1",
                        ),

                        # ----- Quantity + cost -----
                        dbc.Row(
                            [
                                dbc.Col(
                                    [
                                        dbc.Label("Quantity", className="mt-2"),
                                        dbc.Input(id="op-mat-qty", type="number", min=0,
                                                  step=1, value=1),
                                    ],
                                    xs=4,
                                ),
                                dbc.Col(
                                    [
                                        dbc.Label("Unit cost", className="mt-2"),
                                        dbc.Input(id="op-mat-unit-cost", debounce=True,
                                                  placeholder="$0.00"),
                                    ],
                                    xs=4,
                                ),
                                dbc.Col(
                                    [
                                        dbc.Label("Total cost", className="mt-2"),
                                        dbc.Input(id="op-mat-total-cost", debounce=True,
                                                  placeholder="auto"),
                                    ],
                                    xs=4,
                                ),
                            ],
                            className="g-2",
                        ),
                        html.Div(
                            "Leave Total blank to compute Quantity × Unit cost.",
                            className="text-muted small mt-1",
                        ),

                        dbc.Row(
                            [
                                dbc.Col(
                                    [
                                        dbc.Label("Order #", className="mt-2"),
                                        dbc.Input(id="op-mat-order", debounce=True,
                                                  placeholder="e.g., 112-4472839"),
                                    ],
                                    xs=12, sm=6,
                                ),
                                dbc.Col(
                                    [
                                        dbc.Label("Purchase date", className="mt-2"),
                                        dbc.Input(id="op-mat-date", debounce=True,
                                                  placeholder="YYYY-MM-DD"),
                                    ],
                                    xs=12, sm=6,
                                ),
                            ],
                            className="g-2",
                        ),

                        html.Datalist(id="op-mat-type-datalist"),
                        html.Datalist(id="op-mat-vendor-datalist"),

                        dbc.Label("Notes / description", className="mt-2"),
                        dbc.Textarea(id="op-mat-desc", placeholder="Optional details…", rows=2),

                        dbc.Label("Specifications", className="mt-2"),
                        dbc.Textarea(id="op-mat-specs", rows=2,
                                     placeholder="One per line — e.g. 18mm thickness, B/BB grade"),

                        dbc.Label("Tags", className="mt-2"),
                        dbc.Input(id="op-mat-tags", debounce=True,
                                  placeholder="comma,separated,tags"),

                        # ----- Photos -----
                        dbc.Label("Photos", className="mt-3"),
                        dcc.Upload(
                            id="op-mat-image-upload",
                            children=html.Div(
                                [
                                    html.Div("📷", className="upload-icon"),
                                    html.Div([html.Strong("Take photos"), " or ",
                                              html.A("choose files")]),
                                    html.Div("Snap several — they stack up on this material.",
                                             className="text-muted small mt-1"),
                                ]
                            ),
                            multiple=True, accept="image/*", className="upload-dropzone",
                        ),
                        html.Div(id="op-mat-gallery", className="mt-2"),
                        dcc.Store(id="op-mat-images", data=[]),

                        # ----- Documents / invoices -----
                        dbc.Label([html.I(className="bi bi-paperclip me-1"),
                                   "Invoices, specs & documents"], className="mt-3"),
                        dcc.Upload(
                            id="op-mat-doc-upload",
                            children=html.Div(
                                [
                                    html.Div("🧾", className="upload-icon"),
                                    html.Div([html.Strong("Attach a file"), " or ",
                                              html.A("choose files")]),
                                    html.Div("PDF, image, HTML or spec sheet. An invoice is read "
                                             "to auto-fill vendor / date / total.",
                                             className="text-muted small mt-1"),
                                ]
                            ),
                            multiple=True, className="upload-dropzone",
                        ),
                        html.Div(id="op-mat-doc-status", className="small mt-1"),
                        html.Div(id="op-mat-doc-list", className="mt-2"),
                        dcc.Store(id="op-mat-attachments", data=[]),

                        # ----- Actions -----
                        html.Hr(),
                        dbc.Row(
                            [
                                dbc.Col(
                                    dbc.Button([html.I(className="bi bi-save me-1"), "Save material"],
                                               id="op-mat-save", color="primary", className="w-100"),
                                    xs=12, sm=6,
                                ),
                                dbc.Col(
                                    dbc.Button([html.I(className="bi bi-x-circle me-1"), "Cancel"],
                                               id="op-mat-cancel", color="secondary",
                                               outline=True, className="w-100 mt-2 mt-sm-0"),
                                    xs=6, sm=3,
                                ),
                                dbc.Col(
                                    dbc.Button([html.I(className="bi bi-trash me-1"), "Delete"],
                                               id="op-mat-delete", color="danger", outline=True,
                                               className="w-100 mt-2 mt-sm-0", disabled=True),
                                    xs=6, sm=3,
                                ),
                            ],
                            className="g-2",
                        ),
                    ]
                ),
            ],
            className="mb-3 shadow-sm",
        ),
        id="op-mat-form-collapse",
        is_open=False,
    )


def _materials_toolbar():
    return html.Div(
        [
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Button([html.I(className="bi bi-plus-lg me-1"), "Add material"],
                                   id="op-mat-add-toggle", color="primary", className="w-100"),
                        xs=12, sm="auto",
                    ),
                    dbc.Col(
                        dbc.Input(id="op-mat-search", type="search", debounce=True,
                                  placeholder="🔎 Search materials…"),
                        xs=12, sm=True,
                    ),
                    dbc.Col(
                        dcc.Dropdown(id="op-mat-filter-type", placeholder="All types",
                                     options=[], className="op-dropdown"),
                        xs=6, sm=3,
                    ),
                    dbc.Col(
                        dcc.Dropdown(id="op-mat-filter-batch", placeholder="All batches",
                                     options=[], className="op-dropdown"),
                        xs=6, sm=3,
                    ),
                    dbc.Col(
                        dbc.Button([html.I(className="bi bi-download me-1"), "CSV"],
                                   id="op-mat-export", color="secondary", outline=True,
                                   className="w-100"),
                        xs=12, sm="auto",
                    ),
                ],
                className="g-2 align-items-center mb-2",
            ),
            # Bulk actions appear when rows are ticked.
            dbc.Collapse(
                dbc.Card(
                    dbc.CardBody(
                        dbc.Row(
                            [
                                dbc.Col(html.Div(id="op-mat-bulk-label",
                                                 className="fw-semibold"),
                                        xs=12, md="auto", className="d-flex align-items-center"),
                                dbc.Col(
                                    dcc.Dropdown(id="op-mat-bulk-batch",
                                                 placeholder="Assign to batch…",
                                                 options=[], className="op-dropdown"),
                                    xs=12, md=4,
                                ),
                                dbc.Col(
                                    dbc.Button("Assign", id="op-mat-bulk-apply",
                                               color="success", size="sm", className="w-100"),
                                    xs=6, md="auto",
                                ),
                                dbc.Col(
                                    dbc.Button("Unassign", id="op-mat-bulk-unassign",
                                               color="secondary", outline=True, size="sm",
                                               className="w-100"),
                                    xs=6, md="auto",
                                ),
                                dbc.Col(
                                    dbc.Button([html.I(className="bi bi-trash me-1"), "Delete"],
                                               id="op-mat-bulk-delete", color="danger",
                                               outline=True, size="sm", className="w-100"),
                                    xs=12, md="auto",
                                ),
                            ],
                            className="g-2 align-items-center",
                        )
                    ),
                    className="mb-2 border-info",
                ),
                id="op-mat-bulk-collapse", is_open=False,
            ),
        ]
    )


_MAT_COLUMNS = [
    {"name": "Photo", "id": "image", "presentation": "markdown"},
    {"name": "Name", "id": "name"},
    {"name": "Type", "id": "material_type"},
    {"name": "Batch", "id": "batch"},
    {"name": "Qty", "id": "qty", "type": "numeric"},
    {"name": "Unit cost", "id": "unit_cost"},
    {"name": "Total", "id": "total_display"},
    {"name": "Vendor", "id": "vendor", "hideable": True},
    {"name": "Date", "id": "purchase_date", "hideable": True},
    {"name": "Docs", "id": "docs", "hideable": True},
    {"name": "id", "id": "id", "hideable": True},
    {"name": "all_images", "id": "all_images", "hideable": True},
]


def _materials_table():
    table = dash_table.DataTable(
        id="op-mat-table",
        columns=_MAT_COLUMNS,
        data=[],
        page_size=DATATABLE_PAGE_SIZE,
        row_selectable="multi",
        selected_rows=[],
        sort_action="native",
        filter_action="none",
        tooltip_delay=0,
        tooltip_duration=None,
        hidden_columns=["id", "all_images"],
        style_table={"height": "62vh", "overflowY": "auto", "overflowX": "auto",
                     "backgroundColor": "var(--bs-body-bg)"},
        style_as_list_view=True,
        style_header={"position": "sticky", "top": 0, "zIndex": 2,
                      "backgroundColor": "var(--bs-tertiary-bg)", "fontWeight": "700",
                      "borderBottom": "1px solid var(--bs-border-color)",
                      "padding": "12px 8px"},
        style_cell={"padding": "12px 12px", "fontSize": 14, "whiteSpace": "normal",
                    "height": "auto", "verticalAlign": "middle", "textAlign": "left",
                    "color": "var(--bs-body-color)", "backgroundColor": "var(--bs-body-bg)",
                    "borderColor": "var(--bs-border-color)", "minWidth": "56px"},
        style_cell_conditional=[
            {"if": {"column_id": "name"}, "minWidth": "150px", "maxWidth": "240px",
             "fontWeight": "600"},
            {"if": {"column_id": "material_type"}, "minWidth": "90px", "maxWidth": "140px"},
            {"if": {"column_id": "batch"}, "minWidth": "110px", "maxWidth": "180px"},
            {"if": {"column_id": "qty"}, "textAlign": "center", "width": "60px"},
            {"if": {"column_id": "unit_cost"}, "textAlign": "right", "width": "90px"},
            {"if": {"column_id": "total_display"}, "textAlign": "right", "width": "96px",
             "fontWeight": "600", "color": "var(--bs-success)"},
            {"if": {"column_id": "docs"}, "width": "64px", "textAlign": "center"},
            {"if": {"column_id": "image"}, "width": "88px", "minWidth": "88px",
             "maxWidth": "96px", "textAlign": "center", "padding": "6px"},
        ],
        style_data_conditional=[
            {"if": {"row_index": "odd"}, "backgroundColor": "var(--bs-table-striped-bg)"},
        ],
        css=[{"selector": "td div", "rule": "overflow: visible; white-space: normal;"}],
    )
    return html.Div(
        [
            html.Div(
                html.Span(["Tick a row to edit · tick several to group into a batch · tap a ",
                           html.I(className="bi bi-image"), " thumbnail to view photos"],
                          className="text-muted small"),
                className="mb-2",
            ),
            html.Div([table], className="table-responsive"),
        ]
    )


def _materials_tab():
    return html.Div(
        [
            _materials_toolbar(),
            _material_form(),
            _materials_table(),
        ],
        className="mt-3",
    )


# --------------------------------------------------------------------
# Batches — form + rollup cards
# --------------------------------------------------------------------

def _batch_form():
    return dbc.Card(
        [
            dbc.CardHeader(
                html.Div(
                    [
                        html.Span([html.I(className="bi bi-collection me-2"),
                                   "New / Edit Batch"]),
                        html.Span(id="op-batch-form-badge",
                                  className="badge bg-secondary ms-2"),
                    ],
                    className="d-flex align-items-center justify-content-between",
                )
            ),
            dbc.CardBody(
                [
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    dbc.Label("Batch name"),
                                    dbc.Input(id="op-batch-name", debounce=True,
                                              placeholder="e.g., Spring 2026 Coaster Run"),
                                ],
                                xs=12, sm=6,
                            ),
                            dbc.Col(
                                [
                                    dbc.Label("Product / what you made"),
                                    dbc.Input(id="op-batch-product", debounce=True,
                                              placeholder="e.g., Engraved coasters"),
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
                                    dbc.Label([html.I(className="bi bi-123 me-1"),
                                               "Units produced"], className="mt-2"),
                                    dbc.Input(id="op-batch-units", type="number", min=0,
                                              step=1, placeholder="e.g., 200"),
                                    html.Div("Drives the cost-per-unit.",
                                             className="text-muted small"),
                                ],
                                xs=6,
                            ),
                            dbc.Col(
                                [
                                    dbc.Label("Date", className="mt-2"),
                                    dbc.Input(id="op-batch-date", debounce=True,
                                              placeholder="YYYY-MM-DD"),
                                ],
                                xs=6,
                            ),
                        ],
                        className="g-2",
                    ),
                    dbc.Label("Notes", className="mt-2"),
                    dbc.Textarea(id="op-batch-notes", rows=2, placeholder="Optional…"),
                    html.Hr(),
                    dbc.Row(
                        [
                            dbc.Col(
                                dbc.Button([html.I(className="bi bi-save me-1"), "Save batch"],
                                           id="op-batch-save", color="primary", className="w-100"),
                                xs=12, sm=6,
                            ),
                            dbc.Col(
                                dbc.Button("Cancel edit", id="op-batch-cancel",
                                           color="secondary", outline=True,
                                           className="w-100 mt-2 mt-sm-0"),
                                xs=12, sm=6,
                            ),
                        ],
                        className="g-2",
                    ),
                    dcc.Store(id="op-editing-batch"),
                ]
            ),
        ],
        className="mb-3 shadow-sm",
    )


def _batches_tab():
    return html.Div(
        [
            _batch_form(),
            html.Div(
                html.Span("Each batch adds up the cost of the materials assigned to it. "
                          "Record how many units it produced to see your cost per unit.",
                          className="text-muted small"),
                className="mb-2",
            ),
            dcc.Loading(html.Div(id="op-batch-list"), type="default"),
        ],
        className="mt-3",
    )


# --------------------------------------------------------------------
# Image viewer modal (shared, opened from the materials table)
# --------------------------------------------------------------------

def _op_image_modal():
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle(id="op-image-modal-title")),
            dbc.ModalBody(
                dbc.Carousel(id="op-image-carousel", items=[], controls=True,
                             indicators=True, interval=None, ride=False)
            ),
            dbc.ModalFooter(dbc.Button("Close", id="op-close-image-modal",
                                       className="ms-auto", n_clicks=0)),
        ],
        id="op-image-modal", is_open=False, size="xl", centered=True, backdrop="static",
    )


# --------------------------------------------------------------------
# Page
# --------------------------------------------------------------------

def operations_layout():
    return dbc.Container(
        [
            # Cross-callback stores
            dcc.Store(id="op-refresh"),            # bump to reload tables/KPIs
            dcc.Store(id="op-editing-mat"),        # material id being edited (or None)
            dcc.Download(id="op-mat-download"),

            html.H2("🏭 Operations", className="mt-2 mb-1 text-center app-title"),
            html.P("Track the materials you buy to run the business — boards, packaging, "
                   "shipping, marketing — and group them into batches to see what each "
                   "production run cost.",
                   className="text-center text-muted mb-3"),

            _op_kpi_bar(),

            # Feedback toast (top-level so it always shows)
            dbc.Toast(id="op-toast", header="Operations", is_open=False, dismissable=True,
                      icon="primary", duration=3500,
                      style={"position": "fixed", "top": 20, "right": 20, "zIndex": 1080,
                             "minWidth": 280}),

            dbc.Tabs(
                [
                    dbc.Tab(_materials_tab(), label="📦 Materials", tab_id="op-tab-materials"),
                    dbc.Tab(_batches_tab(), label="🏭 Batches", tab_id="op-tab-batches"),
                ],
                id="op-tabs", active_tab="op-tab-materials",
            ),

            _op_image_modal(),
        ],
        fluid=True,
    )
