"""PDF generators — grocery bill, service invoice, and expense summary.

Functions:
  generate_grocery_bill(items, bill_number, lang)        → grocery / shopping PDF
  generate_service_bill(shop_name, customer_name, ...)   → beauty parlour / service PDF
  generate_expense_summary_pdf(expenses, month_label, …) → monthly expense report
  generate_bill_pdf(items, language)                     → backward-compat alias for grocery_bill
  next_service_roll_number(shop_name, date_obj)          → "SNBP-260426-001" style roll number
"""
from __future__ import annotations

import html as _html
import logging
import os
import tempfile
from collections import defaultdict
from datetime import datetime
from itertools import count as _count

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    Image as RLImage,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

logger = logging.getLogger(__name__)

# Built-in Helvetica — no external font file required.
_FONT = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"

# Monotonically increasing counter used to give every ParagraphStyle a unique
# name, preventing ReportLab's internal style registry from returning a stale
# cached style on repeated calls to the same generator function.
_style_seq = _count(1)


def _uid() -> str:
    return str(next(_style_seq))


def _e(value) -> str:
    """HTML-escape an arbitrary value for safe embedding in a ReportLab Paragraph.

    Paragraph is an XML parser — bare '&', '<', '>' in user-supplied text cause
    silent parse failures and empty cells.  Always call _e() on variable data.
    """
    return _html.escape(str(value), quote=False)


def _ps(name: str, bold: bool = False, **kw) -> ParagraphStyle:
    """Create a uniquely-named ParagraphStyle using built-in Helvetica."""
    return ParagraphStyle(
        f"{name}_{_uid()}",
        fontName=_FONT_BOLD if bold else _FONT,
        **kw,
    )


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text, style)


def _build_doc(path: str) -> SimpleDocTemplate:
    return SimpleDocTemplate(
        path,
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
    )


# ── service roll-number generator ─────────────────────────────────────────────

_service_counters: dict[str, int] = defaultdict(int)


def _shop_prefix(shop_name: str) -> str:
    """Return 2–4 uppercase initials from shop name, skipping common stop words."""
    stop = {"the", "and", "&", "of", "for", "in", "at", "a", "an"}
    words = [w for w in shop_name.split() if w.lower() not in stop]
    return "".join(w[0].upper() for w in words[:4]) or "SHOP"


def next_service_roll_number(shop_name: str, date_obj: datetime | None = None) -> str:
    """Return auto-incrementing daily roll number, e.g. 'SNBP-260426-001'."""
    d = date_obj or datetime.now()
    prefix = _shop_prefix(shop_name)
    date_key = d.strftime("%d%m%y")
    counter_key = f"{prefix}:{date_key}"
    _service_counters[counter_key] += 1
    return f"{prefix}-{date_key}-{_service_counters[counter_key]:03d}"


# ── A. Grocery / Shopping Bill ────────────────────────────────────────────────

# A4 usable width = 21.0 cm − 2 × 1.5 cm margins = 18.0 cm
_GROCERY_COL_WIDTHS = [1.5 * cm, 7.3 * cm, 2.0 * cm, 3.6 * cm, 3.6 * cm]  # Σ = 18.0 cm


