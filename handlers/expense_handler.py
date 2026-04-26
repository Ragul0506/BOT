"""Expense tracker handler.

Commands:
  /expense <text>   — log a text expense description
  /summary          — monthly expense summary PDF
  /summary last     — last-month summary

Voice notes are also routed here by voice_handler when the LLM classifies
the intent as "expense".
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
from utils.matplotlib_chart import generate_expense_chart
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

    async def _edit(t: str) -> None:
        if status_msg:
            try:
                await status_msg.edit_text(t, parse_mode="HTML")
            except Exception:
                pass

    await _edit("🔍 Expenses parse பண்றேன்…")

    expenses = await parse_expenses(text, today=str(date.today()))
    if not expenses:
        await _edit(
            "❌ Expense details கண்டுபிடிக்கவில்லை.\n\n"
            "Example: <i>/expense today spent 200 for chai and 500 for petrol</i>",
        )
        return

    # Log to Google Sheets
    if sheets_available():
        await _edit("📊 Google Sheets-ல் save பண்றேன்…")
        try:
            uid = str(update.effective_user.id)
            await append_expenses(uid, expenses)
        except Exception as exc:
            logger.error("Sheets append error: %s", exc, exc_info=True)
            # [H2] Do not expose internal error details to the user.
            await _edit(
                "⚠️ Google Sheets-ல் save ஆகவில்லை. கொஞ்சம் நேரம் கழிச்சு மீண்டும் try பண்ணுங்க."
            )
            return

    # Build reply
    lines = ["✅ <b>Expenses logged!</b>\n"]
    total = 0.0
    for exp in expenses:
        amt = float(exp.get("amount", 0))
        total += amt
        cat = exp.get("category", "general").capitalize()
        note = exp.get("note", "")
        lines.append(f"• ₹{amt:.0f} — {cat} ({hl.escape(note)})")
    lines.append(f"\n<b>Total: ₹{total:.0f}</b>")

    if not sheets_available():
        lines.append(
            "\n⚠️ <i>Google Sheets not configured — expenses not persisted. "
            "Set GOOGLE_SHEETS_CREDENTIALS_JSON and GOOGLE_SHEET_ID.</i>"
        )

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

    # [C4] Enforce rate limit.
    if not rate_limiter.is_allowed(update.effective_user.id):
        await msg.reply_text(
            "⏳ கொஞ்சம் slow பண்ணுங்க! சற்று நேரம் கழிச்சு மீண்டும் try பண்ணுங்க."
        )
        return

    text = " ".join(context.args).strip() if context.args else ""

    if not text:
        await msg.reply_text(
            "📝 <b>Expense Tracker</b>\n\n"
            "Usage: <code>/expense &lt;description&gt;</code>\n\n"
            "Examples:\n"
            "• <code>/expense today chai 30 and petrol 500</code>\n"
            "• <code>/expense yesterday lunch 120 rupees</code>\n"
            "• <code>/expense 200 for medicine on 2024-01-20</code>\n\n"
            "📊 Or send a voice note describing your expenses!",
            parse_mode="HTML",
        )
        return

    status = await msg.reply_text("💰 Processing expense…")
    await process_expense_text(update, text, status_msg=status)


# ── /summary command ──────────────────────────────────────────────────────────


async def handle_summary_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/summary  or  /summary last"""
    msg = update.message
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
        f"📊 <b>{hl.escape(month_label)}</b> expenses fetch பண்றேன்…",
        parse_mode="HTML",
    )

    if not sheets_available():
        await status.edit_text(
            "❌ Google Sheets not configured.\n"
            "Set <code>GOOGLE_SHEETS_CREDENTIALS_JSON</code> and "
            "<code>GOOGLE_SHEET_ID</code> environment variables.",
            parse_mode="HTML",
        )
        return

    uid = str(update.effective_user.id)
    expenses = await get_month_expenses(uid, year, month)

    if not expenses:
        await status.edit_text(
            f"📭 <b>{hl.escape(month_label)}</b>-ல் expenses இல்லை.",
            parse_mode="HTML",
        )
        return

    await status.edit_text(
        f"📈 {len(expenses)} transactions found. Chart + PDF தயாரிக்கிறேன்…"
    )

    # Compute category totals for chart
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
        user_name = update.effective_user.full_name or uid
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
        logger.error("Summary PDF error: %s", exc, exc_info=True)
        # [H2] Never expose raw exception to users.
        await status.edit_text(
            "😕 Summary generate பண்ண முடியல! கொஞ்சம் நேரம் கழிச்சு மீண்டும் try பண்ணுங்க."
        )
    finally:
        for p in (chart_path, pdf_path):
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except OSError:
                    pass
