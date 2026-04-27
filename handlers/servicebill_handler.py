"""Manual /servicebill ConversationHandler — 5-step invoice builder.

Steps:
  1. Customer name & mobile
  2. Services & rates
  3. Discount (amount or %)
  4. GST percentage
  5. Advance paid
  → Generate professional Tax Invoice PDF using default shop profile
"""
from __future__ import annotations

import html as hl
import logging
import os
import re
import tempfile
from datetime import datetime

from telegram import Update
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from utils.lang_store import get_user_lang
from utils.msgs import m
from utils.pdf_generator import generate_service_bill, next_service_roll_number
from utils.shop_profile import get_default_shop

logger = logging.getLogger(__name__)

# ── States ────────────────────────────────────────────────────────────────────
SB_CUSTOMER, SB_SERVICES, SB_DISCOUNT, SB_GST, SB_ADVANCE = range(5)

_SKIP = {"skip", "/skip"}


def _is_skip(text: str) -> bool:
    return text.strip().lower() in _SKIP


def _parse_float(text: str, fallback: float = 0.0) -> float:
    cleaned = re.sub(r"[^0-9.]", "", text.strip())
    try:
        return float(cleaned)
    except ValueError:
        return fallback


def _parse_mobile(text: str) -> str:
    """Extract a 10-digit Indian mobile from text."""
    m_match = re.search(r"\b[6-9]\d{9}\b", text)
    return m_match.group() if m_match else ""


def _parse_name(text: str) -> str:
    """Extract name by removing the mobile number."""
    mobile = _parse_mobile(text)
    name = text.replace(mobile, "").strip().strip(",").strip()
    return name or ""


# ── Entry ─────────────────────────────────────────────────────────────────────


