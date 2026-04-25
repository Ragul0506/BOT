"""Text summarizer handler.

Usage:
  Reply to any message with /summarize
  OR send /summarize followed by text directly.
"""
from __future__ import annotations

import html as hl
import logging

from telegram import Update
from telegram.ext import ContextTypes

from utils.groq_llm import summarize_text

logger = logging.getLogger(__name__)


async def handle_summarize(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message

    # Determine input text
    text_to_summarize = ""

    # Priority 1: replied-to message
    if msg.reply_to_message:
        text_to_summarize = msg.reply_to_message.text or msg.reply_to_message.caption or ""

    # Priority 2: inline args after /summarize
    if not text_to_summarize and context.args:
        text_to_summarize = " ".join(context.args).strip()

    if not text_to_summarize:
        await msg.reply_text(
            "📝 <b>Summarizer</b>\n\n"
            "Usage (two ways):\n"
            "1️⃣ Reply to any long message with <code>/summarize</code>\n"
            "2️⃣ <code>/summarize &lt;your long text here&gt;</code>",
            parse_mode="HTML",
        )
        return

    if len(text_to_summarize) < 50:
        await msg.reply_text(
            "⚠️ Text too short to summarize (min 50 chars).\n"
            "Send a longer paragraph or article."
        )
        return

    status = await msg.reply_text("🤔 Summarize பண்றேன்…")
    try:
        summary = await summarize_text(text_to_summarize)
        await status.edit_text(
            f"📋 <b>Summary:</b>\n\n{hl.escape(summary)}",
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.error("Summarize error: %s", exc)
        await status.edit_text(
            f"❌ <b>Error:</b> {hl.escape(str(exc))}", parse_mode="HTML"
        )
