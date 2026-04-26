"""PDF generators — grocery bill, service invoice, and expense summary.

Functions:
  generate_grocery_bill(items, bill_number, lang)        → grocery / shopping PDF
  generate_service_bill(shop_name, customer_name, ...)   → beauty parlour / service PDF
  generate_expense_summary_pdf(expenses, month_label, …) → monthly expense report
  generate_bill_pdf(items, language)                     → backward-compat alias for grocery_bill
  next_service_roll_number(shop_name, date_obj)          → "SNBP-260426-001" style roll number
"""
from __future__ import annotations

import logging
import os
import tempfile
from collections import defaultdict
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
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

_FONTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fonts")
_FONT_TTF = os.path.join(_FONTS_DIR, "NotoSansTamil-Regular.ttf")
_FONT_NAME = "NotoSansTamil"
_font_ready = False


def _register_tamil_font() -> str:
    """Register the Tamil font once; return font name to use."""
    global _font_ready
    if not _font_ready:
        if os.path.exists(_FONT_TTF):
            pdfmetrics.registerFont(TTFont(_FONT_NAME, _FONT_TTF))
            _font_ready = True
            logger.info("Tamil font registered: %s", _FONT_TTF)
        else:
            logger.warning(
                "Tamil font not found at %s — falling back to Helvetica. "
                "Run `python download_fonts.py` to fix this.",
                _FONT_TTF,
            )
    return _FONT_NAME if _font_ready else "Helvetica"


# ── style helpers ─────────────────────────────────────────────────────────────


def _ps(name: str, font: str, **kw) -> ParagraphStyle:
    return ParagraphStyle(name, fontName=font, **kw)


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text, style)


