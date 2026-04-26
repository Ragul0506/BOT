"""/billhistory [date] — show bill history for a given date.

date argument can be:
  (empty)     → today
  yesterday   → yesterday
  YYYY-MM-DD  → specific date
  DD-MM-YYYY  → alternate format

Multi-user isolation: each user only ever sees their own Bill_History_{uid} tab.
"""
from __future__ import annotations

import html as hl
import logging
import re
from datetime import date as _date, datetime, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from utils.bill_history import bill_history_available, get_bills_for_date
from utils.lang_store import get_user_lang
from utils.msgs import m

logger = logging.getLogger(__name__)


def _parse_date_arg(arg: str) -> str | None:
    """Return YYYY-MM-DD string from user argument, or None on invalid input."""
    today = _date.today()
    stripped = arg.strip().lower()

    if not stripped or stripped == "today":
        return str(today)
    if stripped == "yesterday":
        return str(today - timedelta(days=1))

    # YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}$", stripped):
        try:
            datetime.strptime(stripped, "%Y-%m-%d")
            return stripped
        except ValueError:
            return None

    # DD-MM-YYYY
    match = re.match(r"^(\d{1,2})-(\d{1,2})-(\d{4})$", stripped)
    if match:
        day, mon, year = match.groups()
        candidate = f"{year}-{int(mon):02d}-{int(day):02d}"
        try:
            datetime.strptime(candidate, "%Y-%m-%d")
            return candidate
        except ValueError:
            return None

    return None


def _format_bills(bills: list[dict], date_str: str, lang: str) -> str:
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        display_date = d.strftime("%d %B %Y")
    except Exception:
        display_date = date_str

    if not bills:
        return (
            f"📋 <b>{hl.escape(display_date)} Bills:</b>\n\n"
            + m("billhistory_no_bills", lang)
        )

    lines = [f"📋 <b>{hl.escape(display_date)} Bill History:</b>\n"]
    grand = 0.0
    for b in bills:
        bill_no = hl.escape(str(b.get("Bill_Number", "—")))
        total = float(b.get("Total_Amount") or 0)
        summary = hl.escape(str(b.get("Items_Summary") or ""))
        grand += total
        lines.append(f"🧾 <b>{bill_no}</b> — ₹{total:.2f}")
        if summary:
            lines.append(f"   <i>{summary}</i>")

    lines.append(f"\n<b>Day Total: ₹{grand:.2f}</b>")

    if lang == "en":
        lines.append(f"\n<i>{len(bills)} bill(s) on {display_date}</i>")
    else:
        lines.append(f"\n<i>{display_date}-ல் {len(bills)} bill(s)</i>")

    return "\n".join(lines)


async def handle_billhistory_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/billhistory [date]"""
    msg = update.message
    uid = update.effective_user.id
    lang = await get_user_lang(uid)

    if not bill_history_available():
        await msg.reply_text(m("billhistory_no_sheets", lang))
        return

    arg = " ".join(context.args).strip() if context.args else ""
    date_str = _parse_date_arg(arg)

    if date_str is None:
        if lang == "en":
            usage = (
                "❌ Invalid date format.\n\n"
                "<b>Usage:</b>\n"
                "• <code>/billhistory</code> — today's bills\n"
                "• <code>/billhistory yesterday</code>\n"
                "• <code>/billhistory 2024-04-26</code>"
            )
        else:
            usage = (
                "❌ Invalid date format.\n\n"
                "<b>Usage:</b>\n"
                "• <code>/billhistory</code> — இன்றைய bills\n"
                "• <code>/billhistory yesterday</code>\n"
                "• <code>/billhistory 2024-04-26</code>"
            )
        await msg.reply_text(usage, parse_mode="HTML")
        return

    status = await msg.reply_text(m("billhistory_loading", lang))

    try:
        bills = await get_bills_for_date(uid, date_str)
        text = _format_bills(bills, date_str, lang)
        await status.edit_text(text, parse_mode="HTML")
    except Exception as exc:
        logger.error("Billhistory error for user %s: %s", uid, exc, exc_info=True)
        await status.edit_text(m("billhistory_fail", lang))
