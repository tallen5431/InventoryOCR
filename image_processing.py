from __future__ import annotations
from typing import Union
from pathlib import Path
from io import BytesIO
from PIL import Image, ImageOps, ImageFilter

def verify_and_normalize_image(source: Union[Path, str, bytes, bytearray, Image.Image, object]) -> Image.Image:
    """
    Open and normalize an image from various input types.
    Returns a Pillow Image in RGB or L mode with orientation fixed.
    """
    if isinstance(source, (Path, str)):
        img = Image.open(source)
    elif isinstance(source, (bytes, bytearray)):
        img = Image.open(BytesIO(source))
    elif hasattr(source, "read"):  # e.g. BytesIO
        img = Image.open(source)
    elif isinstance(source, Image.Image):
        img = source
    else:
        raise TypeError(f"Unsupported image source type: {type(source)}")

    img.load()

    # Fix EXIF orientation
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass

    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    return img


def preprocess_for_ocr(
    img: Image.Image,
    *,
    denoise: bool = True,
    adaptive: bool = True,
    threshold: int = 135,
    sharpen: bool = False,
    block_size: int = 31,
    c_bias: int = 5,
) -> Image.Image:
    """
    Light-weight preprocessor that works with or without OpenCV/Numpy.
    If cv2/numpy are present, will use adaptive threshold; otherwise uses PIL steps.
    """
    if img.mode not in ("L", "RGB"):
        img = img.convert("RGB")

    g = ImageOps.grayscale(img)
    if denoise:
        g = g.filter(ImageFilter.MedianFilter(size=3))

    try:
        import numpy as np
        import cv2

        g_np = np.array(g, dtype=np.uint8)
        if adaptive:
            bs = int(block_size or 31)
            if bs < 3: bs = 3
            if bs % 2 == 0: bs += 1
            out_np = cv2.adaptiveThreshold(
                g_np, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, blockSize=bs, C=int(c_bias or 5)
            )
        else:
            t = int(threshold or 135)
            _, out_np = cv2.threshold(g_np, t, 255, cv2.THRESH_BINARY)
        out = Image.fromarray(out_np)
    except Exception:
        g2 = ImageOps.autocontrast(g)
        t = int(threshold or 135)
        out = g2.point(lambda x: 0 if x < t else 255, "1")

    if sharpen:
        out = out.filter(ImageFilter.UnsharpMask(radius=1, percent=200, threshold=3))

    return out


_DEFAULT_OCR_WHITELIST = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-.,:/()%+"
)


def extract_ocr_text(img: Image.Image, lang: str = "eng", psm: int = 6,
                     whitelist: str | None = None, *,
                     timeout: float | None = None,
                     return_conf: bool = False):
    """
    Run Tesseract OCR on a preprocessed image.

    psm        Tesseract page-segmentation mode (the OCR Lab's PSM dropdown feeds
               this through ``run_ocr_with_cache``).
    whitelist  Characters Tesseract is allowed to emit. ``None`` keeps the
               default set; pass ``""`` to disable the whitelist entirely (useful
               when the default is stripping characters the user needs, e.g. the
               ``$``/``#``/``%`` in a price or model line).
    timeout    Seconds before Tesseract is aborted (``None`` = no limit). Honoured
               so a pathological image can't hang the caller/UI thread.
    return_conf  When True return ``(text, mean_conf)`` instead of just ``text``;
               the confidence is the mean over recognised words (0.0 if unknown).
    """
    def _ret(text: str, conf: float = 0.0):
        return (text, conf) if return_conf else text

    try:
        import pytesseract
        from pytesseract import Output
    except Exception:
        return _ret("", 0.0)
    try:
        if img.mode not in ("L", "RGB"):
            img = img.convert("RGB")

        wl = _DEFAULT_OCR_WHITELIST if whitelist is None else whitelist
        config_str = f"--oem 1 --psm {int(psm)}"
        if wl:
            config_str += f" -c tessedit_char_whitelist={wl}"

        # image_to_data gives per-word confidences, so we can report a real mean
        # confidence AND rebuild clean lines in one pass. Fall back to the plain
        # string call if the data variant isn't available on this Tesseract.
        try:
            data = pytesseract.image_to_data(img, lang=lang, config=config_str,
                                             timeout=timeout, output_type=Output.DICT)
            words = data.get("text", []) or []
            confs = data.get("conf", []) or []
            lines: dict = {}
            order: list = []
            kept_confs: list = []
            for i, word in enumerate(words):
                w = (word or "").strip()
                if not w:
                    continue

                def _at(col: str) -> int:
                    try:
                        return int(data[col][i])
                    except (KeyError, IndexError, TypeError, ValueError):
                        return i

                key = (_at("block_num"), _at("par_num"), _at("line_num"))
                if key not in lines:
                    lines[key] = []
                    order.append(key)
                lines[key].append(w)
                try:
                    c = float(confs[i])
                    if c >= 0:
                        kept_confs.append(c)
                except (TypeError, ValueError, IndexError):
                    pass
            text = "\n".join(" ".join(lines[k]) for k in order)
            conf = (sum(kept_confs) / len(kept_confs)) if kept_confs else 0.0
            return _ret(text, conf)
        except Exception:
            text = pytesseract.image_to_string(img, lang=lang, config=config_str,
                                               timeout=timeout) or ""
            text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
            return _ret(text, 0.0)
    except Exception:
        return _ret("", 0.0)
