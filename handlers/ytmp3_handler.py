"""YouTube-to-MP3 handler.

Triggers:
  /ytmp3 <url>           — explicit command
  Any message containing a YouTube URL — auto-detect
"""
from __future__ import annotations

import html as hl
import logging
import os

from telegram import Update
from telegram.ext import ContextTypes

from utils.security import ytdl_rate_limiter
from utils.ytdl_audio import AudioResult, download_audio, extract_yt_url

logger = logging.getLogger(__name__)


async def _send_audio(update: Update, url: str) -> None:
    msg = update.effective_message
    uid = update.effective_user.id

    # [C4] Enforce stricter rate limit for expensive yt-dlp downloads.
    if not ytdl_rate_limiter.is_allowed(uid):
        await msg.reply_text(
            "⏳ YouTube download limit! 5 நிமிடத்தில் 3 மட்டுமே download பண்ணலாம். "
            "கொஞ்சம் நேரம் கழிச்சு try பண்ணுங்க."
        )
        return

    status = await msg.reply_text(
        f"⬇️ Audio download பண்றேன்…\n<code>{hl.escape(url[:60])}</code>",
        parse_mode="HTML",
    )

    result: AudioResult | None = None
    try:
        await status.edit_text("🎵 Downloading & converting to MP3…")
        result = await download_audio(url)

        await status.edit_text(
            f"📤 Sending <b>{hl.escape(result.title[:50])}</b>…",
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
                filename=f"{result.title[:50]}.mp3",
                caption=(
                    f"🎵 <b>{hl.escape(result.title[:60])}</b>\n"
                    f"👤 {hl.escape(result.artist[:40])}"
                ),
                parse_mode="HTML",
            )

    except ValueError as exc:
        # File too large
        await status.edit_text(f"❌ {hl.escape(str(exc))}", parse_mode="HTML")

    except Exception as exc:
        logger.error("YT-MP3 error for %s: %s", url, exc, exc_info=True)
        # [H2] Do not expose yt-dlp internal error (may contain paths/tokens).
        await status.edit_text(
            "❌ இந்த வீடியோவை பதிவிறக்க முடியாது 😕\n"
            "Age-restricted, private அல்லது unavailable video-ஆ check பண்ணுங்க.",
        )

    finally:
        if result and os.path.exists(result.path):
            try:
                os.unlink(result.path)
                # Also remove the temp dir created by ytdl_audio
                os.rmdir(os.path.dirname(result.path))
            except OSError:
                pass


async def handle_ytmp3_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/ytmp3 <url>"""
    url_arg = " ".join(context.args or "").strip()
    url = extract_yt_url(url_arg) if url_arg else None
    if not url:
        await update.message.reply_text(
            "Usage: <code>/ytmp3 &lt;YouTube URL&gt;</code>\n"
            "Example: <code>/ytmp3 https://youtu.be/dQw4w9WgXcQ</code>\n\n"
            "Or simply paste a YouTube link in the chat!",
            parse_mode="HTML",
        )
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
