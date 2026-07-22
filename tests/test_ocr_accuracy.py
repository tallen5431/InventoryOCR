"""Tests for the confidence-filtered OCR pass in ocr_auto._ocr_pass.

Tesseract isn't invoked — a fake ``pytesseract`` returns a canned
``image_to_data`` result so the test runs anywhere. It verifies that
low-confidence words (the garbled-graphics "soup") are dropped at the source
and that surviving words are rebuilt into their original lines.

Run: python3 tests/test_ocr_accuracy.py
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ocr_auto

_ok = True


def _check(name, cond):
    global _ok
    print(("PASS" if cond else "FAIL"), "-", name)
    _ok = cond and _ok


def _install_fake(rows):
    """rows: list of (text, conf, block, par, line). Returns the fake module."""
    data = {
        "text": [r[0] for r in rows],
        "conf": [r[1] for r in rows],
        "block_num": [r[2] for r in rows],
        "par_num": [r[3] for r in rows],
        "line_num": [r[4] for r in rows],
    }

    class _Out:
        DICT = "dict"

    fake = types.ModuleType("pytesseract")
    fake.Output = _Out
    fake.image_to_data = lambda img, lang, config, timeout, output_type: data
    fake.image_to_string = lambda img, lang, config, timeout: "FALLBACK"
    sys.modules["pytesseract"] = fake
    return fake


def main():
    ocr_auto._MIN_CONF = 35  # pin the threshold regardless of env

    # 'soup' (conf 10) is below threshold and dropped; the two real words stay,
    # rebuilt into their own lines.
    _install_fake([
        ("Good", "92", 1, 1, 1),
        ("soup", "10", 1, 1, 1),
        ("SecondLine", "88", 2, 1, 1),
        ("", "95", 2, 1, 1),        # blank token ignored
    ])
    text, conf = ocr_auto._ocr_pass(None, 3)
    _check("low-confidence word dropped", "soup" not in text)
    _check("confident words kept", "Good" in text and "SecondLine" in text)
    _check("lines reconstructed", text == "Good\nSecondLine")
    _check("mean confidence over kept words", 89.0 <= conf <= 91.0)

    # Threshold 0 disables the filter (old behaviour — keep every word).
    ocr_auto._MIN_CONF = 0
    _install_fake([("Good", "92", 1, 1, 1), ("soup", "10", 1, 1, 1)])
    text, _ = ocr_auto._ocr_pass(None, 3)
    _check("threshold 0 keeps everything", "soup" in text)
    ocr_auto._MIN_CONF = 35

    # If image_to_data blows up, fall back to plain image_to_string, never raise.
    fake = _install_fake([])
    def _boom(*a, **k):
        raise RuntimeError("no data api")
    fake.image_to_data = _boom
    text, conf = ocr_auto._ocr_pass(None, 3)
    _check("falls back to image_to_string", text == "FALLBACK" and conf == 0.0)

    print("\nRESULT:", "ALL PASS" if _ok else "SOME FAILED")
    return 0 if _ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        sys.modules.pop("pytesseract", None)
