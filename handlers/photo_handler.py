"""Photo → OCR → Groq LLM → PDF bill handler.

When a user sends a photo of a receipt/bill:
  1. Download the highest-resolution image.
  2. Extract text via EasyOCR / pytesseract.
  3. Pass text to the same Groq LLM bill parser.
  4. Generate and send a PDF bill.
"""
from __future__ import annotations

import logging
import os
import tempfile

from telegram import Update
from telegram.ext import ContextTypes

from utils.easyocr_text import extract_text_from_image
from utils.groq_llm import parse_items
from utils.pdf_generator import generate_bill_pdf

logger = logging.getLogger(__name__)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    status = await msg.reply_text(
        "📸 Photo கிடைச்சது! OCR பண்றேன்…"
    )

    image_path: str | None = None
    pdf_path: str | None = None

    try:
        # ── 1. Download highest-res photo ─────────────────────────────────────
        photo = msg.photo[-1]  # last = largest
        file = await photo.get_file()
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            image_path = tmp.name
        await file.download_to_drive(image_path)
        logger.info("Photo saved: %s (%.1f KB)", image_path, os.path.getsize(image_path) / 1024)

        # ── 2. OCR ────────────────────────────────────────────────────────────
        await status.edit_text("🔍 Text extract பண்றேன் (OCR)…")
        ocr_text = await extract_text_from_image(image_path)
        if not ocr_text.strip():
            await status.edit_text(
                "❌ Photo-ல் text கண்டுபிடிக்கவில்லை.\n"
                "தெளிவான lighting-ல் bill photo எடுங்க."
            )
            return

        preview = ocr_text[:120] + ("…" if len(ocr_text) > 120 else "")
        await status.edit_text(
            f"📝 <b>OCR Text:</b> <i>{preview}</i>\n\nItems parse பண்றேன்…",
            parse_mode="HTML",
        )

        # ── 3. Parse items with LLM ───────────────────────────────────────────
        items = await parse_items(ocr_text)
        if not items:
            await status.edit_text(
                f"❌ Items parse ஆகவில்லை.\n\n"
                f"<b>OCR Text:</b> {ocr_text[:300]}\n\n"
                "Bill-ல் items + prices இருக்கா என்று check பண்ணுங்க.",
                parse_mode="HTML",
            )
            return

        # ── 4. Generate PDF ───────────────────────────────────────────────────
        await status.edit_text(f"📄 {len(items)} items found. PDF தயாரிக்கிறேன்…")
        pdf_path = generate_bill_pdf(items)

        grand_total = sum(float(i.get("qty", 1)) * float(i.get("rate", 0)) for i in items)
        caption = f"இதோ உங்க பில் (photo-ல் இருந்து). மொத்தம் &#8377; {grand_total:.0f}."

        try:
            await status.delete()
        except Exception:
            pass

        with open(pdf_path, "rb") as f:
            await msg.reply_document(
                document=f,
                filename="bill_from_photo.pdf",
                caption=caption,
                parse_mode="HTML",
            )

    except Exception as exc:
        logger.error("Photo handler error: %s", exc, exc_info=True)
        try:
            await status.edit_text(
                f"❌ <b>Error:</b> {exc}\n\nமீண்டும் try பண்ணுங்க.",
                parse_mode="HTML",
            )
        except Exception:
            pass

    finally:
        for path in (image_path, pdf_path):
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except OSError:
                    pass
