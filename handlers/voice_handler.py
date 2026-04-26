"""Voice note handler — transcribe then route by LLM intent.

Flow:
  1. Download OGG from Telegram.
  2. Transcribe with Groq Whisper.
  3. classify_voice_intent() → "bill" | "expense" | "other"
  4a. "bill"    → parse_items → generate_bill_pdf → send PDF → log to bill_history
  4b. "expense" → process_expense_text (expense_handler)
  4c. "other"   → attempt bill flow; if empty, helpful error
"""
from __future__ import annotations

import html as hl
import logging
import os
import tempfile

from telegram import Update
from telegram.ext import ContextTypes

from utils.bill_history import bill_history_available, log_bill
from utils.groq_llm import classify_voice_intent, detect_transcript_language, parse_items
from utils.groq_whisper import transcribe_audio
from utils.lang_store import get_user_lang
from utils.msgs import m
from utils.pdf_generator import generate_bill_pdf
from utils.security import rate_limiter

logger = logging.getLogger(__name__)

_MAX_VOICE_BYTES = 20 * 1024 * 1024  # 20 MB


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    uid = update.effective_user.id
    lang = await get_user_lang(uid)

    # [C4] Enforce rate limit before any processing.
    if not rate_limiter.is_allowed(uid):
        await msg.reply_text(m("rate_limit", lang))
        return

    status = await msg.reply_text(m("voice_received", lang))

    audio_path: str | None = None
    pdf_path: str | None = None

    try:
        # ── 1. Download OGG ───────────────────────────────────────────────────
        voice_file = await msg.voice.get_file()

        # [H4] Check file size before downloading.
        if voice_file.file_size and voice_file.file_size > _MAX_VOICE_BYTES:
            await status.edit_text(m("voice_too_large", lang))
            return

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            audio_path = tmp.name
        await voice_file.download_to_drive(audio_path)
        logger.info("Voice: %s (%.1f KB)", audio_path, os.path.getsize(audio_path) / 1024)

        # ── 2. Transcribe ─────────────────────────────────────────────────────
        await status.edit_text(m("voice_transcribing", lang))
        transcript = await transcribe_audio(audio_path)

        if not transcript.strip():
            await status.edit_text(m("voice_no_transcript", lang))
            return

        # Detect script language for bilingual PDF headers
        pdf_lang = detect_transcript_language(transcript)
        logger.info("Transcript lang detected: %s", pdf_lang)

        # [H1] HTML-escape transcript preview before embedding in HTML message.
        preview = hl.escape(transcript[:100] + ("…" if len(transcript) > 100 else ""))
        await status.edit_text(m("voice_intent", lang, preview=preview), parse_mode="HTML")

        # ── 3. Classify intent ────────────────────────────────────────────────
        intent = await classify_voice_intent(transcript)
        logger.info("Voice intent: '%s' | pdf_lang: '%s' | transcript: %s", intent, pdf_lang, transcript[:80])

        if intent == "expense":
            # ── expense route ─────────────────────────────────────────────────
            from handlers.expense_handler import process_expense_text
            await process_expense_text(update, transcript, status_msg=status)
            return

        # ── bill route (intent == "bill" OR "other") ──────────────────────────
        await status.edit_text(m("voice_parsing_bill", lang))
        items = await parse_items(transcript)

        if not items:
            # [H1] HTML-escape transcript before embedding in HTML message.
            safe_preview = hl.escape(transcript[:200])
            key = "voice_no_items_other" if intent == "other" else "voice_no_items_bill"
            await status.edit_text(m(key, lang, preview=safe_preview), parse_mode="HTML")
            return

        # ── generate PDF ──────────────────────────────────────────────────────
        await status.edit_text(m("voice_pdf_gen", lang, count=len(items)))
        pdf_path = generate_bill_pdf(items, language=pdf_lang)

        grand_total = sum(float(i.get("qty", 1)) * float(i.get("rate", 0)) for i in items)
        caption = m("voice_bill_done", lang, total=grand_total)

        try:
            await status.delete()
        except Exception:
            pass

        with open(pdf_path, "rb") as pdf_file:
            sent = await msg.reply_document(
                document=pdf_file,
                filename="bill.pdf",
                caption=caption,
                parse_mode="HTML",
            )

        # ── log to bill history (non-blocking) ────────────────────────────────
        if bill_history_available():
            pdf_file_id = sent.document.file_id if sent and sent.document else ""
            bill_no = await log_bill(uid, items, grand_total, pdf_file_id)
            if bill_no:
                try:
                    await sent.reply_text(
                        m("bill_logged", lang, bill_no=hl.escape(bill_no)),
                        parse_mode="HTML",
                    )
                except Exception:
                    pass

    except Exception as exc:
        logger.error("Voice handler error for user %s: %s", uid, exc, exc_info=True)
        try:
            # [H2] Never expose raw exception to users; log internally only.
            await status.edit_text(m("generic_error", lang))
        except Exception:
            pass

    finally:
        for path in (audio_path, pdf_path):
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except OSError:
                    pass
