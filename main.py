"""
Telegram bot entry-point (extended edition).

Production : webhook mode — Render.com sets RENDER_EXTERNAL_URL automatically.
Local dev  : polling mode — no RENDER_EXTERNAL_URL set.
"""
from __future__ import annotations

import asyncio
import logging
import os

from aiohttp import web
from dotenv import load_dotenv
from telegram import Update
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
# Telegram will send X-Telegram-Bot-Api-Secret-Token header with every update.
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
        "   <code>/ytmp3 &lt;url&gt;</code> or paste a YouTube link\n\n"
        "📸 <b>Bill Photo:</b> Send a receipt photo → PDF\n\n"
        "📝 <b>Summarize:</b> Reply to any text with <code>/summarize</code>\n\n"
        "🔍 <b>Inline:</b> Type <code>@YourBot Vikram</code> in any chat",
        parse_mode="HTML",
    )


# ── handler registry ──────────────────────────────────────────────────────────


def _register_handlers(app: Application) -> None:
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
    from handlers.watchlist_handler import (
        handle_watchlist_callback,
        handle_watchlist_command,
    )
    from handlers.ytmp3_handler import handle_yt_url_message, handle_ytmp3_command
    from utils.ytdl_audio import YT_URL_RE

    # ── commands ──────────────────────────────────────────────────────────────
    app.add_handler(CommandHandler("start",     _start))
    app.add_handler(CommandHandler("movie",     handle_movie_command))
    app.add_handler(CommandHandler("watchlist", handle_watchlist_command))
    app.add_handler(CommandHandler("expense",   handle_expense_command))
    app.add_handler(CommandHandler("summary",   handle_summary_command))
    app.add_handler(CommandHandler("ytmp3",     handle_ytmp3_command))
    app.add_handler(CommandHandler("summarize", handle_summarize))

    # ── media ─────────────────────────────────────────────────────────────────
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    # ── plain-text triggers ───────────────────────────────────────────────────
    # YouTube URL detection (must come before general text handler)
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.Regex(YT_URL_RE),
            handle_yt_url_message,
        )
    )
    # "movie <name>" without slash
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.Regex(r"(?i)^movie\s+\S"),
            handle_movie_message,
        )
    )

    # ── inline query ──────────────────────────────────────────────────────────
    app.add_handler(InlineQueryHandler(handle_inline_query))

    # ── callback queries ──────────────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(handle_watchlist_callback,        pattern=r"^wl_rm:"))
    app.add_handler(CallbackQueryHandler(handle_movie_watchlist_callback,  pattern=r"^wl_add:"))


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
    logger.info("Webhook → %s (secret_token=%s)", webhook_url, "set" if WEBHOOK_SECRET else "UNSET")

    async def health(_req: web.Request) -> web.Response:
        return web.Response(text="OK")

    async def telegram_webhook(req: web.Request) -> web.Response:
        # [C1] Validate Telegram's secret token to reject spoofed requests.
        if WEBHOOK_SECRET:
            provided = req.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if provided != WEBHOOK_SECRET:
                logger.warning(
                    "Webhook: rejected request with invalid secret token from %s",
                    req.remote,
                )
                return web.Response(status=403, text="Forbidden")
        try:
            payload = await req.json()
            update = Update.de_json(payload, ptb.bot)
            await ptb.process_update(update)
        except Exception as exc:
            logger.error("Webhook error: %s", exc, exc_info=True)
        return web.Response(text="OK")

    web_app = web.Application()
    web_app.router.add_get("/", health)
    web_app.router.add_post(WEBHOOK_PATH, telegram_webhook)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info("aiohttp on 0.0.0.0:%d", PORT)

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
