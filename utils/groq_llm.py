"""Groq LLM – all inference helpers (bill parsing, intent classification,
expense extraction, summarization, language detection)."""
from __future__ import annotations

import json
import logging
import re
from datetime import date as _date
from typing import Literal

from groq import AsyncGroq
import os

from utils.security import wrap_user_input

logger = logging.getLogger(__name__)

_client: AsyncGroq | None = None


def _get_client() -> AsyncGroq:
    global _client
    if _client is None:
        _client = AsyncGroq(api_key=os.environ["GROQ_API_KEY"])
    return _client


# ── low-level wrapper ─────────────────────────────────────────────────────────


async def groq_complete(
    system: str,
    user: str,
    *,
    model: str = "llama3-8b-8192",
    temperature: float = 0.3,
    max_tokens: int = 1024,
) -> str:
    """Single-turn LLM call; returns the assistant content string."""
    client = _get_client()
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content.strip()


# ── JSON helpers ──────────────────────────────────────────────────────────────


def _extract_json_array(raw: str) -> list[dict]:
    """Best-effort JSON array extraction from arbitrary LLM output."""
    cleaned = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
    match = re.search(r"\[[\s\S]*\]", cleaned)
    if not match:
        logger.warning("No JSON array in LLM response: %s", raw[:200])
        return []
    try:
        items = json.loads(match.group())
        return [i for i in items if isinstance(i, dict)]
    except json.JSONDecodeError as exc:
        logger.error("JSON decode error: %s | raw: %s", exc, raw[:200])
        return []


# ── bill parsing ──────────────────────────────────────────────────────────────

