"""Watchlist storage — Supabase (preferred) with automatic SQLite fallback.

Supabase setup:
  1. Create a project at supabase.com (free tier).
  2. Run in SQL editor:
       CREATE TABLE watchlist (
           id        BIGSERIAL PRIMARY KEY,
           user_id   TEXT        NOT NULL,
           movie_id  INTEGER     NOT NULL,
           title     TEXT        NOT NULL,
           poster_url TEXT,
           added_at  TIMESTAMPTZ DEFAULT NOW(),
           UNIQUE (user_id, movie_id)
       );
  3. Set env vars: SUPABASE_URL and SUPABASE_KEY (anon/service-role key).

SQLite fallback:
  When Supabase is not configured the bot stores watchlist in data/watchlist.db.
  NOTE: Render free tier has an ephemeral filesystem — data is lost on restart.
  Use Supabase for real persistence.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).parent.parent / "data" / "watchlist.db"


def _use_supabase() -> bool:
    return bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY"))


# ── Supabase layer ────────────────────────────────────────────────────────────


def _sb_client():
    from supabase import create_client  # type: ignore[import]
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])


def _sync_sb_add(user_id: str, movie_id: int, title: str, poster_url: str | None) -> None:
    sb = _sb_client()
    sb.table("watchlist").upsert(
        {
            "user_id": user_id,
            "movie_id": movie_id,
            "title": title,
            "poster_url": poster_url,
            "added_at": datetime.utcnow().isoformat(),
        },
        on_conflict="user_id,movie_id",
    ).execute()


def _sync_sb_list(user_id: str) -> list[dict]:
    sb = _sb_client()
    resp = (
        sb.table("watchlist")
        .select("id,movie_id,title,poster_url,added_at")
        .eq("user_id", user_id)
        .order("added_at", desc=False)
        .execute()
    )
    return resp.data or []


def _sync_sb_remove(entry_id: int, user_id: str) -> None:
    sb = _sb_client()
    sb.table("watchlist").delete().eq("id", entry_id).eq("user_id", user_id).execute()


# ── SQLite layer ──────────────────────────────────────────────────────────────


def _sqlite_conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS watchlist (
               id         INTEGER  PRIMARY KEY AUTOINCREMENT,
               user_id    TEXT     NOT NULL,
               movie_id   INTEGER  NOT NULL,
               title      TEXT     NOT NULL,
               poster_url TEXT,
               added_at   TEXT     DEFAULT (datetime('now')),
               UNIQUE (user_id, movie_id)
           )"""
    )
    conn.commit()
    return conn


def _sync_sqlite_add(user_id: str, movie_id: int, title: str, poster_url: str | None) -> None:
    conn = _sqlite_conn()
    conn.execute(
        "INSERT OR REPLACE INTO watchlist (user_id, movie_id, title, poster_url) VALUES (?,?,?,?)",
        (user_id, movie_id, title, poster_url),
    )
    conn.commit()
    conn.close()


def _sync_sqlite_list(user_id: str) -> list[dict]:
    conn = _sqlite_conn()
    rows = conn.execute(
        "SELECT id, movie_id, title, poster_url, added_at FROM watchlist WHERE user_id=? ORDER BY added_at ASC",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _sync_sqlite_remove(entry_id: int, user_id: str) -> None:
    conn = _sqlite_conn()
    conn.execute("DELETE FROM watchlist WHERE id=? AND user_id=?", (entry_id, user_id))
    conn.commit()
    conn.close()


# ── async public API ──────────────────────────────────────────────────────────


async def _run(fn, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, fn, *args)


async def add_to_watchlist(
    user_id: str | int, movie_id: int, title: str, poster_url: str | None = None
) -> None:
    uid = str(user_id)
    if _use_supabase():
        await _run(_sync_sb_add, uid, movie_id, title, poster_url)
        logger.info("Supabase: added movie %d for user %s", movie_id, uid)
    else:
        await _run(_sync_sqlite_add, uid, movie_id, title, poster_url)
        logger.info("SQLite: added movie %d for user %s", movie_id, uid)


async def get_watchlist(user_id: str | int) -> list[dict]:
    uid = str(user_id)
    if _use_supabase():
        return await _run(_sync_sb_list, uid)
    return await _run(_sync_sqlite_list, uid)


async def remove_from_watchlist(entry_id: int, user_id: str | int) -> None:
    uid = str(user_id)
    if _use_supabase():
        await _run(_sync_sb_remove, entry_id, uid)
    else:
        await _run(_sync_sqlite_remove, entry_id, uid)
