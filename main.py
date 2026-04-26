"""
Telegram bot entry-point.

Production : webhook mode — Render.com sets RENDER_EXTERNAL_URL automatically.
Local dev  : polling mode — no RENDER_EXTERNAL_URL set.
"""
from __future__ import annotations

import asyncio
import logging
import os

from aiohttp import web
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    InlineQueryHandler,
    MessageHandler,
    filters,
)

load_dotenv()

logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN: str = os.environ["BOT_TOKEN"]
WEBHOOK_BASE: str = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
PORT: int = int(os.environ.get("PORT", 8443))
WEBHOOK_PATH = "/webhook"
# Set WEBHOOK_SECRET in Render dashboard to prevent spoofed webhook requests.
WEBHOOK_SECRET: str = os.environ.get("WEBHOOK_SECRET", "")


# ── /start ────────────────────────────────────────────────────────────────────


async def _start(update: Update, context) -> None:
    await update.message.reply_text(
        "வணக்கம்! 👋 <b>GroceryBot</b> — உங்க AI assistant!\n\n"
        "🎤 <b>Voice note அனுப்புங்க:</b>\n"
        "   • Bill: <i>'2 kg sugar 80, 1 oil 160'</i> → PDF bill\n"
        "   • Expense: <i>'today spent 200 for chai'</i> → Google Sheets-ல் log\n\n"
        "🎬 <b>Movies:</b>\n"
        "   <code>/movie Vikram</code> — poster + trailer + cast + watchlist\n"
        "   <code>/watchlist add Master</code> — watchlist-ல் save\n\n"
        "💰 <b>Expenses:</b>\n"
        "   <code>/expense spent 500 petrol</code> — log expense\n"
        "   <code>/summary</code> — monthly PDF report\n\n"
        "🎵 <b>YouTube MP3:</b>\n"
        "   <code>/ytmp3 &lt;url&gt;</code> or paste a YouTube link\n"
        "   <code>/uploadcookies</code> — fix bot-detection errors\n\n"
        "📸 <b>Bill Photo:</b> Send a receipt photo → PDF\n\n"
        "📋 <b>Bill History:</b>\n"
        "   <code>/billhistory</code> — today's bills\n"
        "   <code>/billhistory yesterday</code> — yesterday's bills\n\n"
        "📝 <b>Summarize:</b> Reply to any text with <code>/summarize</code>\n\n"
        "🔍 <b>Inline:</b> Type <code>@YourBot Vikram</code> in any chat\n\n"
        "⚙️ <code>/setup</code> — check service status\n"
        "🌐 <code>/language</code> — change reply language",
        parse_mode="HTML",
    )


# ── /setup ────────────────────────────────────────────────────────────────────


def _env_status(key: str, label: str, *, extra_key: str | None = None) -> str:
    keys = [key] + ([extra_key] if extra_key else [])
    ok = all(os.environ.get(k) for k in keys)
    return ("✅" if ok else "❌") + f" <b>{label}</b>"