_BILL_SYSTEM = """\
You are a strict billing assistant that parses shopping-list transcripts into structured JSON.
The input may be in Tamil (Unicode), English, or Tanglish (Tamil words spelled in English letters).

═══ STRICT PARSING CONTRACT ═══
Only extract items that have ALL THREE of the following EXPLICITLY stated:
  1. An identifiable ITEM NAME
  2. A clear QUANTITY (number + optional unit)
  3. A clear PRICE (a number in rupees)

If ANY of the three is missing or ambiguous for an item → SKIP that item. Do NOT guess or fill in defaults.

If the transcript contains NO items that satisfy all three conditions (e.g., it is a conversation,
a to-do list, an expense summary, or simply has no prices) → return EXACTLY this object and nothing else:
  {"error":"no_valid_items","reason":"<one short sentence explaining why>"}

═══ OUTPUT FORMAT (when valid items are found) ═══
Output ONLY a valid JSON array. No markdown fences, no explanation, no extra text.
Each element must have exactly three fields:
  - "item"  : product name translated to English (string, Title Case)
  - "qty"   : quantity as a plain number (integer or decimal, NO units in this field)
  - "rate"  : price per unit in rupees as a plain number (NO currency symbols)

═══ VALIDATION — reject these silently ═══
  • qty > 1000               → nonsensical quantity, skip the item entirely
  • item name is empty, a single character, or unrecognisable punctuation → skip
  • rate looks like a phone number, date, or PIN (>9999 and not a plausible price) → skip

═══ UNIT WORDS TO STRIP from qty ═══
  kg, kilo, kilogram, litre, ltr, ml, gram, g, pack, packs, packet, packets,
  piece, pieces, nos, number, bottle, bottles, box, boxes, dozen, set, bundle,
  கிலோ, லிட்டர், கிராம், பாக்கெட், பாட்டில், டஜன்

═══ TANGLISH → ENGLISH ═══
  arisi / அரிசி → Rice               paruppu / பருப்பு → Dal
  thakkali / தக்காளி → Tomato        vengayam / வெங்காயம் → Onion
  poondu / பூண்டு → Garlic           inji / இஞ்சி → Ginger
  karuveppilai / கறிவேப்பிலை → Curry Leaves
  kottamalli / கொத்தமல்லி → Coriander
  milagai / மிளகாய் → Chilli         milagu / மிளகு → Pepper
  jeeragam / சீரகம் → Cumin          manja / மஞ்சள் → Turmeric
  uppu / உப்பு → Salt                rava / ரவை → Semolina
  maida / sennai → Maida             oil / ennai / எண்ணெய் → Oil
  paal / பால் → Milk                 thayir / தயிர் → Curd
  sakkarai / சக்கரை → Sugar          muttai / முட்டை → Egg
  kozhi / கோழி → Chicken             meen / மீன் → Fish
  thengai / தெங்காய் → Coconut       urulai / உருளைக்கிழங்கு → Potato
  vazhai / வாழை → Banana             keerai / கீரை → Greens

PRICE WORDS: rupees, rupe, rs, ரூபாய், ரூ, ₹, /-, per
BRAND NAMES: Keep recognisable brand abbreviations as-is (RR, MDH, Aachi, Tata, Amul, etc.)

═══ FEW-SHOT EXAMPLES ═══

Example 1 — Tanglish with units:
Input:  "2 kg arisi 80 rupees, 1 litre oil 160 rupees, 3 pack biscuit 90"
Output: [{"item":"Rice","qty":2,"rate":80},{"item":"Oil","qty":1,"rate":160},{"item":"Biscuit","qty":3,"rate":90}]

Example 2 — Tamil Unicode:
Input:  "2 கிலோ வெங்காயம் 40, அரை கிலோ தக்காளி 25, 1 லிட்டர் பால் 56 ரூபாய்"
Output: [{"item":"Onion","qty":2,"rate":40},{"item":"Tomato","qty":0.5,"rate":25},{"item":"Milk","qty":1,"rate":56}]

Example 3 — Tamil/English mixed with brand name:
Input:  "2 சதங்கள் ஆர்ஆர் மசாலா 144, 500 gram paruppu 65 rupees, 1 packet Aachi sambar 45"
Output: [{"item":"RR Masala","qty":2,"rate":144},{"item":"Dal","qty":500,"rate":65},{"item":"Aachi Sambar Powder","qty":1,"rate":45}]

Example 4 — Word quantities:
Input:  "half kg sugar 40 rupees, one dozen eggs 90, 2 bottles coconut oil 250 each"
Output: [{"item":"Sugar","qty":0.5,"rate":40},{"item":"Egg","qty":12,"rate":90},{"item":"Coconut Oil","qty":2,"rate":250}]

Example 5 — Tanglish voice note:
Input:  "rendu kilo arisi 80 le, onnu litre paal 56, moonnu packet biscuit 30 rubaa"
Output: [{"item":"Rice","qty":2,"rate":80},{"item":"Milk","qty":1,"rate":56},{"item":"Biscuit","qty":3,"rate":30}]

Example 6 — Tamil/English mixed, some items lack price → skip those:
Input:  "1 kg tomato 30 rupees, vengayam veggies, 2 litre oil 280 rupees"
Output: [{"item":"Tomato","qty":1,"rate":30},{"item":"Oil","qty":2,"rate":280}]

Example 7 — Expense summary, no per-item prices → error:
Input:  "I spent 500 on groceries yesterday at the market"
Output: {"error":"no_valid_items","reason":"Input is a lump-sum expense, not an itemised bill with quantities and prices"}

Example 8 — Tamil shopping to-do list, no prices → error:
Input:  "வெங்காயம் வாங்கணும், தக்காளி வாங்கணும், பால் வாங்கணும்"
Output: {"error":"no_valid_items","reason":"Shopping reminder list with no quantities or prices"}

Example 9 — Nonsensical qty filtered out:
Input:  "2 kg arisi 60 rupees, 1500 packets salt 10 rupees, 3 litre oil 300"
Output: [{"item":"Rice","qty":2,"rate":60},{"item":"Oil","qty":3,"rate":300}]
"""

_MAX_VALID_QTY = 1000


async def parse_items(transcript: str) -> list[dict]:
    """Return list of {'item', 'qty', 'rate'} dicts parsed from a shopping transcript.

    Raises ValueError when the transcript contains no parseable bill items.
    """
    raw = await groq_complete(
        _BILL_SYSTEM,
        f"Parse this shopping list:\n{wrap_user_input(transcript)}",
        temperature=0.1,
        max_tokens=1500,
    )
    logger.info("parse_items raw: %s", raw[:300])

    # Detect explicit error object returned by the LLM
    cleaned = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
    if cleaned.startswith("{"):
        try:
            err_obj = json.loads(cleaned)
            if err_obj.get("error") == "no_valid_items":
                reason = err_obj.get("reason", "no valid bill items found")
                logger.warning("parse_items: LLM signalled no_valid_items — %s", reason)
                raise ValueError(f"No valid bill items: {reason}")
        except json.JSONDecodeError:
            pass

    result = _extract_json_array(raw)

    validated: list[dict] = []
    for i in result:
        item_name = str(i.get("item", "")).strip()
        if not item_name or item_name.lower() in ("unknown", ""):
            logger.debug("parse_items: skipping item with empty/unknown name")
            continue
        try:
            qty = float(i.get("qty", 1))
            rate = float(i.get("rate", 0))
        except (TypeError, ValueError):
            logger.debug("parse_items: skipping %r — non-numeric qty/rate", item_name)
            continue
        if qty > _MAX_VALID_QTY:
            logger.warning("parse_items: skipping %r — qty %.0f exceeds %d", item_name, qty, _MAX_VALID_QTY)
            continue
        validated.append({"item": item_name, "qty": qty, "rate": rate})

    if not validated:
        raise ValueError("No valid bill items could be parsed from the transcript")

    return validated


