from __future__ import annotations
import os
from typing import Dict, Any, Optional, List, Union
from PIL import Image
from image_processing import verify_and_normalize_image, preprocess_for_ocr, extract_ocr_text

def run_ocr_with_cache(
    img: Union[Image.Image, bytes, bytearray, str, "os.PathLike", object],
    *,
    threshold: int | None = None,
    denoise: bool | None = None,
    sharpen: bool | None = None,
    adaptive: bool | None = None,
    debug: bool | None = None,
    profile: str | None = None,
    psm_list: Optional[List[int]] = None,
    whitelist: Optional[str] = None,
    lang: str | None = None,
    timeout: Optional[int] = None,
    already_preprocessed: bool = False,
    settings: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Compatibility wrapper for OCR calls.
    Accepts raw bytes, BytesIO, file path, or PIL.Image and normalizes first.

    ``already_preprocessed`` skips the built-in preprocessing — used when the
    caller (the OCR Lab, with "use preview" on) already binarised/tuned the image
    and re-running preprocess_for_ocr would OCR something different from the
    preview the user is looking at.
    """

    # Normalize to a PIL.Image
    pil_img = verify_and_normalize_image(img)

    # If a dict of settings is provided, override parameters
    s = settings or {}
    threshold = threshold if threshold is not None else s.get("threshold", 135)
    denoise   = denoise   if denoise   is not None else s.get("denoise", True)
    adaptive  = adaptive  if adaptive  is not None else s.get("adaptive", True)
    sharpen   = sharpen   if sharpen   is not None else s.get("sharpen", False)

    if already_preprocessed:
        # OCR the image exactly as handed in (the Lab preview is already processed).
        processed = pil_img
    else:
        processed = preprocess_for_ocr(
            pil_img,
            denoise=denoise,
            adaptive=adaptive,
            threshold=threshold,
            sharpen=sharpen,
        )
    # Honour the caller's page-segmentation mode, character whitelist and timeout.
    # psm_list carries the OCR Lab's PSM selection (first entry wins; default 6).
    # whitelist=None means "no restriction" here — the diagnostic Lab wants the raw
    # text including $/#/% that the built-in default set would otherwise strip; a
    # caller that truly wants the restricted set can pass it explicitly.
    psm = int(psm_list[0]) if psm_list else 6
    wl = whitelist if whitelist is not None else ""
    text, mean_conf = extract_ocr_text(
        processed, lang=lang or "eng", psm=psm, whitelist=wl,
        timeout=timeout, return_conf=True)
    text = (text or "").strip()

    return {
        "text": text,
        "mean_conf": round(float(mean_conf or 0.0), 1),
        "profile_counts": {},
        "roi_count": 1,
        "debug": {},
    }

