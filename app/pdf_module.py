"""
PDF module — reportlab-based voucher PDF generation with Hebrew support.

Uses reportlab directly (not xhtml2pdf) because xhtml2pdf cannot render
Hebrew glyphs. The bidi library handles RTL text reordering.

Design matches the reference: water-blue gradient background, centered
pool photo, warm teal text, treatment info, contact, expiry.
"""

from pathlib import Path

import fitz  # PyMuPDF — used to rasterize the voucher PDF into a PNG image
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A5
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, Color
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from bidi.algorithm import get_display

from app import images    # voucher image library (default + per-voucher override)
from app import settings  # default voucher location/venue

# A5 dimensions
_W, _H = A5   # 148mm x 210mm (≈ 419 x 595 pts)

# Colors — matching the water/teal design
_TEAL      = HexColor("#2a7f8e")    # main title color
_TEAL_DARK = HexColor("#1a5f6e")    # darker teal for emphasis
_WARM      = HexColor("#5a4a3a")    # warm brown for body text
_GREY      = HexColor("#666666")    # secondary text
_LGREY     = HexColor("#999999")    # light info text
_BG_TOP    = HexColor("#d4eef2")    # light water blue (top)
_BG_MID    = HexColor("#e8f4f0")    # very light (middle)
_BG_BOT    = HexColor("#dce8e4")    # soft sage (bottom)
_WHITE     = HexColor("#ffffff")
_ORNAMENT  = HexColor("#7ab5b0")    # decorative elements

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
    """Apply bidi algorithm for correct RTL display in PDF."""
    if not text:
        return ""
    text = str(text)
    if _has_hebrew(text):
        return get_display(text)
    return text


def _draw_centered(c: canvas.Canvas, text: str, y: float,
                   font: str = "Heebo", size: float = 11,
                   color=None):
    """Draw bidi-processed text centered on the page."""
    if color is None:
        color = _WARM
    c.setFont(font, size)
    c.setFillColor(color)
    display_text = _bidi(text)
    text_width = c.stringWidth(display_text, font, size)
    x = (_W - text_width) / 2
    c.drawString(x, y, display_text)


def _draw_centered_fit(c: canvas.Canvas, text: str, y: float,
                       max_size: float, color=None,
                       min_size: float = 7, max_width: float = None):
    """
    Like _draw_centered, but shrinks the font size until the (bidi-processed)
    text fits within max_width. Used for long header / message lines so they
    never overflow the A5 page.
    """
    if max_width is None:
        max_width = _W - 2 * (8 * mm)   # page width minus side margins
    disp = _bidi(text)
    size = max_size
    while size > min_size and c.stringWidth(disp, "Heebo", size) > max_width:
        size -= 0.5
    _draw_centered(c, text, y, size=size, color=color)


def _draw_wrapped(c: canvas.Canvas, text: str, y: float,
                  size: float, color=None, line_h: float = None,
                  max_width: float = None) -> float:
    """
    Draw word-wrapped, centered text. Returns the new y position below the
    last line. Used for the optional free-text greeting.
    """
    if color is None:
        color = _WARM
    if max_width is None:
        max_width = _W - 2 * (12 * mm)
    if line_h is None:
        line_h = (size + 3)

    words = str(text).split()
    lines = []
    current = ""
    for w in words:
        trial = (current + " " + w).strip()
        # Measure the bidi-processed trial line.
        if c.stringWidth(_bidi(trial), "Heebo", size) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = w
    if current:
        lines.append(current)

    for line in lines:
        _draw_centered(c, line, y, size=size, color=color)
        y -= line_h
    return y


def _draw_gradient_bg(c: canvas.Canvas):
    """Draw a soft water-blue gradient background using horizontal bands."""
    steps = 40
    band_h = _H / steps
    for i in range(steps):
        # Blend from BG_TOP (top) through BG_MID to BG_BOT (bottom)
        t = i / steps
        if t < 0.4:
            # Top zone: BG_TOP → BG_MID
            f = t / 0.4
            r = _BG_TOP.red   + (_BG_MID.red   - _BG_TOP.red)   * f
            g = _BG_TOP.green + (_BG_MID.green  - _BG_TOP.green) * f
            b = _BG_TOP.blue  + (_BG_MID.blue   - _BG_TOP.blue)  * f
        else:
            # Bottom zone: BG_MID → BG_BOT
            f = (t - 0.4) / 0.6
            r = _BG_MID.red   + (_BG_BOT.red   - _BG_MID.red)   * f
            g = _BG_MID.green + (_BG_BOT.green  - _BG_MID.green) * f
            b = _BG_MID.blue  + (_BG_BOT.blue   - _BG_MID.blue)  * f
        c.setFillColor(Color(r, g, b))
        c.rect(0, _H - (i + 1) * band_h, _W, band_h + 1, stroke=0, fill=1)


