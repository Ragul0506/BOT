"""Shop profile CRUD — SQLite-backed, per-user shop management.

Table: shops
  id, user_id, shop_name, address, phone, gst, logo_file_id,
  footer, is_default, gst_percent, discount_percent, shop_type,
  theme_color, created_at
"""
from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager

logger = logging.getLogger(__name__)

_DB_PATH = os.environ.get("SHOP_DB_PATH", "/tmp/shops.db")


@contextmanager
def _conn():
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _init_db() -> None:
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS shops (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id          INTEGER NOT NULL,
                shop_name        TEXT    NOT NULL,
                address          TEXT    DEFAULT '',
                phone            TEXT    DEFAULT '',
                gst              TEXT    DEFAULT '',
                logo_file_id     TEXT    DEFAULT '',
                footer           TEXT    DEFAULT 'Thank you for your visit!',
                is_default       INTEGER DEFAULT 0,
                gst_percent      REAL    DEFAULT 0.0,
                discount_percent REAL    DEFAULT 0.0,
                shop_type        TEXT    DEFAULT 'service',
                created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_shops_user ON shops(user_id)"
        )


def _migrate_db() -> None:
    """Add new columns to existing shops table (safe for upgrades)."""
    migrations = [
        "ALTER TABLE shops ADD COLUMN gst_percent REAL DEFAULT 0.0",
        "ALTER TABLE shops ADD COLUMN discount_percent REAL DEFAULT 0.0",
        "ALTER TABLE shops ADD COLUMN shop_type TEXT DEFAULT 'service'",
        "ALTER TABLE shops ADD COLUMN theme_color TEXT DEFAULT '#E91E63'",
    ]
    with _conn() as con:
        for sql in migrations:
            try:
                con.execute(sql)
            except sqlite3.OperationalError:
                pass  # column already exists


_init_db()
_migrate_db()


def create_shop(
    user_id: int,
    shop_name: str,
    address: str = "",
    phone: str = "",
    gst: str = "",
    logo_file_id: str = "",
    footer: str = "",
    gst_percent: float = 0.0,
    discount_percent: float = 0.0,
    shop_type: str = "service",
    theme_color: str = "#E91E63",
) -> int:
    """Create a new shop profile. Returns the new shop's id."""
    footer = footer or "Thank you for your visit!"
    with _conn() as con:
        count = con.execute(
            "SELECT COUNT(*) FROM shops WHERE user_id=?", (user_id,)
        ).fetchone()[0]
        is_default = 1 if count == 0 else 0
        cur = con.execute(
            "INSERT INTO shops "
            "(user_id, shop_name, address, phone, gst, logo_file_id, footer, "
            " is_default, gst_percent, discount_percent, shop_type, theme_color) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (user_id, shop_name, address, phone, gst, logo_file_id, footer,
             is_default, gst_percent, discount_percent, shop_type, theme_color),
        )
        return cur.lastrowid  # type: ignore[return-value]


def list_shops(user_id: int) -> list[dict]:
    """Return all shops for a user, default first."""
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM shops WHERE user_id=? ORDER BY is_default DESC, id ASC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_shop(shop_id: int, user_id: int) -> dict | None:
    """Return a specific shop, verifying ownership."""
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM shops WHERE id=? AND user_id=?",
            (shop_id, user_id),
        ).fetchone()
        return dict(row) if row else None


def get_default_shop(user_id: int) -> dict | None:
    """Return the default (or first) shop for a user."""
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM shops WHERE user_id=? ORDER BY is_default DESC, id ASC LIMIT 1",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None


def set_default_shop(shop_id: int, user_id: int) -> bool:
    """Mark shop_id as the user's default shop. Returns True on success."""
    with _conn() as con:
        exists = con.execute(
            "SELECT id FROM shops WHERE id=? AND user_id=?", (shop_id, user_id)
        ).fetchone()
        if not exists:
            return False
        con.execute("UPDATE shops SET is_default=0 WHERE user_id=?", (user_id,))
        con.execute("UPDATE shops SET is_default=1 WHERE id=?", (shop_id,))
        return True


def update_shop(shop_id: int, user_id: int, **kwargs) -> bool:
    """Update allowed shop fields. Returns True if a row was updated."""
    allowed = {
        "shop_name", "address", "phone", "gst", "logo_file_id", "footer",
        "gst_percent", "discount_percent", "shop_type", "theme_color",
    }
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return False
    set_clause = ", ".join(f"{k}=?" for k in updates)
    values = list(updates.values()) + [shop_id, user_id]
    with _conn() as con:
        cur = con.execute(
            f"UPDATE shops SET {set_clause} WHERE id=? AND user_id=?", values
        )
        return cur.rowcount > 0


def get_shops_by_type(user_id: int, shop_type: str) -> list[dict]:
    """Return shops for user filtered by shop_type, default first."""
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM shops WHERE user_id=? AND shop_type=? "
            "ORDER BY is_default DESC, id ASC",
            (user_id, shop_type),
        ).fetchall()
        return [dict(r) for r in rows]


def delete_shop(shop_id: int, user_id: int) -> bool:
    """Delete a shop profile. Returns True if deleted."""
    with _conn() as con:
        cur = con.execute(
            "DELETE FROM shops WHERE id=? AND user_id=?", (shop_id, user_id)
        )
        return cur.rowcount > 0
