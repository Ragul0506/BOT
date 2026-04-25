"""Watchlist handler — add, list, remove movies.

Commands:
  /watchlist              — list your watchlist
  /watchlist add <movie>  — add a movie
  /watchlist remove <n>   — remove entry number n

Callback pattern:  wl_rm:{entry_id}
"""
from __future__ import annotations

import html as hl
import logging
import re

from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from utils.supabase_client import add_to_watchlist, get_watchlist, remove_from_watchlist
from utils.tmdb import search_movie

logger = logging.getLogger(__name__)


# ── helpers ───────────────────────────────────────────────────────────────────


def _watchlist_text(entries: list[dict]) -> str:
    if not entries:
        return (
            "📋 <b>உங்க Watchlist காலியா இருக்கு!</b>\n\n"
            "Add a movie with:\n"
            "<code>/watchlist add Vikram</code>"
        )
    lines = ["📋 <b>உங்க Watchlist:</b>\n"]
    for i, e in enumerate(entries, 1):
        lines.append(f"{i}. 🎬 {hl.escape(e['title'])}")
    lines.append(
        "\n<i>Use the buttons below to remove, or "
        "/watchlist add &lt;movie&gt; to add more.</i>"
    )
    return "\n".join(lines)


def _watchlist_keyboard(entries: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for i, e in enumerate(entries, 1):
        rows.append(
            [InlineKeyboardButton(f"❌ Remove {i}. {e['title'][:22]}", callback_data=f"wl_rm:{e['id']}")]
        )
    return InlineKeyboardMarkup(rows) if rows else InlineKeyboardMarkup([[]])


# ── /watchlist ────────────────────────────────────────────────────────────────


async def handle_watchlist_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    msg = update.message
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
        await _add_movie(update, movie_name)

    elif sub == "remove":
        num_str = args[1] if len(args) > 1 else ""
        if not num_str.isdigit():
            await msg.reply_text(
                "Usage: <code>/watchlist remove &lt;number&gt;</code>",
                parse_mode="HTML",
            )
            return
        await _remove_by_index(update, int(num_str))

    else:
        await _show_list(update)


async def _show_list(update: Update) -> None:
    uid = update.effective_user.id
    status = await update.effective_message.reply_text("📋 Watchlist load பண்றேன்…")
    try:
        entries = await get_watchlist(uid)
        text = _watchlist_text(entries)
        keyboard = _watchlist_keyboard(entries)
        await status.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as exc:
        logger.error("Watchlist list error: %s", exc)
        await status.edit_text(f"❌ Error: {hl.escape(str(exc))}", parse_mode="HTML")


async def _add_movie(update: Update, movie_name: str) -> None:
    msg = update.effective_message
    status = await msg.reply_text(
        f"🔍 '<b>{hl.escape(movie_name)}</b>' TMDB-ல் தேடுகிறேன்…",
        parse_mode="HTML",
    )
    try:
        movie = await search_movie(movie_name)
        if not movie:
            await status.edit_text(
                f"❌ '<b>{hl.escape(movie_name)}</b>' கண்டுபிடிக்கவில்லை.",
                parse_mode="HTML",
            )
            return
        uid = update.effective_user.id
        await add_to_watchlist(uid, movie["id"], movie["title"], movie.get("poster_url"))
        await status.edit_text(
            f"✅ <b>{hl.escape(movie['title'])}</b> ({movie['year']}) "
            f"watchlist-ல் add ஆச்சு! 🎬",
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.error("Watchlist add error: %s", exc)
        await status.edit_text(f"❌ Error: {hl.escape(str(exc))}", parse_mode="HTML")


async def _remove_by_index(update: Update, n: int) -> None:
    uid = update.effective_user.id
    try:
        entries = await get_watchlist(uid)
        if n < 1 or n > len(entries):
            await update.effective_message.reply_text(
                f"❌ Invalid number. Your watchlist has {len(entries)} entries."
            )
            return
        entry = entries[n - 1]
        await remove_from_watchlist(entry["id"], uid)
        await update.effective_message.reply_text(
            f"🗑️ <b>{hl.escape(entry['title'])}</b> removed from watchlist.",
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.error("Watchlist remove error: %s", exc)
        await update.effective_message.reply_text(f"❌ Error: {hl.escape(str(exc))}", parse_mode="HTML")


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

    try:
        await remove_from_watchlist(entry_id, uid)
        # Refresh the list in place
        entries = await get_watchlist(uid)
        text = _watchlist_text(entries)
        keyboard = _watchlist_keyboard(entries)
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as exc:
        logger.error("Watchlist callback error: %s", exc)
        try:
            await query.edit_message_text(f"❌ Error: {hl.escape(str(exc))}", parse_mode="HTML")
        except Exception:
            pass