def _draw_wave_decoration(c: canvas.Canvas, y: float, color=None):
    """Draw a simple wave-like decorative line."""
    if color is None:
        color = _ORNAMENT
    c.setStrokeColor(color)
    c.setLineWidth(1.5)
    # Draw a wavy line using bezier curves
    margin = 20 * mm
    mid = _W / 2
    p = c.beginPath()
    p.moveTo(margin, y)
    p.curveTo(margin + 20 * mm, y + 3 * mm, mid - 15 * mm, y - 3 * mm, mid, y)
    p.curveTo(mid + 15 * mm, y + 3 * mm, _W - margin - 20 * mm, y - 3 * mm, _W - margin, y)
    c.drawPath(p, stroke=1, fill=0)


def _draw_ornament(c: canvas.Canvas, y: float):
    """Draw a small centered ornamental divider using lines and a diamond shape."""
    mid_x = _W / 2
    mid_y = y + 4
    line_len = 18 * mm
    gap = 5 * mm
    diamond = 2.5  # half-size of diamond

    # Lines on each side
    c.setStrokeColor(_ORNAMENT)
    c.setLineWidth(0.7)
    c.line(mid_x - gap - line_len, mid_y, mid_x - gap, mid_y)
    c.line(mid_x + gap, mid_y, mid_x + gap + line_len, mid_y)

    # Diamond shape in center (drawn with path)
    c.setFillColor(_ORNAMENT)
    p = c.beginPath()
    p.moveTo(mid_x, mid_y + diamond)
    p.lineTo(mid_x + diamond, mid_y)
    p.lineTo(mid_x, mid_y - diamond)
    p.lineTo(mid_x - diamond, mid_y)
    p.close()
    c.drawPath(p, stroke=0, fill=1)


