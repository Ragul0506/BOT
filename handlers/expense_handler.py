"""Expense tracker handler.

Commands:
  /expense <text>   — log a text expense description
  /summary          — monthly expense summary PDF
  /summary last     — last-month summary

Voice notes are also routed here by voice_handler when the LLM classifies
the intent as "expense".

Multi-user isolation: every Sheets call uses user_id as the worksheet tab name.
"""
from __future__ import annotations

import html as hl
import logging
import os
from calendar import month_name
from datetime import date, datetime

from telegram import Update
from telegram.ext import ContextTypes

from utils.groq_llm import parse_expenses
from utils.lang_store import get_user_lang
from utils.matplotlib_chart import generate_expense_chart
from utils.msgs import m
from utils.pdf_generator import generate_expense_summary_pdf
from utils.security import rate_limiter
from utils.sheets_api import append_expenses, get_month_expenses, sheets_available

logger = logging.getLogger(__name__)


# ── shared expense-processing core ───────────────────────────────────────────


async def process_expense_text(
    update: Update,
    text: str,
    *,
    status_msg=None,
) -> None:
    """Parse *text* for expenses, log to Sheets, reply with confirmation."""
    msg = update.effective_message
    uid = update.effective_user.id
    lang = await get_user_lang(uid)

    async def _edit(t: str, html: bool = False) -> None:
        pm = "HTML" if html else None
        if status_msg:
            try:
                await status_msg.edit_text(t, parse_mode=pm)
            except Exception:
                pass

    await _edit(m("expense_parsing", lang))

    expenses = await parse_expenses(text, today=str(date.today()))
    if not expenses:
        await _edit(m("expense_not_found", lang), html=True)
        return

    # Log to Google Sheets
    if sheets_available():
        await _edit(m("expense_sheets_saving", lang))
        try:
            await append_expenses(uid, expenses)
        except Exception as exc:
            logger.error("Sheets append error for user %s: %s", uid, exc, exc_info=True)
            # [H2] Do not expose internal error details to the user.
            await _edit(m("expense_sheets_fail", lang))
            return

    # Build reply
    lines = [
        "✅ <b>Expenses logged!</b>\n" if lang == "en" else "✅ <b>Expenses save ஆச்சு!</b>\n"
    ]
    total = 0.0
    for exp in expenses:
        amt = float(exp.get("amount", 0))
        total += amt
        cat = exp.get("category", "general").capitalize()
        note = exp.get("note", "")
        lines.append(f"• ₹{amt:.0f} — {cat} ({hl.escape(note)})")
    lines.append(f"\n<b>Total: ₹{total:.0f}</b>")

    if not sheets_available():
        lines.append(m("expense_no_sheets_note", lang))

    reply = "\n".join(lines)
    if status_msg:
        try:
            await status_msg.edit_text(reply, parse_mode="HTML")
            return
        except Exception:
            pass
    await msg.reply_text(reply, parse_mode="HTML")


# ── /expense command ──────────────────────────────────────────────────────────


