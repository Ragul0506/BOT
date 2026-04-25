"""Google Sheets expense storage via service-account credentials (gspread).

Setup:
  1. Create a Google Cloud project → enable Google Sheets API.
  2. Create a service account → download JSON credentials.
  3. Create a Google Spreadsheet → share it with the service account email.
  4. Set env vars:
       GOOGLE_SHEETS_CREDENTIALS_JSON = <contents of the JSON key file>
       GOOGLE_SHEET_ID = <the spreadsheet ID from its URL>
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _is_configured() -> bool:
    return bool(
        os.environ.get("GOOGLE_SHEETS_CREDENTIALS_JSON")
        and os.environ.get("GOOGLE_SHEET_ID")
    )


def _get_gc():
    """Return an authenticated gspread client (sync, run in executor)."""
    import gspread
    from google.oauth2.service_account import Credentials

    raw = os.environ["GOOGLE_SHEETS_CREDENTIALS_JSON"]
    creds_info = json.loads(raw)
    creds = Credentials.from_service_account_info(creds_info, scopes=_SCOPES)
    return gspread.authorize(creds)


def _get_or_create_worksheet(gc, user_id: str):
    """Return the user's worksheet, creating it with a header row if absent."""
    import gspread

    spreadsheet = gc.open_by_key(os.environ["GOOGLE_SHEET_ID"])
    try:
        return spreadsheet.worksheet(str(user_id))
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=str(user_id), rows=2000, cols=5)
        ws.append_row(["Date", "Amount", "Category", "Note"])
        return ws


# ── sync workers (run inside executor) ───────────────────────────────────────


def _sync_append(user_id: str, expenses: list[dict]) -> None:
    gc = _get_gc()
    ws = _get_or_create_worksheet(gc, user_id)
    rows = [
        [
            exp.get("date", str(date.today())),
            float(exp.get("amount", 0)),
            exp.get("category", "general"),
            exp.get("note", ""),
        ]
        for exp in expenses
    ]
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
    logger.info("Appended %d expense row(s) for user %s", len(rows), user_id)


def _sync_get_month(user_id: str, year: int, month: int) -> list[dict]:
    gc = _get_gc()
    ws = _get_or_create_worksheet(gc, user_id)
    prefix = f"{year}-{month:02d}"
    records = ws.get_all_records()  # skips header automatically
    return [r for r in records if str(r.get("Date", "")).startswith(prefix)]


# ── async public API ──────────────────────────────────────────────────────────


async def append_expenses(user_id: str | int, expenses: list[dict]) -> None:
    """Append expense rows to the user's Google Sheet worksheet."""
    if not _is_configured():
        raise RuntimeError(
            "GOOGLE_SHEETS_CREDENTIALS_JSON or GOOGLE_SHEET_ID is not set."
        )
    if not expenses:
        return
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _sync_append, str(user_id), expenses)


async def get_month_expenses(
    user_id: str | int, year: int, month: int
) -> list[dict]:
    """Return all expense rows for *user_id* in the given year/month.

    Returns [] (not raises) when Sheets is not configured — callers must check.
    """
    if not _is_configured():
        return []
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(
            None, _sync_get_month, str(user_id), year, month
        )
    except Exception as exc:
        logger.error("Sheets read error: %s", exc)
        return []


def sheets_available() -> bool:
    return _is_configured()
