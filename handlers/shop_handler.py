"""Shop profile management — /setshop (10-step), /listshops.

Flow for /setshop (ConversationHandler):
  1.  Ask shop name
  2.  Ask shop type       (inline buttons — Grocery/Salon/Tailoring/Electronics/General)
  3.  Ask address         (skippable)
  4.  Ask phone           (skippable)
  5.  Ask GST percent     (skippable)
  6.  Ask discount %      (skippable)
  7.  Ask theme colour    (skippable, default #E91E63 pink)
  8.  Ask GST reg. no.    (skippable)
  9.  Ask footer msg      (skippable)
  10. Ask logo photo      (skippable)
  → Save to SQLite via utils.shop_profile

/listshops shows all shops with inline buttons to set default.
"""
from __future__ import annotations

import html as hl
import logging
import os
import re
import tempfile
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from utils.lang_store import get_user_lang
from utils.msgs import m
from utils.shop_profile import (
    create_shop,
    get_shop,
    list_shops,
    set_default_shop,
)

logger = logging.getLogger(__name__)

# ── ConversationHandler states ────────────────────────────────────────────────
(
    SHOP_NAME,
    SHOP_TYPE,      # inline button step — step 2
    SHOP_ADDRESS,
    SHOP_PHONE,
    SHOP_GST_PCT,
    SHOP_DISCOUNT,
    SHOP_THEME,
    SHOP_GST,
    SHOP_FOOTER,
    SHOP_LOGO,
) = range(10)

_SHOP_TYPE_LABELS: dict[str, str] = {
    "grocery":         "🏪 Grocery",
    "salon":           "💇 Salon",
    "tailoring":       "🧵 Tailoring",
    "electronics":     "📱 Electronics",
    "general_service": "🛠️ General Service",
}

_HEX_COLOR_RE = re.compile(r'^#[0-9A-Fa-f]{6}$')

_SKIP_WORDS = {"skip", "-", "no", "none", "нет"}


def _is_skip(text: str) -> bool:
    return text.strip().lower().lstrip("/") in _SKIP_WORDS


def _parse_pct(text: str) -> float:
    """Parse a percentage from text like '18', '18%', '18.5'. Returns 0.0 on failure."""
    cleaned = re.sub(r"[^0-9.]", "", text.strip())
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


# ── /setshop entry ────────────────────────────────────────────────────────────


async def handle_setshop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    uid = update.effective_user.id
    lang = await get_user_lang(uid)
    context.user_data.pop("_shop_draft", None)
    context.user_data["_shop_draft"] = {}
    await update.message.reply_text(m("setshop_ask_name", lang), parse_mode="HTML")
    return SHOP_NAME


# ── step handlers ─────────────────────────────────────────────────────────────


async def _got_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = (update.message.text or "").strip()
    uid = update.effective_user.id
    lang = await get_user_lang(uid)
    if len(name) < 2:
        await update.message.reply_text(m("setshop_name_invalid", lang))
        return SHOP_NAME
    context.user_data["_shop_draft"]["shop_name"] = name
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🏪 Grocery",     callback_data="shoptype_grocery"),
            InlineKeyboardButton("💇 Salon",        callback_data="shoptype_salon"),
        ],
        [
            InlineKeyboardButton("🧵 Tailoring",   callback_data="shoptype_tailoring"),
            InlineKeyboardButton("📱 Electronics",  callback_data="shoptype_electronics"),
        ],
        [
            InlineKeyboardButton("🛠️ General Service", callback_data="shoptype_general_service"),
        ],
    ])
    await update.message.reply_text(
        m("setshop_ask_type", lang), parse_mode="HTML", reply_markup=keyboard
    )
    return SHOP_TYPE


async def _got_shop_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    lang = await get_user_lang(uid)

    raw = (query.data or "").removeprefix("shoptype_")
    shop_type = raw if raw in _SHOP_TYPE_LABELS else "general_service"
    context.user_data["_shop_draft"]["shop_type"] = shop_type

    label = _SHOP_TYPE_LABELS[shop_type]
    await query.edit_message_text(
        f"✅ Shop type: <b>{label}</b>", parse_mode="HTML"
    )
    await query.message.reply_text(m("setshop_ask_address", lang), parse_mode="HTML")
    return SHOP_ADDRESS


