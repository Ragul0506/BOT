"""Song downloader — /song <query> → YouTube search → inline picker → MP3.

Flow:
  1. /song <query> → search YouTube (API or yt-dlp fallback), show inline keyboard.
  2. User taps a result → song_dl:<videoId> callback → download via yt-dlp → send MP3.

Reuses the same yt-dlp infrastructure (cookies, rate limiter) as /ytmp3.
"""
from __future__ import annotations

import asyncio
import html as hl
import logging
import os
import shutil

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from utils.lang_store import get_user_lang
from utils.msgs import m
from utils.security import ytdl_rate_limiter
from utils.ytdl_audio import (
    MAX_BYTES,
    AudioResult,
    YTDLCategoryError,
    download_audio,
    get_category_msg,
)

logger = logging.getLogger(__name__)

_MAX_RESULTS = 5


def _fmt_dur(secs: int) -> str:
    """Format seconds as M:SS or H:MM:SS."""
    if not secs:
        return ""
    h, rem = divmod(int(secs), 3600)
    m_part, s = divmod(rem, 60)
    return f"{h}:{m_part:02d}:{s:02d}" if h else f"{m_part}:{s:02d}"


async def _search_async(query: str) -> list[dict]:
    """Run song search in thread executor (yt-dlp / googleapiclient are sync)."""
    from utils.youtube_search import search_songs
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, search_songs, query, _MAX_RESULTS)


# ── /song command ─────────────────────────────────────────────────────────────


async def handle_song_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    uid = update.effective_user.id
    lang = await get_user_lang(uid)

    query = " ".join(context.args or []).strip()
    if not query:
        await msg.reply_text(m("song_usage", lang), parse_mode="HTML")
        return

    if not ytdl_rate_limiter.is_allowed(uid):
        await msg.reply_text(m("ytmp3_rate_limit", lang))
        return

    status = await msg.reply_text(
        m("song_searching", lang, query=hl.escape(query[:60])), parse_mode="HTML"
    )

    try:
        results = await _search_async(query + " song")
    except Exception as exc:
        logger.error("Song search error for user %s: %s", uid, exc, exc_info=True)
        await status.edit_text(m("song_search_fail", lang))
        return

    if not results:
        await status.edit_text(
            m("song_not_found", lang, query=hl.escape(query[:60])), parse_mode="HTML"
        )
        return

    keyboard = []
    for r in results:
        title_short = r["title"][:42]
        dur = _fmt_dur(r["duration"])
        label = f"🎵 {title_short}" + (f"  [{dur}]" if dur else "")
        keyboard.append([InlineKeyboardButton(
            label, callback_data=f"song_dl:{r['video_id']}"
        )])

    await status.edit_text(
        m("song_results", lang, query=hl.escape(query[:60])),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ── song_dl:<videoId> callback ────────────────────────────────────────────────


async def handle_song_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("⬇️ Downloading…")

    uid = update.effective_user.id
    lang = await get_user_lang(uid)

    video_id = (query.data or "").split(":", 1)[-1].strip()
    if not video_id or len(video_id) > 20:
        await query.answer("❌ Invalid video ID.", show_alert=True)
        return

    url = f"https://www.youtube.com/watch?v={video_id}"
    status_msg = await query.message.reply_text(
        m("song_downloading", lang), parse_mode="HTML"
    )

    result: AudioResult | None = None
    try:
        result = await download_audio(url, user_id=uid)

        await status_msg.edit_text(
            m("ytmp3_sending", lang, title=hl.escape(result.title[:50])),
            parse_mode="HTML",
        )
        try:
            await status_msg.delete()
        except Exception:
            pass

        with open(result.path, "rb") as f:
            await query.message.reply_audio(
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

    except YTDLCategoryError as exc:
        err_text = get_category_msg(exc.category, lang, limit=MAX_BYTES // 1_048_576)
        try:
            await status_msg.edit_text(err_text, parse_mode="HTML")
        except Exception:
            pass

    except ValueError as exc:
        try:
            await status_msg.edit_text(f"❌ {hl.escape(str(exc))}", parse_mode="HTML")
        except Exception:
            pass

    except Exception as exc:
        logger.error("Song download error for user %s: %s", uid, exc, exc_info=True)
        try:
            await status_msg.edit_text(m("generic_error", lang))
        except Exception:
            pass

    finally:
        if result is not None:
            try:
                shutil.rmtree(os.path.dirname(result.path), ignore_errors=True)
            except Exception:
                pass
