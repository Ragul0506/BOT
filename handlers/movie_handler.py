"""Movie search handler — TMDB (with trailer, cast, genres) + Google CSE
+ watchlist add button + inline keyboard.

Multi-user isolation: watchlist add uses the calling user's ID.
"""
from __future__ import annotations

import asyncio
import html as hl
import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from utils.google_search import get_google_search_url, search_streaming_links
from utils.lang_store import get_user_lang
from utils.msgs import m
from utils.security import rate_limiter, safe_callback_data
from utils.tmdb import search_movie
from utils.youtube_search import search_full_movie, youtube_api_configured

logger = logging.getLogger(__name__)

_CAPTION_MAX = 1020  # Telegram photo caption byte limit


def _build_caption(movie: dict, links: list[dict], lang: str) -> str:
    title = hl.escape(movie["title"])
    year = hl.escape(movie.get("year") or "")
    overview = hl.escape(movie["overview"][:380])
    if len(movie["overview"]) > 380:
        overview += "…"

    rating = movie.get("rating", 0)
    rating_stars = round(rating / 2)
    stars = "⭐" * rating_stars + "☆" * (5 - rating_stars)

    lines = [
        f"🎬 <b>{title}</b> ({year})",
        f"{stars}  <b>{rating}/10</b>",
    ]

    if movie.get("genres"):
        lines.append("🎭 " + " · ".join(hl.escape(g) for g in movie["genres"]))

    if movie.get("cast"):
        lines.append("🎭 Cast: " + ", ".join(hl.escape(c) for c in movie["cast"]))

    lines += ["", overview]

    if links:
        header = "🔗 <b>Legal Streams:</b>" if lang == "en" else "🔗 <b>Legal Streams:</b>"
        lines += ["", header]
        for lnk in links[:3]:
            try:
                domain = lnk["link"].split("/")[2]
            except IndexError:
                domain = lnk["link"]
            lines.append(f'• <a href="{hl.escape(lnk["link"])}">{hl.escape(domain)}</a>')

    caption = "\n".join(lines)
    if len(caption.encode()) > _CAPTION_MAX:
        caption = caption.encode()[:_CAPTION_MAX].decode("utf-8", errors="ignore") + "…"
    return caption


def _build_keyboard(movie: dict, yt_full_url: str | None = None) -> InlineKeyboardMarkup:
    """Build inline keyboard with TMDB, Streams, Trailer, Watchlist, and optional YT Full Movie buttons."""
    row1: list[InlineKeyboardButton] = []

    title = movie.get("title", "")
    if title:
        try:
            row1.append(InlineKeyboardButton("▶️ Official Streams", url=get_google_search_url(title)))
        except Exception as exc:
            logger.warning("Streams URL build failed: %s", exc)

    tmdb_url = movie.get("tmdb_url")
    if tmdb_url:
        row1.append(InlineKeyboardButton("🎬 TMDB Page", url=tmdb_url))

    row2: list[InlineKeyboardButton] = []
    trailer_url = movie.get("trailer_url")
    if trailer_url:
        row2.append(InlineKeyboardButton("🎞️ Trailer", url=trailer_url))

    if yt_full_url:
        row2.append(InlineKeyboardButton("▶️ YouTube Full Movie", url=yt_full_url))

    movie_id = movie.get("id")
    if movie_id and title:
        row2.append(
            InlineKeyboardButton(
                "➕ Watchlist",
                callback_data=safe_callback_data("wl_add", movie_id, title),
            )
        )

    rows = [r for r in (row1, row2) if r]
    return InlineKeyboardMarkup(rows or [[]])


