"""
PDF module — reportlab-based voucher PDF generation with Hebrew support.

Uses reportlab directly (not xhtml2pdf) because xhtml2pdf cannot render
Hebrew glyphs. The bidi library handles RTL text reordering.

Design (2026-09, Koby's Word template):
  - Full-page watercolor water background image (assets/voucher-bg-water.png)
  - Brand header image "גלים ✦ ונפש / טיפולי וואטסו" (assets/header-logo.png)
  - Oval pool photo (library image, clipped to a stadium shape)
  - "איזה כיף קיבלת שובר מתנה!" + "טיפול וואטסו ליחיד / זוגי"
  - Small brand ornament, treatment description, contact, validity
  - QR code centered at the bottom, voucher ID (no caption) under it
"""

import tempfile
from pathlib import Path

import fitz  # PyMuPDF — used to rasterize the voucher PDF into a PNG image
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A5
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from bidi.algorithm import get_display

from app import images    # voucher image library (default + per-voucher override)
from app import settings  # default voucher location/venue

# A5 dimensions — same aspect ratio as the background image (1052x1494)
_W, _H = A5   # 148mm x 210mm (≈ 419 x 595 pts)

# Colors — matching the template design
_BLUE      = HexColor("#2c4a63")    # dark slate blue: title, type, labels, phone
_TEXT      = HexColor("#3a3a3a")    # dark grey body text
_GREY      = HexColor("#6b6b6b")    # secondary text (location)
_LGREY     = HexColor("#8a8a8a")    # voucher ID at the bottom

# Assets
_BG_IMAGE   = Path("assets/voucher-bg-water.jpg")   # full-page background (JPEG keeps the PDF small)
_HEADER_IMG = Path("assets/header-logo.png")        # brand header (logo + script subtitle)
_ORNAMENT   = Path("assets/ornament.png")           # small brand swirl divider
_FONT_DIR   = Path("assets/fonts")

# Font registration (once per process)
_font_registered = False

# Fonts: Heebo (body) + David Libre (title / labels). Both are OFL-licensed.
_FONT_BODY  = "Heebo"
_FONT_TITLE = "DavidLibreB"


def _register_fonts():
    """Register the Hebrew fonts once for the process lifetime."""
    global _font_registered
    if _font_registered:
        return
    fonts = {
        "Heebo":       _FONT_DIR / "Heebo-Variable.ttf",
        "DavidLibre":  _FONT_DIR / "DavidLibre-Regular.ttf",
        "DavidLibreB": _FONT_DIR / "DavidLibre-Bold.ttf",
    }
    for name, path in fonts.items():
        if path.exists():
            pdfmetrics.registerFont(TTFont(name, str(path)))
    _font_registered = True


def _has_hebrew(text: str) -> bool:
    """Check if text contains Hebrew characters."""
    return any('֐' <= ch <= '׿' for ch in text)


def _bidi(text: str) -> str:
    """Apply bidi algorithm for correct RTL display in PDF."""
    if not text:
        return ""
    text = str(text)
    if _has_hebrew(text):
        return get_display(text)
    return text


def _draw_centered(c: canvas.Canvas, text: str, y: float,
                   font: str = _FONT_BODY, size: float = 11,
                   color=None):
    """Draw bidi-processed text centered on the page (y = baseline)."""
    if color is None:
        color = _TEXT
    c.setFont(font, size)
    c.setFillColor(color)
    display_text = _bidi(text)
    text_width = c.stringWidth(display_text, font, size)
    x = (_W - text_width) / 2
    c.drawString(x, y, display_text)


def _draw_centered_fit(c: canvas.Canvas, text: str, y: float,
                       max_size: float, color=None, font: str = _FONT_BODY,
                       min_size: float = 7, max_width: float = None):
    """
    Like _draw_centered, but shrinks the font size until the (bidi-processed)
    text fits within max_width, so long lines never overflow the page.
    """
    if max_width is None:
        max_width = _W - 2 * (10 * mm)   # page width minus side margins
    disp = _bidi(text)
    size = max_size
    while size > min_size and c.stringWidth(disp, font, size) > max_width:
        size -= 0.5
    _draw_centered(c, text, y, font=font, size=size, color=color)


