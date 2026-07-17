from __future__ import annotations
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
    settings: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Compatibility wrapper for OCR calls.
    Accepts raw bytes, BytesIO, file path, or PIL.Image and normalizes first.
    """

    # Normalize to a PIL.Image
    pil_img = verify_and_normalize_image(img)

    # If a dict of settings is provided, override parameters
    s = settings or {}
    threshold = threshold if threshold is not None else s.get("threshold", 135)
    denoise   = denoise   if denoise   is not None else s.get("denoise", True)
    adaptive  = adaptive  if adaptive  is not None else s.get("adaptive", True)
    sharpen   = sharpen   if sharpen   is not None else s.get("sharpen", False)

    processed = preprocess_for_ocr(
        pil_img,
        denoise=denoise,
        adaptive=adaptive,
        threshold=threshold,
        sharpen=sharpen,
    )
    # Forward the whitelist only when the caller supplies one. Left as None it
    # keeps extract_ocr_text's label-friendly default (unchanged behaviour for
    # existing callers like the OCR Lab); passing "" disables the whitelist so
    # currency symbols survive — used by invoice + product-listing OCR.
    kw: Dict[str, Any] = {"lang": lang or "eng"}
    if whitelist is not None:
        kw["whitelist"] = whitelist
    text = (extract_ocr_text(processed, **kw) or "").strip()

    return {
        "text": text,
        "mean_conf": 0.0,        # placeholder
        "profile_counts": {},
        "roi_count": 1,
        "debug": {},
    }

def clear_cache() -> None:
    # Placeholder for parity with previous versions; no-op here.
    return
