"""PDF generators — grocery bill, service invoice, and expense summary.

Functions:
  generate_grocery_bill(items, bill_number, lang)                  → grocery PDF
  generate_service_bill(shop_name, shop_address, ...)              → professional Tax Invoice PDF
  generate_expense_summary_pdf(expenses, month_label, …)           → monthly expense report
  generate_bill_pdf(items, language)                               → backward-compat alias
  next_service_roll_number(shop_name, date_obj)                    → "SNBP-260426-001"

Design notes:
  • generate_service_bill() uses ReportLab canvas with drawString exclusively —
    no XML Paragraph escaping issues, pixel-perfect professional salon layout.
  • Grocery bill and expense report use Platypus (unchanged).
  • All fonts are built-in Helvetica — no external font files required.
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

_FONT      = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"

# Monotonically increasing counter prevents ReportLab style registry collisions
_style_seq = _count(1)


def _uid() -> str:
    return str(next(_style_seq))


def safe_text(value) -> str:
    """Sanitise value for ReportLab Paragraph (HTML-escape + strip control chars)."""
    s = _html.escape(str(value), quote=False)
    s = "".join(c if c >= " " or c in "\t\n" else " " for c in s)
    return s


_e = safe_text


def _ps(name: str, bold: bool = False, **kw) -> ParagraphStyle:
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


# ── Theme palette deriver ─────────────────────────────────────────────────────

def _theme_palette(hex_color: str):
    """Derive 7 ReportLab colors from a single hex theme color.

    Returns: (C_DK, C_MD, C_LT, C_STRIPE, C_ACCENT, C_BORDER, C_SUBTITLE)
    """
    raw = (hex_color or "#E91E63").lstrip('#')
    if len(raw) == 3:
        raw = raw[0]*2 + raw[1]*2 + raw[2]*2
    if len(raw) != 6:
        raw = "E91E63"
    try:
        r, g, b = int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)
    except ValueError:
        r, g, b = 233, 30, 99  # fallback pink

    def _hc(rr, gg, bb):
        return colors.HexColor('#{:02X}{:02X}{:02X}'.format(
            max(0, min(255, rr)), max(0, min(255, gg)), max(0, min(255, bb))
        ))

    def dk(f):
        return _hc(int(r * f), int(g * f), int(b * f))

    def lt(f):
        return _hc(int(r + (255 - r) * f), int(g + (255 - g) * f), int(b + (255 - b) * f))

    return (
        dk(0.55),      # C_DK     — dark shade  (header band bg, footer text)
        dk(0.78),      # C_MD     — medium shade (table header, highlight rows)
        lt(0.85),      # C_LT     — pale pastel  (info box bg, summary bg)
        lt(0.93),      # C_STRIPE — near-white   (alternate data rows)
        _hc(r, g, b),  # C_ACCENT — full color   (TAX INVOICE badge, footer line)
        lt(0.60),      # C_BORDER — tinted       (grid lines, box borders)
        lt(0.65),      # C_SUBTITLE — light on dark header
    )


# ── service roll-number generator ─────────────────────────────────────────────

_service_counters: dict[str, int] = defaultdict(int)


def _shop_prefix(shop_name: str) -> str:
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

_GROCERY_COL_WIDTHS = [1.5 * cm, 7.3 * cm, 2.0 * cm, 3.6 * cm, 3.6 * cm]


def generate_grocery_bill(
    items: list[dict],
    bill_number: str = "",
    lang: str = "en",
) -> str:
    """Build a clean grocery/shopping bill PDF. Returns temp file path."""
    NAVY      = colors.HexColor("#1a237e")
    NAVY_DARK = colors.HexColor("#283593")
    STRIPE    = colors.HexColor("#e8eaf6")
    GRID      = colors.HexColor("#c5cae9")

    s_shop = _ps("GShop", bold=True, fontSize=22, alignment=1, textColor=NAVY,        spaceAfter=2)
    s_sub  = _ps("GSub",             fontSize=11, alignment=1, textColor=NAVY_DARK,   spaceAfter=3)
    s_meta = _ps("GMeta",            fontSize=9,  alignment=1, textColor=colors.grey, spaceAfter=2)
    s_foot = _ps("GFoot",            fontSize=8,  alignment=1, textColor=colors.grey)
    s_th   = _ps("GTH",   bold=True, fontSize=10, alignment=1, textColor=colors.white)
    s_tdc  = _ps("GTDC",             fontSize=9,  alignment=1)
    s_tdl  = _ps("GTDL",             fontSize=9,  alignment=0)
    s_tot  = _ps("GTot",  bold=True, fontSize=10, alignment=1, textColor=colors.white)

    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.close()
    doc = _build_doc(tmp.name)
    now = datetime.now()
    bill_no = _e(bill_number or now.strftime("%Y%m%d%H%M"))

    story: list = []

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
            _p(str(idx),         s_tdc),
            _p(name,             s_tdl),
            _p(f"{qty:g}",       s_tdc),
            _p(f"{rate:.2f}",    s_tdc),
            _p(f"{amount:.2f}",  s_tdc),
        ])

    rows.append([
        _p("", s_tot), _p("", s_tot), _p("", s_tot),
        _p("Total",                            s_tot),
        _p(f"&#8377;&nbsp;{grand_total:.2f}",  s_tot),
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


# ── B. Professional Service / Salon Tax Invoice (canvas) ──────────────────────


def generate_service_bill(
    shop_name: str,
    shop_address: str = "",
    shop_phone: str = "",
    shop_gst: str = "",
    shop_discount_percent: float = 0.0,
    customer_name: str = "",
    customer_mobile: str = "",
    services: list[dict] | None = None,
    total: float = 0.0,
    roll_number: str = "",
    date_str: str = "",
    time_str: str = "",
    logo_path: str | None = None,
    footer: str | None = None,
    discount_amount: float = 0.0,
    gst_percent: float = 0.0,
    advance: float = 0.0,
    lang: str = "en",
    theme_color: str = "#E91E63",
    # backward-compat alias
    bill_number: str = "",
) -> str:
    """Build a professional salon Tax Invoice PDF using ReportLab canvas.

    Returns temp file path — caller is responsible for deletion.
    """
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.utils import ImageReader

    services = services or []
    now = datetime.now()
    date_str  = date_str  or now.strftime("%d-%m-%Y")
    time_str  = time_str  or now.strftime("%H:%M")
    footer    = footer    or "Thank you for your visit! Please come again."
    roll_number = roll_number or bill_number or now.strftime("%Y%m%d%H%M")

    # ── Financial calculations ─────────────────────────────────────────────────
    basic_sales = sum(
        float(s.get("qty", 1)) * float(s.get("rate", 0)) for s in services
    )
    if basic_sales == 0 and total > 0:
        basic_sales = total

    if discount_amount <= 0 and shop_discount_percent > 0:
        discount_amount = round(basic_sales * shop_discount_percent / 100, 2)

    subtotal   = basic_sales - discount_amount
    gst_amount = round(subtotal * gst_percent / 100, 2) if gst_percent > 0 else 0.0
    net_amount = subtotal + gst_amount
    balance_due = net_amount - advance

    # ── Colors ────────────────────────────────────────────────────────────────
    (C_DK_GREEN, C_MD_GREEN, C_LT_GREEN,
     C_STRIPE, C_GOLD, C_BORDER, C_SUBTITLE) = _theme_palette(theme_color)
    C_DARK  = colors.HexColor("#212121")
    C_MID   = colors.HexColor("#424242")
    C_GREY  = colors.HexColor("#9E9E9E")
    C_WHITE = colors.white

    # ── Page setup ────────────────────────────────────────────────────────────
    W, H = A4   # 595.27 x 841.89 pt
    LM   = 40.0
    RM   = W - 40.0
    CW   = RM - LM  # 515.27

    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.close()
    c = rl_canvas.Canvas(tmp.name, pagesize=A4)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _t(v) -> str:
        """Strip control chars for drawString (no XML escaping needed)."""
        return "".join(ch if ch >= " " else " " for ch in str(v))

    def txt(x, y, s, font=_FONT, size=10, color=C_DARK, align="left"):
        c.setFont(font, size)
        c.setFillColor(color)
        s = _t(s)
        if align == "right":
            c.drawRightString(x, y, s)
        elif align == "center":
            c.drawCentredString(x, y, s)
        else:
            c.drawString(x, y, s)

    def hline(y, clr=C_BORDER, lw=0.5):
        c.setStrokeColor(clr)
        c.setLineWidth(lw)
        c.line(LM, y, RM, y)

    def filled_rect(x, y_bot, w, h, fill=C_LT_GREEN, stroke=C_BORDER, sw=0.5):
        c.setFillColor(fill)
        c.setStrokeColor(stroke)
        c.setLineWidth(sw)
        c.rect(x, y_bot, w, h, fill=1, stroke=1)

    # ── SECTION 1: HEADER BAND ────────────────────────────────────────────────
    HDR_H = 64
    c.setFillColor(C_DK_GREEN)
    c.rect(0, H - HDR_H, W, HDR_H, fill=1, stroke=0)

    # Logo (optional)
    name_center_x = W / 2
    if logo_path and os.path.exists(logo_path):
        try:
            logo_sz = 52
            c.drawImage(
                ImageReader(logo_path),
                LM, H - HDR_H + 6,
                width=logo_sz, height=logo_sz,
                preserveAspectRatio=True, mask="auto",
            )
            name_center_x = (LM + logo_sz + 8 + RM) / 2
        except Exception as exc:
            logger.warning("Logo draw failed: %s", exc)

    # "TAX INVOICE" gold badge — top right
    badge_w, badge_h = 82, 18
    bx = RM - badge_w
    by = H - 24
    c.setFillColor(C_GOLD)
    c.roundRect(bx, by, badge_w, badge_h, 3, fill=1, stroke=0)
    txt(bx + badge_w / 2, by + 5, "TAX INVOICE",
        font=_FONT_BOLD, size=8, color=C_DARK, align="center")

    # Shop name
    txt(name_center_x, H - 24, shop_name.upper(),
        font=_FONT_BOLD, size=17, color=C_WHITE, align="center")

    # Subtitle
    txt(name_center_x, H - 44, "BEAUTY PARLOUR & STYLE CENTRE",
        font=_FONT, size=9.5, color=C_SUBTITLE, align="center")

    y = H - HDR_H - 8

    # ── SECTION 2: TWO-COLUMN INFO BOXES ─────────────────────────────────────
    BOX_H = 80
    BOX_W = (CW - 6) / 2   # ~254.6

    lbox_x = LM
    rbox_x = LM + BOX_W + 6
    box_bot = y - BOX_H

    # Left box: shop details
    filled_rect(lbox_x, box_bot, BOX_W, BOX_H, fill=C_WHITE, stroke=C_BORDER, sw=0.7)
    # Right box: bill details
    filled_rect(rbox_x, box_bot, BOX_W, BOX_H, fill=C_LT_GREEN, stroke=C_BORDER, sw=0.7)

    # Left box content
    ty = y - 10
    txt(lbox_x + 6, ty, "SHOP DETAILS", font=_FONT_BOLD, size=8, color=C_DK_GREEN)
    ty -= 13

    if shop_address:
        addr = shop_address
        max_ch = 38
        lines_drawn = 0
        while addr and lines_drawn < 3:
            chunk = addr[:max_ch]
            if len(addr) > max_ch:
                sp = chunk.rfind(" ")
                if sp > 8:
                    chunk = chunk[:sp]
            txt(lbox_x + 6, ty, chunk, size=8.5, color=C_MID)
            addr = addr[len(chunk):].strip()
            ty -= 11
            lines_drawn += 1

    if shop_phone:
        txt(lbox_x + 6, ty, f"Ph: {shop_phone}", size=8.5, color=C_MID)
        ty -= 11
    if shop_gst:
        txt(lbox_x + 6, ty, f"GST No: {shop_gst}", size=8, color=C_GREY)

    # Right box content
    ty = y - 10
    txt(rbox_x + 6, ty, "BILL DETAILS", font=_FONT_BOLD, size=8, color=C_DK_GREEN)
    ty -= 13

    lbl_x = rbox_x + 6
    val_x = rbox_x + BOX_W - 6
    meta = [
        ("BILL DATE",  f"{date_str}  {time_str}"),
        ("INVOICE NO", roll_number),
        ("CUSTOMER",   customer_name or "Valued Customer"),
        ("PHONE NO",   customer_mobile or "-"),
    ]
    for lbl, val in meta:
        txt(lbl_x, ty, f"{lbl} :", font=_FONT_BOLD, size=8.5, color=C_MID)
        txt(val_x, ty, _t(val)[:28], size=8.5, color=C_DARK, align="right")
        ty -= 12

    y = box_bot - 8

    # ── SECTION 3: ITEMS TABLE ────────────────────────────────────────────────
    # Columns: PARTICULAR(270) | QTY(50) | RATE(95) | AMOUNT(100) — total 515
    COL_W = [270, 50, 95, 100]
    COL_X = [LM, LM + 270, LM + 320, LM + 415]
    ROW_H = 20

    # Header row
    hdr_top = y
    filled_rect(LM, hdr_top - ROW_H, CW, ROW_H, fill=C_MD_GREEN, stroke=C_MD_GREEN, sw=0)

    # Column separators in header
    c.setStrokeColor(C_DK_GREEN)
    c.setLineWidth(0.5)
    for cx in COL_X[1:]:
        c.line(cx, hdr_top, cx, hdr_top - ROW_H)

    hy = hdr_top - 13
    txt(COL_X[0] + 6,                 hy, "PARTICULAR",    font=_FONT_BOLD, size=9, color=C_WHITE)
    txt(COL_X[1] + COL_W[1] / 2,      hy, "QTY",           font=_FONT_BOLD, size=9, color=C_WHITE, align="center")
    txt(COL_X[2] + COL_W[2] - 5,      hy, "RATE",          font=_FONT_BOLD, size=9, color=C_WHITE, align="right")
    txt(COL_X[3] + COL_W[3] - 5,      hy, "AMOUNT (Rs.)",  font=_FONT_BOLD, size=9, color=C_WHITE, align="right")

    y = hdr_top - ROW_H

    # Data rows
    for idx, svc in enumerate(services):
        item_name = _t(str(svc.get("item", "")))
        qty       = float(svc.get("qty", 1))
        rate      = float(svc.get("rate", 0))
        amount    = qty * rate

        row_fill = C_WHITE if idx % 2 == 0 else C_STRIPE
        filled_rect(LM, y - ROW_H, CW, ROW_H, fill=row_fill, stroke=C_BORDER, sw=0.3)

        c.setStrokeColor(C_BORDER)
        c.setLineWidth(0.3)
        for cx in COL_X[1:]:
            c.line(cx, y, cx, y - ROW_H)

        ry = y - 13
        txt(COL_X[0] + 6,            ry, item_name[:42],    size=9, color=C_DARK)
        txt(COL_X[1] + COL_W[1] / 2, ry, f"{qty:g}",        size=9, color=C_DARK, align="center")
        txt(COL_X[2] + COL_W[2] - 5, ry, f"{rate:,.2f}",    size=9, color=C_DARK, align="right")
        txt(COL_X[3] + COL_W[3] - 5, ry, f"{amount:,.2f}",  size=9, color=C_DARK, align="right")

        y -= ROW_H

    # Table outer border
    c.setStrokeColor(C_MD_GREEN)
    c.setLineWidth(1.0)
    c.rect(LM, y, CW, hdr_top - y, fill=0, stroke=1)

    y -= 10

    # ── SECTION 4: FINANCIAL SUMMARY ─────────────────────────────────────────
    SUM_BOX_W = 250
    SUM_X     = RM - SUM_BOX_W
    SUM_ROW_H = 17

    # Build summary rows
    sum_rows: list[tuple[str, str, bool]] = []
    sum_rows.append(("BASIC SALES AMT", f"{basic_sales:,.2f}", False))

    if discount_amount > 0:
        if shop_discount_percent > 0 and abs(discount_amount - basic_sales * shop_discount_percent / 100) < 0.01:
            dlbl = f"DISCOUNT ({shop_discount_percent:.0f}%)"
        else:
            dlbl = "DISCOUNT"
        sum_rows.append((dlbl, f"- {discount_amount:,.2f}", False))

    sum_rows.append(("SUBTOTAL", f"{subtotal:,.2f}", False))

    if gst_percent > 0:
        sum_rows.append((f"GST TAX ({gst_percent:.0f}%)", f"{gst_amount:,.2f}", False))

    sum_rows.append(("NET AMOUNT", f"{net_amount:,.2f}", True))

    if advance > 0:
        sum_rows.append(("ADVANCE", f"- {advance:,.2f}", False))
        sum_rows.append(("BALANCE DUE", f"{balance_due:,.2f}", True))

    SUM_H = len(sum_rows) * SUM_ROW_H + 10
    filled_rect(SUM_X, y - SUM_H, SUM_BOX_W, SUM_H, fill=C_LT_GREEN, stroke=C_MD_GREEN, sw=0.8)

    # Separator line inside summary box between items
    sy = y - 6
    for label, value, is_bold in sum_rows:
        font_use  = _FONT_BOLD if is_bold else _FONT
        color_use = C_DARK

        # Highlight NET AMOUNT and BALANCE DUE rows
        if is_bold:
            hl_color = C_MD_GREEN if label == "NET AMOUNT" else C_DK_GREEN
            c.setFillColor(hl_color)
            c.rect(SUM_X, sy - SUM_ROW_H + 3, SUM_BOX_W, SUM_ROW_H - 2, fill=1, stroke=0)
            color_use = C_WHITE

        txt(SUM_X + 8,  sy - SUM_ROW_H + 5, label, font=font_use, size=9,   color=color_use)
        txt(RM - 6,     sy - SUM_ROW_H + 5, value, font=font_use, size=9.5, color=color_use, align="right")
        sy -= SUM_ROW_H

    y = y - SUM_H - 14

    # ── SECTION 5: FOOTER ─────────────────────────────────────────────────────
    hline(y + 4, clr=C_MD_GREEN, lw=1.0)
    y -= 4
    txt(W / 2, y - 14, _t(footer),
        font=_FONT_BOLD, size=9, color=C_DK_GREEN, align="center")
    txt(W / 2, y - 28, "This is a computer-generated invoice.",
        font=_FONT, size=7.5, color=C_GREY, align="center")

    c.save()

    logger.info(
        "Service PDF (canvas): %s | shop=%s | roll=%s | items=%d | net=%.2f",
        tmp.name, shop_name, roll_number, len(services), net_amount,
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

    s_title  = _ps("ET",  bold=True, fontSize=18, alignment=1, textColor=NAVY,       spaceAfter=2)
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

    story.append(_p("Monthly Expense Report", s_title))
    story.append(_p(_e(month_label), s_sub))
    if user_name:
        story.append(_p(f"Prepared for: {_e(user_name)}", s_meta))
    story.append(_p(f"Generated: {now.strftime('%d-%m-%Y %H:%M')}", s_meta))
    story.append(HRFlowable(width="100%", thickness=1.5, color=NAVY, spaceAfter=8))

    if chart_path and os.path.exists(chart_path):
        story.append(RLImage(chart_path, width=16 * cm, height=8 * cm))
        story.append(Spacer(1, 0.5 * cm))

    category_totals: dict[str, float] = defaultdict(float)
    grand_total = 0.0
    for row in expenses:
        amt = float(row.get("Amount", 0))
        cat = str(row.get("Category", "general")).capitalize()
        category_totals[cat] += amt
        grand_total += amt

    story.append(_p("Category Breakdown", s_cathdr))

    cat_rows: list[list] = [[
        _p("Category",        s_th),
        _p("Total (&#8377;)", s_th),
        _p("% of Spend",      s_th),
    ]]
    for cat, cat_total in sorted(category_totals.items(), key=lambda x: x[1], reverse=True):
        pct = (cat_total / grand_total * 100) if grand_total > 0 else 0
        cat_rows.append([
            _p(_e(cat),          s_tdl),
            _p(f"{cat_total:,.2f}",  s_tdc),
            _p(f"{pct:.1f}%",    s_tdc),
        ])
    cat_rows.append([
        _p("Grand Total",                      s_tot),
        _p(f"&#8377; {grand_total:,.2f}",      s_tot),
        _p("100%",                             s_tot),
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
