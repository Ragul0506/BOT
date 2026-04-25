"""PDF generators — grocery bill and expense summary — with Tamil Unicode font."""
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
    """Register the Tamil font once and return the font name to use."""
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


# ── helpers ──────────────────────────────────────────────────────────────────


def _ps(name: str, font: str, **kw) -> ParagraphStyle:
    return ParagraphStyle(name, fontName=font, **kw)


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text, style)


# ── public API ────────────────────────────────────────────────────────────────


def generate_bill_pdf(items: list[dict]) -> str:
    """Build a PDF invoice and return its temp-file path (caller must delete)."""
    font = _register_tamil_font()

    # ── styles ────────────────────────────────────────────────────────────────
    NAVY = colors.HexColor("#1a237e")
    NAVY_DARK = colors.HexColor("#283593")
    STRIPE = colors.HexColor("#e8eaf6")
    GRID_CLR = colors.HexColor("#c5cae9")

    s_shop = _ps("ShopName", font, fontSize=20, alignment=1, textColor=NAVY, spaceAfter=2)
    s_sub = _ps("Sub", font, fontSize=11, alignment=1, textColor=NAVY_DARK, spaceAfter=3)
    s_meta = _ps("Meta", font, fontSize=9, alignment=1, textColor=colors.grey, spaceAfter=2)
    s_footer = _ps("Footer", font, fontSize=8, alignment=1, textColor=colors.grey)

    s_th = _ps("TH", font, fontSize=10, textColor=colors.white, alignment=1)
    s_td_c = _ps("TDC", font, fontSize=9, alignment=1)        # centred data cell
    s_td_l = _ps("TDL", font, fontSize=9, alignment=0)        # left-aligned item name
    s_total = _ps("Tot", font, fontSize=10, textColor=colors.white, alignment=1)

    # ── page setup ────────────────────────────────────────────────────────────
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.close()

    doc = SimpleDocTemplate(
        tmp.name,
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
    )

    now = datetime.now()
    story = []

    # ── header ────────────────────────────────────────────────────────────────
    story.append(_p("கிராம மளிகை கடை", s_shop))
    story.append(_p("VILLAGE GROCERY STORE", s_sub))
    story.append(_p("&#128222; +91 99999 99999 &nbsp;|&nbsp; Main Road, Tamil Nadu", s_meta))
    story.append(HRFlowable(width="100%", thickness=1.5, color=NAVY, spaceAfter=6))
    story.append(_p(
        f"Bill Date: {now.strftime('%d-%m-%Y')} &nbsp; | &nbsp; "
        f"Time: {now.strftime('%H:%M')} &nbsp; | &nbsp; "
        f"Bill No: {now.strftime('%Y%m%d%H%M')}",
        s_meta,
    ))
    story.append(Spacer(1, 0.5 * cm))

    # ── item table ────────────────────────────────────────────────────────────
    col_widths = [1.2 * cm, 7.5 * cm, 2 * cm, 3 * cm, 3 * cm]

    rows: list[list] = [[
        _p("S.No", s_th),
        _p("பொருள் / Item", s_th),
        _p("Qty", s_th),
        _p("Rate (&#8377;)", s_th),
        _p("Amount (&#8377;)", s_th),
    ]]

    grand_total = 0.0
    for idx, item in enumerate(items, 1):
        qty = float(item.get("qty", 1))
        rate = float(item.get("rate", 0))
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
        _p("", s_total),
        _p("", s_total),
        _p("", s_total),
        _p("மொத்தம் / Total", s_total),
        _p(f"&#8377; {grand_total:.2f}", s_total),
    ])

    table = Table(rows, colWidths=col_widths, repeatRows=1)

    # Build TableStyle dynamically for alternating row colours
    style_cmds = [
        # Header
        ("BACKGROUND",   (0, 0),  (-1, 0),  NAVY),
        ("ROWHEIGHT",     (0, 0),  (-1, 0),  24),
        # Totals
        ("BACKGROUND",   (0, -1), (-1, -1), NAVY_DARK),
        ("ROWHEIGHT",     (0, -1), (-1, -1), 24),
        # Grid on data rows only
        ("GRID",          (0, 0),  (-1, -2), 0.5, GRID_CLR),
        ("LINEABOVE",     (0, -1), (-1, -1), 1.5, NAVY),
        # Alignment & padding
        ("VALIGN",        (0, 0),  (-1, -1), "MIDDLE"),
        ("LEFTPADDING",   (0, 0),  (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0),  (-1, -1), 6),
        ("TOPPADDING",    (0, 0),  (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0),  (-1, -1), 5),
    ]

    # Alternating row stripes (skip header row 0 and totals row -1)
    for i in range(1, len(rows) - 1):
        bg = colors.white if i % 2 == 1 else STRIPE
        style_cmds.append(("BACKGROUND", (0, i), (-1, i), bg))

    table.setStyle(TableStyle(style_cmds))
    story.append(table)
    story.append(Spacer(1, 0.8 * cm))

    # ── footer ────────────────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    story.append(Spacer(1, 0.2 * cm))
    story.append(_p("நன்றி! மீண்டும் வாருங்கள் &#128591;", s_footer))
    story.append(_p("Thank you for shopping with us. Visit Again!", s_footer))
    story.append(_p(f"Generated by GroceryBot &bull; {now.strftime('%Y')}", s_footer))

    doc.build(story)
    logger.info("PDF ready: %s  |  Grand total: %.2f", tmp.name, grand_total)
    return tmp.name


# ── Expense summary PDF ───────────────────────────────────────────────────────


