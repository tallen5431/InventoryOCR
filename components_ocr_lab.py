from __future__ import annotations
from dash import html, dcc
import dash_bootstrap_components as dbc


def _card(title, body, footer=None, className="mb-3 shadow-sm"):
    return dbc.Card(
        [dbc.CardHeader(title), dbc.CardBody(body), (dbc.CardFooter(footer) if footer else html.Div())],
        className=className,
    )


def _slider(label, cid, min_, max_, step, value, tooltip=True, help_text: str | None = None):
    return html.Div(
        [
            dbc.Row(
                [
                    dbc.Col(dbc.Label(label, className="mb-1"), width=6),
                    dbc.Col(html.Div(id=f"{cid}-readout", className="text-end text-muted small"), width=6),
                ],
                className="g-0",
            ),
            dcc.Slider(
                id=cid,
                min=min_,
                max=max_,
                step=step,
                value=value,
                updatemode="drag",
                tooltip={"placement": "bottom"} if tooltip else None,
            ),
            html.Div(help_text, className="text-muted small mt-1") if help_text else html.Div(),
        ],
        className="mb-3",
    )


def ocr_lab_layout():
    return dbc.Container(
        [
            # Stores / downloads
            dcc.Store(id="ocr-lab-orig-bytes"),
            dcc.Store(id="ocr-lab-preview-base"),
            dcc.Store(id="ocr-lab-proc-bytes"),
            dcc.Download(id="ocr-lab-download"),
            dcc.Download(id="ocr-lab-download-img"),

            html.H2("🧪 OCR Lab", className="mt-2 mb-3 text-center"),

            dbc.Row(
                [
                    # Sticky Preview (shown first on mobile)
                    dbc.Col(
                        [
                            html.Div(
                                _card(
                                    "Images",
                                    dcc.Loading(
                                        type="default",
                                        children=dbc.Row(
                                            [
                                                dbc.Col(
                                                    [
                                                        html.Div("Original", className="text-muted small mb-2"),
                                                        html.Img(id="ocr-lab-original", style={"width": "100%", "borderRadius": "10px"}),
                                                    ],
                                                    xs=12,
                                                    sm=6,
                                                    md=6,
                                                    className="mb-3",
                                                ),
                                                dbc.Col(
                                                    [
                                                        html.Div(["Preview ", html.Span(id="ocr-lab-timing", className="ms-2 text-muted small")], className="mb-2"),
                                                        html.Img(id="ocr-lab-preview", style={"width": "100%", "borderRadius": "10px"}),
                                                    ],
                                                    xs=12,
                                                    sm=6,
                                                    md=6,
                                                ),
                                            ],
                                            className="g-3",
                                        ),
                                    ),
                                ),
                                style={"position": "sticky", "top": "70px", "zIndex": 1000},
                                className="mb-3 mb-lg-0",
                            ),
                        ],
                        xs=12,
                        sm=12,
                        md=12,
                        lg=8,
                        xl=8,
                        className="order-1 order-lg-2",
                    ),
                    # Controls + Text
                    dbc.Col(
                        [
                            dcc.Tabs(
                                id="ocr-settings-tabs",
                                value="basic",
                                colors={"border": "#666", "primary": "#0d6efd", "background": "transparent"},
                                className="mb-3",
                                children=[
                                    # ------------ BASIC ------------
                                    dcc.Tab(
                                        label="Basic",
                                        value="basic",
                                        children=[
                                            # Quick actions
                                            dbc.Row(
                                                [
                                                    dbc.Col(
                                                        dbc.RadioItems(
                                                            id="ocr-preset",
                                                            options=[
                                                                {"label": " Receipt", "value": "receipt"},
                                                                {"label": " Label", "value": "label"},
                                                                {"label": " Document", "value": "document"},
                                                            ],
                                                            value=None,
                                                            inline=True,
                                                        ),
                                                        xs=12,
                                                        md=8,
                                                        className="mb-2 mb-md-0",
                                                    ),
                                                    dbc.Col(
                                                        html.Div(
                                                            [
                                                                dbc.Button("↻ Update", id="ocr-preview-refresh",
                                                                           color="secondary", size="sm", className="me-2 w-auto"),
                                                                dbc.Button("Reset", id="ocr-reset",
                                                                           color="outline-secondary", size="sm", className="w-auto"),
                                                            ],
                                                            className="d-flex justify-content-end flex-wrap gap-1",
                                                        ),
                                                        xs=12,
                                                        md=4,
                                                    ),
                                                ],
                                                className="g-2 mb-3 align-items-center",
                                            ),
                                            # Live toggle
                                            dbc.Checklist(
                                                id="ocr-live",
                                                options=[{"label": " Live preview while adjusting", "value": "live"}],
                                                value=["live"],
                                                switch=True,
                                                className="mb-3",
                                            ),
                                            # Load image
                                            _card(
                                                "Load Image",
                                                html.Div(
                                                    [
                                                        dcc.Upload(
                                                            id="ocr-lab-upload",
                                                            children=html.Div(["📂 Drag & drop or ", html.A("browse")]),
                                                            multiple=False,
                                                            style={
                                                                "width": "100%",
                                                                "borderWidth": "1px dashed #999",
                                                                "borderRadius": "10px",
                                                                "textAlign": "center",
                                                                "padding": "16px",
                                                            },
                                                        ),
                                                        dbc.InputGroup(
                                                            [
                                                                dbc.Input(id="ocr-lab-path", placeholder="Path to an image…"),
                                                                dbc.Button("Load", id="ocr-lab-load-file", color="secondary"),
                                                            ],
                                                            className="mt-2",
                                                        ),
                                                    ]
                                                ),
                                            ),
                                            # Essentials
                                            _slider("Preview size (px)", "ocr-preview-size", 400, 2000, 50, 1200,
                                                    help_text="Affects preview speed/quality. OCR can use preview (Options tab) or full image."),
                                            dbc.Checklist(
                                                id="ocr-bool-toggles",
                                                options=[
                                                    {"label": " Denoise", "value": "denoise"},
                                                    {"label": " Sharpen", "value": "sharpen"},
                                                    {"label": " Adaptive", "value": "adaptive"},
                                                    {"label": " Invert", "value": "invert"},
                                                ],
                                                value=["denoise", "adaptive"],
                                                switch=True,
                                                className="mb-2",
                                            ),
                                            _slider("Brightness", "ocr-brightness", 0.5, 2.0, 0.1, 1.0),
                                            _slider("Contrast", "ocr-contrast", 0.5, 2.0, 0.1, 1.0),
                                            _slider("Threshold", "ocr-threshold", 0, 255, 1, 140),
                                        ],
                                    ),
                                    # ------------ ADVANCED ------------
                                    dcc.Tab(
                                        label="Advanced",
                                        value="advanced",
                                        children=[
                                            _slider("Gamma", "ocr-gamma", 0.1, 3.0, 0.1, 1.0),
                                            _slider("Denoise Strength", "ocr-denoise-strength", 0, 10, 1, 0),
                                            html.Div(
                                                [
                                                    dbc.Row(
                                                        [
                                                            dbc.Col(dbc.Label("Morphology", className="mb-1"), width=6),
                                                            dbc.Col(html.Div(className="text-end text-muted small"), width=6),
                                                        ],
                                                        className="g-0",
                                                    ),
                                                    dcc.Dropdown(
                                                        id="ocr-morph",
                                                        options=[
                                                            {"label": "None", "value": "none"},
                                                            {"label": "Open", "value": "open"},
                                                            {"label": "Close", "value": "close"},
                                                        ],
                                                        value="none",
                                                        clearable=False,
                                                        className="mb-2",
                                                    ),
                                                ]
                                            ),
                                            _slider("Morph Kernel", "ocr-morph-k", 1, 7, 2, 3),
                                            _slider("Rotate (°)", "ocr-rotate", -15, 15, 0.5, 0.0),
                                            _slider("Sharpen Amount", "ocr-sharpen-amt", 0.0, 2.0, 0.1, 0.7),
                                            html.Div(
                                                [
                                                    dbc.Row(
                                                        [
                                                            dbc.Col(dbc.Label("Binarization", className="mb-1"), width=6),
                                                            dbc.Col(html.Div(className="text-end text-muted small"), width=6),
                                                        ],
                                                        className="g-0",
                                                    ),
                                                    dcc.Dropdown(
                                                        id="ocr-binarize",
                                                        options=[
                                                            {"label": "Global (manual)", "value": "global"},
                                                            {"label": "Otsu (auto)", "value": "otsu"},
                                                            {"label": "Adaptive Mean", "value": "adaptive_mean"},
                                                            {"label": "Adaptive Gaussian", "value": "adaptive_gaussian"},
                                                        ],
                                                        value="global",
                                                        clearable=False,
                                                        className="mb-1",
                                                    ),
                                                    html.Div(id="ocr-mode-hint", className="text-muted small"),
                                                ],
                                                className="mt-1",
                                            ),
                                        ],
                                    ),
                                    # ------------ OCR OPTIONS ------------
                                    dcc.Tab(
                                        label="OCR",
                                        value="options",
                                        children=[
                                            dbc.Row(
                                                [
                                                    dbc.Col(
                                                        dbc.RadioItems(
                                                            id="ocr-profile",
                                                            options=[{"label": " Fast", "value": "fast"}, {"label": " Accurate", "value": "accurate"}],
                                                            value="fast",
                                                            inline=True,
                                                        ),
                                                        xs=12,
                                                        sm=6,
                                                        md=8,
                                                        className="mb-2 mb-sm-0",
                                                    ),
                                                    dbc.Col(
                                                        dcc.Dropdown(
                                                            id="ocr-lang",
                                                            options=[
                                                                {"label": "English (eng)", "value": "eng"},
                                                                {"label": "Spanish (spa)", "value": "spa"},
                                                                {"label": "German (deu)", "value": "deu"},
                                                                {"label": "French (fra)", "value": "fra"},
                                                            ],
                                                            value="eng",
                                                            clearable=False,
                                                        ),
                                                        xs=12,
                                                        sm=6,
                                                        md=4,
                                                    ),
                                                ],
                                                className="g-2 mb-3",
                                            ),
                                            dcc.Dropdown(
                                                id="ocr-psm",
                                                options=[
                                                    {"label": "PSM 6 – Block of text", "value": 6},
                                                    {"label": "PSM 7 – Single line", "value": 7},
                                                    {"label": "PSM 4 – Sparse text", "value": 4},
                                                    {"label": "PSM 3 – Fully auto", "value": 3},
                                                ],
                                                value=6,
                                                clearable=False,
                                                className="mb-2",
                                            ),
                                            dbc.Checklist(
                                                id="ocr-use-preview",
                                                options=[{"label": " Use preview size (faster)", "value": "small"}],
                                                value=["small"],
                                                switch=True,
                                                className="mb-2",
                                            ),
                                            dbc.Checklist(
                                                id="ocr-autorun",
                                                options=[{"label": " Auto-run OCR on preview changes", "value": "on"}],
                                                value=[],
                                                switch=True,
                                                className="mb-2",
                                            ),
                                        ],
                                    ),
                                    # ------------ TEXT ------------
                                    dcc.Tab(
                                        label="Text",
                                        value="text",
                                        children=[
                                            dcc.Textarea(
                                                id="ocr-lab-text",
                                                style={"width": "100%", "height": "250px"},
                                                placeholder="Run OCR to populate text…",
                                            ),
                                            html.Div(
                                                [
                                                    html.Div(id="ocr-lab-ocr-meta", className="text-muted small me-3"),
                                                    dcc.Clipboard(target_id="ocr-lab-text", title="Copy",
                                                                  style={"display": "inline-block", "cursor": "pointer"}),
                                                ],
                                                className="mt-2 d-flex align-items-center justify-content-between",
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                        ],
                        xs=12,
                        sm=12,
                        md=12,
                        lg=4,
                        xl=4,
                        className="order-2 order-lg-1",
                    ),
                ],
                className="g-3",
            ),

            # Sticky footer
            dbc.Navbar(
                dbc.Container(
                    [
                        dbc.Button("▶ Run OCR", id="ocr-lab-run", color="primary", className="me-2"),
                        dbc.Button("💾 Save to Item", id="ocr-lab-save-to-item", color="success", className="me-2"),
                        dbc.Button("⬇ Download Text", id="ocr-lab-download-btn", color="secondary", className="me-2"),
                        dbc.Button("⬇ Download Image", id="ocr-lab-download-img-btn", color="secondary"),
                        html.Div(id="ocr-lab-status", className="ms-3 small"),
                    ]
                ),
                fixed="bottom",
                color="light",
                className="shadow-sm py-2",
            ),
        ],
        fluid=True,
        style={"paddingBottom": "64px"},
    )
