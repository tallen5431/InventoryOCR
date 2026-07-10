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
from components import (
    sidebar_form,
    inventory_table,
    detail_panel,
    kpi_bar,
    breakdown_card,
    identify_modal,
    organize_card,
    organize_modal,
    bins_modal,
    duplicates_modal,
    connect_modal,
)

# Page layouts
from components_ocr_lab import ocr_lab_layout
from components_price_compare import price_compare_layout

# Callback registrars
from callbacks import register_callbacks
from callbacks_ocr_lab import register_ocr_lab_callbacks
from callbacks_price_compare import register_price_compare_callbacks

BOOTSTRAP_ICONS = "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css"

# Base URL prefix when served behind a reverse proxy (e.g. /inventory).
# Set URL_PREFIX="" (empty) to serve the app at the site root — this is how the
# HTTP_Server manager runs it, accessed directly at http://<host>:<port>/.
URL_PREFIX = os.getenv("URL_PREFIX", "/inventory").strip().rstrip("/")
if URL_PREFIX and not URL_PREFIX.startswith("/"):
    URL_PREFIX = "/" + URL_PREFIX
# Dash requires pathname prefixes to start and end with "/". At the site root
# that means a bare "/", otherwise "<prefix>/".
PATHNAME_PREFIX = (URL_PREFIX + "/") if URL_PREFIX else "/"
ASSETS_URL_PATH = (URL_PREFIX + "/assets") if URL_PREFIX else "/assets"

