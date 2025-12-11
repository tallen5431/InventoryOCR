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


def extract_ocr_text(img: Image.Image, lang: str = "eng", psm: int = 6) -> str:
    """
    Run Tesseract OCR on a preprocessed image.
    Accepts language and PSM mode for compatibility with ocr_engine.
    """
    try:
        import pytesseract
    except Exception:
        return ""
    try:
        if img.mode not in ("L", "RGB"):
            img = img.convert("RGB")

        # whitelist and config
        whitelist = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-.,:/()%+"
        config_str = f"--oem 1 --psm {psm} -c tessedit_char_whitelist={whitelist}"

        text = pytesseract.image_to_string(img, lang=lang, config=config_str)

        # Clean up text
        return "\n".join(line.strip() for line in text.splitlines() if line.strip())
    except Exception:
        return ""
