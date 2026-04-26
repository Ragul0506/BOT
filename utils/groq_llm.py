"""Groq LLM – all inference helpers (bill parsing, intent classification,
expense extraction, summarization)."""
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


# ── bill parsing (Feature 1, unchanged) ──────────────────────────────────────

_BILL_SYSTEM = """\
You are a billing assistant that parses shopping-list text into structured JSON.
The input may be in Tamil, English, or Tanglish (Tamil words in English letters).

OUTPUT RULES — follow exactly:
1. Output ONLY a valid JSON array. No explanation, no markdown fences, no extra text.
2. Each element must have exactly three fields:
   - "item"  : product name in English (string)
   - "qty"   : quantity as a plain number (integer or decimal, no units)
   - "rate"  : price per unit in rupees as a plain number

Common Tamil/Tanglish unit words to ignore (strip from qty):
  kg, kilo, litre, ltr, ml, gram, pack, packs, packet, packets, piece, pieces,
  nos, number, bottle, bottles, box, boxes

Example input : "2 kg sugar 80 rupees, 1 litre oil 160 rupees, 3 pack biscuit 90"
Example output: [{"item":"Sugar","qty":2,"rate":80},{"item":"Oil","qty":1,"rate":160},{"item":"Biscuit","qty":3,"rate":90}]
"""


async def parse_items(transcript: str) -> list[dict]:
    """Return list of {'item', 'qty', 'rate'} from a shopping transcript."""
    raw = await groq_complete(
        _BILL_SYSTEM,
        f"Parse this shopping list:\n{wrap_user_input(transcript)}",
        temperature=0.1,
    )
    logger.info("parse_items raw: %s", raw[:200])
    result = _extract_json_array(raw)
    return [
        {
            "item": str(i.get("item", "Unknown")),
            "qty": float(i.get("qty", 1)),
            "rate": float(i.get("rate", 0)),
        }
        for i in result
    ]


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
