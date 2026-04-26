"""Bilingual message templates — Tanglish ('ta') and English ('en').

Usage:
    from utils.msgs import m
    await msg.reply_text(m("rate_limit", lang))
    await msg.reply_text(m("movie_not_found", lang, name=safe_title))

All messages are HTML-safe (callers still do hl.escape on dynamic values
before passing them as kwargs). parse_mode="HTML" must be set by caller
for messages that contain HTML tags.
"""
from __future__ import annotations

_T: dict[str, dict[str, str]] = {

    # ── generic ───────────────────────────────────────────────────────────────

    "rate_limit": {
        "ta": "⏳ கொஞ்சம் slow பண்ணுங்க! சற்று நேரம் கழிச்சு மீண்டும் try பண்ணுங்க.",
        "en": "⏳ Slow down! Please try again in a moment.",
    },
    "generic_error": {
        "ta": "😕 ஏதோ problem ஆச்சு! கொஞ்சம் நேரம் கழிச்சு மீண்டும் try பண்ணுங்க.",
        "en": "😕 Something went wrong. Please try again later.",
    },

    # ── voice / bill ──────────────────────────────────────────────────────────

    "voice_received": {
        "ta": "🎤 Voice note கிடைச்சது! Process பண்றேன்…",
        "en": "🎤 Voice note received! Processing…",
    },
    "voice_transcribing": {
        "ta": "🎙️ Transcribe பண்றேன் (Groq Whisper)…",
        "en": "🎙️ Transcribing with Groq Whisper…",
    },
    "voice_no_transcript": {
        "ta": (
            "❌ Audio transcribe ஆகவில்லை.\n"
            "தெளிவாக பேசி, background noise இல்லாம மீண்டும் try பண்ணுங்க."
        ),
        "en": (
            "❌ Could not transcribe audio.\n"
            "Please speak clearly without background noise and try again."
        ),
    },
    "voice_intent": {
        "ta": "📝 <b>Transcript:</b> <i>{preview}</i>\n\n🧠 Intent detect பண்றேன்…",
        "en": "📝 <b>Transcript:</b> <i>{preview}</i>\n\n🧠 Detecting intent…",
    },
    "voice_parsing_bill": {
        "ta": "🔍 Bill items parse பண்றேன்…",
        "en": "🔍 Parsing bill items…",
    },
    "voice_no_items_other": {
        "ta": (
            "🤔 என்ன சொல்றீங்க என்று புரியல.\n\n"
            "<b>Transcript:</b> <i>{preview}</i>\n\n"
            "💡 Bill-ஆ? <i>'2 kg sugar 80 rupees'</i> மாதிரி சொல்லுங்க.\n"
            "💰 Expense-ஆ? <i>'today spent 200 for chai'</i> மாதிரி சொல்லுங்க."
        ),
        "en": (
            "🤔 Could not understand.\n\n"
            "<b>Transcript:</b> <i>{preview}</i>\n\n"
            "💡 For a bill say: <i>'2 kg sugar 80 rupees'</i>\n"
            "💰 For an expense say: <i>'today spent 200 for chai'</i>"
        ),
    },
    "voice_no_items_bill": {
        "ta": (
            "❌ Items parse ஆகவில்லை.\n\n"
            "<b>Transcript:</b> <i>{preview}</i>\n\n"
            "Format: <i>'quantity item rate rupees'</i>\n"
            "Example: <i>2 kg sugar 80 rupees, 1 litre oil 160</i>"
        ),
        "en": (
            "❌ Could not parse items.\n\n"
            "<b>Transcript:</b> <i>{preview}</i>\n\n"
            "Format: <i>'quantity item rate rupees'</i>\n"
            "Example: <i>2 kg sugar 80 rupees, 1 litre oil 160</i>"
        ),
    },
    "voice_pdf_gen": {
        "ta": "📄 {count} items found. PDF தயாரிக்கிறேன்…",
        "en": "📄 Found {count} items. Generating PDF…",
    },
    "voice_bill_done": {
        "ta": "இதோ உங்க பில்! மொத்தம் &#8377; {total:.0f}.",
        "en": "Here is your bill! Total &#8377; {total:.0f}.",
    },
    "voice_service_bill_done": {
        "ta": "&#128136; <b>{shop}</b> Service Invoice!\nRoll No: <b>{roll}</b> | Net &#8377; {total:.2f}.",
        "en": "&#128136; <b>{shop}</b> Service Invoice!\nRoll No: <b>{roll}</b> | Net &#8377; {total:.2f}.",
    },
    "voice_too_large": {
        "ta": "❌ Audio file too large (max 20 MB). சின்னதா record பண்ணுங்க.",
        "en": "❌ Audio file too large (max 20 MB). Please record a shorter note.",
    },

    # ── photo / OCR ───────────────────────────────────────────────────────────

    "photo_received": {
        "ta": "📸 Photo கிடைச்சது! OCR பண்றேன்…",
        "en": "📸 Photo received! Running OCR…",
    },
    "photo_too_large": {
        "ta": "❌ Photo too large (max 10 MB). சின்னதா compress பண்ணி அனுப்புங்க.",
        "en": "❌ Photo too large (max 10 MB). Please compress and resend.",
    },
    "photo_ocr_running": {
        "ta": "🔍 Text extract பண்றேன் (OCR + preprocessing)…",
        "en": "🔍 Extracting text (OCR with preprocessing)…",
    },
    "photo_ocr_fail": {
        "ta": (
            "📸 Photo-ல text சரியா படிக்க முடியல.\n\n"
            "தயவுசெய்து:\n"
            "• Clear lighting-ல் photo எடுங்க\n"
            "• Bill-ஐ flat-ஆ வையுங்க, blur இல்லாம\n"
            "• Shadow இல்லாம clearly visible-ஆ இருக்கணும்\n\n"
            "மீண்டும் try பண்ணுங்க."
        ),
        "en": (
            "📸 Could not read text from photo.\n\n"
            "Please:\n"
            "• Take the photo in clear lighting\n"
            "• Lay the bill flat, no blur\n"
            "• Ensure no shadows\n\n"
            "Try again."
        ),
    },
    "photo_ocr_preview": {
        "ta": "📝 <b>OCR Text:</b> <i>{preview}</i>\n\nItems parse பண்றேன்…",
        "en": "📝 <b>OCR Text:</b> <i>{preview}</i>\n\nParsing items…",
    },
    "photo_no_items": {
        "ta": (
            "❌ Items parse ஆகவில்லை.\n\n"
            "<b>OCR Text:</b> <i>{preview}</i>\n\n"
            "Bill-ல் items + prices இருக்கா என்று check பண்ணுங்க."
        ),
        "en": (
            "❌ Could not parse items.\n\n"
            "<b>OCR Text:</b> <i>{preview}</i>\n\n"
            "Check that the bill contains items and prices."
        ),
    },
    "photo_bill_done": {
        "ta": "இதோ உங்க பில் (photo-ல் இருந்து). மொத்தம் &#8377; {total:.0f}.",
        "en": "Here is your bill (from photo). Total &#8377; {total:.0f}.",
    },
    "photo_service_bill_done": {
        "ta": "&#128136; <b>{shop}</b> Invoice (photo-ல் இருந்து)!\nRoll No: <b>{roll}</b> | Net &#8377; {total:.2f}.",
        "en": "&#128136; <b>{shop}</b> Invoice (from photo)!\nRoll No: <b>{roll}</b> | Net &#8377; {total:.2f}.",
    },
    "photo_pdf_gen": {
        "ta": "📄 {count} items found. PDF தயாரிக்கிறேன்…",
        "en": "📄 Found {count} items. Generating PDF…",
    },

    # ── bill history ──────────────────────────────────────────────────────────

    "bill_logged": {
        "ta": "\n\n📚 Bill <b>{bill_no}</b> history-ல் save ஆச்சு.",
        "en": "\n\n📚 Bill <b>{bill_no}</b> saved to history.",
    },

    # ── watchlist ─────────────────────────────────────────────────────────────

    "watchlist_loading": {
        "ta": "📋 Watchlist load பண்றேன்…",
        "en": "📋 Loading watchlist…",
    },
    "watchlist_empty": {
        "ta": (
            "📋 <b>உங்க Watchlist காலியா இருக்கு!</b>\n\n"
            "Add a movie with:\n"
            "<code>/watchlist add Vikram</code>"
        ),
        "en": (
            "📋 <b>Your Watchlist is empty!</b>\n\n"
            "Add a movie with:\n"
            "<code>/watchlist add Vikram</code>"
        ),
    },
    "watchlist_load_fail": {
        "ta": (
            "😕 Watchlist load பண்ண முடியல!\n\n"
            "<i>Error: {err}</i>\n"
            "சற்று நேரம் கழிச்சு மீண்டும் try பண்ணுங்க."
        ),
        "en": (
            "😕 Could not load watchlist!\n\n"
            "<i>Error: {err}</i>\n"
            "Please try again later."
        ),
    },
    "watchlist_add_searching": {
        "ta": "🔍 '<b>{name}</b>' TMDB-ல் தேடுகிறேன்…",
        "en": "🔍 Searching TMDB for '<b>{name}</b>'…",
    },
    "watchlist_not_found": {
        "ta": "❌ '<b>{name}</b>' கண்டுபிடிக்கவில்லை.",
        "en": "❌ '<b>{name}</b>' not found on TMDB.",
    },
    "watchlist_saving": {
        "ta": "💾 Watchlist-ல் save பண்றேன்…",
        "en": "💾 Saving to watchlist…",
    },
    "watchlist_add_ok": {
        "ta": "✅ <b>{title}</b> ({year}) watchlist-ல் add ஆச்சு! 🎬",
        "en": "✅ <b>{title}</b> ({year}) added to your watchlist! 🎬",
    },
    "watchlist_add_fail": {
        "ta": (
            "😕 Watchlist-ல் add பண்ண முடியல!\n\n"
            "<i>Error: {err}</i>\n"
            "சற்று நேரம் கழிச்சு மீண்டும் try பண்ணுங்க."
        ),
        "en": (
            "😕 Could not add to watchlist!\n\n"
            "<i>Error: {err}</i>\n"
            "Please try again later."
        ),
    },
    "watchlist_remove_ok": {
        "ta": "🗑️ <b>{title}</b> watchlist-ல் இருந்து remove ஆச்சு.",
        "en": "🗑️ <b>{title}</b> removed from your watchlist.",
    },
    "watchlist_remove_fail": {
        "ta": (
            "😕 Remove பண்ண முடியல!\n\n"
            "<i>Error: {err}</i>\n"
            "சற்று நேரம் கழிச்சு மீண்டும் try பண்ணுங்க."
        ),
        "en": (
            "😕 Could not remove entry!\n\n"
            "<i>Error: {err}</i>\n"
            "Please try again later."
        ),
    },
    "watchlist_sqlite_note": {
        "ta": "\n⚠️ <i>Local storage use பண்றோம் (Supabase connect ஆகவில்லை). Restart-ல் data போகும்.</i>",
        "en": "\n⚠️ <i>Using local storage (Supabase unavailable). Data will be lost on restart.</i>",
    },
    "watchlist_invalid_number": {
        "ta": "❌ Invalid number. உங்க watchlist-ல் {count} entries இருக்கு.",
        "en": "❌ Invalid number. Your watchlist has {count} entries.",
    },

    # ── movie ─────────────────────────────────────────────────────────────────

    "movie_searching": {
        "ta": "🔍 '<b>{name}</b>' தேடுகிறேன்…",
        "en": "🔍 Searching for '<b>{name}</b>'…",
    },
    "movie_not_found": {
        "ta": (
            "❌ '<b>{name}</b>' கண்டுபிடிக்கவில்லை.\n"
            "சரியான ஆங்கிலப் பெயரை try பண்ணுங்க."
        ),
        "en": (
            "❌ '<b>{name}</b>' not found.\n"
            "Try the English movie title."
        ),
    },
    "movie_fail": {
        "ta": "😕 Movie தேட முடியல! கொஞ்சம் நேரம் கழிச்சு மீண்டும் try பண்ணுங்க.",
        "en": "😕 Movie search failed. Please try again later.",
    },

    # ── expense ───────────────────────────────────────────────────────────────

    "expense_parsing": {
        "ta": "🔍 Expenses parse பண்றேன்…",
        "en": "🔍 Parsing expenses…",
    },
    "expense_not_found": {
        "ta": (
            "❌ Expense details கண்டுபிடிக்கவில்லை.\n\n"
            "Example: <i>/expense today spent 200 for chai and 500 for petrol</i>"
        ),
        "en": (
            "❌ Could not find expense details.\n\n"
            "Example: <i>/expense today spent 200 for chai and 500 for petrol</i>"
        ),
    },
    "expense_sheets_saving": {
        "ta": "📊 Google Sheets-ல் save பண்றேன்…",
        "en": "📊 Saving to Google Sheets…",
    },
    "expense_sheets_fail": {
        "ta": "⚠️ Google Sheets-ல் save ஆகவில்லை. கொஞ்சம் நேரம் கழிச்சு மீண்டும் try பண்ணுங்க.",
        "en": "⚠️ Could not save to Google Sheets. Please try again later.",
    },
    "expense_no_sheets_note": {
        "ta": (
            "\n⚠️ <i>Google Sheets configure ஆகவில்லை — expenses persist ஆகல. "
            "GOOGLE_SHEETS_CREDENTIALS_JSON மற்றும் GOOGLE_SHEET_ID set பண்ணுங்க.</i>"
        ),
        "en": (
            "\n⚠️ <i>Google Sheets not configured — expenses not persisted. "
            "Set GOOGLE_SHEETS_CREDENTIALS_JSON and GOOGLE_SHEET_ID.</i>"
        ),
    },

    # ── youtube ───────────────────────────────────────────────────────────────

    "ytmp3_start": {
        "ta": "⬇️ Audio download பண்றேன்…\n<code>{url}</code>",
        "en": "⬇️ Downloading audio…\n<code>{url}</code>",
    },
    "ytmp3_converting": {
        "ta": "🎵 Downloading & converting to MP3…",
        "en": "🎵 Downloading & converting to MP3…",
    },
    "ytmp3_sending": {
        "ta": "📤 Sending <b>{title}</b>…",
        "en": "📤 Sending <b>{title}</b>…",
    },
    "ytmp3_rate_limit": {
        "ta": (
            "⏳ YouTube download limit! 5 நிமிடத்தில் 3 மட்டுமே download பண்ணலாம். "
            "கொஞ்சம் நேரம் கழிச்சு try பண்ணுங்க."
        ),
        "en": (
            "⏳ Download limit reached! Max 3 downloads per 5 minutes. "
            "Please wait and try again."
        ),
    },

    # ── summarize ─────────────────────────────────────────────────────────────

    "summarize_start": {
        "ta": "🤔 Summarize பண்றேன்…",
        "en": "🤔 Summarizing…",
    },
    "summarize_too_short": {
        "ta": "⚠️ Text too short to summarize (min 50 chars).\nநீண்ட paragraph அனுப்புங்க.",
        "en": "⚠️ Text too short to summarize (minimum 50 characters).\nPlease send a longer paragraph.",
    },
    "summarize_fail": {
        "ta": "😕 Summarize பண்ண முடியல! கொஞ்சம் நேரம் கழிச்சு மீண்டும் try பண்ணுங்க.",
        "en": "😕 Could not summarize. Please try again later.",
    },

    # ── bill history ──────────────────────────────────────────────────────────

    "billhistory_loading": {
        "ta": "📋 Bill history fetch பண்றேன்…",
        "en": "📋 Fetching bill history…",
    },
    "billhistory_no_sheets": {
        "ta": (
            "❌ Bill History feature-க்கு Google Sheets configure செய்யணும்.\n"
            "/setup பார்க்கவும்."
        ),
        "en": (
            "❌ Bill History requires Google Sheets to be configured.\n"
            "See /setup for details."
        ),
    },
    "billhistory_fail": {
        "ta": "😕 Bill history load பண்ண முடியல! மீண்டும் try பண்ணுங்க.",
        "en": "😕 Could not load bill history. Please try again.",
    },
    "billhistory_no_bills": {
        "ta": "இந்த நாளில் bills இல்லை.",
        "en": "No bills found for this date.",
    },

    # ── shop management (/setshop — 8 steps) ─────────────────────────────────

    "setshop_ask_name": {
        "ta": (
            "🏪 <b>Shop Profile Setup</b>\n\n"
            "Step 1/8: உங்க <b>Shop பெயர்</b> என்ன?\n"
            "<i>Example: Sri Narpavi Beauty Parlour</i>\n\n"
            "Cancel பண்ண /cancel அனுப்புங்க."
        ),
        "en": (
            "🏪 <b>Shop Profile Setup</b>\n\n"
            "Step 1/8: What is your <b>shop name</b>?\n"
            "<i>Example: Sri Narpavi Beauty Parlour</i>\n\n"
            "Send /cancel to abort."
        ),
    },
    "setshop_name_invalid": {
        "ta": "❌ Shop பெயர் valid-ஆ இல்ல. குறைந்தது 2 characters இருக்கணும். மீண்டும் try பண்ணுங்க.",
        "en": "❌ Invalid shop name. Must be at least 2 characters. Try again.",
    },
    "setshop_ask_address": {
        "ta": (
            "Step 2/8: <b>Address</b> என்ன?\n"
            "<i>Example: No. 12, Anna Salai, Chennai - 600002</i>\n"
            "Skip பண்ண <code>skip</code> அனுப்புங்க."
        ),
        "en": (
            "Step 2/8: What is the <b>shop address</b>?\n"
            "<i>Example: No. 12, Anna Salai, Chennai - 600002</i>\n"
            "Send <code>skip</code> to skip."
        ),
    },
    "setshop_ask_phone": {
        "ta": (
            "Step 3/8: <b>Phone number</b> என்ன?\n"
            "<i>Example: 9876543210</i>\n"
            "Skip பண்ண <code>skip</code> அனுப்புங்க."
        ),
        "en": (
            "Step 3/8: What is the <b>phone number</b>?\n"
            "<i>Example: 9876543210</i>\n"
            "Send <code>skip</code> to skip."
        ),
    },
    "setshop_ask_gst_pct": {
        "ta": (
            "Step 4/8: Default <b>GST percentage</b> என்ன? (Optional)\n"
            "<i>Example: 18 (for 18%)</i>\n"
            "GST இல்லை என்றால் <code>skip</code> அனுப்புங்க."
        ),
        "en": (
            "Step 4/8: What is the default <b>GST percentage</b>? (Optional)\n"
            "<i>Example: 18 (for 18%)</i>\n"
            "Send <code>skip</code> if no GST."
        ),
    },
    "setshop_ask_discount_pct": {
        "ta": (
            "Step 5/8: Default <b>Discount percentage</b> என்ன? (Optional)\n"
            "<i>Example: 5 (for 5% member discount)</i>\n"
            "Discount இல்லை என்றால் <code>skip</code> அனுப்புங்க."
        ),
        "en": (
            "Step 5/8: What is the default <b>discount percentage</b>? (Optional)\n"
            "<i>Example: 5 (for 5% member discount)</i>\n"
            "Send <code>skip</code> if no default discount."
        ),
    },
    "setshop_ask_gst": {
        "ta": (
            "Step 6/8: <b>GST Registration Number</b> என்ன? (Optional)\n"
            "<i>Example: 33AABCU9603R1ZM</i>\n"
            "Skip பண்ண <code>skip</code> அனுப்புங்க."
        ),
        "en": (
            "Step 6/8: What is your <b>GST registration number</b>? (Optional)\n"
            "<i>Example: 33AABCU9603R1ZM</i>\n"
            "Send <code>skip</code> to skip."
        ),
    },
    "setshop_ask_footer": {
        "ta": (
            "Step 7/8: Invoice-ல் காட்டணும் <b>Footer message</b> என்ன?\n"
            "<i>Example: Thank you for your visit! Please come again.</i>\n"
            "Default பண்ண <code>skip</code> அனுப்புங்க."
        ),
        "en": (
            "Step 7/8: What <b>footer message</b> should appear on invoices?\n"
            "<i>Example: Thank you for your visit! Please come again.</i>\n"
            "Send <code>skip</code> for default."
        ),
    },
    "setshop_ask_logo": {
        "ta": (
            "✅ கிட்டத்தட்ட முடிஞ்சுடுச்சு! (Step 8/8)\n\n"
            "உங்க shop-ஓட <b>Logo photo</b> அனுப்புங்க (optional).\n"
            "Logo வேண்டாம் என்றால் <code>skip</code> அனுப்புங்க."
        ),
        "en": (
            "✅ Almost done! (Step 8/8)\n\n"
            "Send your <b>shop logo</b> as a photo (optional).\n"
            "Send <code>skip</code> if you don't have a logo."
        ),
    },
    "setshop_done": {
        "ta": (
            "✅ <b>{shop}</b> shop profile save ஆச்சு!\n\n"
            "இனி service voice note அனுப்பும்போது இந்த profile use ஆகும்.\n"
            "📋 /listshops — உங்க shops பார்க்க\n"
            "🏪 /setshop — புதுசா shop add பண்ண"
        ),
        "en": (
            "✅ Shop profile <b>{shop}</b> saved!\n\n"
            "This profile will be used for service invoices.\n"
            "📋 /listshops — view your shops\n"
            "🏪 /setshop — add another shop"
        ),
    },
    "setshop_cancelled": {
        "ta": "❌ Shop setup cancel ஆச்சு.",
        "en": "❌ Shop setup cancelled.",
    },
    "listshops_empty": {
        "ta": (
            "🏪 Shop profiles இல்லை!\n\n"
            "<code>/setshop</code> command use பண்ணி உங்க shop profile create பண்ணுங்க."
        ),
        "en": (
            "🏪 No shop profiles found!\n\n"
            "Use <code>/setshop</code> to create your shop profile."
        ),
    },
    "listshops_header": {
        "ta": "🏪 <b>உங்க Shops:</b>\n",
        "en": "🏪 <b>Your Shops:</b>\n",
    },
    "shop_default_set": {
        "ta": "⭐ <b>{shop}</b> default shop-ஆ set ஆச்சு!",
        "en": "⭐ <b>{shop}</b> is now your default shop!",
    },
    "shop_select_prompt": {
        "ta": (
            "🏪 உங்களுக்கு multiple shops இருக்கு.\n"
            "இந்த service bill-க்கு எந்த shop use பண்ணணும்?"
        ),
        "en": (
            "🏪 You have multiple shop profiles.\n"
            "Which shop should be used for this service bill?"
        ),
    },
    "shop_bill_expired": {
        "ta": "❌ Bill data expire ஆச்சு. மீண்டும் voice note அனுப்புங்க.",
        "en": "❌ Bill data expired. Please resend your voice note.",
    },

    # ── /servicebill manual command ───────────────────────────────────────────

    "servicebill_start": {
        "ta": (
            "🧾 <b>Service Bill Generator</b>\n\n"
            "Step-by-step invoice உருவாக்குவோம்.\n"
            "எந்த step-லயும் /skip அனுப்பலாம். Cancel-க்கு /cancel."
        ),
        "en": (
            "🧾 <b>Service Bill Generator</b>\n\n"
            "Let's create your invoice step by step.\n"
            "Send /skip for any step. /cancel to abort."
        ),
    },
    "servicebill_no_shop": {
        "ta": (
            "⚠️ Shop profile இல்லை!\n\n"
            "<code>/setshop</code> command use பண்ணி shop create பண்ணுங்க.\n"
            "அல்லது default shop name use ஆகும்."
        ),
        "en": (
            "⚠️ No shop profile found!\n\n"
            "Use <code>/setshop</code> to create a shop profile.\n"
            "A default shop name will be used for now."
        ),
    },
    "servicebill_ask_customer": {
        "ta": (
            "Step 1/5: <b>Customer பெயரும் Mobile-உம்</b> சொல்லுங்க.\n"
            "<i>Example: Ramesh 9876543210</i>\n"
            "Skip: <code>/skip</code>"
        ),
        "en": (
            "Step 1/5: Enter <b>customer name and mobile</b>.\n"
            "<i>Example: Ramesh 9876543210</i>\n"
            "Send <code>/skip</code> to skip."
        ),
    },
    "servicebill_ask_services": {
        "ta": (
            "Step 2/5: <b>Services மற்றும் rates</b> சொல்லுங்க.\n"
            "<i>Example: Haircut 200, Facial 500, Waxing 300</i>\n"
            "Skip: <code>/skip</code>"
        ),
        "en": (
            "Step 2/5: Enter <b>services and their rates</b>.\n"
            "<i>Example: Haircut 200, Facial 500, Waxing 300</i>\n"
            "Send <code>/skip</code> to skip."
        ),
    },
    "servicebill_ask_discount": {
        "ta": (
            "Step 3/5: <b>Discount</b> இருக்கா?\n"
            "<i>Amount: 100 | Percentage: 10%</i>\n"
            "Discount இல்லை என்றால் <code>/skip</code>."
        ),
        "en": (
            "Step 3/5: Any <b>discount</b>?\n"
            "<i>Amount: 100 | Percentage: 10%</i>\n"
            "Send <code>/skip</code> if no discount."
        ),
    },
    "servicebill_ask_gst": {
        "ta": (
            "Step 4/5: <b>GST percentage</b> என்ன?\n"
            "<i>Example: 18 (for 18%)</i>\n"
            "GST இல்லை என்றால் <code>/skip</code>."
        ),
        "en": (
            "Step 4/5: What is the <b>GST percentage</b>?\n"
            "<i>Example: 18 (for 18%)</i>\n"
            "Send <code>/skip</code> if no GST."
        ),
    },
    "servicebill_ask_advance": {
        "ta": (
            "Step 5/5: <b>Advance</b> எவ்வளவு கட்டினாங்க?\n"
            "<i>Example: 500</i>\n"
            "Advance இல்லை என்றால் <code>/skip</code>."
        ),
        "en": (
            "Step 5/5: How much <b>advance</b> was paid?\n"
            "<i>Example: 500</i>\n"
            "Send <code>/skip</code> if no advance."
        ),
    },
    "servicebill_generating": {
        "ta": "📄 Invoice PDF தயாரிக்கிறேன்…",
        "en": "📄 Generating invoice PDF…",
    },
    "servicebill_no_items": {
        "ta": (
            "❌ Services parse ஆகவில்லை.\n\n"
            "Format: <i>Service name Rate</i>\n"
            "Example: <i>Haircut 200, Facial 500</i>"
        ),
        "en": (
            "❌ Could not parse services.\n\n"
            "Format: <i>Service name Rate</i>\n"
            "Example: <i>Haircut 200, Facial 500</i>"
        ),
    },
    "servicebill_done": {
        "ta": (
            "✅ <b>{shop}</b> Invoice!\n"
            "Roll No: <b>{roll}</b>\n"
            "Net Amount: &#8377; {net:.2f}"
        ),
        "en": (
            "✅ <b>{shop}</b> Invoice!\n"
            "Roll No: <b>{roll}</b>\n"
            "Net Amount: &#8377; {net:.2f}"
        ),
    },
    "servicebill_cancelled": {
        "ta": "❌ Service bill cancel ஆச்சு.",
        "en": "❌ Service bill generation cancelled.",
    },
}


def m(key: str, lang: str = "ta", **kwargs) -> str:
    """Return the message for *key* in *lang*, with optional format substitutions.

    Falls back to 'ta' if *lang* variant is missing.
    Falls back to key name if key is not found (prevents crashes).
    """
    entry = _T.get(key, {})
    text = entry.get(lang) or entry.get("ta") or f"[msg:{key}]"
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, ValueError):
            pass
    return text
