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
from utils.lang_store import get_user_lang
from utils.msgs import m

logger = logging.getLogger(__name__)


async def handle_summarize(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    uid = update.effective_user.id
    lang = await get_user_lang(uid)

    # Determine input text
    text_to_summarize = ""

    # Priority 1: replied-to message
    if msg.reply_to_message:
        text_to_summarize = msg.reply_to_message.text or msg.reply_to_message.caption or ""

    # Priority 2: inline args after /summarize
    if not text_to_summarize and context.args:
        text_to_summarize = " ".join(context.args).strip()

    if not text_to_summarize:
        if lang == "en":
            help_text = (
                "📝 <b>Summarizer</b>\n\n"
                "Two ways to use:\n"
                "1️⃣ Reply to any long message with <code>/summarize</code>\n"
                "2️⃣ <code>/summarize &lt;your long text here&gt;</code>"
            )
        else:
            help_text = (
                "📝 <b>Summarizer</b>\n\n"
                "இரண்டு ways-ல் use பண்ணலாம்:\n"
                "1️⃣ Long message-ஐ reply பண்ணி <code>/summarize</code>\n"
                "2️⃣ <code>/summarize &lt;உங்க text இங்க&gt;</code>"
            )
        await msg.reply_text(help_text, parse_mode="HTML")
        return

    if len(text_to_summarize) < 50:
        await msg.reply_text(m("summarize_too_short", lang))
        return

    status = await msg.reply_text(m("summarize_start", lang))
    try:
        summary = await summarize_text(text_to_summarize)
        await status.edit_text(
            f"📋 <b>Summary:</b>\n\n{hl.escape(summary)}",
            parse_mode="HTML",
        )
    except Exception as exc:
        # [H2] Log internally — do NOT expose raw exception to users.
        logger.error("Summarize error for user %s: %s", uid, exc, exc_info=True)
        await status.edit_text(m("summarize_fail", lang))