def _draw_wrapped(c: canvas.Canvas, text: str, y: float,
                  size: float, color=None, line_h: float = None,
                  max_width: float = None, font: str = _FONT_BODY) -> float:
    """
    Draw word-wrapped, centered text. Returns the new y position below the
    last line. Used for the optional free-text greeting.
    """
    if color is None:
        color = _TEXT
    if max_width is None:
        max_width = _W - 2 * (14 * mm)
    if line_h is None:
        line_h = (size + 3)

    words = str(text).split()
    lines = []
    current = ""
    for w in words:
        trial = (current + " " + w).strip()
        # Measure the bidi-processed trial line.
        if c.stringWidth(_bidi(trial), font, size) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = w
    if current:
        lines.append(current)

    for line in lines:
        _draw_centered(c, line, y, font=font, size=size, color=color)
        y -= line_h
    return y


def _draw_image_centered(c: canvas.Canvas, path: Path, width: float,
                         top: float) -> float:
    """
    Draw an image centered horizontally with the given width, its top edge at
    `top` (points from the page bottom). Height follows the image aspect ratio.
    Returns the image height (0 if the file is missing / unreadable).
    """
    if not path.exists():
        return 0
    try:
        img = ImageReader(str(path))
        iw, ih = img.getSize()
        height = width * ih / iw
        c.drawImage(img, (_W - width) / 2, top - height, width, height,
                    mask='auto')
        return height
    except Exception:
        return 0


def _draw_pool_photo(c: canvas.Canvas, path: Path, width: float,
                     height: float, top: float) -> None:
    """
    Draw the pool photo centered, clipped to a stadium (oval) shape.
    The library default image already has this shape with a transparent
    surround; the clip keeps uploaded rectangular photos in the same shape.
    """
    if not path.exists():
        return
    x = (_W - width) / 2
    y = top - height
    try:
        img = ImageReader(str(path))
        c.saveState()
        clip = c.beginPath()
        clip.roundRect(x, y, width, height, height / 2)   # radius = half height → oval ends
        c.clipPath(clip, stroke=0)
        c.drawImage(img, x, y, width, height,
                    preserveAspectRatio=True, mask='auto')
        c.restoreState()
    except Exception:
        pass


def _is_couple(voucher) -> bool:
    """True for a couple voucher (current 'זוגי' or the legacy 'לזוג' value)."""
    return voucher.voucher_type in ("זוגי", "לזוג")