def get_local_ip() -> str:
    """Get the local IP address for LAN access."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip

def get_external_url(host: str, port: int, url_prefix: str) -> tuple[str, list[str]]:
    """
    Automatically determine the correct external URL(s) for accessing the application.
    Returns (primary_url, list_of_additional_urls)
    """
    urls = []

    # 1. Check for PUBLIC_BASE environment variable (highest priority)
    public_base = os.environ.get("PUBLIC_BASE", "").rstrip("/")
    if public_base:
        return f"{public_base}{url_prefix}", []

    # 2. Check for common cloud platform environment variables
    # Railway
    if os.environ.get("RAILWAY_PUBLIC_DOMAIN"):
        domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
        return f"https://{domain}{url_prefix}", []

    # Render
    if os.environ.get("RENDER_EXTERNAL_URL"):
        return f"{os.environ.get('RENDER_EXTERNAL_URL')}{url_prefix}", []

    # Heroku
    if os.environ.get("HEROKU_APP_NAME"):
        app_name = os.environ.get("HEROKU_APP_NAME")
        return f"https://{app_name}.herokuapp.com{url_prefix}", []

    # Vercel
    if os.environ.get("VERCEL_URL"):
        return f"https://{os.environ.get('VERCEL_URL')}{url_prefix}", []

    # AWS / Generic
    if os.environ.get("AWS_EXECUTION_ENV"):
        # Try to get the public hostname if available
        try:
            import urllib.request
            public_ip = urllib.request.urlopen('http://169.254.169.254/latest/meta-data/public-ipv4', timeout=1).read().decode()
            return f"http://{public_ip}:{port}{url_prefix}", []
        except:
            pass

    # 3. Check if running behind a reverse proxy (look for proxy headers env vars)
    if os.environ.get("FORWARDED_ALLOW_IPS") or os.environ.get("PROXY_COUNT"):
        # Likely behind nginx/caddy - use hostname
        hostname = socket.gethostname()
        scheme = os.environ.get("SCHEME", "https" if os.environ.get("HTTPS") else "http")
        return f"{scheme}://{hostname}{url_prefix}", []

    # 4. Local development fallback - provide multiple access options
    local_ip = get_local_ip()
    scheme = os.environ.get("SCHEME", "http")

    # Build list of access URLs
    primary = f"{scheme}://localhost:{port}{url_prefix}"
    alternatives = []

    # Add local IP if different from localhost
    if local_ip and local_ip != "127.0.0.1":
        alternatives.append(f"{scheme}://{local_ip}:{port}{url_prefix}")

    # Add hostname if available
    try:
        hostname = socket.gethostname()
        if hostname and hostname != "localhost":
            alternatives.append(f"{scheme}://{hostname}:{port}{url_prefix}")
    except:
        pass

    return primary, alternatives

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
    # Served under /inventory/ behind a proxy, or at "/" when standalone
    requests_pathname_prefix=PATHNAME_PREFIX,
    routes_pathname_prefix=PATHNAME_PREFIX,
    assets_url_path=ASSETS_URL_PATH,
)
app.title = "📦 Inventory Manager"

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
                    dbc.NavItem(dbc.NavLink("💲 Price Compare", href="/price-compare", external_link=False)),
                ],
                className="ms-3",
                navbar=True,
            ),
            html.Div(
                [
                    dbc.Button(
                        [html.I(className="bi bi-phone me-1"), "Connect"],
                        id="open-connect",
                        color="secondary",
                        outline=True,
                        size="sm",
                        n_clicks=0,
                        className="me-3",
                        title="Open on your phone / another device",
                    ),
                    dbc.Switch(id="theme-switch", label="Dark", value=(THEME_DEFAULT_MODE == "dark")),
                ],
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
            html.H2("📦 Inventory Manager", className="mt-2 mb-1 text-center app-title"),
            html.P(
                "Snap a photo, tag where it lives, track how many you have.",
                className="text-center text-muted mb-3",
            ),
            kpi_bar(),
            html.Div(id="undo-bar"),
            dbc.Row(
                [
                    dbc.Col(sidebar_form(), xs=12, sm=12, md=12, lg=4, xl=4, className="mb-3 mb-lg-0"),
                    dbc.Col([inventory_table()], xs=12, sm=12, md=12, lg=8, xl=8),
                ],
                className="g-3",
            ),
            dbc.Row([dbc.Col(breakdown_card(), width=12)]),
            dbc.Row([dbc.Col(organize_card(), width=12)]),
            identify_modal(),
            organize_modal(),
            bins_modal(),
            duplicates_modal(),
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
        connect_modal(),
        # cross-page stores
        dcc.Store(id="image-contents"),
        dcc.Store(id="ocr-target"),
        dcc.Store(id="ocr-result"),
        dcc.Store(id="theme-mode", storage_type="local", data=THEME_DEFAULT_MODE),
        # tiny diagnostics (hidden)
        dcc.Interval(id="diag-interval", interval=4000, n_intervals=0),
        html.Div(id="diag", style={"display": "none"}),
        # sink for the clientside theme-attribute callback (below)
        html.Div(id="theme-attr-sink", style={"display": "none"}),
        # seed content so first paint isn't blank
        html.Div(id="page-content", children=dashboard_layout()),
    ]
)

# Important: let Dash see all components/IDs across pages
app.validation_layout = html.Div([dashboard_layout(), ocr_lab_layout(), price_compare_layout()])

# ---------- Router ----------
@app.callback(Output("page-content", "children"), Input("url", "pathname"), prevent_initial_call=False)
def display_page(pathname):
    key = _route_key(pathname)
    try:
        if key == "/ocr-lab":
            return ocr_lab_layout()
        if key == "/price-compare":
            return price_compare_layout()
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

# Stamp the active theme onto the document so custom CSS can style the widgets
# that don't come from the Bootswatch theme (dcc.Dropdown, DataTable filters).
app.clientside_callback(
    """
    function(mode) {
        try {
            document.documentElement.setAttribute('data-theme', mode === 'light' ? 'light' : 'dark');
        } catch (e) {}
        return '';
    }
    """,
    Output("theme-attr-sink", "children"),
    Input("theme-mode", "data"),
)

# NOTE: we deliberately do NOT set the `capture` attribute on the photo input.
# With a plain `<input type="file" accept="image/*">`, mobile browsers (iOS
# Safari, Android Chrome) show a chooser offering BOTH "Take Photo" and "Photo
# Library / Choose File", so the same button lets you snap a new picture or pick
# an existing one. Forcing `capture="environment"` would open the camera
# directly and hide the library option.

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
register_price_compare_callbacks(app)

if __name__ == "__main__":
    from waitress import serve

    host = os.environ.get("HOST", "0.0.0.0")
    # Default port aligned with your Caddy backend (PORT=8001)
    port = int(os.environ.get("PORT", 8001))

    # Automatically determine the correct external URL(s)
    primary_url, alternative_urls = get_external_url(host, port, URL_PREFIX)

    print("=" * 60)
    print("📦 Inventory OCR Server Started")
    print("=" * 60)
    print(f"✓ Primary URL:  {primary_url}")

    if alternative_urls:
        print("\n📍 Alternative access URLs:")
        for url in alternative_urls:
            print(f"  • {url}")

    print(f"\n🔧 Internal:    http://{host}:{port}{URL_PREFIX}")
    print("=" * 60)

    serve(server, host=host, port=port, expose_tracebacks=True)