async def _setup(update: Update, context) -> None:
    from utils.supabase_client import get_storage_status

    storage = get_storage_status()
    storage_icon = "✅" if storage["healthy"] else "⚠️"

    lines = [
        "⚙️ <b>GroceryBot — Service Status</b>\n",
        _env_status("BOT_TOKEN",    "Telegram Bot Token"),
        _env_status("GROQ_API_KEY", "Groq (Voice transcription + LLM)"),
        _env_status("TMDB_API_KEY", "TMDB (Movie search)"),
        "",
        "<b>Optional services:</b>",
        f"{storage_icon} <b>Watchlist storage:</b> {storage['detail']}",
        _env_status("GOOGLE_API_KEY",                 "Google CSE (Streaming links)", extra_key="GOOGLE_CSE_ID"),
        _env_status("GOOGLE_SHEETS_CREDENTIALS_JSON", "Google Sheets (Expenses + Bill history)", extra_key="GOOGLE_SHEET_ID"),
        _env_status("YOUTUBE_API_KEY", "YouTube Data API (Full movie button in /movie)"),
        _env_status("WEBHOOK_SECRET", "Webhook Secret (Security)"),
        "",
        "❌ = not configured (feature degraded) | ✅ = configured",
        "",
        "<b>Quick setup tips:</b>",
        "• <b>Watchlist:</b> Set <code>SUPABASE_URL</code> + <code>SUPABASE_KEY</code> (service-role key).",
        "• <b>Streaming links:</b> Set <code>GOOGLE_API_KEY</code> + <code>GOOGLE_CSE_ID</code>.",
        "• <b>Expenses + Bill history:</b> Set <code>GOOGLE_SHEETS_CREDENTIALS_JSON</code> + <code>GOOGLE_SHEET_ID</code>.",
        "• <b>YouTube Full Movie:</b> Set <code>YOUTUBE_API_KEY</code> (Google Cloud → YouTube Data API v3).",
        "• <b>Service bill shop name:</b> Set <code>SERVICE_SHOP_NAME</code> (default: SRI NARPAVI BEAUTY PARLOUR).",
        "• <b>Security:</b> Set <code>WEBHOOK_SECRET</code> to a random 32-char hex token.",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ── /language ─────────────────────────────────────────────────────────────────


async def _language(update: Update, context) -> None:
    uid = update.effective_user.id
    from utils.lang_store import get_user_lang
    current = await get_user_lang(uid)
    label = "🇮🇳 Tanglish (Tamil)" if current == "ta" else "🇬🇧 English"

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🇮🇳 Tanglish (Tamil)", callback_data="lang:ta"),
        InlineKeyboardButton("🇬🇧 English",          callback_data="lang:en"),
    ]])
    await update.message.reply_text(
        f"🌐 <b>Language / மொழி</b>\n\n"
        f"Current: <b>{label}</b>\n\n"
        "தேர்வு பண்ணுங்க / Choose your language:",
        parse_mode="HTML",
        reply_markup=keyboard,
    )


async def _language_callback(update: Update, context) -> None:
    """Handles lang:ta / lang:en inline button callbacks."""
    query = update.callback_query
    await query.answer()

    lang = (query.data or "").split(":")[-1]
    if lang not in ("ta", "en"):
        return

    uid = update.effective_user.id
    from utils.lang_store import set_user_lang
    await set_user_lang(uid, lang)

    label = "🇮🇳 Tanglish (Tamil)" if lang == "ta" else "🇬🇧 English"
    logger.info("Language changed: user=%s lang=%s", uid, lang)

    confirm = (
        f"✅ மொழி மாற்றப்பட்டது: <b>{label}</b>\nஇனி Tanglish-ல் reply பண்றேன்!"
        if lang == "ta"
        else f"✅ Language changed to: <b>{label}</b>\nI'll reply in English from now on!"
    )
    await query.edit_message_text(confirm, parse_mode="HTML")


# ── handler registry ──────────────────────────────────────────────────────────


