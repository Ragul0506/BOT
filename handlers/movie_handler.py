"""Movie search handler — TMDB (with trailer, cast, genres) + Google CSE
+ watchlist add button + inline keyboard."""
from __future__ import annotations

import html as hl
import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from utils.google_search import get_google_search_url, search_streaming_links
from utils.tmdb import search_movie

logger = logging.getLogger(__name__)


def _build_caption(movie: dict, links: list[dict]) -> str:
    title = hl.escape(movie["title"])
    year = hl.escape(movie["year"])
    overview = hl.escape(movie["overview"][:380])
    if len(movie["overview"]) > 380:
        overview += "…"

    rating_stars = round(movie["rating"] / 2)
    stars = "⭐" * rating_stars + "☆" * (5 - rating_stars)

    lines = [
        f"🎬 <b>{title}</b> ({year})",
        f"{stars}  <b>{movie['rating']}/10</b>",
    ]

    if movie.get("genres"):
        lines.append("🎭 " + " · ".join(hl.escape(g) for g in movie["genres"]))

    if movie.get("cast"):
        lines.append("🎭 Cast: " + ", ".join(hl.escape(c) for c in movie["cast"]))

    lines += ["", overview]

    if links:
        lines += ["", "🔗 <b>Legal Streams:</b>"]
        for lnk in links[:3]:
            try:
                domain = lnk["link"].split("/")[2]
            except IndexError:
                domain = lnk["link"]
            lines.append(f'• <a href="{hl.escape(lnk["link"])}">{hl.escape(domain)}</a>')

    return "\n".join(lines)


def _build_keyboard(movie: dict) -> InlineKeyboardMarkup:
    row1 = [
        InlineKeyboardButton(
            "▶️ Official Streams",
            url=get_google_search_url(movie["title"]),
        ),
        InlineKeyboardButton("🎬 TMDB", url=movie["tmdb_url"]),
    ]
    row2 = []
    if movie.get("trailer_url"):
        row2.append(InlineKeyboardButton("🎞️ Trailer", url=movie["trailer_url"]))
    row2.append(
        InlineKeyboardButton(
            "➕ Watchlist",
            callback_data=f"wl_add:{movie['id']}:{hl.escape(movie['title'])[:30]}",
        )
    )
    rows = [row1]
    if row2:
        rows.append(row2)
    return InlineKeyboardMarkup(rows)


async def _send_movie(update: Update, movie_name: str) -> None:
    msg = update.message
    status = await msg.reply_text(
        f"🔍 '<b>{hl.escape(movie_name)}</b>' தேடுகிறேன்…",
        parse_mode="HTML",
    )

    try:
        movie = await search_movie(movie_name)

        if not movie:
            await status.edit_text(
                f"❌ '<b>{hl.escape(movie_name)}</b>' கண்டுபிடிக்கவில்லை.\n"
                "சரியான ஆங்கிலப் பெயரை try பண்ணுங்க.",
                parse_mode="HTML",
            )
            return

        links = await search_streaming_links(movie["title"])
        caption = _build_caption(movie, links)
        keyboard = _build_keyboard(movie)

        try:
            await status.delete()
        except Exception:
            pass

        if movie.get("poster_url"):
            await msg.reply_photo(
                photo=movie["poster_url"],
                caption=caption,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        else:
            await msg.reply_text(caption, reply_markup=keyboard, parse_mode="HTML")

    except Exception as exc:
        logger.error("Movie handler error: %s", exc, exc_info=True)
        try:
            await status.edit_text(
                f"❌ <b>Error:</b> {hl.escape(str(exc))}", parse_mode="HTML"
            )
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
        # Fetch a light result to get poster_url
        results = await search_movies_multi(title, n=1)
        poster_url = results[0].get("poster_url") if results else None

        await add_to_watchlist(uid, movie_id, title, poster_url)
        await query.answer(f"✅ '{title[:30]}' watchlist-ல் add ஆச்சு!", show_alert=False)
    except Exception as exc:
        logger.error("wl_add callback error: %s", exc)
        await query.answer(f"❌ Error: {str(exc)[:60]}", show_alert=True)


# ── PTB handler entry-points ──────────────────────────────────────────────────


async def handle_movie_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/movie <name>"""
    if not context.args:
        await update.message.reply_text(
            "Usage: <code>/movie &lt;movie name&gt;</code>\n"
            "Example: <code>/movie Vikram</code>",
            parse_mode="HTML",
        )
        return
    await _send_movie(update, " ".join(context.args))


async def handle_movie_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle plain-text 'movie <name>' messages."""
    text = (update.message.text or "").strip()
    m = re.match(r"(?i)^movie\s+(.+)", text)
    if m:
        await _send_movie(update, m.group(1).strip())
