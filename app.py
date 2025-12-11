from __future__ import annotations
import os, socket, json, traceback
from dash import Dash, html, dcc, Input, Output, State
import dash_bootstrap_components as dbc
from dash.exceptions import PreventUpdate
from werkzeug.middleware.proxy_fix import ProxyFix  # NEW: reverse-proxy aware

# Config / theme
from config import (
    THEME_LIGHT,
    THEME_DARK,
    THEME_DEFAULT_MODE,
    ASSET_IMAGE_PATH,
    ASSET_THUMB_PATH,
)
from flask import send_from_directory

# UI components
from components import sidebar_form, inventory_table, detail_panel, kpi_bar

# Page layouts
from components_ocr_lab import ocr_lab_layout

# Callback registrars
from callbacks import register_callbacks
from callbacks_ocr_lab import register_ocr_lab_callbacks

BOOTSTRAP_ICONS = "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css"

# Base URL prefix when served behind Caddy (e.g. /inventory)
URL_PREFIX = os.getenv("URL_PREFIX", "/inventory").rstrip("/")
if not URL_PREFIX.startswith("/"):
    URL_PREFIX = "/" + URL_PREFIX

def get_local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip

def _route_key(path: str | None) -> str:
    """
    Normalize paths so that:
      /inventory         → "/"
      /inventory/        → "/"
      /inventory/ocr-lab → "/ocr-lab"
    """
    if not path:
        return "/"

    p = path.split("?", 1)[0]

    # Strip the URL_PREFIX (e.g. /inventory) if present
    if p.startswith(URL_PREFIX):
        p = p[len(URL_PREFIX):] or "/"

    p = p.rstrip("/")
    return p or "/"

# ---- Dash app ----
app = Dash(
    __name__,
    external_stylesheets=[BOOTSTRAP_ICONS],
    suppress_callback_exceptions=True,
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
    # Served under /inventory/ when behind Caddy
    requests_pathname_prefix=URL_PREFIX + "/",
    routes_pathname_prefix=URL_PREFIX + "/",
    assets_url_path=URL_PREFIX + "/assets",
)
app.title = "📦 Inventory Tracker"

# Make the underlying Flask server proxy-aware (respect X-Forwarded-* from Caddy)
server = app.server
server.wsgi_app = ProxyFix(
    server.wsgi_app,
    x_for=1,
    x_proto=1,
    x_host=1,
    x_port=1,
    x_prefix=1,
)

# ---- Static asset routes for images & thumbnails -----------------
# Browser URLs look like:
#   https://<host>:8443/inventory/assets/images/<file>
#   https://<host>:8443/inventory/assets/thumbnails/<file>

@server.route(f"{URL_PREFIX}/assets/thumbnails/<path:filename>")
def serve_thumbnail(filename: str):
    return send_from_directory(str(ASSET_THUMB_PATH), filename, as_attachment=False)


@server.route(f"{URL_PREFIX}/assets/images/<path:filename>")
def serve_image(filename: str):
    return send_from_directory(str(ASSET_IMAGE_PATH), filename, as_attachment=False)

# ---------- Navbar ----------
navbar = dbc.Navbar(
    dbc.Container(
        [
            dbc.NavbarBrand("📦 Inventory OCR", href="/"),
            dbc.Nav(
                [
                    dbc.NavItem(dbc.NavLink("Dashboard", href="/", external_link=False)),
                    dbc.NavItem(dbc.NavLink("🧪 OCR Lab", href="/ocr-lab", external_link=False)),
                ],
                className="ms-3",
                navbar=True,
            ),
            html.Div(
                dbc.Switch(id="theme-switch", label="Dark", value=(THEME_DEFAULT_MODE == "dark"), className="ms-3"),
                className="ms-auto d-flex align-items-center",
            ),
        ],
        fluid=True,
    ),
    id="top-navbar",
    color=("dark" if THEME_DEFAULT_MODE == "dark" else "light"),
    dark=(THEME_DEFAULT_MODE == "dark"),
    className="mb-4",
)