def _register_handlers(app: Application) -> None:
    from handlers.billhistory_handler import handle_billhistory_command
    from handlers.expense_handler import handle_expense_command, handle_summary_command
    from handlers.inline_handler import handle_inline_query
    from handlers.movie_handler import (
        handle_movie_command,
        handle_movie_message,
        handle_movie_watchlist_callback,
    )
    from handlers.photo_handler import handle_photo
    from handlers.summarize_handler import handle_summarize
    from handlers.voice_handler import handle_voice
    from handlers.watchlist_handler import handle_watchlist_callback, handle_watchlist_command
    from handlers.ytmp3_handler import (
        handle_uploadcookies_command,
        handle_yt_url_message,
        handle_ytmp3_command,
    )
    from utils.ytdl_audio import YT_URL_RE

    # ── commands ──────────────────────────────────────────────────────────────
    app.add_handler(CommandHandler("start",        _start))
    app.add_handler(CommandHandler("setup",        _setup))
    app.add_handler(CommandHandler("language",     _language))
    app.add_handler(CommandHandler("lang",         _language))
    app.add_handler(CommandHandler("movie",        handle_movie_command))
    app.add_handler(CommandHandler("watchlist",    handle_watchlist_command))
    app.add_handler(CommandHandler("expense",      handle_expense_command))
    app.add_handler(CommandHandler("summary",      handle_summary_command))
    app.add_handler(CommandHandler("ytmp3",         handle_ytmp3_command))
    app.add_handler(CommandHandler("uploadcookies", handle_uploadcookies_command))
    app.add_handler(CommandHandler("summarize",    handle_summarize))
    app.add_handler(CommandHandler("billhistory",  handle_billhistory_command))

    # ── media ─────────────────────────────────────────────────────────────────
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    # ── plain-text triggers ───────────────────────────────────────────────────
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.Regex(YT_URL_RE),
            handle_yt_url_message,
        )
    )
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.Regex(r"(?i)^movie\s+\S"),
            handle_movie_message,
        )
    )

    # ── inline query ──────────────────────────────────────────────────────────
    app.add_handler(InlineQueryHandler(handle_inline_query))

    # ── callback queries ──────────────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(handle_watchlist_callback,       pattern=r"^wl_rm:"))
    app.add_handler(CallbackQueryHandler(handle_movie_watchlist_callback, pattern=r"^wl_add:"))
    app.add_handler(CallbackQueryHandler(_language_callback,              pattern=r"^lang:"))


# ── webhook mode ──────────────────────────────────────────────────────────────


async def _run_webhook() -> None:
    ptb = Application.builder().token(BOT_TOKEN).updater(None).build()
    _register_handlers(ptb)

    await ptb.initialize()
    await ptb.start()

    webhook_url = f"{WEBHOOK_BASE}{WEBHOOK_PATH}"
    await ptb.bot.set_webhook(
        url=webhook_url,
        drop_pending_updates=True,
        secret_token=WEBHOOK_SECRET or None,
    )
    logger.info("Webhook → %s (secret_token=%s)", webhook_url, "set" if WEBHOOK_SECRET else "UNSET ⚠️")

    async def health(_req: web.Request) -> web.Response:
        return web.Response(text="OK")

    async def telegram_webhook(req: web.Request) -> web.Response:
        # [C1] Validate Telegram's secret token to reject spoofed requests.
        if WEBHOOK_SECRET:
            provided = req.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if provided != WEBHOOK_SECRET:
                logger.warning(
                    "Webhook: rejected request with invalid secret from %s", req.remote
                )
                return web.Response(status=403, text="Forbidden")
        try:
            payload = await req.json()
            update = Update.de_json(payload, ptb.bot)
            await ptb.process_update(update)
        except Exception as exc:
            logger.error("Webhook processing error: %s", exc, exc_info=True)
        return web.Response(text="OK")

    web_app = web.Application()
    web_app.router.add_get("/",          health)
    web_app.router.add_post(WEBHOOK_PATH, telegram_webhook)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info("aiohttp listening on 0.0.0.0:%d", PORT)

    stop = asyncio.Event()
    try:
        await stop.wait()
    finally:
        await runner.cleanup()
        await ptb.stop()
        await ptb.shutdown()


# ── polling mode ──────────────────────────────────────────────────────────────


def _run_polling() -> None:
    ptb = Application.builder().token(BOT_TOKEN).build()
    _register_handlers(ptb)
    logger.info("Polling mode (local dev)…")
    ptb.run_polling(drop_pending_updates=True)


# ── entry-point ───────────────────────────────────────────────────────────────


if __name__ == "__main__":
    if WEBHOOK_BASE:
        asyncio.run(_run_webhook())
    else:
        _run_polling()
