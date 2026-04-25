"""OCR text extraction — EasyOCR preferred, pytesseract fallback.

Runtime detection: neither library is imported at module load to keep startup
fast. We attempt EasyOCR first; if unavailable we fall back to pytesseract.

Render.com free tier note:
  EasyOCR requires torch (~700 MB) + model download (~1 GB).
  pytesseract is much lighter — install via:
    apt-get install tesseract-ocr tesseract-ocr-tam
    pip install pytesseract Pillow
  Recommend pytesseract on the free tier.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_easyocr_reader = None  # lazy singleton
_EASYOCR_LANGS = ["ta", "en"]


def _get_easyocr_reader():
    global _easyocr_reader
    if _easyocr_reader is None:
        import easyocr  # type: ignore[import]
        logger.info("Initialising EasyOCR reader (first call is slow)…")
        _easyocr_reader = easyocr.Reader(_EASYOCR_LANGS, gpu=False)
    return _easyocr_reader


def _sync_easyocr(image_path: str) -> str:
    reader = _get_easyocr_reader()
    results = reader.readtext(image_path)
    lines = [text for (_, text, conf) in results if conf > 0.25]
    return " ".join(lines)


def _sync_pytesseract(image_path: str) -> str:
    import pytesseract  # type: ignore[import]
    from PIL import Image  # type: ignore[import]

    img = Image.open(image_path).convert("RGB")
    return pytesseract.image_to_string(img, lang="tam+eng")


def _sync_extract(image_path: str) -> str:
    # Try EasyOCR
    try:
        text = _sync_easyocr(image_path)
        if text.strip():
            logger.info("EasyOCR extracted %d chars", len(text))
            return text
    except Exception as exc:
        logger.warning("EasyOCR failed (%s), trying pytesseract…", exc)

    # Try pytesseract
    try:
        text = _sync_pytesseract(image_path)
        if text.strip():
            logger.info("pytesseract extracted %d chars", len(text))
            return text
    except Exception as exc:
        logger.error("pytesseract failed: %s", exc)

    raise RuntimeError(
        "OCR failed — neither EasyOCR nor pytesseract could extract text. "
        "Make sure at least one OCR engine is installed."
    )


async def extract_text_from_image(image_path: str) -> str:
    """Extract text from *image_path* (JPEG / PNG). Runs in a thread executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _sync_extract, image_path)
