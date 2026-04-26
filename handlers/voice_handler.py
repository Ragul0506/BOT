"""Voice note handler — transcribe then route by LLM intent.

Flow:
  1. Download OGG from Telegram.
  2. Transcribe with Groq Whisper.
  3. classify_voice_intent() → "bill" | "expense" | "other"
  4. "bill"    → parse_items → generate_bill_pdf → send PDF
     "expense" → process_expense_text (expense_handler)
     "other"   → attempt bill flow; if empty, helpful error
"""
from __future__ import annotations

import html as hl
import logging
import os
import tempfile

from telegram import Update
from telegram.ext import ContextTypes

from utils.groq_llm import classify_voice_intent, parse_items
from utils.groq_whisper import transcribe_audio
from utils.pdf_generator import generate_bill_pdf
from utils.security import rate_limiter

logger = logging.getLogger(__name__)

_MAX_VOICE_BYTES = 20 * 1024 * 1024  # 20 MB


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    uid = update.effective_user.id

    # [C4] Enforce rate limit before any processing.
    if not rate_limiter.is_allowed(uid):
        await msg.reply_text(
            "⏳ கொஞ்சம் slow பண்ணுங்க! சற்று நேரம் கழிச்சு மீண்டும் try பண்ணுங்க."
        )
        return

    status = await msg.reply_text("🎤 Voice note கிடைச்சது! Process பண்றேன்…")

    audio_path: str | None = None
    pdf_path: str | None = None

    try:
        # ── 1. Download OGG ───────────────────────────────────────────────────
        voice_file = await msg.voice.get_file()

        # [H4] Check file size before downloading.
        if voice_file.file_size and voice_file.file_size > _MAX_VOICE_BYTES:
            await status.edit_text(
                "❌ Audio file too large (max 20 MB). சின்னதா record பண்ணுங்க."
            )
            return

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            audio_path = tmp.name
        await voice_file.download_to_drive(audio_path)
        logger.info("Voice: %s (%.1f KB)", audio_path, os.path.getsize(audio_path) / 1024)

        # ── 2. Transcribe ─────────────────────────────────────────────────────
        await status.edit_text("🎙️ Transcribe பண்றேன் (Groq Whisper)…")
        transcript = await transcribe_audio(audio_path)

        if not transcript.strip():
            await status.edit_text(
                "❌ Audio transcribe ஆகவில்லை.\n"
                "தெளிவாக பேசி, background noise இல்லாம மீண்டும் try பண்ணுங்க."
            )
            return

        # [H1] HTML-escape transcript preview before embedding in HTML message.
        preview = hl.escape(transcript[:100] + ("…" if len(transcript) > 100 else ""))
        await status.edit_text(
            f"📝 <b>Transcript:</b> <i>{preview}</i>\n\n🧠 Intent detect பண்றேன்…",
            parse_mode="HTML",
        )

        # ── 3. Classify intent ────────────────────────────────────────────────
        intent = await classify_voice_intent(transcript)
        logger.info("Voice intent: '%s' | transcript: %s", intent, transcript[:80])

        if intent == "expense":
            # ── expense route ─────────────────────────────────────────────────
            from handlers.expense_handler import process_expense_text
            await process_expense_text(update, transcript, status_msg=status)
            return

        # ── bill route (intent == "bill" OR "other") ──────────────────────────
        await status.edit_text("🔍 Bill items parse பண்றேன்…")
        items = await parse_items(transcript)

        if not items:
            # [H1] HTML-escape transcript before embedding in HTML message.
            safe_transcript = hl.escape(transcript[:200])
            if intent == "other":
                await status.edit_text(
                    f"🤔 என்ன சொல்றீங்க என்று புரியல.\n\n"
                    f"<b>Transcript:</b> <i>{safe_transcript}</i>\n\n"
                    "💡 Bill-ஆ? <i>'2 kg sugar 80 rupees'</i> மாதிரி சொல்லுங்க.\n"
                    "💰 Expense-ஆ? <i>'today spent 200 for chai'</i> மாதிரி சொல்லுங்க.",
                    parse_mode="HTML",
                )
            else:
                await status.edit_text(
                    f"❌ Items parse ஆகவில்லை.\n\n"
                    f"<b>Transcript:</b> <i>{safe_transcript}</i>\n\n"
                    "Format: <i>'quantity item rate rupees'</i>\n"
                    "Example: <i>2 kg sugar 80 rupees, 1 litre oil 160</i>",
                    parse_mode="HTML",
                )
            return

        # ── generate PDF ──────────────────────────────────────────────────────
        await status.edit_text(f"📄 {len(items)} items found. PDF தயாரிக்கிறேன்…")
        pdf_path = generate_bill_pdf(items)

        grand_total = sum(float(i.get("qty", 1)) * float(i.get("rate", 0)) for i in items)
        caption = f"இதோ உங்க பில்! மொத்தம் &#8377; {grand_total:.0f}."

        try:
            await status.delete()
        except Exception:
            pass

        with open(pdf_path, "rb") as pdf_file:
            await msg.reply_document(
                document=pdf_file,
                filename="bill.pdf",
                caption=caption,
                parse_mode="HTML",
            )

    except Exception as exc:
        logger.error("Voice handler error: %s", exc, exc_info=True)
        try:
            # [H2] Never expose raw exception to users; log internally only.
            await status.edit_text(
                "😕 ஏதோ problem ஆச்சு! கொஞ்சம் நேரம் கழிச்சு மீண்டும் try பண்ணுங்க."
            )
        except Exception:
            pass

    finally:
        for path in (audio_path, pdf_path):
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except OSError:
                    pass
