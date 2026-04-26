"""Groq LLM – all inference helpers (bill parsing, intent classification,
expense extraction, summarization, language detection, bill type classification)."""
from __future__ import annotations

import json
import logging
import re
from datetime import date as _date, timedelta
from typing import Literal

from groq import AsyncGroq
import os

from utils.security import wrap_user_input

logger = logging.getLogger(__name__)

GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

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
    model: str = "",
    temperature: float = 0.3,
    max_tokens: int = 1024,
) -> str:
    """Single-turn LLM call; returns the assistant content string."""
    client = _get_client()
    resp = await client.chat.completions.create(
        model=model or GROQ_MODEL,
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
You are a strict billing assistant that parses shopping-list and service-receipt transcripts into structured JSON.
The input may be in Tamil (Unicode), English, or Tanglish (Tamil words spelled in English letters).

═══ PARSING CONTRACT ═══
Extract ALL items/services that have an identifiable NAME and a PRICE.
  • Physical goods (rice, oil, vegetables, etc.): require explicit quantity.
  • Services (haircut, beauty, tailoring, repair, etc.): default qty=1 if not stated.

If transcript has NO parseable items/services → return EXACTLY this object:
  {"error":"no_valid_items","reason":"<one short sentence>"}

═══ OUTPUT FORMAT ═══
Output ONLY a valid JSON array. No markdown fences, no explanation, no extra text.
Each element must have exactly three fields:
  - "item"  : name translated to English, Title Case
  - "qty"   : quantity as a plain number (integer or decimal, NO units here)
  - "rate"  : price per unit in rupees as a plain number (NO currency symbols)

═══ SERVICE HANDLING ═══
Services: haircut, shave, facial, waxing, threading, manicure, pedicure,
          spa, massage, tailoring, stitching, dyeing, dry cleaning, repair,
          eyebrows, cleanup, bleach, hair color, mehendi, pedicure, laundry, alteration
  • Name + price only (no qty) → set qty=1
  • "Haircut 200" → {"item":"Haircut","qty":1,"rate":200}
  • "facial 500, waxing 300" → [{"item":"Facial","qty":1,"rate":500},{"item":"Waxing","qty":1,"rate":300}]
  • "blouse stitching 150" → {"item":"Blouse Stitching","qty":1,"rate":150}

═══ VALIDATION ═══
  • qty > 1000 → skip item
  • item name empty, single character, or unrecognisable punctuation → skip
  • rate looks like a phone number, date, or PIN (>9999 and not a plausible price) → skip

═══ UNIT WORDS TO STRIP from qty field ═══
  kg, kilo, kilogram, litre, ltr, ml, gram, g, pack, packs, packet, packets,
  piece, pieces, nos, number, bottle, bottles, box, boxes, dozen, set, bundle,
  கிலோ, லிட்டர், கிராம், பாக்கெட், பாட்டில், டஜன்

═══ TANGLISH → ENGLISH ═══
  arisi/அரிசி→Rice       paruppu/பருப்பு→Dal      thakkali/தக்காளி→Tomato
  vengayam/வெங்காயம்→Onion  poondu/பூண்டு→Garlic    inji/இஞ்சி→Ginger
  karuveppilai→Curry Leaves  kottamalli→Coriander   milagai→Chilli
  milagu→Pepper  jeeragam→Cumin  manja→Turmeric  uppu→Salt  rava→Semolina
  oil/ennai/எண்ணெய்→Oil  paal/பால்→Milk  thayir/தயிர்→Curd
  sakkarai→Sugar  muttai→Egg  kozhi→Chicken  meen→Fish
  thengai→Coconut  urulai→Potato  vazhai→Banana  keerai→Greens
  Salon/Tanglish: kutty cut/hair cut→Hair Cut  dadhi/shave→Shave
    facial→Facial  waxing→Waxing  threading→Threading  eyebrow→Eyebrow
  Tailoring: stitching/stich→Stitching  blouse→Blouse

PRICE WORDS: rupees, rupe, rs, ரூபாய், ரூ, ₹, /-, per
BRAND NAMES: Keep brand abbreviations as-is (RR, MDH, Aachi, Tata, Amul, etc.)

═══ FEW-SHOT EXAMPLES ═══

Example 1 — Grocery Tanglish:
Input:  "2 kg arisi 80 rupees, 1 litre oil 160, 3 pack biscuit 90"
Output: [{"item":"Rice","qty":2,"rate":80},{"item":"Oil","qty":1,"rate":160},{"item":"Biscuit","qty":3,"rate":90}]

Example 2 — Salon services (no qty given):
Input:  "Haircut 200, shave 100"
Output: [{"item":"Haircut","qty":1,"rate":200},{"item":"Shave","qty":1,"rate":100}]

Example 3 — Beauty parlour mixed:
Input:  "facial 500, waxing 300, threading 50, eyebrows 30"
Output: [{"item":"Facial","qty":1,"rate":500},{"item":"Waxing","qty":1,"rate":300},{"item":"Threading","qty":1,"rate":50},{"item":"Eyebrows","qty":1,"rate":30}]

Example 4 — Tailoring services:
Input:  "blouse stitching 150, saree fall 50"
Output: [{"item":"Blouse Stitching","qty":1,"rate":150},{"item":"Saree Fall","qty":1,"rate":50}]

Example 5 — Tanglish salon (voice):
Input:  "hair cut panninaanga 200 rubaai, eyebrows 50 rupe"
Output: [{"item":"Hair Cut","qty":1,"rate":200},{"item":"Eyebrows","qty":1,"rate":50}]

Example 6 — Tamil Unicode grocery:
Input:  "2 கிலோ வெங்காயம் 40, 1 லிட்டர் பால் 56 ரூபாய்"
Output: [{"item":"Onion","qty":2,"rate":40},{"item":"Milk","qty":1,"rate":56}]

Example 7 — Word quantities:
Input:  "half kg sugar 40, one dozen eggs 90"
Output: [{"item":"Sugar","qty":0.5,"rate":40},{"item":"Egg","qty":12,"rate":90}]

Example 8 — Some items lack price → skip those:
Input:  "1 kg tomato 30 rupees, vengayam veggies, 2 litre oil 280 rupees"
Output: [{"item":"Tomato","qty":1,"rate":30},{"item":"Oil","qty":2,"rate":280}]

Example 9 — Lump-sum expense → error:
Input:  "I spent 500 on groceries yesterday"
Output: {"error":"no_valid_items","reason":"Lump-sum expense without itemised prices"}

Example 10 — Shopping to-do list, no prices → error:
Input:  "வெங்காயம் வாங்கணும், தக்காளி வாங்கணும்"
Output: {"error":"no_valid_items","reason":"Shopping reminder list with no quantities or prices"}
"""

_MAX_VALID_QTY = 1000


async def parse_items(transcript: str) -> list[dict]:
    """Return list of {'item', 'qty', 'rate'} dicts parsed from a shopping/service transcript.

    Raises ValueError when the transcript contains no parseable bill items.
    """
    raw = await groq_complete(
        _BILL_SYSTEM,
        f"Parse this bill/service list:\n{wrap_user_input(transcript)}",
        temperature=0.1,
        max_tokens=1500,
    )
    logger.info("parse_items raw: %s", raw[:300])

    cleaned = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
    if cleaned.startswith("{"):
        try:
            err_obj = json.loads(cleaned)
            if err_obj.get("error") == "no_valid_items":
                reason = err_obj.get("reason", "no valid items found")
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
    """Return 'ta' if text contains significant Tamil Unicode, else 'en'."""
    tamil_chars = sum(1 for c in text if "஀" <= c <= "௿")
    alpha_chars = sum(1 for c in text if c.isalpha())
    if alpha_chars == 0:
        return "ta"
    return "ta" if (tamil_chars / alpha_chars) >= 0.10 else "en"


# ── voice intent classification ───────────────────────────────────────────────

_INTENT_SYSTEM = """\
Classify the user's speech into exactly one category:
- "bill"    : listing items to buy/bought with quantities AND prices (grocery bill, shopping list, service receipt)
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


# ── bill type classification ──────────────────────────────────────────────────

_BILL_TYPE_SYSTEM = """\
Classify the following bill/receipt text as exactly one type:
- "grocery"  : contains food items, vegetables, fruits, household groceries, kirana items, supermarket goods,
               spices, rice, dal, oil, milk, eggs, chicken, fish, snacks, beverages
- "service"  : contains services like haircut, beauty parlour, salon, facial, waxing, threading, eyebrows,
               spa, massage, tailoring, stitching, dry cleaning, repair, laundry, dyeing, alteration,
               manicure, pedicure, mehendi, hair color, bleach, cleanup
- "other"    : does not clearly fit grocery or service (electronics, medicines, clothing purchase, etc.)

Output ONLY one word: grocery, service, or other. No explanation, no punctuation."""


async def classify_bill_type(text: str) -> Literal["grocery", "service", "other"]:
    """Returns 'grocery', 'service', or 'other' for a given bill/receipt text."""
    raw = await groq_complete(
        _BILL_TYPE_SYSTEM,
        wrap_user_input(text, max_len=500),
        temperature=0.0,
        max_tokens=5,
    )
    word = raw.strip().lower().split()[0] if raw.strip() else "other"
    return word if word in ("grocery", "service") else "other"  # type: ignore[return-value]


# ── expense parsing ───────────────────────────────────────────────────────────

_EXPENSE_SYSTEM_TPL = """\
You are an expense tracker. Extract ALL expense entries from the input text.
Today is {today}. Yesterday was {yesterday}. Use these exact dates in output.

OUTPUT RULES:
1. Output ONLY a valid JSON array. No markdown fences, no extra text.
2. Each element must have exactly four fields:
   - "date"     : YYYY-MM-DD format (use today or yesterday dates above)
   - "amount"   : numeric amount in rupees (no currency symbols)
   - "category" : one of: food, fuel, transport, medical, utilities, grocery, clothing, entertainment, personal, family, general
   - "note"     : short 1-5 word description in English

CATEGORY MAPPING (use the most specific match):
  food        : tea, coffee, chai, snack, lunch, dinner, restaurant, hotel, tiffin, mess, biryani, sweets, bakery
  fuel        : petrol, diesel, fuel, gas, bunk, filling
  transport   : bus, auto, cab, uber, ola, train, flight, metro, ticket, fare
  medical     : medicine, hospital, doctor, pharmacy, clinic, medical, health, treatment, tablet
  utilities   : electricity, water, internet, mobile, phone, recharge, bill, wifi, broadband
  grocery     : vegetable, rice, dal, grocery, supermarket, kirana, market, shopping, provisions, fruits
  clothing    : dress, saree, shirt, pant, clothes, kurta, jeans, blouse, fabric, footwear, shoes, sandal, leggings, churidar
  entertainment: movie, cinema, game, concert, fun, outing, park, theatre, amusement
  personal    : girlfriend, boyfriend, wife, husband, friend, self, beauty, salon, haircut, cosmetics, gift (for non-family)
  family      : mother, father, mom, dad, amma, appa, parents, brother, sister, son, daughter, child, kids, home, family
  general     : everything else

PATTERN RECOGNITION:
  "AMOUNT for ITEM"       → ITEM is the note, map to best category
  "spent AMOUNT on X"     → X is the note, map to best category
  "ITEM AMOUNT"           → ITEM is note, AMOUNT is rupees
  "AMOUNT for PERSON"     → girlfriend/friend/self → personal; mother/father/family → family
  Multiple items in one phrase → extract EACH as a separate entry

═══ FEW-SHOT EXAMPLES ═══

Example 1:
Input:  "today chai 30 petrol 500"
Output: [{{"date":"{today}","amount":30,"category":"food","note":"chai"}},{{"date":"{today}","amount":500,"category":"fuel","note":"petrol"}}]

Example 2 — "AMOUNT for CATEGORY" pattern:
Input:  "today spent dress 2000 5000 for medical 2500 for girlfriend 10000 for mother"
Output: [
  {{"date":"{today}","amount":2000,"category":"clothing","note":"dress"}},
  {{"date":"{today}","amount":5000,"category":"medical","note":"medical"}},
  {{"date":"{today}","amount":2500,"category":"personal","note":"girlfriend"}},
  {{"date":"{today}","amount":10000,"category":"family","note":"mother"}}
]

Example 3 — Mixed dates:
Input:  "yesterday medicine 200, today lunch 120 and bus 40"
Output: [
  {{"date":"{yesterday}","amount":200,"category":"medical","note":"medicine"}},
  {{"date":"{today}","amount":120,"category":"food","note":"lunch"}},
  {{"date":"{today}","amount":40,"category":"transport","note":"bus"}}
]

Example 4 — Relationship expenses:
Input:  "500 for wife, 200 for friend, 1000 for father"
Output: [
  {{"date":"{today}","amount":500,"category":"personal","note":"wife"}},
  {{"date":"{today}","amount":200,"category":"personal","note":"friend"}},
  {{"date":"{today}","amount":1000,"category":"family","note":"father"}}
]

Example 5 — Tanglish:
Input:  "today petrol 400, lunch 80 rupees, mobile recharge 199"
Output: [
  {{"date":"{today}","amount":400,"category":"fuel","note":"petrol"}},
  {{"date":"{today}","amount":80,"category":"food","note":"lunch"}},
  {{"date":"{today}","amount":199,"category":"utilities","note":"mobile recharge"}}
]
"""


async def parse_expenses(text: str, today: str = "") -> list[dict]:
    """Return list of {'date', 'amount', 'category', 'note'} expense dicts."""
    today = today or str(_date.today())
    yesterday = str(_date.fromisoformat(today) - timedelta(days=1))
    raw = await groq_complete(
        _EXPENSE_SYSTEM_TPL.format(today=today, yesterday=yesterday),
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
