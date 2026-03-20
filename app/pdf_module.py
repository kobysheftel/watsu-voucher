"""
PDF module — reportlab-based voucher PDF generation with Hebrew support.

Uses reportlab directly (not xhtml2pdf) because xhtml2pdf cannot render
Hebrew glyphs. The bidi library handles RTL text reordering.

Design: A5 portrait voucher with double border, pool image, QR code,
holder details, and validity info — all on a single page.
"""

from pathlib import Path

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A5
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from bidi.algorithm import get_display

# A5 dimensions
_W, _H = A5   # 148mm x 210mm (≈ 419 x 595 pts)

# Margins
_M = 8 * mm

# Colors
_GOLD    = HexColor("#8B7355")
_DARK    = HexColor("#2c3e50")
_GREY    = HexColor("#888888")
_LGREY   = HexColor("#aaaaaa")
_RED     = HexColor("#c0392b")
_DIVIDER = HexColor("#dddddd")

# Assets
_POOL_IMAGE = Path("assets/Pool.png")
_FONT_PATH  = Path("assets/fonts/Heebo-Variable.ttf")

# Font registration (once per process)
_font_registered = False


def _register_fonts():
    """Register Heebo Hebrew font once for the process lifetime."""
    global _font_registered
    if _font_registered:
        return
    if _FONT_PATH.exists():
        pdfmetrics.registerFont(TTFont("Heebo", str(_FONT_PATH)))
        _font_registered = True


def _has_hebrew(text: str) -> bool:
    """Check if text contains Hebrew characters."""
    return any('\u0590' <= ch <= '\u05FF' for ch in text)


def _bidi(text: str) -> str:
    """Apply bidi algorithm for correct RTL display in PDF.
    Only applies to text containing Hebrew — pure LTR text is left as-is."""
    if not text:
        return ""
    text = str(text)
    if _has_hebrew(text):
        return get_display(text)
    return text


def _draw_centered(c: canvas.Canvas, text: str, y: float,
                   font: str = "Heebo", size: float = 11,
                   color=_DARK):
    """Draw bidi-processed text centered on the page."""
    c.setFont(font, size)
    c.setFillColor(color)
    display_text = _bidi(text)
    text_width = c.stringWidth(display_text, font, size)
    x = (_W - text_width) / 2
    c.drawString(x, y, display_text)


def _draw_right(c: canvas.Canvas, text: str, x: float, y: float,
                font: str = "Heebo", size: float = 11,
                color=_DARK):
    """Draw bidi-processed text right-aligned at x."""
    c.setFont(font, size)
    c.setFillColor(color)
    display_text = _bidi(text)
    text_width = c.stringWidth(display_text, font, size)
    c.drawString(x - text_width, y, display_text)


def _hline(c: canvas.Canvas, y: float, color=_DIVIDER, width: float = 0.5):
    """Draw a horizontal divider line."""
    c.setStrokeColor(color)
    c.setLineWidth(width)
    c.line(_M + 5 * mm, y, _W - _M - 5 * mm, y)


