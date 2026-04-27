"""Photo → OCR → Groq LLM → PDF bill handler.

Flow:
  1. Download highest-resolution image.
  2. extract_text_from_image() — grayscale + Otsu + pytesseract PSM-6 fallback.
  3. classify_bill_type() to detect grocery vs service.
  4. parse_items() with Groq LLM.
  5. Service bill: check shop profile, extract customer/GST/discount/advance.
  6. Generate appropriate PDF (grocery or professional service invoice).
  7. Log the bill to bill history (if configured).
"""
from __future__ import annotations

import asyncio
import html as hl
import logging
import os
import tempfile
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from utils.bill_history import bill_history_available, log_bill
from utils.easyocr_text import extract_text_from_image
from utils.groq_llm import classify_bill_type, extract_service_details, parse_items
from utils.lang_store import get_user_lang
from utils.msgs import m
from utils.pdf_generator import (
    generate_grocery_bill,
    generate_service_bill,
    next_service_roll_number,
)
from utils.security import rate_limiter
from utils.shop_profile import get_shops_by_type, list_shops

_SERVICE_TYPES = frozenset({"salon", "tailoring", "electronics", "general_service"})

logger = logging.getLogger(__name__)

_MAX_PHOTO_BYTES = 10 * 1024 * 1024  # 10 MB


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    uid = update.effective_user.id
    lang = await get_user_lang(uid)

    if not rate_limiter.is_allowed(uid):
        await msg.reply_text(m("rate_limit", lang))
        return

    status = await msg.reply_text(m("photo_received", lang))

    image_path: str | None = None
    pdf_path: str | None = None

    try:
        # ── 1. Download highest-res photo ─────────────────────────────────────
        photo = msg.photo[-1]
        file = await photo.get_file()

        if file.file_size and file.file_size > _MAX_PHOTO_BYTES:
            await status.edit_text(m("photo_too_large", lang))
            return

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            image_path = tmp.name
        await file.download_to_drive(image_path)
        logger.info("Photo saved: %s (%.1f KB)", image_path, os.path.getsize(image_path) / 1024)

        # ── 2. OCR with preprocessing ─────────────────────────────────────────
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

        preview = hl.escape(ocr_text[:120] + ("…" if len(ocr_text) > 120 else ""))
        await status.edit_text(
            m("photo_ocr_preview", lang, preview=preview), parse_mode="HTML"
        )

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

        basic_sales = sum(
            float(i.get("qty", 1)) * float(i.get("rate", 0)) for i in items
        )

        await status.edit_text(m("photo_pdf_gen", lang, count=len(items)))

        # ── 4. Service bill route ─────────────────────────────────────────────
        if bill_type in _SERVICE_TYPES:
            svc_details = await extract_service_details(ocr_text)
            customer_name = (
                svc_details.get("customer_name")
                or update.effective_user.first_name
                or update.effective_user.full_name
                or "Valued Customer"
            )
            customer_mobile  = svc_details.get("customer_mobile", "")
            voice_discount_a = float(svc_details.get("discount_amount", 0) or 0)
            voice_discount_p = float(svc_details.get("discount_percent", 0) or 0)
            voice_gst_pct    = float(svc_details.get("gst_percent", 0) or 0)
            voice_advance    = float(svc_details.get("advance", 0) or 0)

            # Prefer shops matching detected type; fallback to all shops
            matching = get_shops_by_type(uid, bill_type)
            shops = matching if matching else list_shops(uid)

            if len(shops) == 0:
                shop_name = os.environ.get(
                    "SERVICE_SHOP_NAME", "SRI NARPAVI BEAUTY PARLOUR"
                )
                shop_data: dict = {}

            elif len(shops) == 1:
                shop_data = shops[0]
                shop_name = shop_data["shop_name"]

            else:
                # Multiple shops: ask user to pick
                context.user_data["pending_service_bill"] = {
                    "items":            items,
                    "customer_name":    customer_name,
                    "customer_mobile":  customer_mobile,
                    "discount_amount":  voice_discount_a,
                    "discount_percent": voice_discount_p,
                    "gst_percent":      voice_gst_pct,
                    "advance":          voice_advance,
                }
                keyboard = [
                    [InlineKeyboardButton(
                        s["shop_name"][:30],
                        callback_data=f"shop_select_bill:{s['id']}",
                    )]
                    for s in shops
                ]
                await status.edit_text(
                    m("shop_select_prompt", lang),
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="HTML",
                )
                return

            # ── Merge OCR values with shop defaults ───────────────────────────
            shop_gst_pct  = float(shop_data.get("gst_percent", 0) or 0)
            shop_disc_pct = float(shop_data.get("discount_percent", 0) or 0)

            gst_pct = voice_gst_pct or shop_gst_pct

            discount_amount = voice_discount_a
            if discount_amount <= 0 and voice_discount_p > 0:
                discount_amount = round(basic_sales * voice_discount_p / 100, 2)
            elif discount_amount <= 0 and shop_disc_pct > 0:
                discount_amount = round(basic_sales * shop_disc_pct / 100, 2)

            subtotal   = basic_sales - discount_amount
            gst_amount = round(subtotal * gst_pct / 100, 2) if gst_pct > 0 else 0.0
            net_amount = subtotal + gst_amount

            # Download logo
            logo_path_tmp: str | None = None
            if shop_data.get("logo_file_id"):
                try:
                    logo_file = await context.bot.get_file(shop_data["logo_file_id"])
                    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as t:
                        logo_path_tmp = t.name
                    await logo_file.download_to_drive(logo_path_tmp)
                except Exception as exc:
                    logger.warning("Logo download failed: %s", exc)
                    logo_path_tmp = None

            now = datetime.now()
            roll_no = next_service_roll_number(shop_name, now)
            try:
                pdf_path = generate_service_bill(
                    shop_name=shop_name,
                    shop_address=shop_data.get("address", ""),
                    shop_phone=shop_data.get("phone", ""),
                    shop_gst=shop_data.get("gst", ""),
                    shop_discount_percent=shop_disc_pct,
                    customer_name=customer_name,
                    customer_mobile=customer_mobile,
                    services=items,
                    total=basic_sales,
                    roll_number=roll_no,
                    date_str=now.strftime("%d-%m-%Y"),
                    time_str=now.strftime("%H:%M"),
                    logo_path=logo_path_tmp,
                    footer=shop_data.get("footer", ""),
                    discount_amount=discount_amount,
                    gst_percent=gst_pct,
                    advance=voice_advance,
                    theme_color=shop_data.get("theme_color") or "#E91E63",
                )
            finally:
                if logo_path_tmp and os.path.exists(logo_path_tmp):
                    try:
                        os.unlink(logo_path_tmp)
                    except OSError:
                        pass

            caption = m(
                "photo_service_bill_done", lang,
                shop=hl.escape(shop_name),
                roll=hl.escape(roll_no),
                total=net_amount,
            )

        else:
            pdf_path = generate_grocery_bill(items, lang="en")
            caption = m("photo_bill_done", lang, total=basic_sales)

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

        # ── 5. Log to bill history ────────────────────────────────────────────
        if bill_history_available():
            pdf_file_id = sent.document.file_id if sent and sent.document else ""
            bill_no = await log_bill(uid, items, basic_sales, pdf_file_id)
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