async def handle_servicebill(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    uid = update.effective_user.id
    lang = await get_user_lang(uid)
    context.user_data.pop("_sb_draft", None)
    context.user_data["_sb_draft"] = {}
    await update.message.reply_text(m("servicebill_start", lang), parse_mode="HTML")
    await update.message.reply_text(m("servicebill_ask_customer", lang), parse_mode="HTML")
    return SB_CUSTOMER


# ── Step 1: customer ──────────────────────────────────────────────────────────


async def _got_customer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()
    uid = update.effective_user.id
    lang = await get_user_lang(uid)
    draft = context.user_data["_sb_draft"]

    if not _is_skip(text):
        draft["customer_name"]   = _parse_name(text)
        draft["customer_mobile"] = _parse_mobile(text)
    else:
        draft["customer_name"]   = ""
        draft["customer_mobile"] = ""

    await update.message.reply_text(m("servicebill_ask_services", lang), parse_mode="HTML")
    return SB_SERVICES


# ── Step 2: services ──────────────────────────────────────────────────────────


async def _got_services(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()
    uid = update.effective_user.id
    lang = await get_user_lang(uid)
    draft = context.user_data["_sb_draft"]

    if not _is_skip(text):
        await update.message.reply_text(m("servicebill_generating", lang))
        try:
            from utils.groq_llm import parse_items
            items = await parse_items(text)
            draft["services"] = items
        except ValueError:
            await update.message.reply_text(m("servicebill_no_items", lang), parse_mode="HTML")
            return SB_SERVICES
    else:
        draft["services"] = []

    await update.message.reply_text(m("servicebill_ask_discount", lang), parse_mode="HTML")
    return SB_DISCOUNT


# ── Step 3: discount ──────────────────────────────────────────────────────────


async def _got_discount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()
    uid = update.effective_user.id
    lang = await get_user_lang(uid)
    draft = context.user_data["_sb_draft"]

    if not _is_skip(text):
        if "%" in text:
            draft["discount_percent"] = _parse_float(text.split("%")[0])
            draft["discount_amount"]  = 0.0
        else:
            draft["discount_amount"]  = _parse_float(text)
            draft["discount_percent"] = 0.0
    else:
        draft["discount_amount"]  = 0.0
        draft["discount_percent"] = 0.0

    await update.message.reply_text(m("servicebill_ask_gst", lang), parse_mode="HTML")
    return SB_GST


# ── Step 4: GST ───────────────────────────────────────────────────────────────


async def _got_gst(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()
    uid = update.effective_user.id
    lang = await get_user_lang(uid)
    draft = context.user_data["_sb_draft"]

    if not _is_skip(text):
        draft["gst_percent"] = _parse_float(text.replace("%", ""))
    else:
        draft["gst_percent"] = 0.0

    await update.message.reply_text(m("servicebill_ask_advance", lang), parse_mode="HTML")
    return SB_ADVANCE


# ── Step 5: advance → generate PDF ───────────────────────────────────────────


async def _got_advance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()
    uid = update.effective_user.id
    lang = await get_user_lang(uid)
    draft = context.user_data.pop("_sb_draft", {})

    advance = _parse_float(text) if not _is_skip(text) else 0.0

    services = draft.get("services", [])
    if not services:
        await update.message.reply_text(m("servicebill_no_items", lang), parse_mode="HTML")
        return ConversationHandler.END

    # Fetch default shop profile
    shop = get_default_shop(uid)
    shop_name     = shop["shop_name"]  if shop else os.environ.get("SERVICE_SHOP_NAME", "My Shop")
    shop_address  = shop.get("address", "") if shop else ""
    shop_phone    = shop.get("phone", "")   if shop else ""
    shop_gst      = shop.get("gst", "")     if shop else ""
    shop_disc_pct = float(shop.get("discount_percent", 0) or 0) if shop else 0.0
    shop_footer   = shop.get("footer", "") if shop else ""
    shop_theme    = (shop.get("theme_color") or "#E91E63") if shop else "#E91E63"

    # Merge draft values with shop defaults
    gst_pct          = float(draft.get("gst_percent", 0) or 0) or float(shop.get("gst_percent", 0) or 0) if shop else 0.0
    discount_amount  = float(draft.get("discount_amount", 0) or 0)
    discount_percent = float(draft.get("discount_percent", 0) or 0)

    basic_sales = sum(float(s.get("qty", 1)) * float(s.get("rate", 0)) for s in services)

    if discount_amount <= 0 and discount_percent > 0:
        discount_amount = round(basic_sales * discount_percent / 100, 2)
    elif discount_amount <= 0 and shop_disc_pct > 0:
        discount_amount = round(basic_sales * shop_disc_pct / 100, 2)

    subtotal   = basic_sales - discount_amount
    gst_amount = round(subtotal * gst_pct / 100, 2) if gst_pct > 0 else 0.0
    net_amount = subtotal + gst_amount

    # Download logo if shop has one
    logo_path_tmp: str | None = None
    if shop and shop.get("logo_file_id"):
        try:
            logo_file = await context.bot.get_file(shop["logo_file_id"])
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as t:
                logo_path_tmp = t.name
            await logo_file.download_to_drive(logo_path_tmp)
        except Exception as exc:
            logger.warning("Logo download failed: %s", exc)
            logo_path_tmp = None

    status = await update.message.reply_text(m("servicebill_generating", lang))
    pdf_path: str | None = None

    try:
        now = datetime.now()
        roll_no = next_service_roll_number(shop_name, now)

        pdf_path = generate_service_bill(
            shop_name=shop_name,
            shop_address=shop_address,
            shop_phone=shop_phone,
            shop_gst=shop_gst,
            shop_discount_percent=shop_disc_pct,
            customer_name=draft.get("customer_name", "") or "Valued Customer",
            customer_mobile=draft.get("customer_mobile", ""),
            services=services,
            total=basic_sales,
            roll_number=roll_no,
            date_str=now.strftime("%d-%m-%Y"),
            time_str=now.strftime("%H:%M"),
            logo_path=logo_path_tmp,
            footer=shop_footer,
            discount_amount=discount_amount,
            gst_percent=gst_pct,
            advance=advance,
            theme_color=shop_theme,
        )

        caption = m(
            "servicebill_done", lang,
            shop=hl.escape(shop_name),
            roll=hl.escape(roll_no),
            net=net_amount,
        )

        with open(pdf_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename="service_invoice.pdf",
                caption=caption,
                parse_mode="HTML",
            )
        try:
            await status.delete()
        except Exception:
            pass

    except Exception as exc:
        logger.error("servicebill_handler generate error: %s", exc, exc_info=True)
        await status.edit_text(m("generic_error", lang))

    finally:
        for p in (pdf_path, logo_path_tmp):
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except OSError:
                    pass

    return ConversationHandler.END


# ── Cancel ────────────────────────────────────────────────────────────────────


async def _cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    uid = update.effective_user.id
    lang = await get_user_lang(uid)
    context.user_data.pop("_sb_draft", None)
    await update.message.reply_text(m("servicebill_cancelled", lang))
    return ConversationHandler.END


# ── ConversationHandler factory ───────────────────────────────────────────────


def get_servicebill_conversation_handler() -> ConversationHandler:
    skip_filter = filters.Regex(r"(?i)^/?\s*skip$")
    return ConversationHandler(
        entry_points=[CommandHandler("servicebill", handle_servicebill)],
        states={
            SB_CUSTOMER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND | skip_filter, _got_customer),
                MessageHandler(filters.COMMAND & filters.Regex(r"(?i)^/skip"), _got_customer),
            ],
            SB_SERVICES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND | skip_filter, _got_services),
                MessageHandler(filters.COMMAND & filters.Regex(r"(?i)^/skip"), _got_services),
            ],
            SB_DISCOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND | skip_filter, _got_discount),
                MessageHandler(filters.COMMAND & filters.Regex(r"(?i)^/skip"), _got_discount),
            ],
            SB_GST: [
                MessageHandler(filters.TEXT & ~filters.COMMAND | skip_filter, _got_gst),
                MessageHandler(filters.COMMAND & filters.Regex(r"(?i)^/skip"), _got_gst),
            ],
            SB_ADVANCE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND | skip_filter, _got_advance),
                MessageHandler(filters.COMMAND & filters.Regex(r"(?i)^/skip"), _got_advance),
            ],
        },
        fallbacks=[CommandHandler("cancel", _cancel)],
        per_user=True,
        per_chat=True,
        name="servicebill_conversation",
        persistent=False,
    )
