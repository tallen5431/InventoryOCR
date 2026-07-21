"""Shared presentation helpers for the Dash UIs.

Pure formatters and small Dash-component builders used by BOTH the inventory
dashboard (:mod:`callbacks`) and the Operations tab (:mod:`callbacks_operations`),
kept here so there is exactly one implementation of each.

Note: data-*normalization* helpers deliberately live in each data module
(:mod:`data` / :mod:`operations_data`) rather than here — their coercion rules
differ on purpose (e.g. materials clamp quantity to ``>= 0`` while inventory
allows a hand-edited negative), so they are intentionally not shared.
"""
from __future__ import annotations

import os

from dash import html, dcc
import dash_bootstrap_components as dbc

from utils import get_thumbnail_url

# Asset URL base — mirrors utils/app so document links resolve behind a reverse
# proxy that mounts the app under a prefix (e.g. /inventory).
URL_PREFIX = os.getenv("URL_PREFIX", "/inventory").strip().rstrip("/")
if URL_PREFIX and not URL_PREFIX.startswith("/"):
    URL_PREFIX = "/" + URL_PREFIX
ASSET_URL_BASE = f"{URL_PREFIX}/assets" if URL_PREFIX else "/assets"

# Bootstrap icon per attachment kind (see utils.attachment_kind).
ATTACH_ICON = {"image": "bi-file-image", "html": "bi-filetype-html",
               "pdf": "bi-file-pdf", "other": "bi-file-earmark"}


# --------------------------------------------------------------------
# Pure formatters
# --------------------------------------------------------------------

def money(v):
    """Format a number as ``$1,234.56``; anything non-numeric (None) → em dash."""
    return f"${v:,.2f}" if isinstance(v, (int, float)) else "—"


def specs_to_text(specs):
    """Render a stored specifications list as one-per-line text for a textarea."""
    if isinstance(specs, list):
        return "\n".join(str(s) for s in specs if str(s).strip())
    return str(specs or "")


def tags_to_text(tags):
    """Render a stored tags list as a comma-separated string for an input."""
    if isinstance(tags, list):
        return ", ".join(str(t) for t in tags if str(t).strip())
    return str(tags or "")


def human_size(n) -> str:
    """Human-readable file size ('12 B', '3.4 KB', …); '' for 0/unknown."""
    try:
        size = float(n)
    except (TypeError, ValueError):
        return ""
    if size <= 0:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return ""


def doc_url(filename: str, *, download: bool = False) -> str:
    """URL for an attached document; ``download=True`` forces a save dialog."""
    url = f"{ASSET_URL_BASE}/documents/{filename}"
    return url + "?download=1" if download else url


# --------------------------------------------------------------------
# Dash component builders
# --------------------------------------------------------------------

def fullres_links(originals):
    """Footer control that keeps the full-resolution originals one tap away when
    the viewer is showing the fast preview. One link for a single photo, numbered
    links when there are several."""
    originals = [u for u in (originals or []) if u]
    if not originals:
        return ""
    if len(originals) == 1:
        return html.A([html.I(className="bi bi-arrows-fullscreen me-1"),
                       "View full resolution"],
                      href=originals[0], target="_blank", rel="noopener noreferrer",
                      className="text-decoration-none")
    links = [html.Span("Full resolution: ", className="text-muted")]
    for i, u in enumerate(originals):
        links.append(html.A(str(i + 1), href=u, target="_blank",
                            rel="noopener noreferrer", className="me-2"))
    return html.Span(links)


def attachment_list(atts, remove_type="attach-remove", *,
                    empty_msg="No documents attached yet."):
    """Compact list of attached documents: icon, name, size, view + remove.

    ``remove_type`` names the pattern-matching id of the × button so each form
    (dashboard main / Quick Add / Operations) gets independent remove wiring.
    Pass ``remove_type=None`` for a read-only list with no remove button."""
    atts = atts or []
    if not atts:
        return html.Div(empty_msg, className="text-muted small")
    rows = []
    for i, a in enumerate(atts):
        fn = a.get("filename", "")
        icon = ATTACH_ICON.get(a.get("kind", "other"), "bi-file-earmark")
        meta = " · ".join([x for x in [a.get("kind", ""), human_size(a.get("size"))] if x])
        kind = a.get("kind", "other")
        line = [
            html.I(className=f"bi {icon} me-2 text-secondary"),
            html.A(a.get("original_name") or fn, href=doc_url(fn), target="_blank",
                   rel="noopener noreferrer", className="text-truncate me-2",
                   style={"maxWidth": "55%"}),
            html.Span(meta, className="text-muted small me-2"),
            # In-app preview (image/pdf/html render inline; other types offer a
            # download). Filename + kind ride in the id so one global callback
            # serves every attachment_list on any page — no store lookup needed.
            dbc.Button(html.I(className="bi bi-eye"),
                       id={"type": "doc-view", "name": fn, "kind": kind,
                           "label": a.get("original_name") or fn},
                       color="outline-secondary", size="sm", className="py-0 px-1 me-1",
                       title="View", n_clicks=0),
            html.A(html.I(className="bi bi-download"), href=doc_url(fn, download=True),
                   className="btn btn-sm btn-outline-secondary py-0 px-1 me-1", title="Download"),
        ]
        if remove_type:
            line.append(
                dbc.Button(html.I(className="bi bi-x-lg"),
                           id={"type": remove_type, "index": i}, color="outline-danger",
                           size="sm", className="py-0 px-1", title="Remove", n_clicks=0)
            )
        rows.append(html.Div(line, className="d-flex align-items-center border rounded px-2 py-1 mb-1"))
    return html.Div(rows)


