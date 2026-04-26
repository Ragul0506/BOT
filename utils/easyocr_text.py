"""OCR text extraction — EasyOCR preferred, pytesseract fallback.

Image preprocessing pipeline (PIL only — no OpenCV):
  1. Convert to grayscale
  2. Upscale if too small (< 800 px on shortest side)
  3. Enhance contrast (2×)
  4. Autocontrast
  5. Otsu binary threshold
  6. Save preprocessed PNG → pass to OCR

pytesseract fallback uses --psm 6 (uniform block of text) for better
handling of handwritten / tabular bills.
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile

logger = logging.getLogger(__name__)

_easyocr_reader = None
_EASYOCR_LANGS = ["ta", "en"]


def _get_easyocr_reader():
    global _easyocr_reader
    if _easyocr_reader is None:
        import easyocr  # type: ignore[import]
        logger.info("Initialising EasyOCR reader (first call is slow)…")
        _easyocr_reader = easyocr.Reader(_EASYOCR_LANGS, gpu=False)
    return _easyocr_reader


# ── Otsu threshold (pure Python — no numpy needed) ───────────────────────────

def _otsu_threshold(hist: list[int], total: int) -> int:
    sum_all = sum(i * hist[i] for i in range(256))
    sum_b = 0
    w_b = 0
    max_var = 0.0
    threshold = 128
    for i in range(256):
        w_b += hist[i]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += i * hist[i]
        mean_b = sum_b / w_b
        mean_f = (sum_all - sum_b) / w_f
        var = w_b * w_f * (mean_b - mean_f) ** 2
        if var > max_var:
            max_var = var
            threshold = i
    return threshold


def _preprocess_image(image_path: str) -> str:
    """Return path to a preprocessed temp PNG (grayscale, contrast, Otsu).

    Caller is responsible for deleting the returned temp file.
    Falls back to returning a copy of the original if PIL is unavailable.
    """
    try:
        from PIL import Image, ImageEnhance, ImageOps  # type: ignore[import]
    except ImportError:
        logger.warning("PIL not available — skipping preprocessing")
        # Return a copy so callers can safely delete the path
        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        tmp.close()
        import shutil
        shutil.copy2(image_path, tmp.name)
        return tmp.name

    img = Image.open(image_path).convert("L")  # grayscale

    # Upscale tiny images so OCR has enough pixels
    w, h = img.size
    min_side = min(w, h)
    if min_side < 800:
        scale = 800 / min_side
        new_w, new_h = int(w * scale), int(h * scale)
        try:
            img = img.resize((new_w, new_h), Image.LANCZOS)
        except AttributeError:
            img = img.resize((new_w, new_h), Image.ANTIALIAS)  # Pillow < 10

    # Enhance contrast
    img = ImageEnhance.Contrast(img).enhance(2.0)

    # Autocontrast (stretches histogram)
    img = ImageOps.autocontrast(img, cutoff=1)

    # Otsu threshold → clean binary image
    hist = img.histogram()
    total_px = sum(hist)
    thresh = _otsu_threshold(hist, total_px)
    img = img.point(lambda px: 255 if px > thresh else 0, "L")

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    img.save(tmp.name)
    logger.debug("Preprocessed image → %s (thresh=%d)", tmp.name, thresh)
    return tmp.name


# ── OCR backends ──────────────────────────────────────────────────────────────

def _sync_easyocr(image_path: str) -> str:
    reader = _get_easyocr_reader()
    results = reader.readtext(image_path)
    lines = [text for (_, text, conf) in results if conf > 0.25]
    return " ".join(lines)


def _sync_pytesseract(image_path: str, psm: int = 6) -> str:
    import pytesseract  # type: ignore[import]
    from PIL import Image  # type: ignore[import]
    img = Image.open(image_path).convert("RGB")
    cfg = f"--psm {psm}"
    return pytesseract.image_to_string(img, lang="tam+eng", config=cfg)


# ── main extraction logic ─────────────────────────────────────────────────────

def _sync_extract(image_path: str) -> str:
    preproc_path: str | None = None
    try:
        preproc_path = _preprocess_image(image_path)

        # 1. EasyOCR on preprocessed image
        try:
            text = _sync_easyocr(preproc_path)
            if text.strip():
                logger.info("EasyOCR (preprocessed) extracted %d chars", len(text))
                return text
        except Exception as exc:
            logger.warning("EasyOCR failed (%s), trying pytesseract…", exc)

        # 2. pytesseract PSM 6 on preprocessed image
        try:
            text = _sync_pytesseract(preproc_path, psm=6)
            if text.strip():
                logger.info("pytesseract PSM-6 (preprocessed) extracted %d chars", len(text))
                return text
        except Exception as exc:
            logger.warning("pytesseract PSM-6 failed (%s), trying original…", exc)

        # 3. pytesseract PSM 6 on the *original* image (last resort)
        try:
            text = _sync_pytesseract(image_path, psm=6)
            if text.strip():
                logger.info("pytesseract PSM-6 (original) extracted %d chars", len(text))
                return text
        except Exception as exc:
            logger.error("All OCR methods failed: %s", exc)

    finally:
        if preproc_path and os.path.exists(preproc_path):
            try:
                os.unlink(preproc_path)
            except OSError:
                pass

    raise RuntimeError(
        "OCR failed — neither EasyOCR nor pytesseract could extract text. "
        "Make sure at least one OCR engine is installed and the image is legible."
    )


async def extract_text_from_image(image_path: str) -> str:
    """Extract text from *image_path* (JPEG / PNG). Runs in a thread executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _sync_extract, image_path)
