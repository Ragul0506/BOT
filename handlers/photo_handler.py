"""Photo → OCR → Groq LLM → PDF bill handler.

When a user sends a photo of a receipt/bill:
  1. Download the highest-resolution image.
  2. Extract text via EasyOCR / pytesseract.
  3. classify_bill_type() to detect grocery vs service.
  4. Parse items with Groq LLM.
  5. Generate appropriate PDF (grocery or service invoice).
  6. Log the bill to Google Sheets bill history (if configured).

All PDFs are generated in English.
"""
from __future__ import annotations

import asyncio
import html as hl
import logging
import os
import tempfile
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from utils.bill_history import bill_history_available, log_bill
from utils.easyocr_text import extract_text_from_image
from utils.groq_llm import classify_bill_type, parse_items
from utils.lang_store import get_user_lang
from utils.msgs import m
from utils.pdf_generator import (
    generate_grocery_bill,
    generate_service_bill,
    next_service_roll_number,
)
from utils.security import rate_limiter

logger = logging.getLogger(__name__)

_MAX_PHOTO_BYTES = 10 * 1024 * 1024  # 10 MB


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    uid = update.effective_user.id
    lang = await get_user_lang(uid)

    # [C4] Enforce rate limit before any processing.
    if not rate_limiter.is_allowed(uid):
        await msg.reply_text(m("rate_limit", lang))
        return

    status = await msg.reply_text(m("photo_received", lang))

    image_path: str | None = None
    pdf_path: str | None = None

    try:
        # ── 1. Download highest-res photo ─────────────────────────────────────
        photo = msg.photo[-1]  # last = largest
        file = await photo.get_file()

        # [H4] Check file size before downloading.
        if file.file_size and file.file_size > _MAX_PHOTO_BYTES:
            await status.edit_text(m("photo_too_large", lang))
            return

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            image_path = tmp.name
        await file.download_to_drive(image_path)
        logger.info("Photo saved: %s (%.1f KB)", image_path, os.path.getsize(image_path) / 1024)

        # ── 2. OCR ────────────────────────────────────────────────────────────
        await status.edit_text(m("photo_ocr_running", lang))
        try:
            ocr_text = await extract_text_from_image(image_path)
        except RuntimeError as ocr_exc:
            logger.warning("OCR engine failure for user %s: %s", uid, ocr_exc)
            await status.edit_text(m("photo_ocr_fail", lang))
            return
        except Exception as ocr_exc:
            logger.error("Unexpected OCR error for user %s: %s", uid, ocr_exc, exc_info=True)
            await status.edit_text(m("photo_ocr_fail", lang))
            return

        if not ocr_text.strip():
            await status.edit_text(m("photo_ocr_fail", lang))
            return

        # [H1] HTML-escape OCR output before embedding in HTML message.
        preview = hl.escape(ocr_text[:120] + ("…" if len(ocr_text) > 120 else ""))
        await status.edit_text(m("photo_ocr_preview", lang, preview=preview), parse_mode="HTML")

        # ── 3. Parse items + classify bill type in parallel ───────────────────
        try:
            items, bill_type = await asyncio.gather(
                parse_items(ocr_text),
                classify_bill_type(ocr_text),
            )
        except ValueError:
            await status.edit_text(
                m("photo_no_items", lang, preview=hl.escape(ocr_text[:300])),
                parse_mode="HTML",
            )
            return

        if not items:
            await status.edit_text(
                m("photo_no_items", lang, preview=hl.escape(ocr_text[:300])),
                parse_mode="HTML",
            )
            return

        logger.info("Photo bill_type=%s items=%d", bill_type, len(items))

        # ── 4. Generate PDF ───────────────────────────────────────────────────
        await status.edit_text(m("photo_pdf_gen", lang, count=len(items)))
        grand_total = sum(float(i.get("qty", 1)) * float(i.get("rate", 0)) for i in items)

        if bill_type == "service":
            shop_name = os.environ.get("SERVICE_SHOP_NAME", "SRI NARPAVI BEAUTY PARLOUR")
            customer_name = (
                update.effective_user.first_name
                or update.effective_user.full_name
                or "Valued Customer"
            )
            now = datetime.now()
            roll_no = next_service_roll_number(shop_name, now)
            pdf_path = generate_service_bill(
                shop_name=shop_name,
                customer_name=customer_name,
                services=items,
                bill_number=roll_no,
                date_str=now.strftime("%d-%m-%Y"),
                time_str=now.strftime("%H:%M"),
            )
            caption = m("photo_service_bill_done", lang,
                        shop=hl.escape(shop_name), roll=hl.escape(roll_no), total=grand_total)
        else:
            pdf_path = generate_grocery_bill(items, lang="en")
            caption = m("photo_bill_done", lang, total=grand_total)

        try:
            await status.delete()
        except Exception:
            pass

        with open(pdf_path, "rb") as f:
            sent = await msg.reply_document(
                document=f,
                filename="bill_from_photo.pdf",
                caption=caption,
                parse_mode="HTML",
            )

        # ── 5. Log to bill history (non-blocking) ─────────────────────────────
        if bill_history_available():
            pdf_file_id = sent.document.file_id if sent and sent.document else ""
            bill_no = await log_bill(uid, items, grand_total, pdf_file_id)
            if bill_no:
                try:
                    await sent.reply_text(
                        m("bill_logged", lang, bill_no=hl.escape(bill_no)),
                        parse_mode="HTML",
                    )
                except Exception:
                    pass

    except Exception as exc:
        logger.error("Photo handler error for user %s: %s", uid, exc, exc_info=True)
        try:
            # [H2] Never expose raw exception to users; log internally only.
            await status.edit_text(m("generic_error", lang))
        except Exception:
            pass

    finally:
        for path in (image_path, pdf_path):
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except OSError:
                    pass
