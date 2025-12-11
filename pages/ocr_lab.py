# pages/ocr_lab.py

import io
import base64
import dash
from dash import dcc, html, Input, Output, State
import dash_bootstrap_components as dbc
from PIL import Image
import cv2
import numpy as np
import pytesseract

dash.register_page(__name__, path="/ocr-lab", name="OCR Lab")

layout = dbc.Container([
    html.H2("🧪 OCR Lab"),
    html.P("Experiment with OCR settings without affecting your inventory."),

    dbc.Row([
        dbc.Col([
            dcc.Upload(
                id="ocr-upload",
                children=html.Div(["Drag & Drop or ", html.A("Select an Image")]),
                style={
                    "width": "100%", "height": "80px", "lineHeight": "80px",
                    "borderWidth": "1px", "borderStyle": "dashed",
                    "borderRadius": "5px", "textAlign": "center"
                },
                multiple=False
            ),
            html.Br(),
            dbc.Label("OCR Language"),
            dcc.Input(id="ocr-lang", type="text", value="eng", debounce=True),

            dbc.Label("Preprocessing"),
            dbc.Checklist(
                id="ocr-preproc",
                options=[
                    {"label": "Grayscale", "value": "gray"},
                    {"label": "Threshold", "value": "thresh"},
                    {"label": "Denoise", "value": "denoise"},
                    {"label": "Sharpen", "value": "sharpen"},
                    {"label": "Adaptive Threshold", "value": "adaptive"}
                ],
                value=["gray"]
            ),
        ], md=4),

        dbc.Col([
            html.H5("Processed Preview"),
            html.Img(id="ocr-preview", style={"maxWidth": "100%"}),
            html.H5("OCR Output"),
            html.Pre(id="ocr-output", style={
                "whiteSpace": "pre-wrap",
                "backgroundColor": "#f8f9fa",
                "padding": "10px",
                "border": "1px solid #ddd"
            }),
        ], md=8),
    ])
], fluid=True)


def preprocess_image(pil_img, steps):
    img = np.array(pil_img)

    if "gray" in steps:
        img = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    if "thresh" in steps:
        _, img = cv2.threshold(img, 150, 255, cv2.THRESH_BINARY)
    if "adaptive" in steps:
        img = cv2.adaptiveThreshold(
            img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 11, 2
        )
    if "denoise" in steps:
        img = cv2.fastNlMeansDenoising(img, None, 30, 7, 21)
    if "sharpen" in steps:
        kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
        img = cv2.filter2D(img, -1, kernel)

    return Image.fromarray(img)


@dash.callback(
    Output("ocr-preview", "src"),
    Output("ocr-output", "children"),
    Input("ocr-upload", "contents"),
    State("ocr-upload", "filename"),
    State("ocr-lang", "value"),
    State("ocr-preproc", "value"),
    prevent_initial_call=True
)
def run_ocr(contents, filename, lang, steps):
    if not contents:
        return dash.no_update, dash.no_update

    content_type, content_string = contents.split(",")
    decoded = base64.b64decode(content_string)
    pil_img = Image.open(io.BytesIO(decoded)).convert("RGB")

    processed_img = preprocess_image(pil_img, steps)

    ocr_text = pytesseract.image_to_string(processed_img, lang=lang or "eng")

    buf = io.BytesIO()
    processed_img.save(buf, format="PNG")
    preview_b64 = base64.b64encode(buf.getvalue()).decode()

    return f"data:image/png;base64,{preview_b64}", ocr_text.strip()
