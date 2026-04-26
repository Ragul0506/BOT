"""Bill history — logs each generated bill to a user-specific Google Sheets tab.

Tab name pattern : Bill_History_{user_id}
Columns          : Date | Bill_Number | Total_Amount | Items_Summary | PDF_File_ID

Bill_Number format: DDMon-NNN   (e.g. "26Apr-001", resets daily per user)

Multi-user isolation is guaranteed by using per-user worksheet tabs, exactly
like the expense tracker.  Different users can never read or write each other's
Bill_History tab because each call filters by the user_id-derived tab name.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date as _date, datetime

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_HEADER = ["Date", "Bill_Number", "Total_Amount", "Items_Summary", "PDF_File_ID"]

_creds_cache: dict | None = None


# ── availability check ────────────────────────────────────────────────────────


def bill_history_available() -> bool:
    """True when Google Sheets credentials are configured."""
    return bool(
        os.environ.get("GOOGLE_SHEETS_CREDENTIALS_JSON")
        and os.environ.get("GOOGLE_SHEET_ID")
    )


# ── low-level Sheets helpers ──────────────────────────────────────────────────


def _get_gc():
    """Return an authenticated gspread client (sync; call inside executor).

    Raises RuntimeError with a descriptive message on any credential problem
    so the async callers can catch it and degrade gracefully.
    """
    global _creds_cache
    import gspread
    from google.oauth2.service_account import Credentials

    if _creds_cache is None:
        raw = os.environ.get("GOOGLE_SHEETS_CREDENTIALS_JSON", "").strip()
        if not raw:
            raise RuntimeError("GOOGLE_SHEETS_CREDENTIALS_JSON is not set")

        # Accept both the JSON content directly and a file path.
        if raw.startswith("{"):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"GOOGLE_SHEETS_CREDENTIALS_JSON is not valid JSON: {exc}"
                ) from exc
        else:
            try:
                with open(raw) as fh:
                    parsed = json.load(fh)
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError(
                    f"Cannot read service account credentials from '{raw}': {exc}"
                ) from exc

        if not isinstance(parsed, dict):
            raise RuntimeError(
                "Service account credentials must be a JSON object (got "
                f"{type(parsed).__name__})"
            )

        required = {"token_uri", "client_email", "private_key"}
        missing = required - set(parsed.keys())
        if missing:
            raise RuntimeError(
                f"Service account JSON missing required fields: {missing}. "
                "Ensure GOOGLE_SHEETS_CREDENTIALS_JSON contains the full "
                "service-account key file content, not just a file path."
            )

        _creds_cache = parsed

    try:
        creds = Credentials.from_service_account_info(_creds_cache, scopes=_SCOPES)
        return gspread.authorize(creds)
    except Exception as exc:
        raise RuntimeError(f"Failed to authorize Google Sheets client: {exc}") from exc


def _tab_name(user_id: str) -> str:
    return f"Bill_History_{user_id}"


def _get_or_create_tab(gc, user_id: str):
    import gspread

    spreadsheet = gc.open_by_key(os.environ["GOOGLE_SHEET_ID"])
    name = _tab_name(user_id)
    try:
        ws = spreadsheet.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=name, rows=5000, cols=5)
        # [C3] Use RAW to prevent formula injection in all sheet writes.
        ws.append_row(_HEADER, value_input_option="RAW")
        logger.info("Created bill history tab: %s", name)
    return ws


def _next_bill_number(ws, date_str: str) -> str:
    """Count existing rows for *date_str*, return next bill number.

    Format: DDMon-NNN  (e.g. "26Apr-001")
    """
    try:
        records = ws.get_all_records()
    except Exception:
        records = []

    count = sum(1 for r in records if str(r.get("Date", "")) == date_str)
    num = count + 1
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{d.strftime('%d%b')}-{num:03d}"


def _items_summary(items: list[dict], max_chars: int = 120) -> str:
    """Build a short comma-joined string of item names for the summary column."""
    names = [str(i.get("item", "?")) for i in items[:6]]
    summary = ", ".join(names)
    if len(items) > 6:
        summary += f" +{len(items) - 6} more"
    return summary[:max_chars]


# ── sync workers (run inside thread executor) ─────────────────────────────────


def _sync_log_bill(
    user_id: str,
    items: list[dict],
    total: float,
    pdf_file_id: str,
    date_str: str,
) -> str:
    """Append a bill row; return the bill_number string."""
    gc = _get_gc()
    ws = _get_or_create_tab(gc, user_id)
    bill_no = _next_bill_number(ws, date_str)
    summary = _items_summary(items)
    ws.append_row(
        [date_str, bill_no, round(total, 2), summary, pdf_file_id],
        value_input_option="RAW",
    )
    logger.info(
        "Bill logged: user=%s bill_no=%s items=%d total=%.2f file_id=%s",
        user_id, bill_no, len(items), total, pdf_file_id[:20] if pdf_file_id else "",
    )
    return bill_no


def _sync_get_bills(user_id: str, date_str: str) -> list[dict]:
    """Return all bill rows for *user_id* on *date_str*."""
    gc = _get_gc()
    ws = _get_or_create_tab(gc, user_id)
    records = ws.get_all_records()
    return [r for r in records if str(r.get("Date", "")) == date_str]


# ── async public API ──────────────────────────────────────────────────────────


async def log_bill(
    user_id: str | int,
    items: list[dict],
    total: float,
    pdf_file_id: str = "",
    date_str: str = "",
) -> str:
    """Async: log bill to Google Sheets; return bill_number or '' on error.

    Never raises — errors are logged but do not interrupt the main flow.
    """
    if not bill_history_available():
        return ""
    if not date_str:
        date_str = str(_date.today())
    uid = str(user_id)
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(
            None, _sync_log_bill, uid, items, total, pdf_file_id, date_str
        )
    except Exception as exc:
        logger.error("Bill history log error for user %s: %s", uid, exc, exc_info=True)
        return ""


async def get_bills_for_date(user_id: str | int, date_str: str = "") -> list[dict]:
    """Async: return list of bill-row dicts for *user_id* on *date_str*.

    Returns [] on error or when Sheets is not configured.
    """
    if not bill_history_available():
        return []
    if not date_str:
        date_str = str(_date.today())
    uid = str(user_id)
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, _sync_get_bills, uid, date_str)
    except Exception as exc:
        logger.error("Bill history fetch error for user %s: %s", uid, exc, exc_info=True)
        return []
