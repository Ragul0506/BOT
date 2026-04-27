"""Voice note handler — transcribe then route by LLM intent.

Flow:
  1. Download OGG from Telegram.
  2. Transcribe with Groq Whisper.
  3. classify_voice_intent() → "bill" | "expense" | "other"
  4a. "expense" → process_expense_text (expense_handler)
  4b. "bill" / "other":
       → classify_bill_type()
       → "service": extract_service_details(), check shop profile
            • 0 shops  → use SERVICE_SHOP_NAME env var (legacy)
            • 1 shop   → generate immediately with full GST/discount/advance
            • 2+ shops → store pending data, show inline shop-picker
       → "grocery" / "other": generate_grocery_bill()
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
from utils.groq_llm import (
    classify_bill_type,
    classify_voice_intent,
    extract_service_details,
    parse_items,
)
from utils.groq_whisper import transcribe_audio
from utils.lang_store import get_user_lang
from utils.msgs import m
from utils.pdf_generator import (
    generate_grocery_bill,
    generate_service_bill,
    next_service_roll_number,
)
from utils.security import rate_limiter
from utils.shop_profile import get_default_shop, get_shops_by_type, list_shops

_SERVICE_TYPES = frozenset({"salon", "tailoring", "electronics", "general_service"})

logger = logging.getLogger(__name__)

_MAX_VOICE_BYTES = 20 * 1024 * 1024  # 20 MB


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    uid = update.effective_user.id
    lang = await get_user_lang(uid)

    if not rate_limiter.is_allowed(uid):
        await msg.reply_text(m("rate_limit", lang))
        return

    status = await msg.reply_text(m("voice_received", lang))

    audio_path: str | None = None
    pdf_path: str | None = None

    try:
        # ── 1. Download OGG ───────────────────────────────────────────────────
        voice_file = await msg.voice.get_file()

        if voice_file.file_size and voice_file.file_size > _MAX_VOICE_BYTES:
            await status.edit_text(m("voice_too_large", lang))
            return

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            audio_path = tmp.name
        await voice_file.download_to_drive(audio_path)
        logger.info("Voice: %s (%.1f KB)", audio_path, os.path.getsize(audio_path) / 1024)

        # ── 2. Transcribe ─────────────────────────────────────────────────────
        await status.edit_text(m("voice_transcribing", lang))
        transcript = await transcribe_audio(audio_path)

        if not transcript.strip():
            await status.edit_text(m("voice_no_transcript", lang))
            return

        preview = hl.escape(transcript[:100] + ("…" if len(transcript) > 100 else ""))
        await status.edit_text(m("voice_intent", lang, preview=preview), parse_mode="HTML")

        # ── 3. Classify intent ────────────────────────────────────────────────
        intent = await classify_voice_intent(transcript)
        logger.info("Voice intent: '%s' | transcript: %s", intent, transcript[:80])

        if intent == "expense":
            from handlers.expense_handler import process_expense_text
            await process_expense_text(update, transcript, status_msg=status)
            return

        # ── 4. Bill route ─────────────────────────────────────────────────────
        await status.edit_text(m("voice_parsing_bill", lang))

        try:
            items, bill_type = await asyncio.gather(
                parse_items(transcript),
                classify_bill_type(transcript),
            )
        except ValueError:
            safe_preview = hl.escape(transcript[:200])
            key = "voice_no_items_other" if intent == "other" else "voice_no_items_bill"
            await status.edit_text(m(key, lang, preview=safe_preview), parse_mode="HTML")
            return

        logger.info("Bill type: '%s' | items: %d", bill_type, len(items))

        if not items:
            safe_preview = hl.escape(transcript[:200])
            key = "voice_no_items_other" if intent == "other" else "voice_no_items_bill"
            await status.edit_text(m(key, lang, preview=safe_preview), parse_mode="HTML")
            return

        basic_sales = sum(
            float(i.get("qty", 1)) * float(i.get("rate", 0)) for i in items
        )

        await status.edit_text(m("voice_pdf_gen", lang, count=len(items)))

        # ── 5a. Service bill route ────────────────────────────────────────────
        if bill_type in _SERVICE_TYPES:
            svc_details = await extract_service_details(transcript)
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
                # Multiple shops: store pending data and ask user to pick
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
                return  # PDF generated in shop_handler callback

            # ── Merge voice values with shop defaults ─────────────────────────
            shop_gst_pct  = float(shop_data.get("gst_percent", 0) or 0)
            shop_disc_pct = float(shop_data.get("discount_percent", 0) or 0)

            gst_pct = voice_gst_pct or shop_gst_pct

            # Resolve discount: voice amount > voice percent > shop default percent
            discount_amount = voice_discount_a
            if discount_amount <= 0 and voice_discount_p > 0:
                discount_amount = round(basic_sales * voice_discount_p / 100, 2)
            elif discount_amount <= 0 and shop_disc_pct > 0:
                discount_amount = round(basic_sales * shop_disc_pct / 100, 2)

            subtotal   = basic_sales - discount_amount
            gst_amount = round(subtotal * gst_pct / 100, 2) if gst_pct > 0 else 0.0
            net_amount = subtotal + gst_amount

            # Download logo if available
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
                "voice_service_bill_done", lang,
                shop=hl.escape(shop_name),
                roll=hl.escape(roll_no),
                total=net_amount,
            )

        # ── 5b. Grocery / other bill route ────────────────────────────────────
        else:
            pdf_path = generate_grocery_bill(items, lang="en")
            caption = m("voice_bill_done", lang, total=basic_sales)

        # ── 6. Send PDF ───────────────────────────────────────────────────────
        try:
            await status.delete()
        except Exception:
            pass

        with open(pdf_path, "rb") as pdf_file:
            sent = await msg.reply_document(
                document=pdf_file,
                filename="bill.pdf",
                caption=caption,
                parse_mode="HTML",
            )

        # ── 7. Log to bill history ────────────────────────────────────────────
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
        logger.error("Voice handler error for user %s: %s", uid, exc, exc_info=True)
        try:
            await status.edit_text(m("generic_error", lang))
        except Exception:
            pass

    finally:
        for path in (audio_path, pdf_path):
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except OSError:
                    pass