def generate_pdf(voucher, folder: Path) -> Path:
    """
    Generate a single-page A5 voucher PDF using reportlab.

    Layout (top to bottom):
      - Business name + subtitle
      - "שובר מתנה" title
      - Voucher type (large, gold)
      - Divider
      - Holder details (name, phone, email) — right-aligned labels
      - Divider
      - Pool image (center) + QR code (bottom-right)
      - Validity date (red, centered)
      - Voucher ID + receipt number (small, centered)

    Returns the saved PDF path.
    """
    _register_fonts()

    pdf_path = folder / "voucher.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=A5)

    # ── Double border frame ──
    # Outer border
    c.setStrokeColor(_GOLD)
    c.setLineWidth(2)
    c.rect(_M, _M, _W - 2 * _M, _H - 2 * _M)
    # Inner border (2pt inset)
    c.setLineWidth(0.5)
    c.rect(_M + 3, _M + 3, _W - 2 * _M - 6, _H - 2 * _M - 6)

    # ── Starting Y position (from top) ──
    y = _H - _M - 15 * mm

    # ── Business name ──
    _draw_centered(c, "גלים ונפש", y, size=22, color=_GOLD)
    y -= 5 * mm

    # ── Subtitle ──
    _draw_centered(c, "ווטסו — טיפול במים חמים", y, size=9, color=_GREY)
    y -= 3 * mm

    # ── Divider under header ──
    _hline(c, y, color=_GOLD, width=0.8)
    y -= 7 * mm

    # ── Gift voucher title ──
    _draw_centered(c, "שובר מתנה", y, size=15, color=_DARK)
    y -= 8 * mm

    # ── Voucher type (large, gold) ──
    _draw_centered(c, voucher.voucher_type, y, size=22, color=_GOLD)
    y -= 5 * mm

    # ── Divider ──
    _hline(c, y)
    y -= 7 * mm

    # ── Holder details (RTL layout: label on right edge, value to its left) ──
    label_x = _W - _M - 10 * mm   # right edge for label text (right-aligned)
    gap = 3 * mm                   # space between label and value

    def _detail_row(label_text, value_text, value_size=12):
        """Draw a label: value row, RTL. Returns nothing, caller manages y."""
        # Label (small, grey, right-aligned)
        c.setFont("Heebo", 8)
        c.setFillColor(_LGREY)
        label_display = _bidi(label_text)
        label_w = c.stringWidth(label_display, "Heebo", 8)
        c.drawString(label_x - label_w, y, label_display)

        # Value (bold, dark, positioned left of label)
        c.setFont("Heebo", value_size)
        c.setFillColor(_DARK)
        value_display = _bidi(value_text)
        value_w = c.stringWidth(value_display, "Heebo", value_size)
        c.drawString(label_x - label_w - gap - value_w, y, value_display)

    # Name
    _detail_row("מוענק ל:", voucher.holder_name or "")
    y -= 5.5 * mm

    # Phone
    _detail_row("טלפון:", voucher.holder_mobile or "")
    y -= 5.5 * mm

    # Email (if exists)
    if voucher.holder_email:
        _detail_row("מייל:", voucher.holder_email, value_size=9)
        y -= 5.5 * mm

    y -= 2 * mm

    # ── Divider ──
    _hline(c, y)
    y -= 5 * mm

    # ── Pool image + QR code ──
    pool_img_h = 45 * mm
    pool_img_w = 55 * mm
    qr_size = 25 * mm

    # Pool image — centered horizontally, shifted left to make room for QR
    if _POOL_IMAGE.exists():
        pool_x = (_W - pool_img_w) / 2 - 10 * mm
        pool_y = y - pool_img_h
        try:
            img = ImageReader(str(_POOL_IMAGE))
            c.drawImage(img, pool_x, pool_y, pool_img_w, pool_img_h,
                        preserveAspectRatio=True, mask='auto')
        except Exception:
            pass  # skip if image can't be loaded

    # QR code — bottom-right area
    if voucher.qr_path and Path(voucher.qr_path).exists():
        qr_x = _W - _M - 12 * mm - qr_size
        qr_y = y - pool_img_h + 2 * mm
        try:
            qr_img = ImageReader(str(voucher.qr_path))
            c.drawImage(qr_img, qr_x, qr_y, qr_size, qr_size)
        except Exception:
            pass

        # "סרוק לאימות" under QR
        c.setFont("Heebo", 5)
        c.setFillColor(_LGREY)
        label = _bidi("סרוק לאימות")
        lw = c.stringWidth(label, "Heebo", 5)
        c.drawString(qr_x + (qr_size - lw) / 2, qr_y - 3 * mm, label)

    y -= pool_img_h + 5 * mm

    # ── Validity date (red, centered) ──
    valid_str = voucher.valid_until.strftime('%d/%m/%Y')
    _draw_centered(c, f"בתוקף עד: {valid_str}", y, size=11, color=_RED)
    y -= 5 * mm

    # ── Voucher ID (small, centered) ──
    _draw_centered(c, f"מס׳ שובר: {voucher.voucher_id}", y, size=7, color=_LGREY)
    y -= 3.5 * mm

    # ── Receipt number (if exists) ──
    if voucher.receipt_number:
        _draw_centered(c, f"מס׳ קבלה: {voucher.receipt_number}", y,
                        size=7, color=_LGREY)

    c.save()
    return pdf_path