def generate_grocery_bill(
    items: list[dict],
    bill_number: str = "",
    lang: str = "en",
) -> str:
    """Build a clean English grocery/shopping bill PDF.

    Args:
        items:       List of {'item': str, 'qty': number, 'rate': number} dicts.
        bill_number: Optional bill number (auto-generated from datetime if empty).
        lang:        Accepted for API compatibility; always generates English PDF.
    Returns:
        Temp file path — caller is responsible for deletion.
    """
    NAVY = colors.HexColor("#1a237e")
    NAVY_DARK = colors.HexColor("#283593")
    STRIPE = colors.HexColor("#e8eaf6")
    GRID = colors.HexColor("#c5cae9")

    s_shop = _ps("GShop", bold=True,  fontSize=22, alignment=1, textColor=NAVY,       spaceAfter=2)
    s_sub  = _ps("GSub",               fontSize=11, alignment=1, textColor=NAVY_DARK,  spaceAfter=3)
    s_meta = _ps("GMeta",              fontSize=9,  alignment=1, textColor=colors.grey, spaceAfter=2)
    s_foot = _ps("GFoot",              fontSize=8,  alignment=1, textColor=colors.grey)
    s_th   = _ps("GTH",   bold=True,  fontSize=10, alignment=1, textColor=colors.white)
    s_tdc  = _ps("GTDC",               fontSize=9,  alignment=1)
    s_tdl  = _ps("GTDL",               fontSize=9,  alignment=0)
    s_tot  = _ps("GTot",  bold=True,  fontSize=10, alignment=1, textColor=colors.white)

    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.close()
    doc = _build_doc(tmp.name)
    now = datetime.now()
    bill_no = _e(bill_number or now.strftime("%Y%m%d%H%M"))

    story: list = []

    # ── Header ────────────────────────────────────────────────────────────────
    story.append(_p("GroceryBot Store", s_shop))
    story.append(_p("Invoice", s_sub))
    story.append(HRFlowable(width="100%", thickness=2, color=NAVY, spaceAfter=4))
    story.append(_p(
        f"Date: {now.strftime('%d-%m-%Y')}&nbsp;&nbsp;|&nbsp;&nbsp;"
        f"Time: {now.strftime('%H:%M')}&nbsp;&nbsp;|&nbsp;&nbsp;"
        f"Bill No: {bill_no}",
        s_meta,
    ))
    story.append(Spacer(1, 0.5 * cm))

    # ── Item table ─────────────────────────────────────────────────────────────
    rows: list[list] = [[
        _p("S.No",             s_th),
        _p("Item",             s_th),
        _p("Qty",              s_th),
        _p("Rate (&#8377;)",   s_th),
        _p("Amount (&#8377;)", s_th),
    ]]

    grand_total = 0.0
    for idx, item in enumerate(items, 1):
        name   = _e(item.get("item", ""))
        qty    = float(item.get("qty", 1))
        rate   = float(item.get("rate", 0))
        amount = qty * rate
        grand_total += amount
        rows.append([
            _p(str(idx),       s_tdc),
            _p(name,           s_tdl),
            _p(f"{qty:g}",     s_tdc),
            _p(f"{rate:.2f}",  s_tdc),
            _p(f"{amount:.2f}", s_tdc),
        ])

    rows.append([
        _p("", s_tot), _p("", s_tot), _p("", s_tot),
        _p("Total",                           s_tot),
        _p(f"&#8377;&nbsp;{grand_total:.2f}", s_tot),
    ])

    tbl = Table(rows, colWidths=_GROCERY_COL_WIDTHS, repeatRows=1)
    cmds = [
        ("BACKGROUND",    (0,  0), (-1,  0), NAVY),
        ("ROWHEIGHT",     (0,  0), (-1,  0), 24),
        ("BACKGROUND",    (0, -1), (-1, -1), NAVY_DARK),
        ("ROWHEIGHT",     (0, -1), (-1, -1), 26),
        ("GRID",          (0,  0), (-1, -2), 0.5, GRID),
        ("LINEABOVE",     (0, -1), (-1, -1), 1.5, NAVY),
        ("VALIGN",        (0,  0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",   (0,  0), (-1, -1), 6),
        ("RIGHTPADDING",  (0,  0), (-1, -1), 6),
        ("TOPPADDING",    (0,  0), (-1, -1), 5),
        ("BOTTOMPADDING", (0,  0), (-1, -1), 5),
    ]
    for i in range(1, len(rows) - 1):
        cmds.append(("BACKGROUND", (0, i), (-1, i),
                     colors.white if i % 2 == 1 else STRIPE))
    tbl.setStyle(TableStyle(cmds))
    story.append(tbl)
    story.append(Spacer(1, 0.8 * cm))

    # ── Footer ────────────────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    story.append(Spacer(1, 0.2 * cm))
    story.append(_p("Thank you for your purchase!", s_foot))
    story.append(_p(f"Generated by GroceryBot &bull; {now.strftime('%Y')}", s_foot))

    doc.build(story)
    logger.info(
        "Grocery PDF: %s | bill_no=%s | items=%d | total=%.2f",
        tmp.name, bill_no, len(items), grand_total,
    )
    return tmp.name


# ── B. Service / Beauty Parlour Bill ─────────────────────────────────────────

_SERVICE_COL_WIDTHS = [1.5 * cm, 11.3 * cm, 5.2 * cm]  # Σ = 18.0 cm


def generate_service_bill(
    shop_name: str,
    customer_name: str,
    services: list[dict],   # [{'item': str, 'qty': number, 'rate': number}]
    bill_number: str,
    date_str: str = "",
    time_str: str = "",
) -> str:
    """Build a professional service invoice PDF (beauty parlour, tailoring, etc.).

    Args:
        shop_name:     Shop / parlour name (e.g. "SRI NARPAVI BEAUTY PARLOUR").
        customer_name: Customer's first name or "Valued Customer".
        services:      List of {'item': str, 'qty': number, 'rate': number} dicts.
        bill_number:   Roll number e.g. "SNBP-260426-001".
        date_str:      Bill date DD-MM-YYYY; auto-filled if empty.
        time_str:      Bill time HH:MM; auto-filled if empty.
    Returns:
        Temp file path — caller is responsible for deletion.
    """
    now = datetime.now()
    date_str = date_str or now.strftime("%d-%m-%Y")
    time_str = time_str or now.strftime("%H:%M")

    PINK      = colors.HexColor("#880e4f")
    PINK_DARK = colors.HexColor("#c2185b")
    STRIPE    = colors.HexColor("#fce4ec")
    GRID      = colors.HexColor("#f48fb1")

    s_shop  = _ps("SShop", bold=True, fontSize=20, alignment=1, textColor=PINK,      spaceAfter=2)
    s_sub   = _ps("SSub",             fontSize=11, alignment=1, textColor=PINK_DARK, spaceAfter=3)
    s_foot  = _ps("SFoot",            fontSize=8,  alignment=1, textColor=PINK_DARK)
    s_th    = _ps("STH",   bold=True, fontSize=10, alignment=1, textColor=colors.white)
    s_tdc   = _ps("STDC",             fontSize=9,  alignment=1)
    s_tdl   = _ps("STDL",             fontSize=9,  alignment=0)
    s_tot   = _ps("STot",  bold=True, fontSize=11, alignment=1, textColor=colors.white)
    s_lbl   = _ps("SLbl",  bold=True, fontSize=9,  alignment=0, textColor=PINK)
    s_val   = _ps("SVal",             fontSize=9,  alignment=0)

    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.close()
    doc = _build_doc(tmp.name)

    story: list = []

    # ── Header ────────────────────────────────────────────────────────────────
    story.append(_p(_e(shop_name.upper()), s_shop))
    story.append(_p("Service Invoice", s_sub))
    story.append(HRFlowable(width="100%", thickness=2, color=PINK, spaceAfter=6))

    # ── Bill meta (2-column label / value layout) ─────────────────────────────
    meta_rows = [
        [_p("Roll No",   s_lbl), _p(_e(bill_number),   s_val),
         _p("Date",      s_lbl), _p(_e(date_str),      s_val)],
        [_p("Customer",  s_lbl), _p(_e(customer_name), s_val),
         _p("Time",      s_lbl), _p(_e(time_str),      s_val)],
    ]
    meta_tbl = Table(meta_rows, colWidths=[2.5 * cm, 6.5 * cm, 2.0 * cm, 4.0 * cm])
    meta_tbl.setStyle(TableStyle([
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
    ]))
    story.append(meta_tbl)
    story.append(Spacer(1, 0.3 * cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=GRID, spaceAfter=6))

    # ── Services table ─────────────────────────────────────────────────────────
    rows: list[list] = [[
        _p("S.No",             s_th),
        _p("Service",          s_th),
        _p("Amount (&#8377;)", s_th),
    ]]

    grand_total = 0.0
    for idx, svc in enumerate(services, 1):
        name   = _e(svc.get("item", ""))
        qty    = float(svc.get("qty", 1))
        rate   = float(svc.get("rate", 0))
        amount = qty * rate
        grand_total += amount
        rows.append([
            _p(str(idx),        s_tdc),
            _p(name,            s_tdl),
            _p(f"{amount:.2f}", s_tdc),
        ])

    rows.append([
        _p("",                                s_tot),
        _p("Total Amount",                    s_tot),
        _p(f"&#8377;&nbsp;{grand_total:.2f}", s_tot),
    ])

    tbl = Table(rows, colWidths=_SERVICE_COL_WIDTHS, repeatRows=1)
    cmds = [
        ("BACKGROUND",    (0,  0), (-1,  0), PINK),
        ("ROWHEIGHT",     (0,  0), (-1,  0), 24),
        ("BACKGROUND",    (0, -1), (-1, -1), PINK_DARK),
        ("ROWHEIGHT",     (0, -1), (-1, -1), 26),
        ("GRID",          (0,  0), (-1, -2), 0.5, GRID),
        ("LINEABOVE",     (0, -1), (-1, -1), 1.5, PINK),
        ("VALIGN",        (0,  0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",   (0,  0), (-1, -1), 6),
        ("RIGHTPADDING",  (0,  0), (-1, -1), 6),
        ("TOPPADDING",    (0,  0), (-1, -1), 5),
        ("BOTTOMPADDING", (0,  0), (-1, -1), 5),
    ]
    for i in range(1, len(rows) - 1):
        cmds.append(("BACKGROUND", (0, i), (-1, i),
                     colors.white if i % 2 == 1 else STRIPE))
    tbl.setStyle(TableStyle(cmds))
    story.append(tbl)
    story.append(Spacer(1, 0.8 * cm))

    # ── Footer ────────────────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=GRID))
    story.append(Spacer(1, 0.2 * cm))
    story.append(_p("We care for your beauty &#8211; Visit again! &#10084;", s_foot))
    story.append(_p(f"Generated by GroceryBot &bull; {now.strftime('%Y')}", s_foot))

    doc.build(story)
    logger.info(
        "Service PDF: %s | shop=%s | roll=%s | items=%d | total=%.2f",
        tmp.name, shop_name, bill_number, len(services), grand_total,
    )
    return tmp.name


# ── C. Monthly Expense Summary PDF ───────────────────────────────────────────


def generate_expense_summary_pdf(
    expenses: list[dict],
    month_label: str,
    user_name: str = "",
    chart_path: str | None = None,
) -> str:
    """Build a monthly expense report PDF; return temp file path."""
    NAVY      = colors.HexColor("#1a237e")
    NAVY_DARK = colors.HexColor("#283593")
    STRIPE    = colors.HexColor("#e8eaf6")
    GRID      = colors.HexColor("#c5cae9")

    s_title  = _ps("ET",  bold=True, fontSize=18, alignment=1, textColor=NAVY,      spaceAfter=2)
    s_sub    = _ps("ES",             fontSize=11, alignment=1, textColor=NAVY_DARK,  spaceAfter=3)
    s_meta   = _ps("EM",             fontSize=9,  alignment=1, textColor=colors.grey, spaceAfter=2)
    s_foot   = _ps("EF",             fontSize=8,  alignment=1, textColor=colors.grey)
    s_th     = _ps("ETH", bold=True, fontSize=10, alignment=1, textColor=colors.white)
    s_tdc    = _ps("ETC",            fontSize=9,  alignment=1)
    s_tdl    = _ps("ETL",            fontSize=9,  alignment=0)
    s_cathdr = _ps("ECH", bold=True, fontSize=12, textColor=NAVY, spaceAfter=4, spaceBefore=8)
    s_tot    = _ps("ETot",bold=True, fontSize=11, alignment=1, textColor=colors.white)

    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.close()
    doc = _build_doc(tmp.name)
    now = datetime.now()

    story: list = []

    story.append(_p("Ragul&#8217;s Monthly Expense Report", s_title))
    story.append(_p(_e(month_label), s_sub))
    if user_name:
        story.append(_p(f"Prepared for: {_e(user_name)}", s_meta))
    story.append(_p(f"Generated: {now.strftime('%d-%m-%Y %H:%M')}", s_meta))
    story.append(HRFlowable(width="100%", thickness=1.5, color=NAVY, spaceAfter=8))

    if chart_path and os.path.exists(chart_path):
        story.append(RLImage(chart_path, width=16 * cm, height=8 * cm))
        story.append(Spacer(1, 0.5 * cm))

    # Category breakdown
    category_totals: dict[str, float] = defaultdict(float)
    grand_total = 0.0
    for row in expenses:
        amt = float(row.get("Amount", 0))
        cat = str(row.get("Category", "general")).capitalize()
        category_totals[cat] += amt
        grand_total += amt

    story.append(_p("Category Breakdown", s_cathdr))

    cat_rows: list[list] = [[
        _p("Category",       s_th),
        _p("Total (&#8377;)", s_th),
        _p("% of Spend",     s_th),
    ]]
    for cat, total in sorted(category_totals.items(), key=lambda x: x[1], reverse=True):
        pct = (total / grand_total * 100) if grand_total > 0 else 0
        cat_rows.append([
            _p(_e(cat),             s_tdl),
            _p(f"{total:,.2f}",     s_tdc),
            _p(f"{pct:.1f}%",       s_tdc),
        ])
    cat_rows.append([
        _p("Grand Total",                     s_tot),
        _p(f"&#8377; {grand_total:,.2f}",     s_tot),
        _p("100%",                            s_tot),
    ])

    cat_tbl = Table(cat_rows, colWidths=[8 * cm, 5 * cm, 5 * cm])
    cat_style = [
        ("BACKGROUND",    (0,  0), (-1,  0), NAVY),
        ("BACKGROUND",    (0, -1), (-1, -1), NAVY_DARK),
        ("GRID",          (0,  0), (-1, -2), 0.5, GRID),
        ("LINEABOVE",     (0, -1), (-1, -1), 1.5, NAVY),
        ("VALIGN",        (0,  0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",   (0,  0), (-1, -1), 6),
        ("RIGHTPADDING",  (0,  0), (-1, -1), 6),
        ("TOPPADDING",    (0,  0), (-1, -1), 5),
        ("BOTTOMPADDING", (0,  0), (-1, -1), 5),
    ]
    for i in range(1, len(cat_rows) - 1):
        cat_style.append(("BACKGROUND", (0, i), (-1, i),
                          colors.white if i % 2 == 1 else STRIPE))
    cat_tbl.setStyle(TableStyle(cat_style))
    story.append(cat_tbl)
    story.append(Spacer(1, 0.8 * cm))

    # All transactions detail
    story.append(_p("All Transactions", s_cathdr))

    det_rows: list[list] = [[
        _p("Date",             s_th),
        _p("Category",         s_th),
        _p("Note",             s_th),
        _p("Amount (&#8377;)", s_th),
    ]]
    for row in expenses:
        det_rows.append([
            _p(_e(row.get("Date", "")),                           s_tdc),
            _p(_e(str(row.get("Category", "")).capitalize()),     s_tdc),
            _p(_e(row.get("Note", "")),                           s_tdl),
            _p(f"{float(row.get('Amount', 0)):,.2f}",             s_tdc),
        ])

    det_tbl = Table(det_rows, colWidths=[3 * cm, 3.5 * cm, 7 * cm, 4.5 * cm])
    det_style = [
        ("BACKGROUND",    (0, 0), (-1,  0), NAVY),
        ("GRID",          (0, 0), (-1, -1), 0.5, GRID),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for i in range(1, len(det_rows)):
        det_style.append(("BACKGROUND", (0, i), (-1, i),
                          colors.white if i % 2 == 1 else STRIPE))
    det_tbl.setStyle(TableStyle(det_style))
    story.append(det_tbl)
    story.append(Spacer(1, 0.8 * cm))

    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    story.append(Spacer(1, 0.2 * cm))
    story.append(_p(f"GroceryBot Expense Tracker &bull; {now.strftime('%Y')}", s_foot))

    doc.build(story)
    logger.info(
        "Expense PDF: %s | total=%.2f | rows=%d",
        tmp.name, grand_total, len(expenses),
    )
    return tmp.name


# ── backward-compat alias ─────────────────────────────────────────────────────


def generate_bill_pdf(items: list[dict], language: str = "en") -> str:
    """Backward-compatible alias — delegates to generate_grocery_bill()."""
    return generate_grocery_bill(items, lang="en")