async def _got_address(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()
    context.user_data["_shop_draft"]["address"] = "" if _is_skip(text) else text
    uid = update.effective_user.id
    lang = await get_user_lang(uid)
    await update.message.reply_text(m("setshop_ask_phone", lang), parse_mode="HTML")
    return SHOP_PHONE


async def _got_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()
    context.user_data["_shop_draft"]["phone"] = "" if _is_skip(text) else text
    uid = update.effective_user.id
    lang = await get_user_lang(uid)
    await update.message.reply_text(m("setshop_ask_gst_pct", lang), parse_mode="HTML")
    return SHOP_GST_PCT


async def _got_gst_pct(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()
    uid = update.effective_user.id
    lang = await get_user_lang(uid)
    pct = 0.0 if _is_skip(text) else _parse_pct(text)
    context.user_data["_shop_draft"]["gst_percent"] = pct
    await update.message.reply_text(m("setshop_ask_discount_pct", lang), parse_mode="HTML")
    return SHOP_DISCOUNT


async def _got_discount_pct(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()
    uid = update.effective_user.id
    lang = await get_user_lang(uid)
    pct = 0.0 if _is_skip(text) else _parse_pct(text)
    context.user_data["_shop_draft"]["discount_percent"] = pct
    await update.message.reply_text(m("setshop_ask_theme", lang), parse_mode="HTML")
    return SHOP_THEME


async def _got_theme_color(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()
    uid = update.effective_user.id
    lang = await get_user_lang(uid)

    if _is_skip(text):
        color = "#E91E63"
    else:
        # Normalise 3-char shorthand (#RGB → #RRGGBB)
        if re.match(r'^#[0-9A-Fa-f]{3}$', text):
            text = '#' + text[1]*2 + text[2]*2 + text[3]*2
        if _HEX_COLOR_RE.match(text):
            color = text.upper()
        else:
            await update.message.reply_text(m("setshop_theme_invalid", lang))
            return SHOP_THEME

    context.user_data["_shop_draft"]["theme_color"] = color
    await update.message.reply_text(m("setshop_ask_gst", lang), parse_mode="HTML")
    return SHOP_GST


async def _got_gst(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()
    context.user_data["_shop_draft"]["gst"] = "" if _is_skip(text) else text
    uid = update.effective_user.id
    lang = await get_user_lang(uid)
    await update.message.reply_text(m("setshop_ask_footer", lang), parse_mode="HTML")
    return SHOP_FOOTER


async def _got_footer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (update.message.text or "").strip()
    context.user_data["_shop_draft"]["footer"] = "" if _is_skip(text) else text
    uid = update.effective_user.id
    lang = await get_user_lang(uid)
    await update.message.reply_text(m("setshop_ask_logo", lang), parse_mode="HTML")
    return SHOP_LOGO


async def _got_logo_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logo_file_id = update.message.photo[-1].file_id
    context.user_data["_shop_draft"]["logo_file_id"] = logo_file_id
    return await _save_shop(update, context)


async def _got_logo_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["_shop_draft"]["logo_file_id"] = ""
    return await _save_shop(update, context)


async def _save_shop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    uid = update.effective_user.id
    lang = await get_user_lang(uid)
    draft = context.user_data.pop("_shop_draft", {})

    shop_id = create_shop(
        user_id=uid,
        shop_name=draft.get("shop_name", "My Shop"),
        address=draft.get("address", ""),
        phone=draft.get("phone", ""),
        gst=draft.get("gst", ""),
        logo_file_id=draft.get("logo_file_id", ""),
        footer=draft.get("footer", ""),
        gst_percent=float(draft.get("gst_percent", 0) or 0),
        discount_percent=float(draft.get("discount_percent", 0) or 0),
        shop_type=draft.get("shop_type", "general_service"),
        theme_color=draft.get("theme_color", "#E91E63"),
    )
    shop_name = draft.get("shop_name", "My Shop")
    logger.info("Created shop id=%d name=%r for user=%d", shop_id, shop_name, uid)
    await update.message.reply_text(
        m("setshop_done", lang, shop=hl.escape(shop_name)),
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def _cancel_setshop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    uid = update.effective_user.id
    lang = await get_user_lang(uid)
    context.user_data.pop("_shop_draft", None)
    await update.message.reply_text(m("setshop_cancelled", lang))
    return ConversationHandler.END


# ── /listshops ────────────────────────────────────────────────────────────────


async def handle_listshops(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    lang = await get_user_lang(uid)
    shops = list_shops(uid)

    if not shops:
        await update.message.reply_text(m("listshops_empty", lang), parse_mode="HTML")
        return

    lines = [m("listshops_header", lang)]
    for i, s in enumerate(shops, 1):
        star = " ⭐" if s["is_default"] else ""
        lines.append(f"{i}. <b>{hl.escape(s['shop_name'])}</b>{star}")
        if s.get("address"):
            lines.append(f"   📍 {hl.escape(s['address'])}")
        if s.get("phone"):
            lines.append(f"   📞 {hl.escape(s['phone'])}")
        if s.get("gst"):
            lines.append(f"   🏷️ GST: {hl.escape(s['gst'])}")
        gst_pct = float(s.get("gst_percent", 0) or 0)
        disc_pct = float(s.get("discount_percent", 0) or 0)
        if gst_pct > 0:
            lines.append(f"   💸 GST: {gst_pct:.1f}%")
        if disc_pct > 0:
            lines.append(f"   🎟️ Discount: {disc_pct:.1f}%")

    keyboard = [
        [InlineKeyboardButton(
            f"⭐ Set '{s['shop_name'][:18]}' as Default",
            callback_data=f"shop_default:{s['id']}",
        )]
        for s in shops
        if not s["is_default"]
    ]

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
    )


# ── callback: shop_default:<id> and shop_select_bill:<id> ─────────────────────


async def handle_shop_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()

    uid = update.effective_user.id
    lang = await get_user_lang(uid)
    data = query.data or ""

    if data.startswith("shop_default:"):
        shop_id = int(data.split(":", 1)[1])
        if set_default_shop(shop_id, uid):
            shops = list_shops(uid)
            shop = next((s for s in shops if s["id"] == shop_id), None)
            name = shop["shop_name"] if shop else "Shop"
            await query.edit_message_text(
                m("shop_default_set", lang, shop=hl.escape(name)),
                parse_mode="HTML",
            )
        else:
            await query.answer("❌ Could not update default.", show_alert=True)

    elif data.startswith("shop_select_bill:"):
        shop_id = int(data.split(":", 1)[1])
        await _generate_pending_bill(update, context, shop_id)


# ── pending-bill generation (called after shop selection) ─────────────────────


async def _generate_pending_bill(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    shop_id: int,
) -> None:
    """Generate service PDF after user selects a shop via inline button."""
    from utils.pdf_generator import generate_service_bill, next_service_roll_number

    query = update.callback_query
    uid = update.effective_user.id
    lang = await get_user_lang(uid)

    pending = context.user_data.get("pending_service_bill")
    if not pending:
        await query.edit_message_text(m("shop_bill_expired", lang))
        return

    shop = get_shop(shop_id, uid)
    if not shop:
        await query.edit_message_text("❌ Shop not found.")
        return

    # Download logo if available
    logo_path: str | None = None
    if shop.get("logo_file_id"):
        try:
            logo_file = await context.bot.get_file(shop["logo_file_id"])
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                logo_path = tmp.name
            await logo_file.download_to_drive(logo_path)
        except Exception as exc:
            logger.warning("Logo download failed for shop %d: %s", shop_id, exc)
            logo_path = None

    pdf_path: str | None = None
    try:
        items = pending["items"]
        basic_sales = sum(
            float(i.get("qty", 1)) * float(i.get("rate", 0)) for i in items
        )

        # Merge voice-extracted values with shop defaults
        discount_amount  = float(pending.get("discount_amount", 0) or 0)
        discount_percent = float(pending.get("discount_percent", 0) or 0)
        gst_pct          = float(pending.get("gst_percent", 0) or 0) or float(shop.get("gst_percent", 0) or 0)
        advance          = float(pending.get("advance", 0) or 0)
        shop_disc_pct    = float(shop.get("discount_percent", 0) or 0)

        # Resolve discount: explicit voice amount > voice percent > shop default
        if discount_amount <= 0 and discount_percent > 0:
            discount_amount = round(basic_sales * discount_percent / 100, 2)
        elif discount_amount <= 0 and shop_disc_pct > 0:
            discount_amount = round(basic_sales * shop_disc_pct / 100, 2)

        subtotal   = basic_sales - discount_amount
        gst_amount = round(subtotal * gst_pct / 100, 2) if gst_pct > 0 else 0.0
        net_amount = subtotal + gst_amount

        now = datetime.now()
        roll_no = next_service_roll_number(shop["shop_name"], now)

        pdf_path = generate_service_bill(
            shop_name=shop["shop_name"],
            shop_address=shop.get("address", ""),
            shop_phone=shop.get("phone", ""),
            shop_gst=shop.get("gst", ""),
            shop_discount_percent=shop_disc_pct,
            customer_name=pending.get("customer_name", "Valued Customer"),
            customer_mobile=pending.get("customer_mobile", ""),
            services=items,
            total=basic_sales,
            roll_number=roll_no,
            date_str=now.strftime("%d-%m-%Y"),
            time_str=now.strftime("%H:%M"),
            logo_path=logo_path,
            footer=shop.get("footer", ""),
            discount_amount=discount_amount,
            gst_percent=gst_pct,
            advance=advance,
            theme_color=shop.get("theme_color") or "#E91E63",
        )

        caption = m(
            "voice_service_bill_done", lang,
            shop=hl.escape(shop["shop_name"]),
            roll=hl.escape(roll_no),
            total=net_amount,
        )

        msg = query.message
        with open(pdf_path, "rb") as f:
            await msg.reply_document(
                document=f,
                filename="service_invoice.pdf",
                caption=caption,
                parse_mode="HTML",
            )
        await query.edit_message_text("✅ Invoice generated!", parse_mode="HTML")

    except Exception as exc:
        logger.error("_generate_pending_bill error: %s", exc, exc_info=True)
        await query.edit_message_text("❌ Could not generate invoice. Try again.")

    finally:
        for p in (pdf_path, logo_path):
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except OSError:
                    pass
        context.user_data.pop("pending_service_bill", None)


# ── ConversationHandler factory (imported by main.py) ─────────────────────────


def get_shop_conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("setshop", handle_setshop)],
        states={
            SHOP_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, _got_name),
            ],
            SHOP_TYPE: [
                CallbackQueryHandler(_got_shop_type, pattern=r"^shoptype_"),
            ],
            SHOP_ADDRESS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, _got_address),
            ],
            SHOP_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, _got_phone),
            ],
            SHOP_GST_PCT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, _got_gst_pct),
                MessageHandler(filters.COMMAND, _got_gst_pct),  # /skip
            ],
            SHOP_DISCOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, _got_discount_pct),
                MessageHandler(filters.COMMAND, _got_discount_pct),  # /skip
            ],
            SHOP_THEME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, _got_theme_color),
                MessageHandler(filters.COMMAND, _got_theme_color),  # /skip
            ],
            SHOP_GST: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, _got_gst),
            ],
            SHOP_FOOTER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, _got_footer),
            ],
            SHOP_LOGO: [
                MessageHandler(filters.PHOTO, _got_logo_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, _got_logo_skip),
                MessageHandler(filters.COMMAND, _got_logo_skip),  # /skip
            ],
        },
        fallbacks=[CommandHandler("cancel", _cancel_setshop)],
        per_user=True,
        per_chat=True,
        name="setshop_conversation",
        persistent=False,
    )
