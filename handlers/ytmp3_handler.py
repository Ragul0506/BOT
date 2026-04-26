"""YouTube-to-MP3 handler.

Triggers:
  /ytmp3 <url>           — explicit command
  Any message containing a YouTube URL — auto-detect
  /uploadcookies         — upload a Netscape-format cookies .txt file
"""
from __future__ import annotations

import html as hl
import logging
import os
import shutil

from telegram import Update
from telegram.ext import ContextTypes

from utils.lang_store import get_user_lang
from utils.msgs import m
from utils.security import ytdl_rate_limiter
from utils.ytdl_audio import (
    AudioResult,
    YTDLCategoryError,
    download_audio,
    extract_yt_url,
    get_category_msg,
)

logger = logging.getLogger(__name__)


async def _send_audio(update: Update, url: str) -> None:
    msg = update.effective_message
    uid = update.effective_user.id
    lang = await get_user_lang(uid)

    # [C4] Enforce stricter rate limit for expensive yt-dlp downloads.
    if not ytdl_rate_limiter.is_allowed(uid):
        await msg.reply_text(m("ytmp3_rate_limit", lang))
        return

    status = await msg.reply_text(
        m("ytmp3_start", lang, url=hl.escape(url[:60])),
        parse_mode="HTML",
    )

    result: AudioResult | None = None
    try:
        await status.edit_text(m("ytmp3_converting", lang))
        result = await download_audio(url, user_id=uid)

        await status.edit_text(
            m("ytmp3_sending", lang, title=hl.escape(result.title[:50])),
            parse_mode="HTML",
        )
        try:
            await status.delete()
        except Exception:
            pass

        with open(result.path, "rb") as f:
            await msg.reply_audio(
                audio=f,
                title=result.title[:64],
                performer=result.artist[:64],
                duration=result.duration_secs,
                filename=f"{result.title[:50]}.{result.fmt}",
                caption=(
                    f"🎵 <b>{hl.escape(result.title[:60])}</b>\n"
                    f"👤 {hl.escape(result.artist[:40])}"
                    + (f"\n<i>Format: {result.fmt}</i>" if result.fmt != "mp3" else "")
                ),
                parse_mode="HTML",
            )

    except ValueError as exc:
        # File too large — message is already user-safe from ytdl_audio.
        await status.edit_text(f"❌ {hl.escape(str(exc))}", parse_mode="HTML")

    except YTDLCategoryError as exc:
        # Specific, categorized error (age-restricted, private, region-locked, …)
        logger.warning("YT-MP3 category error [%s] for %s (user %s)", exc.category, url, uid)
        await status.edit_text(
            get_category_msg(exc.category, lang, limit=45),
            parse_mode="HTML",
        )

    except Exception as exc:
        logger.error("YT-MP3 unexpected error for %s (user %s): %s", url, uid, exc, exc_info=True)
        # [H2] Do not expose yt-dlp internal error (may contain paths/tokens).
        await status.edit_text(
            get_category_msg("unavailable", lang),
            parse_mode="HTML",
        )

    finally:
        if result and os.path.exists(result.path):
            try:
                out_dir = os.path.dirname(result.path)
                shutil.rmtree(out_dir, ignore_errors=True)
            except OSError:
                pass


async def handle_ytmp3_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/ytmp3 <url>"""
    uid = update.effective_user.id
    lang = await get_user_lang(uid)
    url_arg = " ".join(context.args or "").strip()
    url = extract_yt_url(url_arg) if url_arg else None
    if not url:
        if lang == "en":
            usage = (
                "Usage: <code>/ytmp3 &lt;YouTube URL&gt;</code>\n"
                "Example: <code>/ytmp3 https://youtu.be/dQw4w9WgXcQ</code>\n\n"
                "Or simply paste a YouTube link in the chat!"
            )
        else:
            usage = (
                "Usage: <code>/ytmp3 &lt;YouTube URL&gt;</code>\n"
                "Example: <code>/ytmp3 https://youtu.be/dQw4w9WgXcQ</code>\n\n"
                "அல்லது YouTube link-ஐ chat-ல் paste பண்ணுங்க!"
            )
        await update.message.reply_text(usage, parse_mode="HTML")
        return
    await _send_audio(update, url)


async def handle_yt_url_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Auto-triggered when a message contains a YouTube URL."""
    text = update.message.text or ""
    url = extract_yt_url(text)
    if url:
        await _send_audio(update, url)


async def handle_uploadcookies_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/uploadcookies — save a Netscape-format .txt cookies file for yt-dlp.

    Usage:
      Send the .txt file as a document with caption /uploadcookies
      — or — send /uploadcookies as text to get instructions.
    """
    msg = update.effective_message
    uid = update.effective_user.id
    lang = await get_user_lang(uid)

    doc = msg.document if msg else None

    if doc is None:
        # No document attached — show instructions.
        if lang == "en":
            text = (
                "📎 <b>How to upload YouTube cookies:</b>\n\n"
                "1. Install the <i>Get cookies.txt LOCALLY</i> browser extension\n"
                "2. Log in to <b>youtube.com</b>\n"
                "3. Click the extension → Export → save as <code>.txt</code>\n"
                "4. Send that <code>.txt</code> file here with caption "
                "<code>/uploadcookies</code>\n\n"
                "This lets the bot bypass YouTube's bot-detection for you."
            )
        else:
            text = (
                "📎 <b>YouTube cookies எப்படி upload பண்றது:</b>\n\n"
                "1. <i>Get cookies.txt LOCALLY</i> browser extension install பண்ணுங்க\n"
                "2. <b>youtube.com</b>-ல் login பண்ணுங்க\n"
                "3. Extension click பண்ணி → Export → <code>.txt</code>-ஆ save பண்ணுங்க\n"
                "4. அந்த <code>.txt</code> file-ஐ caption "
                "<code>/uploadcookies</code>-ஆ இங்க அனுப்புங்க\n\n"
                "இதனால் YouTube bot-detection bypass பண்ண முடியும்."
            )
        await msg.reply_text(text, parse_mode="HTML")
        return

    # Validate file type by name and MIME type.
    fname = doc.file_name or ""
    mime = doc.mime_type or ""
    if not fname.lower().endswith(".txt") and "text" not in mime:
        err = (
            "❌ Please send a <code>.txt</code> cookies file (Netscape format)."
            if lang == "en"
            else "❌ <code>.txt</code> format cookies file மட்டுமே அனுப்புங்க."
        )
        await msg.reply_text(err, parse_mode="HTML")
        return

    # Download and persist the file.
    try:
        tg_file = await doc.get_file()
        cookie_path = f"/tmp/cookies_{uid}.txt"
        await tg_file.download_to_drive(cookie_path)
        logger.info("Cookies saved for user %s → %s (%d bytes)", uid, cookie_path, doc.file_size or 0)
        reply = (
            "✅ Cookies saved! YouTube downloads will now use your account cookies."
            if lang == "en"
            else "✅ Cookies சேமிக்கப்பட்டது! இனி YouTube downloads உங்க cookies use பண்ணும்."
        )
        await msg.reply_text(reply)
    except Exception as exc:
        logger.error("Failed to save cookies for user %s: %s", uid, exc, exc_info=True)
        err = (
            "❌ Failed to save cookies file. Please try again."
            if lang == "en"
            else "❌ Cookies save பண்ண முடியலை. மீண்டும் try பண்ணுங்க."
        )
        await msg.reply_text(err)