# ---------- Dashboard layout ----------
def dashboard_layout():
    return dbc.Container(
        [
            dcc.Store(id="refresh-seq"),
            html.H2("📦 Inventory Tracker", className="mt-2 mb-2 text-center app-title"),
            kpi_bar(),
            dbc.Row(
                [
                    dbc.Col(sidebar_form(), width=4, className="pe-2"),
                    dbc.Col([inventory_table()], width=8, className="ps-2"),
                ]
            ),
            dbc.Row([dbc.Col(detail_panel(), width=12)], className="mt-4"),
        ],
        fluid=True,
    )

# ---------- App shell ----------
app.layout = html.Div(
    [
        dcc.Location(id="url", refresh=False),
        # Theme links (toggle 'media' to switch)
        html.Link(
            id="theme-light-link",
            rel="stylesheet",
            href=THEME_LIGHT,
            media=("not all" if THEME_DEFAULT_MODE == "dark" else "all"),
        ),
        html.Link(
            id="theme-dark-link",
            rel="stylesheet",
            href=THEME_DARK,
            media=("all" if THEME_DEFAULT_MODE == "dark" else "not all"),
        ),
        navbar,
        # cross-page stores
        dcc.Store(id="image-contents"),
        dcc.Store(id="ocr-target"),
        dcc.Store(id="ocr-result"),
        dcc.Store(id="theme-mode", storage_type="local", data=THEME_DEFAULT_MODE),
        # tiny diagnostics (hidden)
        dcc.Interval(id="diag-interval", interval=4000, n_intervals=0),
        html.Div(id="diag", style={"display": "none"}),
        # seed content so first paint isn't blank
        html.Div(id="page-content", children=dashboard_layout()),
    ]
)

# Important: let Dash see all components/IDs across pages
app.validation_layout = html.Div([dashboard_layout(), ocr_lab_layout()])

# ---------- Router ----------
@app.callback(Output("page-content", "children"), Input("url", "pathname"), prevent_initial_call=False)
def display_page(pathname):
    key = _route_key(pathname)
    try:
        if key == "/ocr-lab":
            return ocr_lab_layout()
        return dashboard_layout()
    except Exception:
        return html.Pre("display_page error:\n" + traceback.format_exc())

# ---------- Theme switcher ----------
@app.callback(
    Output("theme-light-link", "media"),
    Output("theme-dark-link", "media"),
    Output("top-navbar", "color"),
    Output("top-navbar", "dark"),
    Output("theme-switch", "value"),
    Input("theme-mode", "data"),
)
def _apply_theme(mode):
    is_dark = (mode or THEME_DEFAULT_MODE) == "dark"
    return (
        "not all" if is_dark else "all",
        "all" if is_dark else "not all",
        "dark" if is_dark else "light",
        is_dark,
        is_dark,
    )

@app.callback(
    Output("theme-mode", "data", allow_duplicate=True),
    Input("theme-switch", "value"),
    State("theme-mode", "data"),
    prevent_initial_call=True,
)
def _on_switch(is_dark, current):
    desired = "dark" if is_dark else "light"
    if desired == current:
        raise PreventUpdate
    return desired

# ---------- Diagnostics ----------
@app.callback(Output("diag", "children"), Input("diag-interval", "n_intervals"), Input("url", "pathname"))
def _diag(_, path):
    try:
        return json.dumps({"path": path, "callbacks": len(app.callback_map)}, indent=2)
    except Exception:
        return "diag-error"

# ---------- Register feature callbacks ----------
register_callbacks(app)
register_ocr_lab_callbacks(app)

if __name__ == "__main__":
    from waitress import serve

    host = os.environ.get("HOST", "0.0.0.0")
    # Default port aligned with your Caddy backend (PORT=8001)
    port = int(os.environ.get("PORT", 8001))
    ip = get_local_ip()

    # External URL banner (works nicely behind Caddy if PUBLIC_BASE is set)
    public_base = os.environ.get("PUBLIC_BASE", "").rstrip("/")
    if public_base:
        external_url = f"{public_base}{URL_PREFIX}"
    else:
        scheme = os.environ.get("SCHEME", "http")
        external_url = f"{scheme}://{ip}:{port}{URL_PREFIX}"

    print(f"[INFO] Inventory OCR Server running on {external_url}")
    print(f"[INFO] Internal: http://{host}:{port}{URL_PREFIX}")

    serve(server, host=host, port=port, expose_tracebacks=True)