def generate_pdf(voucher, folder: Path) -> Path:
    """
    Generate a single-page A5 voucher PDF matching the water-blue design.

    Layout (top to bottom):
      - Water-blue gradient background
      - "גלים ונפש" header in teal
      - "טיפולי וואטסו" subtitle
      - Wave decoration
      - Pool photo (oval/rounded, centered)
      - "!איזה כיף קיבלת שובר מתנה" excitement title
      - "טיפול וואטסו {type}" voucher type
      - Ornamental divider
      - Treatment description text
      - Contact info
      - Expiry date
      - Small voucher ID + receipt number

    Returns the saved PDF path.
    """
    _register_fonts()

    pdf_path = folder / "voucher.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=A5)

    # ── Background gradient ──
    _draw_gradient_bg(c)

    # ── Starting Y position (from top) ──
    y = _H - 20 * mm

    # ── Business name (fit to width — long line) ──
    _draw_centered_fit(c, "גלים ונפש - אביגל מאור", y, max_size=22, color=_TEAL)
    y -= 8 * mm

    # ── Subtitle (fit to width — four terms) ──
    _draw_centered_fit(c, "וואטסו - פסיכותרפיה - הידרותרפיה - מים פתוחים",
                       y, max_size=11, color=_TEAL_DARK)
    y -= 5 * mm

    # ── Wave decoration ──
    _draw_wave_decoration(c, y)
    y -= 6 * mm

    # ── Pool photo (centered, large, with rounded clip) ──
    pool_w = 70 * mm
    pool_h = 52 * mm

    # Per-voucher image override (cemented on first send) or library default.
    pool_path = images.image_path(getattr(voucher, "image_file", None)
                                  or images.get_default())

    if pool_path.exists():
        pool_x = (_W - pool_w) / 2
        pool_y = y - pool_h
        try:
            # White rounded frame behind image
            c.setFillColor(_WHITE)
            c.setStrokeColor(_ORNAMENT)
            c.setLineWidth(1.5)
            c.roundRect(pool_x - 2, pool_y - 2, pool_w + 4, pool_h + 4,
                        8 * mm, stroke=1, fill=1)

            img = ImageReader(str(pool_path))
            # Clip to rounded rect
            c.saveState()
            clip_path = c.beginPath()
            clip_path.roundRect(pool_x, pool_y, pool_w, pool_h, 7 * mm)
            c.clipPath(clip_path, stroke=0)
            c.drawImage(img, pool_x, pool_y, pool_w, pool_h,
                        preserveAspectRatio=True, mask='auto')
            c.restoreState()
        except Exception:
            pass

    y -= pool_h + 6 * mm

    # ── Message — "קבלת/קבלתם שובר לטיפול {type}" ──
    # Plural form for couple vouchers (זוגי), singular otherwise.
    plural = (voucher.voucher_type == "זוגי")
    verb = "קבלתם" if plural else "קבלת"
    message = f"{verb} שובר לטיפול {voucher.voucher_type}"
    _draw_centered_fit(c, message, y, max_size=17, color=_TEAL)
    y -= 7 * mm

    # ── Location / venue line (just before the greeting) ──
    location = (getattr(voucher, 'location', None)
                or settings.get_default_location() or "").strip()
    if location:
        _draw_centered_fit(c, f"מיקום: {location}", y, max_size=11, color=_GREY)
        y -= 5 * mm

    # ── Optional greeting / blessing (word-wrapped) ──
    greeting = (getattr(voucher, 'greeting', None) or "").strip()
    if greeting:
        y = _draw_wrapped(c, greeting, y, size=11, color=_TEAL_DARK, line_h=5 * mm)
        y -= 1 * mm

    # ── Ornamental divider ──
    _draw_ornament(c, y)
    y -= 7 * mm

    # ── Description text (treatment info) ──
    desc_lines = [
        "וואטסו במים בבריכה חמימה בחצר מקורה ושקטה",
        "מומלץ לבוא בבגד ים, להביא מגבות ובגדים להחלפה",
        "הטיפול הוא כ- 50 דק׳ במי הבריכה החמימים",
    ]
    for line in desc_lines:
        _draw_centered(c, line, y, size=9.5, color=_WARM)
        y -= 4.5 * mm

    y -= 2 * mm

    # ── Contact info ──
    _draw_centered(c, "למימוש ותיאום תאריך", y, size=10, color=_GREY)
    y -= 5 * mm
    _draw_centered(c, "אביגל 050-4014696", y, size=12, color=_TEAL_DARK)
    y -= 6 * mm

    # ── Expiry date ──
    valid_str = voucher.valid_until.strftime('%d/%m/%Y')
    _draw_centered(c, f"השובר בתוקף עד {valid_str}", y, size=12, color=_WARM)
    y -= 5 * mm

    # ── QR code (if exists) — small, centered ──
    if voucher.qr_path and Path(voucher.qr_path).exists():
        qr_size = 20 * mm
        qr_x = (_W - qr_size) / 2
        qr_y = y - qr_size
        try:
            qr_img = ImageReader(str(voucher.qr_path))
            c.drawImage(qr_img, qr_x, qr_y, qr_size, qr_size)
        except Exception:
            pass

    # ── Voucher ID + receipt (pinned to bottom of page) ──
    bottom_y = 10 * mm
    if voucher.receipt_number:
        _draw_centered(c, f"מס׳ קבלה {voucher.receipt_number}  |  מס׳ שובר {voucher.voucher_id}",
                        bottom_y, size=6, color=_LGREY)
    else:
        _draw_centered(c, f"מס׳ שובר {voucher.voucher_id}",
                        bottom_y, size=6, color=_LGREY)

    c.save()

    # Also render a PNG image version of the voucher (default send format).
    generate_image(pdf_path, folder)

    return pdf_path


# Rasterization zoom factor: 3x ≈ 216 DPI — crisp Hebrew text and a scannable QR,
# while keeping the PNG light enough (~400 KB) for WhatsApp.
_IMAGE_ZOOM = 3


def generate_image(pdf_path: Path, folder: Path) -> Path:
    """
    Render the (already generated) voucher PDF into a PNG image.

    Reuses the exact PDF design — the image is just a high-resolution raster
    of the same single A5 page. Saved next to the PDF as voucher.png.

    Returns the saved PNG path.
    """
    png_path = folder / "voucher.png"

    # Open the PDF and rasterize its first (only) page.
    doc = fitz.open(str(pdf_path))
    try:
        page = doc[0]
        matrix = fitz.Matrix(_IMAGE_ZOOM, _IMAGE_ZOOM)
        pix = page.get_pixmap(matrix=matrix, alpha=False)  # no transparency — solid bg
        pix.save(str(png_path))
    finally:
        doc.close()

    return png_path
