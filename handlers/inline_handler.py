"""Inline query handler — type @YourBot movie name in any chat.

Returns up to 5 TMDB movie results as InlineQueryResultArticle items.
Each result sends a full movie card when tapped.

Enable via BotFather:
  /setinline → @YourBot → set placeholder text e.g. "Search movies…"
"""
from __future__ import annotations

import html as hl
import logging
import uuid

from telegram import (
    InlineQueryResultArticle,
    InputTextMessageContent,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Update,
)
from telegram.ext import ContextTypes

from utils.google_search import get_google_search_url
from utils.tmdb import search_movies_multi

logger = logging.getLogger(__name__)


def _movie_message(movie: dict) -> str:
    title = hl.escape(movie["title"])
    year = hl.escape(movie["year"])
    rating = movie["rating"]
    overview = hl.escape(movie["overview"][:350])
    if len(movie["overview"]) > 350:
        overview += "…"

    stars = "⭐" * round(rating / 2)
    lines = [
        f"🎬 <b>{title}</b> ({year})",
        f"{stars} <b>{rating}/10</b>",
        "",
        overview,
    ]
    return "\n".join(lines)


def _movie_keyboard(movie: dict) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            "▶️ Official Streams",
            url=get_google_search_url(movie["title"]),
        ),
        InlineKeyboardButton("🎬 TMDB", url=movie["tmdb_url"]),
    ]
    return InlineKeyboardMarkup([buttons])


async def handle_inline_query(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query_text = (update.inline_query.query or "").strip()

    if not query_text or len(query_text) < 2:
        await update.inline_query.answer([], cache_time=0)
        return

    try:
        movies = await search_movies_multi(query_text, n=5)
    except Exception as exc:
        logger.error("Inline TMDB error: %s", exc)
        await update.inline_query.answer([], cache_time=0)
        return

    results = []
    for movie in movies:
        msg_text = _movie_message(movie)
        keyboard = _movie_keyboard(movie)

        label = f"🎬 {movie['title']} ({movie['year']})"
        desc = f"⭐{movie['rating']}/10  {movie['overview'][:90]}…"

        article = InlineQueryResultArticle(
            id=str(uuid.uuid4()),
            title=label,
            description=desc,
            thumbnail_url=movie.get("thumb_url"),
            input_message_content=InputTextMessageContent(
                message_text=msg_text,
                parse_mode="HTML",
            ),
            reply_markup=keyboard,
        )
        results.append(article)

    await update.inline_query.answer(results, cache_time=300)
    logger.info("Inline: returned %d results for '%s'", len(results), query_text)