async def handle_expense_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/expense <description>"""
    msg = update.message
    uid = update.effective_user.id
    lang = await get_user_lang(uid)

    # [C4] Enforce rate limit.
    if not rate_limiter.is_allowed(uid):
        await msg.reply_text(m("rate_limit", lang))
        return

    text = " ".join(context.args).strip() if context.args else ""

    if not text:
        if lang == "en":
            help_text = (
                "📝 <b>Expense Tracker</b>\n\n"
                "Usage: <code>/expense &lt;description&gt;</code>\n\n"
                "Examples:\n"
                "• <code>/expense today chai 30 and petrol 500</code>\n"
                "• <code>/expense yesterday lunch 120 rupees</code>\n"
                "• <code>/expense 200 for medicine on 2024-01-20</code>\n\n"
                "📊 Or send a voice note describing your expenses!"
            )
        else:
            help_text = (
                "📝 <b>Expense Tracker</b>\n\n"
                "Usage: <code>/expense &lt;description&gt;</code>\n\n"
                "Examples:\n"
                "• <code>/expense today chai 30 and petrol 500</code>\n"
                "• <code>/expense yesterday lunch 120 rupees</code>\n"
                "• <code>/expense 200 for medicine on 2024-01-20</code>\n\n"
                "📊 அல்லது voice note அனுப்புங்க!"
            )
        await msg.reply_text(help_text, parse_mode="HTML")
        return

    status = await msg.reply_text(m("expense_parsing", lang))
    await process_expense_text(update, text, status_msg=status)


# ── /summary command ──────────────────────────────────────────────────────────


async def handle_summary_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/summary  or  /summary last"""
    msg = update.message
    uid = update.effective_user.id
    lang = await get_user_lang(uid)

    arg = (" ".join(context.args) if context.args else "").strip().lower()
    last_month = "last" in arg

    today = date.today()
    if last_month:
        if today.month == 1:
            year, month = today.year - 1, 12
        else:
            year, month = today.year, today.month - 1
    else:
        year, month = today.year, today.month

    month_label = f"{month_name[month]} {year}"
    status = await msg.reply_text(
        f"📊 <b>{hl.escape(month_label)}</b> expenses fetch பண்றேன்…"
        if lang == "ta"
        else f"📊 Fetching <b>{hl.escape(month_label)}</b> expenses…",
        parse_mode="HTML",
    )

    if not sheets_available():
        no_sheets = (
            "❌ Google Sheets configure ஆகவில்லை.\n"
            "<code>GOOGLE_SHEETS_CREDENTIALS_JSON</code> மற்றும் "
            "<code>GOOGLE_SHEET_ID</code> set பண்ணுங்க."
            if lang == "ta" else
            "❌ Google Sheets not configured.\n"
            "Set <code>GOOGLE_SHEETS_CREDENTIALS_JSON</code> and "
            "<code>GOOGLE_SHEET_ID</code> environment variables."
        )
        await status.edit_text(no_sheets, parse_mode="HTML")
        return

    expenses = await get_month_expenses(uid, year, month)

    if not expenses:
        no_exp = (
            f"📭 <b>{hl.escape(month_label)}</b>-ல் expenses இல்லை."
            if lang == "ta"
            else f"📭 No expenses found for <b>{hl.escape(month_label)}</b>."
        )
        await status.edit_text(no_exp, parse_mode="HTML")
        return

    status_txt = (
        f"📈 {len(expenses)} transactions found. Chart + PDF தயாரிக்கிறேன்…"
        if lang == "ta"
        else f"📈 {len(expenses)} transactions found. Generating chart + PDF…"
    )
    await status.edit_text(status_txt)

    from collections import defaultdict
    category_totals: dict[str, float] = defaultdict(float)
    grand_total = 0.0
    for row in expenses:
        amt = float(row.get("Amount", 0))
        cat = str(row.get("Category", "general")).capitalize()
        category_totals[cat] += amt
        grand_total += amt

    chart_path: str | None = None
    pdf_path: str | None = None

    try:
        chart_path = generate_expense_chart(dict(category_totals), month_label)
        user_name = update.effective_user.full_name or str(uid)
        pdf_path = generate_expense_summary_pdf(
            expenses, month_label, user_name=user_name, chart_path=chart_path
        )

        summary_lines = [
            f"💰 <b>{hl.escape(month_label)} Summary</b>",
            f"Total: <b>₹{grand_total:,.0f}</b> across {len(expenses)} transactions",
            "",
        ]
        for cat, total in sorted(category_totals.items(), key=lambda x: x[1], reverse=True):
            summary_lines.append(f"• {cat}: ₹{total:,.0f}")

        caption = "\n".join(summary_lines)

        try:
            await status.delete()
        except Exception:
            pass

        with open(pdf_path, "rb") as f:
            await msg.reply_document(
                document=f,
                filename=f"expenses_{year}_{month:02d}.pdf",
                caption=caption,
                parse_mode="HTML",
            )

    except Exception as exc:
        logger.error("Summary PDF error for user %s: %s", uid, exc, exc_info=True)
        # [H2] Never expose raw exception to users.
        await status.edit_text(m("generic_error", lang))
    finally:
        for p in (chart_path, pdf_path):
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except OSError:
                    pass