def _build_doc(tmp_path: str) -> SimpleDocTemplate:
    return SimpleDocTemplate(
        tmp_path,
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


def generate_grocery_bill(
    items: list[dict],
    bill_number: str = "",
    lang: str = "en",
) -> str:
    """Build a clean English grocery/shopping bill PDF.

    Args:
        items:       List of {'item', 'qty', 'rate'} dicts.
        bill_number: Optional bill number string (auto-generated from datetime if empty).
        lang:        'en' (default) or 'ta' for bilingual headers.
    Returns:
        Temp file path (caller must delete).
    """
    font = _register_tamil_font()

    NAVY = colors.HexColor("#1a237e")
    NAVY_DARK = colors.HexColor("#283593")
    STRIPE = colors.HexColor("#e8eaf6")
    GRID_CLR = colors.HexColor("#c5cae9")

    s_shop   = _ps("GShop",   font, fontSize=20, alignment=1, textColor=NAVY,      spaceAfter=2)
    s_sub    = _ps("GSub",    font, fontSize=11, alignment=1, textColor=NAVY_DARK,  spaceAfter=3)
    s_meta   = _ps("GMeta",   font, fontSize=9,  alignment=1, textColor=colors.grey, spaceAfter=2)
    s_footer = _ps("GFoot",   font, fontSize=8,  alignment=1, textColor=colors.grey)
    s_th     = _ps("GTH",     font, fontSize=10, textColor=colors.white, alignment=1)
    s_td_c   = _ps("GTDC",    font, fontSize=9,  alignment=1)
    s_td_l   = _ps("GTDL",    font, fontSize=9,  alignment=0)
    s_total  = _ps("GTot",    font, fontSize=10, textColor=colors.white, alignment=1)

    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.close()
    doc = _build_doc(tmp.name)
    now = datetime.now()
    bill_no = bill_number or now.strftime("%Y%m%d%H%M")

    story = []

    # Header
    story.append(_p("GroceryBot Bill", s_shop))
    story.append(_p("Your Personal Shopping Invoice", s_sub))
    story.append(_p("&#128222; GroceryBot &nbsp;|&nbsp; AI-Powered Bill Generator", s_meta))
    story.append(HRFlowable(width="100%", thickness=1.5, color=NAVY, spaceAfter=6))
    story.append(_p(
        f"Date: {now.strftime('%d-%m-%Y')} &nbsp;|&nbsp; "
        f"Time: {now.strftime('%H:%M')} &nbsp;|&nbsp; "
        f"Bill No: {bill_no}",
        s_meta,
    ))
    story.append(Spacer(1, 0.5 * cm))

    # Item table
    col_widths = [1.2 * cm, 7.5 * cm, 2 * cm, 3 * cm, 3 * cm]
    rows: list[list] = [[
        _p("S.No", s_th),
        _p("Item", s_th),
        _p("Qty", s_th),
        _p("Rate (&#8377;)", s_th),
        _p("Amount (&#8377;)", s_th),
    ]]

    grand_total = 0.0
    for idx, item in enumerate(items, 1):
        qty    = float(item.get("qty", 1))
        rate   = float(item.get("rate", 0))
        amount = qty * rate
        grand_total += amount
        rows.append([
            _p(str(idx), s_td_c),
            _p(str(item.get("item", "")), s_td_l),
            _p(f"{qty:g}", s_td_c),
            _p(f"{rate:.2f}", s_td_c),
            _p(f"{amount:.2f}", s_td_c),
        ])

    rows.append([
        _p("", s_total), _p("", s_total), _p("", s_total),
        _p("Total", s_total),
        _p(f"&#8377; {grand_total:.2f}", s_total),
    ])

    table = Table(rows, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ("BACKGROUND",    (0, 0),  (-1, 0),  NAVY),
        ("ROWHEIGHT",      (0, 0),  (-1, 0),  24),
        ("BACKGROUND",    (0, -1), (-1, -1), NAVY_DARK),
        ("ROWHEIGHT",      (0, -1), (-1, -1), 24),
        ("GRID",           (0, 0),  (-1, -2), 0.5, GRID_CLR),
        ("LINEABOVE",      (0, -1), (-1, -1), 1.5, NAVY),
        ("VALIGN",         (0, 0),  (-1, -1), "MIDDLE"),
        ("LEFTPADDING",    (0, 0),  (-1, -1), 6),
        ("RIGHTPADDING",   (0, 0),  (-1, -1), 6),
        ("TOPPADDING",     (0, 0),  (-1, -1), 5),
        ("BOTTOMPADDING",  (0, 0),  (-1, -1), 5),
    ]
    for i in range(1, len(rows) - 1):
        style_cmds.append(("BACKGROUND", (0, i), (-1, i),
                           colors.white if i % 2 == 1 else STRIPE))
    table.setStyle(TableStyle(style_cmds))
    story.append(table)
    story.append(Spacer(1, 0.8 * cm))

    # Footer
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    story.append(Spacer(1, 0.2 * cm))
    story.append(_p("Thank you for your purchase!", s_footer))
    story.append(_p(f"Generated by GroceryBot &bull; {now.strftime('%Y')}", s_footer))

    doc.build(story)
    logger.info("Grocery PDF: %s | bill_no=%s | total=%.2f", tmp.name, bill_no, grand_total)
    return tmp.name


# ── B. Service / Beauty Parlour Bill ─────────────────────────────────────────


def generate_service_bill(
    shop_name: str,
    customer_name: str,
    services: list[dict],   # [{'item': str, 'qty': float, 'rate': float}]
    bill_number: str,
    date_str: str = "",
    time_str: str = "",
) -> str:
    """Build a professional service invoice PDF (beauty parlour, tailoring, etc.).

    Args:
        shop_name:     Shop / parlour name (e.g. "SRI NARPAVI BEAUTY PARLOUR").
        customer_name: Customer's first name or "Valued Customer".
        services:      List of {'item', 'qty', 'rate'} dicts from parse_items().
        bill_number:   Roll number e.g. "SNBP-260426-001".
        date_str:      Bill date in DD-MM-YYYY; auto-filled if empty.
        time_str:      Bill time in HH:MM; auto-filled if empty.
    Returns:
        Temp file path (caller must delete).
    """
    font = _register_tamil_font()
    now = datetime.now()
    date_str = date_str or now.strftime("%d-%m-%Y")
    time_str = time_str or now.strftime("%H:%M")

    # Pink / rose color scheme for beauty/service bills
    PINK      = colors.HexColor("#880e4f")
    PINK_DARK = colors.HexColor("#c2185b")
    STRIPE    = colors.HexColor("#fce4ec")
    GRID_CLR  = colors.HexColor("#f48fb1")

    s_shop   = _ps("SShop",  font, fontSize=18, alignment=1, textColor=PINK,      spaceAfter=2)
    s_sub    = _ps("SSub",   font, fontSize=10, alignment=1, textColor=PINK_DARK, spaceAfter=3)
    s_meta   = _ps("SMeta",  font, fontSize=9,  alignment=1, textColor=colors.grey, spaceAfter=2)
    s_label  = _ps("SLabel", font, fontSize=9,  alignment=0, textColor=colors.HexColor("#444444"))
    s_footer = _ps("SFoot",  font, fontSize=8,  alignment=1, textColor=PINK_DARK)
    s_th     = _ps("STH",    font, fontSize=10, textColor=colors.white, alignment=1)
    s_td_c   = _ps("STDC",   font, fontSize=9,  alignment=1)
    s_td_l   = _ps("STDL",   font, fontSize=9,  alignment=0)
    s_total  = _ps("STot",   font, fontSize=11, textColor=colors.white, alignment=1)

    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.close()
    doc = _build_doc(tmp.name)

    story = []

    # Header
    story.append(_p(shop_name.upper(), s_shop))
    story.append(_p("Service Invoice", s_sub))
    story.append(HRFlowable(width="100%", thickness=2, color=PINK, spaceAfter=6))

    # Bill meta info table (2-column layout)
    meta_rows = [
        ["Roll No:",    bill_number,   "Date:", date_str],
        ["Customer:",   customer_name, "Time:", time_str],
    ]
    meta_table = Table(meta_rows, colWidths=[3 * cm, 6 * cm, 2.5 * cm, 4.5 * cm])
    meta_table.setStyle(TableStyle([
        ("FONTNAME",    (0, 0), (-1, -1), font),
        ("FONTSIZE",    (0, 0), (-1, -1), 9),
        ("TEXTCOLOR",   (0, 0), (0, -1), PINK),
        ("TEXTCOLOR",   (2, 0), (2, -1), PINK),
        ("FONTNAME",    (0, 0), (0, -1), font),
        ("FONTNAME",    (2, 0), (2, -1), font),
        ("TOPPADDING",  (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 0.4 * cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=GRID_CLR, spaceAfter=6))

    # Services table
    col_widths = [1.2 * cm, 9 * cm, 5.8 * cm]
    rows: list[list] = [[
        _p("S.No", s_th),
        _p("Service", s_th),
        _p("Amount (&#8377;)", s_th),
    ]]

    grand_total = 0.0
    for idx, svc in enumerate(services, 1):
        qty    = float(svc.get("qty", 1))
        rate   = float(svc.get("rate", 0))
        amount = qty * rate
        grand_total += amount
        rows.append([
            _p(str(idx), s_td_c),
            _p(str(svc.get("item", "")), s_td_l),
            _p(f"{amount:.2f}", s_td_c),
        ])

    rows.append([
        _p("", s_total),
        _p("Total Amount", s_total),
        _p(f"&#8377; {grand_total:.2f}", s_total),
    ])

    table = Table(rows, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ("BACKGROUND",    (0, 0),  (-1, 0),  PINK),
        ("ROWHEIGHT",      (0, 0),  (-1, 0),  24),
        ("BACKGROUND",    (0, -1), (-1, -1), PINK_DARK),
        ("ROWHEIGHT",      (0, -1), (-1, -1), 26),
        ("GRID",           (0, 0),  (-1, -2), 0.5, GRID_CLR),
        ("LINEABOVE",      (0, -1), (-1, -1), 1.5, PINK),
        ("VALIGN",         (0, 0),  (-1, -1), "MIDDLE"),
        ("LEFTPADDING",    (0, 0),  (-1, -1), 6),
        ("RIGHTPADDING",   (0, 0),  (-1, -1), 6),
        ("TOPPADDING",     (0, 0),  (-1, -1), 5),
        ("BOTTOMPADDING",  (0, 0),  (-1, -1), 5),
    ]
    for i in range(1, len(rows) - 1):
        style_cmds.append(("BACKGROUND", (0, i), (-1, i),
                           colors.white if i % 2 == 1 else STRIPE))
    table.setStyle(TableStyle(style_cmds))
    story.append(table)
    story.append(Spacer(1, 0.8 * cm))

    # Footer
    story.append(HRFlowable(width="100%", thickness=0.5, color=GRID_CLR))
    story.append(Spacer(1, 0.2 * cm))
    story.append(_p("We care for your beauty – Visit again! &#10084;", s_footer))
    story.append(_p(f"Generated by GroceryBot &bull; {now.strftime('%Y')}", s_footer))

    doc.build(story)
    logger.info(
        "Service PDF: %s | shop=%s | roll=%s | total=%.2f",
        tmp.name, shop_name, bill_number, grand_total,
    )
    return tmp.name


# ── C. Monthly Expense Summary PDF ───────────────────────────────────────────


def generate_expense_summary_pdf(
    expenses: list[dict],
    month_label: str,
    user_name: str = "",
    chart_path: str | None = None,
) -> str:
    """Build a monthly expense report PDF; return temp file path.

    Title: "Ragul's Monthly Expense Report – {month_label}"
    """
    font = _register_tamil_font()

    NAVY      = colors.HexColor("#1a237e")
    NAVY_DARK = colors.HexColor("#283593")
    STRIPE    = colors.HexColor("#e8eaf6")
    GRID_CLR  = colors.HexColor("#c5cae9")

    def sp(name, **kw):
        return ParagraphStyle(name, fontName=font, **kw)

    s_title   = sp("ET",  fontSize=18, alignment=1, textColor=NAVY,      spaceAfter=2)
    s_sub     = sp("ES",  fontSize=11, alignment=1, textColor=NAVY_DARK,  spaceAfter=3)
    s_meta    = sp("EM",  fontSize=9,  alignment=1, textColor=colors.grey, spaceAfter=2)
    s_footer  = sp("EF",  fontSize=8,  alignment=1, textColor=colors.grey)
    s_th      = sp("ETH", fontSize=10, textColor=colors.white, alignment=1)
    s_td_c    = sp("ETC", fontSize=9,  alignment=1)
    s_td_l    = sp("ETL", fontSize=9,  alignment=0)
    s_cat_hdr = sp("ECH", fontSize=12, textColor=NAVY,  spaceAfter=4, spaceBefore=8)
    s_total   = sp("ETot",fontSize=11, textColor=colors.white, alignment=1)

    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.close()
    doc = _build_doc(tmp.name)

    now = datetime.now()
    story: list = []

    story.append(Paragraph("Ragul's Monthly Expense Report", s_title))
    story.append(Paragraph(month_label, s_sub))
    if user_name:
        story.append(Paragraph(f"Prepared for: {user_name}", s_meta))
    story.append(Paragraph(f"Generated: {now.strftime('%d-%m-%Y %H:%M')}", s_meta))
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

    story.append(Paragraph("Category Breakdown", s_cat_hdr))

    cat_rows: list[list] = [[
        Paragraph("Category", s_th),
        Paragraph("Total (&#8377;)", s_th),
        Paragraph("% of Spend", s_th),
    ]]
    for cat, total in sorted(category_totals.items(), key=lambda x: x[1], reverse=True):
        pct = (total / grand_total * 100) if grand_total > 0 else 0
        cat_rows.append([
            Paragraph(cat, s_td_l),
            Paragraph(f"{total:,.2f}", s_td_c),
            Paragraph(f"{pct:.1f}%", s_td_c),
        ])
    cat_rows.append([
        Paragraph("Grand Total", s_total),
        Paragraph(f"&#8377; {grand_total:,.2f}", s_total),
        Paragraph("100%", s_total),
    ])

    cat_table = Table(cat_rows, colWidths=[8 * cm, 4 * cm, 4 * cm])
    cat_style = [
        ("BACKGROUND",    (0, 0),  (-1, 0),  NAVY),
        ("BACKGROUND",    (0, -1), (-1, -1), NAVY_DARK),
        ("GRID",           (0, 0),  (-1, -2), 0.5, GRID_CLR),
        ("LINEABOVE",      (0, -1), (-1, -1), 1.5, NAVY),
        ("VALIGN",         (0, 0),  (-1, -1), "MIDDLE"),
        ("LEFTPADDING",    (0, 0),  (-1, -1), 6),
        ("RIGHTPADDING",   (0, 0),  (-1, -1), 6),
        ("TOPPADDING",     (0, 0),  (-1, -1), 5),
        ("BOTTOMPADDING",  (0, 0),  (-1, -1), 5),
    ]
    for i in range(1, len(cat_rows) - 1):
        cat_style.append(("BACKGROUND", (0, i), (-1, i),
                          colors.white if i % 2 == 1 else STRIPE))
    cat_table.setStyle(TableStyle(cat_style))
    story.append(cat_table)
    story.append(Spacer(1, 0.8 * cm))

    # All transactions detail
    story.append(Paragraph("All Transactions", s_cat_hdr))

    det_rows: list[list] = [[
        Paragraph("Date", s_th),
        Paragraph("Category", s_th),
        Paragraph("Note", s_th),
        Paragraph("Amount (&#8377;)", s_th),
    ]]
    for row in expenses:
        det_rows.append([
            Paragraph(str(row.get("Date", "")), s_td_c),
            Paragraph(str(row.get("Category", "")).capitalize(), s_td_c),
            Paragraph(str(row.get("Note", "")), s_td_l),
            Paragraph(f"{float(row.get('Amount', 0)):,.2f}", s_td_c),
        ])

    det_table = Table(det_rows, colWidths=[3 * cm, 3.5 * cm, 6 * cm, 3.5 * cm])
    det_style = [
        ("BACKGROUND",    (0, 0),  (-1, 0),  NAVY),
        ("GRID",           (0, 0),  (-1, -1), 0.5, GRID_CLR),
        ("VALIGN",         (0, 0),  (-1, -1), "MIDDLE"),
        ("LEFTPADDING",    (0, 0),  (-1, -1), 5),
        ("RIGHTPADDING",   (0, 0),  (-1, -1), 5),
        ("TOPPADDING",     (0, 0),  (-1, -1), 4),
        ("BOTTOMPADDING",  (0, 0),  (-1, -1), 4),
    ]
    for i in range(1, len(det_rows)):
        det_style.append(("BACKGROUND", (0, i), (-1, i),
                          colors.white if i % 2 == 1 else STRIPE))
    det_table.setStyle(TableStyle(det_style))
    story.append(det_table)
    story.append(Spacer(1, 0.8 * cm))

    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph(f"GroceryBot Expense Tracker &bull; {now.strftime('%Y')}", s_footer))

    doc.build(story)
    logger.info("Expense PDF: %s | total=%.2f | rows=%d", tmp.name, grand_total, len(expenses))
    return tmp.name


# ── backward-compat alias ─────────────────────────────────────────────────────


def generate_bill_pdf(items: list[dict], language: str = "en") -> str:
    """Backward-compatible alias — delegates to generate_grocery_bill().

    Always generates an English-first grocery bill.
    """
    return generate_grocery_bill(items, lang="en")
