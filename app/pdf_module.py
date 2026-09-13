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

import math
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
from datetime import timezone
from zoneinfo import ZoneInfo

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


def _draw_punch_row(c: canvas.Canvas, n: int, y: float, filled: int = 0) -> None:
    """
    Draw n small circles centred on the page at baseline y — the "punch
    card" look of a multi-treatment ticket. The first `filled` circles are
    drawn solid (treatments already used); the rest stay empty.
    """
    r = 1.8 * mm            # circle radius
    gap = 2.2 * mm          # space between circles
    total_w = n * 2 * r + (n - 1) * gap
    # Right-to-left: the first (used) circles sit on the right, like Hebrew reading order
    x = (_W + total_w) / 2 - r
    c.setStrokeColor(_BLUE)
    c.setFillColor(_BLUE)
    c.setLineWidth(0.8)
    for i in range(n):
        c.circle(x, y + r, r, stroke=1, fill=1 if i < filled else 0)
        x -= 2 * r + gap


def _local_time(dt) -> str:
    """Format a naive-UTC datetime from the DB as Israel local 'dd/mm/yyyy HH:MM'."""
    if dt is None:
        return ""
    try:
        local = dt.replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Asia/Jerusalem"))
    except Exception:
        local = dt
    return local.strftime("%d/%m/%Y %H:%M")


def _consumed_entries(voucher) -> list[tuple[int, str]]:
    """
    (seq, when) for every consumed entry, oldest first. `when` is the
    scheduled treatment time when one was recorded (a hold that was
    consumed), else the moment it was marked consumed.
    """
    rows = []
    for e in getattr(voucher, "entries", None) or []:
        if e.status != "consumed":
            continue
        when = e.scheduled_for.strftime("%d/%m/%Y %H:%M") if e.scheduled_for \
            else _local_time(e.consumed_at)
        rows.append((e.seq, when))
    rows.sort(key=lambda r: r[0])
    return rows


