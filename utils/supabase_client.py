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

  3. For server-side bots, use the SERVICE_ROLE key (bypasses RLS safely):
       SUPABASE_URL  = https://xxxx.supabase.co
       SUPABASE_KEY  = <service_role key>   ← NOT the anon key
     The anon key + RLS policies require a user JWT that this bot cannot provide.

SQLite fallback:
  When Supabase is not configured or fails, the bot stores watchlist in
  /tmp/watchlist.db.  NOTE: Render free tier has an ephemeral filesystem —
  data is lost on restart.  Use Supabase for real persistence.
  Override path via WATCHLIST_DB_PATH env var if a volume is mounted.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# /tmp is always writable inside Docker containers.
# Override with WATCHLIST_DB_PATH if a persistent volume is available.
_DB_PATH = Path(os.environ.get("WATCHLIST_DB_PATH", "/tmp/watchlist.db"))

# Tri-state Supabase health flag.
# None = not yet tested, True = working, False = failed (use SQLite only).
_sb_working: bool | None = None


def _has_supabase_config() -> bool:
    return bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY"))


def _use_supabase() -> bool:
    """True only when Supabase is configured AND has not previously failed."""
    global _sb_working
    if not _has_supabase_config():
        return False
    return _sb_working is not False


def get_storage_status() -> dict:
    """Return a dict describing the current storage backend — used by /setup."""
    if not _has_supabase_config():
        return {
            "backend": "sqlite",
            "detail": f"SQLite @ {_DB_PATH} (ephemeral)",
            "healthy": True,
        }
    if _sb_working is True:
        return {"backend": "supabase", "detail": "Supabase ✅", "healthy": True}
    if _sb_working is False:
        return {
            "backend": "sqlite",
            "detail": f"Supabase ❌ → SQLite fallback @ {_DB_PATH}",
            "healthy": True,
        }
    return {"backend": "supabase?", "detail": "Supabase (untested)", "healthy": None}


# ── Supabase layer ────────────────────────────────────────────────────────────


def _sb_client():
    from supabase import create_client  # type: ignore[import]
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    logger.debug("Creating Supabase client for URL: %s", url[:30] + "…")
    return create_client(url, key)


def _sync_sb_add(user_id: str, movie_id: int, title: str, poster_url: str | None) -> None:
    global _sb_working
    try:
        sb = _sb_client()
        result = sb.table("watchlist").upsert(
            {
                "user_id": user_id,
                "movie_id": movie_id,
                "title": title,
                "poster_url": poster_url,
                "added_at": datetime.utcnow().isoformat(),
            },
            on_conflict="user_id,movie_id",
        ).execute()
        logger.info("Supabase ADD ok: movie %d for user %s", movie_id, user_id)
        _sb_working = True
    except Exception as exc:
        _sb_working = False
        logger.error(
            "Supabase ADD failed for user %s / movie %d: %s — falling back to SQLite",
            user_id, movie_id, exc,
        )
        raise


def _sync_sb_list(user_id: str) -> list[dict]:
    global _sb_working
    try:
        sb = _sb_client()
        resp = (
            sb.table("watchlist")
            .select("id,movie_id,title,poster_url,added_at")
            .eq("user_id", user_id)
            .order("added_at", desc=False)
            .execute()
        )
        logger.info("Supabase LIST ok: %d rows for user %s", len(resp.data or []), user_id)
        _sb_working = True
        return resp.data or []
    except Exception as exc:
        _sb_working = False
        logger.error(
            "Supabase LIST failed for user %s: %s — falling back to SQLite", user_id, exc
        )
        raise


def _sync_sb_remove(entry_id: int, user_id: str) -> None:
    global _sb_working
    try:
        sb = _sb_client()
        sb.table("watchlist").delete().eq("id", entry_id).eq("user_id", user_id).execute()
        logger.info("Supabase REMOVE ok: entry %d for user %s", entry_id, user_id)
        _sb_working = True
    except Exception as exc:
        _sb_working = False
        logger.error(
            "Supabase REMOVE failed for user %s / entry %d: %s — falling back to SQLite",
            user_id, entry_id, exc,
        )
        raise


# ── SQLite layer ──────────────────────────────────────────────────────────────


def _sqlite_conn() -> sqlite3.Connection:
    try:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            _DB_PATH.parent.chmod(0o700)
        except OSError:
            pass
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
        logger.debug("SQLite connected: %s", _DB_PATH)
        return conn
    except Exception as exc:
        logger.error("SQLite connect failed at %s: %s", _DB_PATH, exc)
        raise


def _sync_sqlite_add(user_id: str, movie_id: int, title: str, poster_url: str | None) -> None:
    conn = _sqlite_conn()
    conn.execute(
        "INSERT OR REPLACE INTO watchlist (user_id, movie_id, title, poster_url) VALUES (?,?,?,?)",
        (user_id, movie_id, title, poster_url),
    )
    conn.commit()
    conn.close()
    logger.info("SQLite ADD ok: movie %d for user %s", movie_id, user_id)


def _sync_sqlite_list(user_id: str) -> list[dict]:
    conn = _sqlite_conn()
    rows = conn.execute(
        "SELECT id, movie_id, title, poster_url, added_at FROM watchlist "
        "WHERE user_id=? ORDER BY added_at ASC",
        (user_id,),
    ).fetchall()
    conn.close()
    logger.info("SQLite LIST ok: %d rows for user %s", len(rows), user_id)
    return [dict(r) for r in rows]


def _sync_sqlite_remove(entry_id: int, user_id: str) -> None:
    conn = _sqlite_conn()
    conn.execute("DELETE FROM watchlist WHERE id=? AND user_id=?", (entry_id, user_id))
    conn.commit()
    conn.close()
    logger.info("SQLite REMOVE ok: entry %d for user %s", entry_id, user_id)


# ── async public API ──────────────────────────────────────────────────────────


async def _run(fn, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, fn, *args)


async def add_to_watchlist(
    user_id: str | int, movie_id: int, title: str, poster_url: str | None = None
) -> str:
    """Add movie to watchlist. Returns the backend used ('supabase' or 'sqlite')."""
    uid = str(user_id)
    if _use_supabase():
        try:
            await _run(_sync_sb_add, uid, movie_id, title, poster_url)
            return "supabase"
        except Exception:
            logger.warning("Supabase unavailable, using SQLite fallback for user %s", uid)
    await _run(_sync_sqlite_add, uid, movie_id, title, poster_url)
    return "sqlite"


async def get_watchlist(user_id: str | int) -> list[dict]:
    """Get watchlist entries. Falls back to SQLite if Supabase fails."""
    uid = str(user_id)
    if _use_supabase():
        try:
            return await _run(_sync_sb_list, uid)
        except Exception:
            logger.warning("Supabase unavailable, using SQLite fallback for user %s", uid)
    return await _run(_sync_sqlite_list, uid)


async def remove_from_watchlist(entry_id: int, user_id: str | int) -> None:
    """Remove a watchlist entry. Falls back to SQLite if Supabase fails."""
    uid = str(user_id)
    if _use_supabase():
        try:
            await _run(_sync_sb_remove, entry_id, uid)
            return
        except Exception:
            logger.warning("Supabase unavailable, using SQLite fallback for user %s", uid)
    await _run(_sync_sqlite_remove, entry_id, uid)
