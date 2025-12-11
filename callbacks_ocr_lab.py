from __future__ import annotations
import base64, io, time, traceback
from typing import Optional

import numpy as np
import cv2
from PIL import Image, ImageOps

from dash import Input, Output, State, html, no_update, dcc, ctx
from dash.exceptions import PreventUpdate

# Data layer
import data

# OCR engine (prefer cache wrapper if available)
try:
    from ocr_engine import run_ocr_with_cache as _run_ocr_base  # type: ignore
    HAVE_CACHE = True
except Exception:
    from ocr_engine import run_ocr as _run_ocr_base  # type: ignore
    HAVE_CACHE = False


def _decode_data_url_to_bytes(contents: str) -> bytes:
    if not contents:
        return b""
    if "," in contents:
        contents = contents.split(",", 1)[1]
    return base64.b64decode(contents)


def _b64enc(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _b64dec(s: Optional[str]) -> bytes:
    if not s:
        return b""
    return base64.b64decode(s.encode("ascii"))


def _bytes_to_data_url(b: bytes, fmt: str = "png") -> str:
    return f"data:image/{fmt};base64," + base64.b64encode(b).decode("ascii")


def _pil_from_bytes(b: bytes) -> Image.Image:
    im = Image.open(io.BytesIO(b))
    try:
        im = ImageOps.exif_transpose(im)
    except Exception:
        pass
    return im


def _resize_long_edge(im: Image.Image, max_px: int) -> Image.Image:
    w, h = im.size
    long_side = max(w, h)
    if long_side <= max_px:
        return im.copy()
    scale = max_px / float(long_side)
    new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
    return im.resize(new_size, Image.LANCZOS)


def _proc_preview_bytes(
    base_png_bytes: bytes,
    threshold: int,
    denoise_flag: bool,
    sharpen_flag: bool,
    adaptive_flag: bool,
    brightness: float = 1.0,
    contrast: float = 1.0,
    gamma: float = 1.0,
    denoise_strength: int = 0,
    morph: str = "none",
    binarize: str = "global",
    invert_flag: bool = False,
    morph_k: int = 3,
    rotate_deg: float = 0.0,
    sharpen_amt: float = 0.7,
):
    t0 = time.perf_counter()

    im = _pil_from_bytes(base_png_bytes).convert("L")
    arr = np.array(im).astype(np.float32)

    if rotate_deg and abs(rotate_deg) > 1e-3:
        h, w = arr.shape[:2]
        M = cv2.getRotationMatrix2D((w / 2, h / 2), float(rotate_deg), 1.0)
        arr = cv2.warpAffine(
            arr, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE
        ).astype(np.float32)

    if denoise_flag:
        arr = cv2.medianBlur(arr.astype(np.uint8), 3).astype(np.float32)

    arr = cv2.normalize(arr, None, 0, 255, cv2.NORM_MINMAX)
    arr = arr * float(contrast) * float(brightness)

    if denoise_flag and (denoise_strength or 0) > 0:
        k = int(denoise_strength) * 2 + 1
        k = max(3, min(k, 21))
        arr = cv2.GaussianBlur(arr, (k, k), 0)

    if gamma and abs(gamma - 1.0) > 1e-3:
        arr_u8 = np.clip(arr, 0, 255).astype(np.uint8)
        lut = (np.power(np.arange(256, dtype=np.float32) / 255.0, float(gamma)) * 255.0).astype(np.uint8)
        arr = cv2.LUT(arr_u8, lut).astype(np.float32)

    arr = np.clip(arr, 0, 255).astype(np.uint8)

    mode = (binarize or "global").lower()
    if mode == "otsu":
        _, arr = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    elif mode == "adaptive_mean":
        arr = cv2.adaptiveThreshold(arr, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 15, 2)
    elif mode == "adaptive_gaussian":
        arr = cv2.adaptiveThreshold(arr, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 2)
    else:
        if adaptive_flag:
            arr = cv2.adaptiveThreshold(arr, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 2)
        else:
            _, arr = cv2.threshold(arr, int(threshold or 140), 255, cv2.THRESH_BINARY)

    if invert_flag:
        arr = 255 - arr

    if morph in ("open", "close"):
        ksize = int(morph_k) if morph_k else 3
        if ksize % 2 == 0:
            ksize += 1
        ksize = max(1, min(ksize, 9))
        kernel = np.ones((ksize, ksize), np.uint8)
        op = cv2.MORPH_OPEN if morph == "open" else cv2.MORPH_CLOSE
        arr = cv2.morphologyEx(arr, op, kernel)

    if sharpen_flag and (sharpen_amt or 0) > 0:
        amt = float(sharpen_amt)
        arr = cv2.GaussianBlur(arr, (0, 0), 0.0)
        arr = cv2.addWeighted(arr, 1.0 + amt, arr, -amt, 0)

    ok, buf = cv2.imencode(".png", arr)
    if not ok:
        raise RuntimeError("Failed to encode preview PNG")
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return (bytes(buf), elapsed_ms)


def _is_on(val_list: Optional[list], key: str) -> bool:
    return bool(val_list and key in val_list)


def register_ocr_lab_callbacks(app):
    # 1) Load image (upload, path, or external dashboard signal)
    @app.callback(
        Output("ocr-lab-orig-bytes", "data"),
        Output("ocr-lab-original", "src"),
        Output("ocr-lab-status", "children"),
        Input("ocr-lab-upload", "contents"),
        Input("ocr-lab-load-file", "n_clicks"),
        Input("image-contents", "data"),
        State("ocr-lab-path", "value"),
        prevent_initial_call=False,
    )
    def _load_source(upload_contents, load_clicks, dashboard_contents, path_value):
        try:
            trig = ctx.triggered_id
            raw: bytes | None = None
            note = ""
            if trig == "ocr-lab-upload" and upload_contents:
                raw = _decode_data_url_to_bytes(upload_contents)
                note = "Loaded from upload."
            elif trig == "ocr-lab-load-file" and path_value:
                with open(path_value, "rb") as f:
                    raw = f.read()
                note = f"Loaded from file: {path_value}"
            elif trig == "image-contents" and dashboard_contents:
                raw = _decode_data_url_to_bytes(dashboard_contents)
                note = "Loaded from dashboard."
            else:
                raise PreventUpdate

            im = _pil_from_bytes(raw)
            buf = io.BytesIO()
            im.save(buf, format="PNG")
            png_bytes = buf.getvalue()
            return _b64enc(png_bytes), _bytes_to_data_url(png_bytes, "png"), html.Div([html.Code(note)])
        except PreventUpdate:
            raise
        except Exception:
            return no_update, no_update, html.Pre("Load error:\n" + traceback.format_exc())

    # 2) Build preview base
    @app.callback(
        Output("ocr-lab-preview-base", "data"),
        Output("ocr-lab-preview", "src"),
        Output("ocr-lab-timing", "children"),
        Output("ocr-lab-proc-bytes", "data"),
        Input("ocr-lab-orig-bytes", "data"),
        Input("ocr-preview-size", "value"),
        prevent_initial_call=True,
    )
    def _rebuild_preview_base(orig_b64, max_px):
        if not orig_b64:
            raise PreventUpdate
        try:
            orig_png = _b64dec(orig_b64)
            im = _pil_from_bytes(orig_png)
            im_small = _resize_long_edge(im, int(max(200, max_px or 1200)))
            buf = io.BytesIO()
            im_small.save(buf, format="PNG")
            base_png = buf.getvalue()
            base_b64 = _b64enc(base_png)
            return base_b64, _bytes_to_data_url(base_png, "png"), "", base_b64
        except Exception:
            return no_update, no_update, "", no_update

    # 3) Live / manual preview update
    @app.callback(
        Output("ocr-lab-preview", "src", allow_duplicate=True),
        Output("ocr-lab-timing", "children", allow_duplicate=True),
        Output("ocr-lab-proc-bytes", "data", allow_duplicate=True),
        Input("ocr-lab-preview-base", "data"),
        Input("ocr-bool-toggles", "value"),
        Input("ocr-threshold", "value"),
        Input("ocr-brightness", "value"),
        Input("ocr-contrast", "value"),
        Input("ocr-gamma", "value"),
        Input("ocr-denoise-strength", "value"),
        Input("ocr-morph", "value"),
        Input("ocr-binarize", "value"),
        Input("ocr-morph-k", "value"),
        Input("ocr-rotate", "value"),
        Input("ocr-sharpen-amt", "value"),
        Input("ocr-live", "value"),
        Input("ocr-preset", "value"),
        Input("ocr-preview-refresh", "n_clicks"),
        prevent_initial_call=True,
    )
    def _live_preview(
        preview_base_b64,
        toggles,
        threshold,
        brightness,
        contrast,
        gamma,
        denoise_strength,
        morph,
        binarize,
        morph_k,
        rotate_deg,
        sharpen_amt,
        live_list,
        preset_val,
        refresh_clicks,
    ):
        if not preview_base_b64:
            raise PreventUpdate

        if not _is_on(live_list, "live"):
            if ctx.triggered_id not in ("ocr-preview-refresh", "ocr-preset"):
                raise PreventUpdate

        try:
            denoise = _is_on(toggles, "denoise")
            sharpen = _is_on(toggles, "sharpen")
            adaptive = _is_on(toggles, "adaptive")
            invert = _is_on(toggles, "invert")
            base_png = _b64dec(preview_base_b64)

            png_bytes, ms = _proc_preview_bytes(
                base_png,
                int(threshold or 140),
                denoise,
                sharpen,
                adaptive,
                float(brightness or 1.0),
                float(contrast or 1.0),
                float(gamma or 1.0),
                int(denoise_strength or 0),
                str(morph or "none"),
                str(binarize or "global"),
                bool(invert),
                int(morph_k or 3),
                float(rotate_deg or 0.0),
                float(sharpen_amt or 0.7),
            )
            return _bytes_to_data_url(png_bytes, "png"), f"{ms:.0f} ms", _b64enc(png_bytes)
        except Exception:
            return no_update, "err", no_update

    # 3b) Binarization UI affordances
    @app.callback(
        Output("ocr-threshold", "disabled"),
        Output("ocr-mode-hint", "children"),
        Input("ocr-binarize", "value"),
    )
    def _threshold_ui(mode):
        mode = (mode or "global").lower()
        if mode in ("otsu", "adaptive_mean", "adaptive_gaussian"):
            return True, "Threshold slider and 'Adaptive' switch are ignored in this mode."
        return False, ""

    # 3c) Reset to defaults
    @app.callback(
        Output("ocr-bool-toggles", "value", allow_duplicate=True),
        Output("ocr-binarize", "value", allow_duplicate=True),
        Output("ocr-threshold", "value", allow_duplicate=True),
        Output("ocr-preview-size", "value", allow_duplicate=True),
        Output("ocr-brightness", "value", allow_duplicate=True),
        Output("ocr-contrast", "value", allow_duplicate=True),
        Output("ocr-gamma", "value", allow_duplicate=True),
        Output("ocr-denoise-strength", "value", allow_duplicate=True),
        Output("ocr-morph", "value", allow_duplicate=True),
        Output("ocr-morph-k", "value", allow_duplicate=True),
        Output("ocr-rotate", "value", allow_duplicate=True),
        Output("ocr-sharpen-amt", "value", allow_duplicate=True),
        Output("ocr-profile", "value", allow_duplicate=True),
        Output("ocr-autorun", "value", allow_duplicate=True),
        Output("ocr-use-preview", "value", allow_duplicate=True),
        Input("ocr-reset", "n_clicks"),
        prevent_initial_call=True,
    )
    def _reset(n):
        if not n: raise PreventUpdate
        return (
            ["denoise", "adaptive"], "global", 140, 1200, 1.0, 1.0, 1.0, 0,
            "none", 3, 0.0, 0.7, "fast", [], ["small"],
        )

    # 4) Slider readouts
    @app.callback(
        Output("ocr-threshold-readout", "children"),
        Output("ocr-preview-size-readout", "children"),
        Output("ocr-brightness-readout", "children"),
        Output("ocr-contrast-readout", "children"),
        Output("ocr-gamma-readout", "children"),
        Output("ocr-denoise-strength-readout", "children"),
        Output("ocr-morph-k-readout", "children"),
        Output("ocr-rotate-readout", "children"),
        Output("ocr-sharpen-amt-readout", "children"),
        Input("ocr-threshold", "value"),
        Input("ocr-preview-size", "value"),
        Input("ocr-brightness", "value"),
        Input("ocr-contrast", "value"),
        Input("ocr-gamma", "value"),
        Input("ocr-denoise-strength", "value"),
        Input("ocr-morph-k", "value"),
        Input("ocr-rotate", "value"),
        Input("ocr-sharpen-amt", "value"),
    )
    def _readouts(thr, psize, br, con, gam, dns, mk, rot, sha):
        return (
            f"{thr}",
            f"{psize}px",
            f"{(br or 1.0):.1f}",
            f"{(con or 1.0):.1f}",
            f"{(gam or 1.0):.1f}",
            f"{int(dns or 0)}",
            f"{int(mk or 3)}",
            f"{(rot or 0):.1f}°",
            f"{(sha or 0.7):.1f}",
        )

    # 4c) Quick presets
    @app.callback(
        Output("ocr-bool-toggles", "value", allow_duplicate=True),
        Output("ocr-binarize", "value", allow_duplicate=True),
        Output("ocr-threshold", "value", allow_duplicate=True),
        Output("ocr-profile", "value", allow_duplicate=True),
        Input("ocr-preset", "value"),
        prevent_initial_call=True,
    )
    def _apply_preset(preset):
        if not preset: raise PreventUpdate
        if preset == "receipt":  return ["denoise", "adaptive"], "adaptive_gaussian", 140, "fast"
        if preset == "label":    return ["denoise", "sharpen"], "global", 160, "fast"
        if preset == "document": return ["denoise", "adaptive"], "otsu", 140, "accurate"
        raise PreventUpdate

    # 5) Run OCR
    @app.callback(
        Output("ocr-lab-text", "value"),
        Output("ocr-lab-ocr-meta", "children"),
        Output("ocr-lab-status", "children", allow_duplicate=True),
        Output("ocr-settings-tabs", "value", allow_duplicate=True),
        Input("ocr-lab-run", "n_clicks"),
        State("ocr-lab-orig-bytes", "data"),
        State("ocr-lab-proc-bytes", "data"),
        State("ocr-profile", "value"),
        State("ocr-use-preview", "value"),
        State("ocr-lang", "value"),
        State("ocr-psm", "value"),
        prevent_initial_call=True,
    )
    def _run_ocr(n, orig_b64, proc_b64, profile, use_small, lang, psm):
        if not n: raise PreventUpdate
        try:
            t0 = time.perf_counter()
            use_preview = ("small" in (use_small or [])) and proc_b64
            img_b = _b64dec(proc_b64 if use_preview else orig_b64) or _b64dec(orig_b64)
            if not img_b: raise PreventUpdate

            kw = dict(
                profile=("fast" if profile == "fast" else None),
                timeout=12 if profile == "fast" else 25,
                lang=(lang or "eng"),
                psm_list=[int(psm)] if (profile == "fast" and psm) else None,
            )
            res = _run_ocr_base(io.BytesIO(img_b), **kw)
            text = (res.get("text") or "").strip()
            conf = res.get("mean_conf", 0.0)
            roi_count = res.get("roi_count", 0)
            meta = f"Confidence: {conf:.1f} — ROIs: {roi_count} — Cache:{'on' if HAVE_CACHE else 'off'}"
            return text, meta, html.Div(["OCR complete. ", html.Code(meta)]), "text"
        except Exception:
            return "", "", html.Pre("OCR error:\n" + traceback.format_exc()), no_update

    # 5b) Auto-run OCR
    @app.callback(
        Output("ocr-lab-text", "value", allow_duplicate=True),
        Output("ocr-lab-ocr-meta", "children", allow_duplicate=True),
        Output("ocr-lab-status", "children", allow_duplicate=True),
        Input("ocr-lab-proc-bytes", "data"),
        State("ocr-autorun", "value"),
        State("ocr-profile", "value"),
        State("ocr-lang", "value"),
        State("ocr-psm", "value"),
        prevent_initial_call=True,
    )
    def _autorun(proc_b64, autorun_list, profile, lang, psm):
        if not proc_b64 or not _is_on(autorun_list, "on"):
            raise PreventUpdate
        try:
            img_b = _b64dec(proc_b64)
            kw = dict(
                profile=("fast" if profile == "fast" else None),
                timeout=10 if profile == "fast" else 18,
                lang=(lang or "eng"),
                psm_list=[int(psm)] if (profile == "fast" and psm) else None,
            )
            res = _run_ocr_base(io.BytesIO(img_b), **kw)
            text = (res.get("text") or "").strip()
            conf = res.get("mean_conf", 0.0)
            roi_count = res.get("roi_count", 0)
            meta = f"(Auto) Conf: {conf:.1f} — ROIs: {roi_count} — Cache:{'on' if HAVE_CACHE else 'off'}"
            return text, meta, html.Div(["Auto OCR complete. ", html.Code(meta)])
        except Exception:
            return no_update, no_update, html.Pre("Auto OCR error:\n" + traceback.format_exc())

    # 6) Downloads
    @app.callback(
        Output("ocr-lab-download", "data"),
        Input("ocr-lab-download-btn", "n_clicks"),
        State("ocr-lab-text", "value"),
        prevent_initial_call=True,
    )
    def _dl_text(n, text):
        if not n: raise PreventUpdate
        return dict(content=text or "", filename="ocr.txt")

    @app.callback(
        Output("ocr-lab-download-img", "data"),
        Input("ocr-lab-download-img-btn", "n_clicks"),
        State("ocr-lab-proc-bytes", "data"),
        State("ocr-lab-preview-base", "data"),
        prevent_initial_call=True,
    )
    def _dl_img(n, proc_b64, base_b64):
        if not n: raise PreventUpdate
        s = proc_b64 or base_b64
        if not s: raise PreventUpdate
        return dcc.send_bytes(_b64dec(s), "preview.png")

    # 7) Save back to item
    @app.callback(
        Output("ocr-lab-status", "children", allow_duplicate=True),
        Input("ocr-lab-save-to-item", "n_clicks"),
        State("ocr-target", "data"),
        State("ocr-lab-text", "value"),
        prevent_initial_call=True,
    )
    def _save_back(n, target, text_val):
        if not n: raise PreventUpdate
        if not (target and target.get("item_id")):
            return html.Div(["No target item selected. Open OCR Lab via the table’s radio button."], className="text-warning")
        try:
            item_id = target["item_id"]
            all_items = data.inventory()
            cur = next((it for it in all_items if it.get("id") == item_id), None)
            if not cur: return html.Div([html.Code(item_id), " not found."], className="text-danger")
            data.update_item(
                item_id=item_id,
                name=cur.get("name", ""),
                description=cur.get("description", ""),
                qty=int(cur.get("qty", 0)),
                images=cur.get("images", []),
                ocr_text=(text_val or "").strip(),
            )
            return html.Div(["Saved OCR text back to item “", html.Code(cur.get("name", "")), "”."])
        except Exception:
            return html.Pre("Save error:\n" + traceback.format_exc())