def camera_upload(upload_id, label="Take a photo"):
    """A 'Take photo' button that opens the CAMERA directly on a phone (vs the
    plain dropzone, which opens the file picker / photo library).

    dcc.Upload doesn't expose the HTML ``capture`` attribute, so assets/camera.js
    stamps ``capture=environment`` onto the inner <input> of any element whose id
    ends in ``-cam`` — therefore ``upload_id`` MUST end in ``-cam``. Feeds the
    same photo-staging callback as its sibling dropzone, so shots accumulate."""
    assert str(upload_id).endswith("-cam"), "camera_upload id must end in '-cam'"
    return dcc.Upload(
        id=upload_id, accept="image/*", multiple=True,
        children=dbc.Button([html.I(className="bi bi-camera-fill me-1"), label],
                            color="primary", outline=True, className="w-100"),
        className="d-block mt-2",
    )


def doc_viewer_modal():
    """Global modal that previews an attached document in-app (so you can confirm
    something that didn't get parsed without leaving the page). Images render as
    an <img>, PDFs/HTML in an <iframe>; unpreviewable types show a download
    prompt. Mounted once in the app shell; opened by the 'doc-view' buttons that
    attachment_list renders (a single callback wires them, see app.py)."""
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle(
                [html.I(className="bi bi-file-earmark-text me-2"),
                 html.Span(id="doc-viewer-title")])),
            dbc.ModalBody(html.Div(id="doc-viewer-body"), style={"minHeight": "40vh"}),
            dbc.ModalFooter(
                [
                    html.A([html.I(className="bi bi-box-arrow-up-right me-1"), "Open in new tab"],
                           id="doc-viewer-newtab", href="", target="_blank",
                           rel="noopener noreferrer", className="btn btn-outline-secondary me-auto"),
                    dbc.Button("Close", id="doc-viewer-close", color="secondary", n_clicks=0),
                ],
                className="d-flex",
            ),
        ],
        id="doc-viewer-modal", is_open=False, size="xl", centered=True, scrollable=True,
    )


def doc_viewer_body(filename: str, kind: str):
    """Build the preview element for a document by kind. Never raises."""
    url = doc_url(filename)
    if kind == "image":
        return html.Img(src=url, style={"maxWidth": "100%", "maxHeight": "78vh",
                                        "objectFit": "contain", "display": "block",
                                        "margin": "0 auto"})
    if kind in ("pdf", "html"):
        # Same-origin iframe: PDFs use the browser's built-in viewer; saved HTML
        # pages render inline. Sandbox keeps a saved page's scripts from running.
        sandbox = "" if kind == "pdf" else "allow-same-origin"
        return html.Iframe(src=url, style={"width": "100%", "height": "78vh", "border": "none"},
                           sandbox=sandbox)
    return html.Div(
        [html.I(className="bi bi-info-circle me-2"),
         "No inline preview for this file type — use Download or Open in new tab."],
        className="text-muted py-4 text-center",
    )


def photo_gallery(images, remove_type, *, labels=True, empty_msg="No photos yet."):
    """Thumbnail grid with a × remove button per photo (pattern id ``remove_type``).
    ``labels=True`` adds a 'Photo N' caption under each thumbnail."""
    images = images or []
    items = []
    for i, fn in enumerate(images):
        thumb = get_thumbnail_url(fn)
        if not thumb:
            continue
        cell = [
            html.Img(src=thumb, className="gallery-thumb"),
            html.Button("×", id={"type": remove_type, "index": i},
                        className="btn btn-sm btn-danger delete-img-btn",
                        title="Remove photo", n_clicks=0),
        ]
        if labels:
            cell.append(html.Div(f"Photo {i + 1}", className="text-muted small text-center"))
        items.append(html.Div(cell, className="gallery-item"))
    if not items:
        return html.Div(empty_msg, className="text-muted small")
    return html.Div(items, className="image-gallery-grid")