# ── language detection (script-based, no extra API call) ─────────────────────


def detect_transcript_language(text: str) -> str:
    """Return 'ta' if text contains significant Tamil Unicode, else 'en'.

    Tamil Unicode block: U+0B80–U+0BFF.
    If ≥10 % of alphabetic characters are Tamil script → language is Tamil.
    Tanglish (Tamil words in English letters) defaults to 'ta' because
    Whisper usually emits Tamil Unicode for Tamil speech.
    """
    tamil_chars = sum(1 for c in text if "஀" <= c <= "௿")
    alpha_chars = sum(1 for c in text if c.isalpha())
    if alpha_chars == 0:
        return "ta"
    return "ta" if (tamil_chars / alpha_chars) >= 0.10 else "en"


# ── voice intent classification ───────────────────────────────────────────────

_INTENT_SYSTEM = """\
Classify the user's speech into exactly one category:
- "bill"    : listing items to buy/bought with quantities AND prices (grocery bill, shopping list)
- "expense" : reporting money spent on services/activities (fuel, food, travel, utilities, chai)
- "other"   : does not fit the above two

Output ONLY one word: bill, expense, or other. No punctuation, no explanation."""


async def classify_voice_intent(text: str) -> Literal["bill", "expense", "other"]:
    """Returns 'bill', 'expense', or 'other'."""
    raw = await groq_complete(
        _INTENT_SYSTEM, wrap_user_input(text, max_len=500), temperature=0.0, max_tokens=5
    )
    word = raw.strip().lower().split()[0] if raw.strip() else "other"
    return word if word in ("bill", "expense") else "other"  # type: ignore[return-value]


# ── expense parsing ───────────────────────────────────────────────────────────

_EXPENSE_SYSTEM_TPL = """\
You are an expense tracker. Extract all expense entries from the input text.
Today's date is {today}. Use today's date if no date is mentioned.

OUTPUT RULES:
1. Output ONLY a valid JSON array. No markdown fences, no extra text.
2. Each element must have exactly four fields:
   - "date"     : YYYY-MM-DD format
   - "amount"   : numeric amount in rupees (no currency symbols)
   - "category" : one of: food, fuel, transport, medical, utilities, grocery, clothing, entertainment, general
   - "note"     : short 1–5 word description

Category hints:
  tea/coffee/chai/snack/lunch/dinner/restaurant → food
  petrol/diesel/fuel/gas → fuel
  bus/auto/cab/uber/ola/train/flight → transport
  medicine/hospital/doctor/pharmacy → medical
  electricity/water/internet/mobile/phone/recharge → utilities
  vegetable/rice/dal/grocery/supermarket/kirana → grocery

Example output: [{{"date":"2024-01-15","amount":200,"category":"food","note":"chai and snacks"}}]
"""


async def parse_expenses(text: str, today: str = "") -> list[dict]:
    """Return list of {'date', 'amount', 'category', 'note'} expense dicts."""
    today = today or str(_date.today())
    raw = await groq_complete(
        _EXPENSE_SYSTEM_TPL.format(today=today),
        f"Extract expenses:\n{wrap_user_input(text)}",
        temperature=0.1,
        max_tokens=1024,
    )
    logger.info("parse_expenses raw: %s", raw[:300])
    result = _extract_json_array(raw)
    validated = []
    for item in result:
        try:
            validated.append(
                {
                    "date": str(item.get("date", today)),
                    "amount": float(item.get("amount", 0)),
                    "category": str(item.get("category", "general")),
                    "note": str(item.get("note", "")),
                }
            )
        except (TypeError, ValueError):
            continue
    return validated


# ── text summarizer ───────────────────────────────────────────────────────────

_SUMMARIZE_SYSTEM = """\
You are a concise summarizer. Summarize the given text into 3–5 crisp bullet points.
Write in the same language as the input (Tamil, English, or mixed Tanglish).
Use • as the bullet character. Be direct. No preamble, no conclusion sentence."""


async def summarize_text(text: str) -> str:
    """Summarize text into 3–5 bullet points."""
    return await groq_complete(
        _SUMMARIZE_SYSTEM,
        f"Summarize:\n{wrap_user_input(text, max_len=4000)}",
        temperature=0.3,
        max_tokens=512,
    )