def _draw_consumed_lines(c: canvas.Canvas, rows: list[tuple[int, str]],
                         y: float, per_line: int = 3,
                         line_h: float = 4.2 * mm) -> float:
    """
    Print the used treatments as compact "n. dd/mm/yyyy HH:MM" items,
    `per_line` per row, centred. Returns the y below the last line.
    """
    if not rows:
        return y
    c.setFont(_FONT_BODY, 8.5)
    c.setFillColor(_TEXT)
    items = [f"{seq}. {when}" for seq, when in rows]
    for i in range(0, len(items), per_line):
        chunk = items[i:i + per_line]
        line = "   |   ".join(chunk)
        width = c.stringWidth(line, _FONT_BODY, 8.5)
        c.drawString((_W - width) / 2, y, line)   # digits only — no bidi needed
        y -= line_h
    return y


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

    # ── Gather the per-ticket facts that decide the layout ──
    is_pass = getattr(voucher, "kind", "VOUCHER") == "PASS"
    n_entries = int(getattr(voucher, "entries_total", 1) or 1)
    type_word = "זוגי" if _is_couple(voucher) else "ליחיד"
    consumed = _consumed_entries(voucher)
    show_circles = 1 < n_entries <= 20
    greeting = (getattr(voucher, 'greeting', None) or "").strip()
    if is_pass:
        greeting = ""                       # a pass carries no gift greeting
    name = ""
    if is_pass:
        # Pass: the holder's name (display_name override, else cemented / live name)
        name = (getattr(voucher, "display_name", None)
                or getattr(voucher, "holder_name", None)
                or (voucher.holder_ref.name if getattr(voucher, "holder_ref", None) else "")
                or "").strip()
    location = (getattr(voucher, 'location', None)
                or settings.get_default_location() or "").strip()

    # ── Adaptive vertical layout ──
    # The QR is pinned to the bottom; everything between the photo and the
    # validity date flows downward. Optional blocks (name, punch circles, used
    # treatments, greeting) make the flow longer, so first shrink the photo a
    # little, then compress the gaps, so nothing ever runs into the QR.
    id_y = 11 * mm                     # baseline of the voucher ID line
    qr_size = 18 * mm
    qr_y = id_y + 2.5 * mm             # QR sits just above the ID line
    min_y = qr_y + qr_size + 4 * mm    # lowest allowed baseline for the date

    optional_h = 0.0
    if name:
        optional_h += 6 * mm
    if show_circles:
        optional_h += 6 * mm
    if consumed:
        optional_h += 4.5 * mm + math.ceil(len(consumed) / 3) * 4.2 * mm + 1 * mm
    if greeting:
        optional_h += 1 * mm + 5 * mm * 2 + 1 * mm     # allow two wrapped lines
    # Fixed part below the type line (ornament, description, contact, validity)
    fixed_h = (6 * mm + 8 * mm) + 3 * 6.5 * mm + 3 * mm + 6 * mm + 5 * mm \
              + (5 * mm if location else 0) + 3 * mm + 6 * mm

    photo_h = 46 * mm
    y_start = _H - (33 + 12 + 8 + 5) * mm - photo_h      # baseline after the type line
    overflow = (optional_h + fixed_h + min_y) - y_start
    if overflow > 0:
        # 1. Shrink the photo (keep its oval proportions), up to 14 mm
        shrink = min(overflow, 14 * mm)
        photo_h -= shrink
        y_start += shrink
        overflow -= shrink
    g = 1.0                                              # gap scale
    if overflow > 0:
        # 2. Compress every vertical gap in the flow (never below 70 %)
        needed = optional_h + fixed_h
        g = max(0.7, (needed - overflow) / needed)
    photo_w = photo_h * 69 / 46

    # ── Oval pool photo (per-voucher image, cemented on first send, or library default) ──
    pool_path = images.image_path(getattr(voucher, "image_file", None)
                                  or images.get_default())
    _draw_pool_photo(c, pool_path, width=photo_w, height=photo_h, top=top(33))

    # ── Title + type line (differs by kind and number of treatments) ──
    y = top(33) - photo_h - 12 * mm
    if is_pass:
        _draw_centered_fit(c, "כרטיסיה — גלים ונפש", y,
                           max_size=24, color=_BLUE, font=_FONT_TITLE)
    else:
        _draw_centered_fit(c, "איזה כיף קיבלת שובר מתנה!", y,
                           max_size=24, color=_BLUE, font=_FONT_TITLE)
    type_line = (f"{n_entries} טיפולי וואטסו {type_word}" if n_entries > 1
                 else f"טיפול וואטסו {type_word}")
    y -= 8 * mm
    _draw_centered(c, type_line, y, font=_FONT_TITLE, size=14, color=_BLUE)
    y -= 5 * mm

    # Pass: holder name
    if name:
        _draw_centered(c, f"על שם: {name}", y, size=11.5, color=_BLUE)
        y -= 6 * mm * g

    # Used treatments: filled circles + the date/time of each one, so a
    # re-sent ticket always shows what was already used (Koby, 2026-09-13).
    if show_circles:
        _draw_punch_row(c, n_entries, y, filled=len(consumed))
        y -= 6 * mm * g
    if consumed:
        _draw_centered(c, "טיפולים שמומשו:", y, size=9.5, color=_BLUE, font=_FONT_TITLE)
        y -= 4.5 * mm * g
        y = _draw_consumed_lines(c, consumed, y, line_h=4.2 * mm * g)
        y -= 1 * mm * g

    # ── Optional greeting (word-wrapped); everything below shifts down ──
    if greeting:
        y = _draw_wrapped(c, greeting, y - 1 * mm, size=11, color=_BLUE,
                          line_h=5 * mm * g)
        y -= 1 * mm

    # ── Ornament divider ──
    orn_h = _draw_image_centered(c, _ORNAMENT, width=9 * mm, top=y)
    y -= (orn_h or 6 * mm) + 8 * mm * g

    # ── Treatment description ──
    desc_lines = [
        "וואטסו במים בבריכה חמימה בחצר מקורה ושקטה.",
        "מומלץ לבוא בבגד ים, להביא מגבות ובגדים להחלפה.",
        "הטיפול הוא כ- 50 דק׳ במי הבריכה החמימים.",
    ]
    for line in desc_lines:
        _draw_centered_fit(c, line, y, max_size=11.5 * (0.85 + 0.15 * g), color=_TEXT)
        y -= 6.5 * mm * g

    # ── Contact ──
    y -= 3 * mm * g
    _draw_centered(c, "למימוש ותיאום תאריך:", y, font=_FONT_TITLE, size=12, color=_BLUE)
    y -= 6 * mm * g
    _draw_centered(c, "אביגל: 050-4014696", y, size=12, color=_BLUE)
    y -= 5 * mm * g

    # Location / venue (per-voucher override or default), small grey line
    if location:
        _draw_centered(c, location, y, size=9.5, color=_GREY)
        y -= 5 * mm * g

    # ── Validity ──
    y -= 3 * mm * g
    validity_label = "הכרטיסיה בתוקף עד:" if is_pass else "השובר בתוקף עד:"
    _draw_centered(c, validity_label, y, font=_FONT_TITLE, size=12, color=_BLUE)
    y -= 6 * mm * g
    _draw_centered(c, voucher.valid_until.strftime('%d/%m/%Y'), max(y, min_y), size=12, color=_BLUE)

    # ── QR code + voucher ID — pinned to the bottom of the page (id_y / qr_y set above) ──
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
