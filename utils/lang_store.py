"""User language-preference store — in-memory cache backed by SQLite.

Supported values:
  'ta' — Tanglish (default): Tamil ideas, English script
  'en' — English replies
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

_LANG_DB = Path("/tmp/lang_prefs.db")
_cache: dict[int, str] = {}

SUPPORTED_LANGS = {"ta", "en"}
DEFAULT_LANG = "ta"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(_LANG_DB))
    c.execute(
        "CREATE TABLE IF NOT EXISTS lang_prefs "
        "(user_id INTEGER PRIMARY KEY, lang TEXT NOT NULL)"
    )
    c.commit()
    return c


def _sync_get(uid: int) -> str:
    try:
        conn = _conn()
        row = conn.execute(
            "SELECT lang FROM lang_prefs WHERE user_id=?", (uid,)
        ).fetchone()
        conn.close()
        return row[0] if row else DEFAULT_LANG
    except Exception as exc:
        logger.warning("lang_store get error: %s", exc)
        return DEFAULT_LANG


def _sync_set(uid: int, lang: str) -> None:
    try:
        conn = _conn()
        conn.execute(
            "INSERT OR REPLACE INTO lang_prefs (user_id, lang) VALUES (?,?)",
            (uid, lang),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.warning("lang_store set error: %s", exc)


async def get_user_lang(user_id: int) -> str:
    """Return user's language pref: 'ta' (Tanglish/default) or 'en' (English)."""
    if user_id in _cache:
        return _cache[user_id]
    loop = asyncio.get_running_loop()
    lang = await loop.run_in_executor(None, _sync_get, user_id)
    _cache[user_id] = lang
    return lang


async def set_user_lang(user_id: int, lang: str) -> None:
    """Persist user's language preference."""
    if lang not in SUPPORTED_LANGS:
        lang = DEFAULT_LANG
    _cache[user_id] = lang
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _sync_set, user_id, lang)