def generate_pdf(voucher, folder: Path) -> Path:
    """
    Generate a single-page A5 voucher PDF in the template design.

    Layout (top to bottom, all centered):
      - Watercolor water background (full page)
      - Brand header image
      - Oval pool photo
      - "איזה כיף קיבלת שובר מתנה!"
      - "טיפול וואטסו ליחיד" / "טיפול וואטסו זוגי"
      - Optional greeting (word-wrapped)
      - Small ornament divider
      - Treatment description (3 lines)
      - Contact: "למימוש ותיאום תאריך:" + "אביגל: 050-4014696" + location
      - "השובר בתוקף עד:" + date
      - QR code (18 mm) at the bottom
      - Voucher ID only (no caption) under the QR

    Returns the saved PDF path.
    """
    _register_fonts()

    pdf_path = folder / "voucher.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=A5)

    # ── Background image (full page) ──
    if _BG_IMAGE.exists():
        try:
            c.drawImage(ImageReader(str(_BG_IMAGE)), 0, 0, _W, _H)
        except Exception:
            pass

    # Helper: convert "mm from the top edge" into reportlab y (from bottom).
    def top(y_mm: float) -> float:
        return _H - y_mm * mm

    # ── Brand header image ──
    _draw_image_centered(c, _HEADER_IMG, width=62 * mm, top=top(8))

    # ── Oval pool photo (per-voucher image, cemented on first send, or library default) ──
    pool_path = images.image_path(getattr(voucher, "image_file", None)
                                  or images.get_default())
    _draw_pool_photo(c, pool_path, width=69 * mm, height=46 * mm, top=top(33))

    # ── Title ──
    _draw_centered_fit(c, "איזה כיף קיבלת שובר מתנה!", top(91),
                       max_size=24, color=_BLUE, font=_FONT_TITLE)

    # ── Voucher type line ──
    type_line = "טיפול וואטסו זוגי" if _is_couple(voucher) else "טיפול וואטסו ליחיד"
    _draw_centered(c, type_line, top(99), font=_FONT_TITLE, size=14, color=_BLUE)

    # ── Optional greeting (word-wrapped); everything below shifts down ──
    y = top(104)
    greeting = (getattr(voucher, 'greeting', None) or "").strip()
    if greeting:
        y = _draw_wrapped(c, greeting, y - 1 * mm, size=11, color=_BLUE,
                          line_h=5 * mm)
        y -= 1 * mm

    # ── Ornament divider ──
    orn_h = _draw_image_centered(c, _ORNAMENT, width=9 * mm, top=y)
    y -= (orn_h or 6 * mm) + 8 * mm

    # ── Treatment description ──
    desc_lines = [
        "וואטסו במים בבריכה חמימה בחצר מקורה ושקטה.",
        "מומלץ לבוא בבגד ים, להביא מגבות ובגדים להחלפה.",
        "הטיפול הוא כ- 50 דק׳ במי הבריכה החמימים.",
    ]
    for line in desc_lines:
        _draw_centered_fit(c, line, y, max_size=11.5, color=_TEXT)
        y -= 6.5 * mm

    # ── Contact ──
    y -= 3 * mm
    _draw_centered(c, "למימוש ותיאום תאריך:", y, font=_FONT_TITLE, size=12, color=_BLUE)
    y -= 6 * mm
    _draw_centered(c, "אביגל: 050-4014696", y, size=12, color=_BLUE)
    y -= 5 * mm

    # Location / venue (per-voucher override or default), small grey line
    location = (getattr(voucher, 'location', None)
                or settings.get_default_location() or "").strip()
    if location:
        _draw_centered(c, location, y, size=9.5, color=_GREY)
        y -= 5 * mm

    # ── Validity ──
    y -= 3 * mm
    _draw_centered(c, "השובר בתוקף עד:", y, font=_FONT_TITLE, size=12, color=_BLUE)
    y -= 6 * mm
    _draw_centered(c, voucher.valid_until.strftime('%d/%m/%Y'), y, size=12, color=_BLUE)

    # ── QR code + voucher ID — pinned to the bottom of the page ──
    id_y = 11 * mm                     # baseline of the voucher ID line
    qr_size = 18 * mm
    qr_y = id_y + 2.5 * mm             # QR sits just above the ID line
    if voucher.qr_path and Path(voucher.qr_path).exists():
        try:
            c.drawImage(ImageReader(str(voucher.qr_path)),
                        (_W - qr_size) / 2, qr_y, qr_size, qr_size)
        except Exception:
            pass

    # Voucher ID only — no caption (Koby's request)
    _draw_centered(c, voucher.voucher_id, id_y, size=7.5, color=_LGREY)

    c.save()

    # Also render a PNG image version of the voucher (default send format).
    generate_image(pdf_path, folder)

    return pdf_path


def render_preview(voucher) -> tuple[bytes, bytes]:
    """
    Render the voucher on the fly WITHOUT touching its files or state.

    Used to show a draft voucher (not yet sent) exactly as it will look —
    minus the QR, which is only generated on first send. Also used as a
    fallback when a sent voucher's files are missing on disk.

    Returns (pdf_bytes, jpeg_bytes). Nothing is persisted.
    """
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        pdf_path = generate_pdf(voucher, folder)   # also writes the JPEG
        return pdf_path.read_bytes(), (folder / IMAGE_FILENAME).read_bytes()


# Rasterization zoom factor: 3x ≈ 216 DPI — crisp Hebrew text and a scannable QR.
_IMAGE_ZOOM = 3

# JPEG quality for the image send format. The watercolor background does not
# compress well as PNG (~3 MB); JPEG at this quality is ~300 KB and WhatsApp-friendly.
_IMAGE_JPEG_QUALITY = 85

# Filename of the raster image next to voucher.pdf (used by the /image endpoint too)
IMAGE_FILENAME = "voucher.jpg"


def generate_image(pdf_path: Path, folder: Path) -> Path:
    """
    Render the (already generated) voucher PDF into a JPEG image.

    Reuses the exact PDF design — the image is just a high-resolution raster
    of the same single A5 page. Saved next to the PDF as voucher.jpg.

    Returns the saved image path.
    """
    img_path = folder / IMAGE_FILENAME

    # Open the PDF and rasterize its first (only) page.
    doc = fitz.open(str(pdf_path))
    try:
        page = doc[0]
        matrix = fitz.Matrix(_IMAGE_ZOOM, _IMAGE_ZOOM)
        pix = page.get_pixmap(matrix=matrix, alpha=False)  # no transparency — solid bg
        pix.save(str(img_path), jpg_quality=_IMAGE_JPEG_QUALITY)
    finally:
        doc.close()

    return img_path