def generate_expense_summary_pdf(
    expenses: list[dict],
    month_label: str,
    user_name: str = "",
    chart_path: str | None = None,
) -> str:
    """Build a monthly expense summary PDF; return temp-file path.

    Args:
        expenses:    List of {'Date','Amount','Category','Note'} dicts from Sheets.
        month_label: Human-readable label like "January 2024".
        user_name:   Optional display name for the header.
        chart_path:  Optional path to a matplotlib PNG chart to embed.
    """
    font = _register_tamil_font()

    NAVY = colors.HexColor("#1a237e")
    NAVY_DARK = colors.HexColor("#283593")
    STRIPE = colors.HexColor("#e8eaf6")
    GRID_CLR = colors.HexColor("#c5cae9")

    def sp(name, **kw):
        return ParagraphStyle(name, fontName=font, **kw)

    s_title = sp("ET", fontSize=20, alignment=1, textColor=NAVY, spaceAfter=2)
    s_sub = sp("ES", fontSize=11, alignment=1, textColor=NAVY_DARK, spaceAfter=3)
    s_meta = sp("EM", fontSize=9, alignment=1, textColor=colors.grey, spaceAfter=2)
    s_footer = sp("EF", fontSize=8, alignment=1, textColor=colors.grey)
    s_th = sp("ETH", fontSize=10, textColor=colors.white, alignment=1)
    s_td_c = sp("ETC", fontSize=9, alignment=1)
    s_td_l = sp("ETL", fontSize=9, alignment=0)
    s_cat_hdr = sp("ECH", fontSize=12, textColor=NAVY, spaceAfter=4, spaceBefore=8)
    s_total = sp("ETot", fontSize=11, textColor=colors.white, alignment=1)

    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.close()

    doc = SimpleDocTemplate(
        tmp.name,
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
    )

    now = datetime.now()
    story: list = []

    # ── header ────────────────────────────────────────────────────────────────
    story.append(Paragraph("செலவு சுருக்கம்", s_title))
    story.append(Paragraph(f"Expense Summary — {month_label}", s_sub))
    if user_name:
        story.append(Paragraph(f"User: {user_name}", s_meta))
    story.append(Paragraph(f"Generated: {now.strftime('%d-%m-%Y %H:%M')}", s_meta))
    story.append(HRFlowable(width="100%", thickness=1.5, color=NAVY, spaceAfter=8))

    # ── embedded chart ────────────────────────────────────────────────────────
    if chart_path and os.path.exists(chart_path):
        story.append(RLImage(chart_path, width=16 * cm, height=8 * cm))
        story.append(Spacer(1, 0.5 * cm))

    # ── compute totals ────────────────────────────────────────────────────────
    category_totals: dict[str, float] = defaultdict(float)
    grand_total = 0.0
    for row in expenses:
        amt = float(row.get("Amount", 0))
        cat = str(row.get("Category", "general")).capitalize()
        category_totals[cat] += amt
        grand_total += amt

    # ── category summary table ────────────────────────────────────────────────
    story.append(Paragraph("Category Breakdown", s_cat_hdr))

    cat_rows: list[list] = [[
        Paragraph("Category", s_th),
        Paragraph("Total (&#8377;)", s_th),
        Paragraph("% of spend", s_th),
    ]]
    for cat, total in sorted(category_totals.items(), key=lambda x: x[1], reverse=True):
        pct = (total / grand_total * 100) if grand_total > 0 else 0
        cat_rows.append([
            Paragraph(cat, s_td_l),
            Paragraph(f"{total:,.2f}", s_td_c),
            Paragraph(f"{pct:.1f}%", s_td_c),
        ])
    cat_rows.append([
        Paragraph("மொத்தம் / Grand Total", s_total),
        Paragraph(f"&#8377; {grand_total:,.2f}", s_total),
        Paragraph("100%", s_total),
    ])

    cat_table = Table(cat_rows, colWidths=[8 * cm, 4 * cm, 4 * cm])
    cat_style = [
        ("BACKGROUND",   (0, 0),  (-1, 0),  NAVY),
        ("BACKGROUND",   (0, -1), (-1, -1), NAVY_DARK),
        ("GRID",          (0, 0),  (-1, -2), 0.5, GRID_CLR),
        ("LINEABOVE",     (0, -1), (-1, -1), 1.5, NAVY),
        ("VALIGN",        (0, 0),  (-1, -1), "MIDDLE"),
        ("LEFTPADDING",   (0, 0),  (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0),  (-1, -1), 6),
        ("TOPPADDING",    (0, 0),  (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0),  (-1, -1), 5),
    ]
    for i in range(1, len(cat_rows) - 1):
        cat_style.append(("BACKGROUND", (0, i), (-1, i),
                           colors.white if i % 2 == 1 else STRIPE))
    cat_table.setStyle(TableStyle(cat_style))
    story.append(cat_table)
    story.append(Spacer(1, 0.8 * cm))

    # ── detailed transactions ─────────────────────────────────────────────────
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
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID",        (0, 0), (-1, -1), 0.5, GRID_CLR),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",(0, 0), (-1, -1), 5),
        ("TOPPADDING",  (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0),(-1, -1), 4),
    ]
    for i in range(1, len(det_rows)):
        det_style.append(("BACKGROUND", (0, i), (-1, i),
                           colors.white if i % 2 == 1 else STRIPE))
    det_table.setStyle(TableStyle(det_style))
    story.append(det_table)
    story.append(Spacer(1, 0.8 * cm))

    # ── footer ────────────────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph(f"GroceryBot Expense Tracker &bull; {now.strftime('%Y')}", s_footer))

    doc.build(story)
    logger.info("Expense PDF: %s | total=%.2f | rows=%d", tmp.name, grand_total, len(expenses))
    return tmp.name
