"""Watchlist handler — add, list, remove movies.

Commands:
  /watchlist              — list your watchlist
  /watchlist add <movie>  — add a movie
  /watchlist remove <n>   — remove entry number n

Callback pattern:  wl_rm:{entry_id}

Multi-user isolation: every Supabase/SQLite query is scoped to user_id.
"""
from __future__ import annotations

import html as hl
import logging
import re

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from utils.lang_store import get_user_lang
from utils.msgs import m
from utils.supabase_client import add_to_watchlist, get_watchlist, remove_from_watchlist
from utils.tmdb import search_movie

logger = logging.getLogger(__name__)


# ── helpers ───────────────────────────────────────────────────────────────────


def _watchlist_text(entries: list[dict], lang: str) -> str:
    if not entries:
        return m("watchlist_empty", lang)
    lines = ["📋 <b>உங்க Watchlist:</b>\n" if lang == "ta" else "📋 <b>Your Watchlist:</b>\n"]
    for i, e in enumerate(entries, 1):
        lines.append(f"{i}. 🎬 {hl.escape(e['title'])}")
    if lang == "en":
        lines.append("\n<i>Use the buttons below to remove, or /watchlist add &lt;movie&gt; to add more.</i>")
    else:
        lines.append("\n<i>Remove பண்ண below buttons use பண்ணுங்க, அல்லது /watchlist add &lt;movie&gt;.</i>")
    return "\n".join(lines)


def _watchlist_keyboard(entries: list[dict]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(f"❌ {i}. {e['title'][:24]}", callback_data=f"wl_rm:{e['id']}")]
        for i, e in enumerate(entries, 1)
    ]
    return InlineKeyboardMarkup(rows) if rows else InlineKeyboardMarkup([[]])


# ── /watchlist command ────────────────────────────────────────────────────────


async def handle_watchlist_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    msg = update.message
    uid = update.effective_user.id
    lang = await get_user_lang(uid)
    args = context.args or []
    sub = args[0].lower() if args else ""

    if sub == "add":
        movie_name = " ".join(args[1:]).strip()
        if not movie_name:
            await msg.reply_text(
                "Usage: <code>/watchlist add &lt;movie name&gt;</code>",
                parse_mode="HTML",
            )
            return
        await _add_movie(update, movie_name, lang)

    elif sub == "remove":
        num_str = args[1] if len(args) > 1 else ""
        if not num_str.isdigit():
            await msg.reply_text(
                "Usage: <code>/watchlist remove &lt;number&gt;</code>",
                parse_mode="HTML",
            )
            return
        await _remove_by_index(update, int(num_str), lang)

    else:
        await _show_list(update, lang)


async def _show_list(update: Update, lang: str) -> None:
    uid = update.effective_user.id
    status = await update.effective_message.reply_text(m("watchlist_loading", lang))
    try:
        entries = await get_watchlist(uid)
        text = _watchlist_text(entries, lang)
        keyboard = _watchlist_keyboard(entries)
        await status.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as exc:
        logger.error("Watchlist list error for user %s: %s", uid, exc, exc_info=True)
        await status.edit_text(
            m("watchlist_load_fail", lang, err=hl.escape(type(exc).__name__)),
            parse_mode="HTML",
        )


async def _add_movie(update: Update, movie_name: str, lang: str) -> None:
    msg = update.effective_message
    uid = update.effective_user.id
    status = await msg.reply_text(
        m("watchlist_add_searching", lang, name=hl.escape(movie_name)),
        parse_mode="HTML",
    )
    try:
        movie = await search_movie(movie_name)
        if not movie:
            await status.edit_text(
                m("watchlist_not_found", lang, name=hl.escape(movie_name)),
                parse_mode="HTML",
            )
            return

        await status.edit_text(m("watchlist_saving", lang))
        backend = await add_to_watchlist(uid, movie["id"], movie["title"], movie.get("poster_url"))

        note = m("watchlist_sqlite_note", lang) if backend == "sqlite" else ""
        await status.edit_text(
            m("watchlist_add_ok", lang,
              title=hl.escape(movie["title"]),
              year=hl.escape(movie.get("year") or "")) + note,
            parse_mode="HTML",
        )
        logger.info("Watchlist add OK: user=%s movie=%s backend=%s", uid, movie["title"], backend)
    except Exception as exc:
        logger.error("Watchlist add error for user %s / '%s': %s", uid, movie_name, exc, exc_info=True)
        await status.edit_text(
            m("watchlist_add_fail", lang, err=hl.escape(type(exc).__name__)),
            parse_mode="HTML",
        )


async def _remove_by_index(update: Update, n: int, lang: str) -> None:
    uid = update.effective_user.id
    try:
        entries = await get_watchlist(uid)
        if n < 1 or n > len(entries):
            await update.effective_message.reply_text(
                m("watchlist_invalid_number", lang, count=len(entries))
            )
            return
        entry = entries[n - 1]
        await remove_from_watchlist(entry["id"], uid)
        await update.effective_message.reply_text(
            m("watchlist_remove_ok", lang, title=hl.escape(entry["title"])),
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.error("Watchlist remove error for user %s: %s", uid, exc, exc_info=True)
        await update.effective_message.reply_text(
            m("watchlist_remove_fail", lang, err=hl.escape(type(exc).__name__)),
            parse_mode="HTML",
        )


# ── callback: remove via inline button ───────────────────────────────────────


async def handle_watchlist_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handles wl_rm:{entry_id} callbacks."""
    query: CallbackQuery = update.callback_query
    await query.answer()

    match = re.match(r"^wl_rm:(\d+)$", query.data or "")
    if not match:
        return

    entry_id = int(match.group(1))
    uid = update.effective_user.id
    lang = await get_user_lang(uid)

    try:
        await remove_from_watchlist(entry_id, uid)
        entries = await get_watchlist(uid)
        text = _watchlist_text(entries, lang)
        keyboard = _watchlist_keyboard(entries)
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as exc:
        logger.error("Watchlist callback error for user %s: %s", uid, exc, exc_info=True)
        try:
            await query.edit_message_text(
                m("watchlist_remove_fail", lang, err=hl.escape(type(exc).__name__)),
                parse_mode="HTML",
            )
        except Exception:
            pass
