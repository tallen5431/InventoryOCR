"""Price Compare page — upload several product pages for the same kind of item,
find the best price per unit, and track prices over time."""
from __future__ import annotations
from dash import html, dcc
import dash_bootstrap_components as dbc


def price_compare_layout():
    return dbc.Container(
        [
            dcc.Store(id="pc-results"),          # current batch: {products, errors, best}
            dcc.Store(id="pc-saved-refresh"),    # bump to reload the saved dropdown

            html.H2("💲 Price Compare", className="mt-2 mb-1 text-center"),
            html.P(
                "Drop the .html for a few product pages — or a whole search-results page — "
                "and see the best price per unit. Packs of many are priced fairly against "
                "singles, and a results page is split into every listing it holds.",
                className="text-center text-muted mb-3",
            ),

            dbc.Row(
                [
                    # ---------------- Upload + actions ----------------
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.Div(
                                        [html.I(className="bi bi-filetype-html me-2"),
                                         html.Strong("Product pages")],
                                        className="mb-1",
                                    ),
                                    html.Div(
                                        "Open each listing — or a search-results page — in your "
                                        "browser, Save Page As (.html), then drop them all here. "
                                        "A results page is expanded into every listing on it.",
                                        className="text-muted small mb-2",
                                    ),
                                    dcc.Upload(
                                        id="pc-upload",
                                        multiple=True,
                                        accept=".html,.htm,text/html",
                                        className="upload-dropzone",
                                        children=html.Div(
                                            [
                                                html.Div("🗂️", className="upload-icon"),
                                                html.Div([html.Strong("Drop HTML files"),
                                                          " or ", html.A("choose files")]),
                                                html.Div("Compare as many listings as you like",
                                                         className="text-muted small mt-1"),
                                            ]
                                        ),
                                    ),
                                    html.Div(id="pc-filelist", className="small mt-2"),
                                    dbc.Button(
                                        [html.I(className="bi bi-calculator me-1"), "Compare prices"],
                                        id="pc-compare", color="primary", n_clicks=0,
                                        className="w-100 mt-2",
                                    ),
                                    html.Div(id="pc-status", className="small mt-2"),
                                    html.Hr(),
                                    html.Div(
                                        [html.I(className="bi bi-clock-history me-2"),
                                         html.Strong("Track this over time")],
                                        className="mb-1",
                                    ),
                                    html.Div(
                                        "Save this comparison under a name. Re-run it later "
                                        "and the price history builds up.",
                                        className="text-muted small mb-2",
                                    ),
                                    dbc.InputGroup(
                                        [
                                            dbc.Input(id="pc-name", placeholder="e.g. AA Batteries",
                                                      debounce=True),
                                            dbc.Button(
                                                [html.I(className="bi bi-save me-1"), "Save"],
                                                id="pc-save", color="success", n_clicks=0,
                                            ),
                                        ]
                                    ),
                                    html.Div(id="pc-save-status", className="small mt-1"),
                                ]
                            ),
                            className="mb-3 shadow-sm",
                        ),
                        xs=12, lg=4, className="mb-3 mb-lg-0",
                    ),

                    # ---------------- Results ----------------
                    dbc.Col(
                        [
                            html.Div(id="pc-best"),
                            dcc.Loading(html.Div(id="pc-table"), type="default"),
                            html.Div(id="pc-writeback"),
                            html.Div(id="pc-errors", className="mt-2"),
                        ],
                        xs=12, lg=8,
                    ),
                ],
                className="g-3",
            ),

            html.Hr(className="my-4"),

            # ---------------- Tracked searches over time ----------------
            dbc.Card(
                dbc.CardBody(
                    [
                        html.Div(
                            [html.I(className="bi bi-graph-up me-2"),
                             html.Strong("Tracked searches — price over time")],
                            className="mb-2",
                        ),
                        dbc.Row(
                            [
                                dbc.Col(
                                    dcc.Dropdown(id="pc-saved-select", placeholder="Pick a saved search…",
                                                 className="pc-dropdown"),
                                    xs=12, sm=9,
                                ),
                                dbc.Col(
                                    dbc.Button(
                                        [html.I(className="bi bi-trash me-1"), "Delete"],
                                        id="pc-delete", color="outline-danger", n_clicks=0,
                                        className="w-100",
                                    ),
                                    xs=12, sm=3,
                                ),
                            ],
                            className="g-2",
                        ),
                        html.Div(id="pc-history", className="mt-3"),
                    ]
                ),
                className="shadow-sm",
            ),
        ],
        fluid=True,
    )