async def _send_movie(update: Update, movie_name: str) -> None:
    msg = update.message
    uid = update.effective_user.id
    lang = await get_user_lang(uid)

    # [C4] Rate limit movie lookups.
    if not rate_limiter.is_allowed(uid):
        await msg.reply_text(m("rate_limit", lang))
        return

    status = await msg.reply_text(
        m("movie_searching", lang, name=hl.escape(movie_name)),
        parse_mode="HTML",
    )

    try:
        movie = await search_movie(movie_name)

        if not movie:
            await status.edit_text(
                m("movie_not_found", lang, name=hl.escape(movie_name)),
                parse_mode="HTML",
            )
            return

        # Fetch streaming links and YouTube full movie URL concurrently.
        yt_full_url: str | None = None
        if youtube_api_configured():
            loop = asyncio.get_event_loop()
            links, yt_full_url = await asyncio.gather(
                search_streaming_links(movie["title"]),
                loop.run_in_executor(
                    None, search_full_movie, movie["title"], str(movie.get("year") or "")
                ),
            )
        else:
            links = await search_streaming_links(movie["title"])

        caption = _build_caption(movie, links, lang)

        try:
            keyboard = _build_keyboard(movie, yt_full_url=yt_full_url)
        except Exception as exc:
            logger.error("Keyboard build error for '%s': %s", movie_name, exc)
            keyboard = InlineKeyboardMarkup([[]])

        try:
            await status.delete()
        except Exception:
            pass

        poster_url = movie.get("poster_url")
        if poster_url:
            try:
                await msg.reply_photo(
                    photo=poster_url,
                    caption=caption,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                )
                return
            except Exception as exc:
                # Poster URL invalid or Telegram rejected it — fall through to text.
                logger.warning("reply_photo failed for '%s': %s — using text", movie_name, exc)

        await msg.reply_text(caption, reply_markup=keyboard, parse_mode="HTML")

    except Exception as exc:
        logger.error("Movie handler error for '%s' (user %s): %s", movie_name, uid, exc, exc_info=True)
        try:
            # [H2] Never expose raw exception to users.
            await status.edit_text(m("movie_fail", lang))
        except Exception:
            pass


# ── quick-add watchlist from movie card (wl_add callback) ────────────────────


async def handle_movie_watchlist_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handles wl_add:{movie_id}:{title} callbacks from movie cards."""
    from utils.supabase_client import add_to_watchlist
    from utils.tmdb import search_movies_multi

    query = update.callback_query
    await query.answer()

    match = re.match(r"^wl_add:(\d+):(.+)$", query.data or "")
    if not match:
        return

    movie_id = int(match.group(1))
    title = match.group(2)
    uid = update.effective_user.id

    try:
        # [M1] Use TMDB authoritative title rather than callback_data (could be truncated).
        results = await search_movies_multi(title, n=1)
        if results:
            authoritative_title = results[0].get("title", title)
            poster_url = results[0].get("poster_url")
        else:
            authoritative_title = title
            poster_url = None

        await add_to_watchlist(uid, movie_id, authoritative_title, poster_url)
        await query.answer(
            f"✅ '{authoritative_title[:30]}' watchlist-ல் add ஆச்சு!", show_alert=False
        )
    except Exception as exc:
        logger.error("wl_add callback error for user %s: %s", uid, exc)
        # [H2] Do not expose exception details in callback answer.
        await query.answer("❌ Watchlist-ல் add பண்ண முடியல! மீண்டும் try பண்ணுங்க.", show_alert=True)


# ── PTB handler entry-points ──────────────────────────────────────────────────


async def handle_movie_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/movie <name>"""
    if not context.args:
        uid = update.effective_user.id
        lang = await get_user_lang(uid)
        if lang == "en":
            usage = (
                "Usage: <code>/movie &lt;movie name&gt;</code>\n"
                "Example: <code>/movie Vikram</code>"
            )
        else:
            usage = (
                "Usage: <code>/movie &lt;movie name&gt;</code>\n"
                "Example: <code>/movie Vikram</code>"
            )
        await update.message.reply_text(usage, parse_mode="HTML")
        return
    await _send_movie(update, " ".join(context.args))


async def handle_movie_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle plain-text 'movie <name>' messages."""
    text = (update.message.text or "").strip()
    match = re.match(r"(?i)^movie\s+(.+)", text)
    if match:
        await _send_movie(update, match.group(1).strip())
