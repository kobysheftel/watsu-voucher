"""
PDF module — Jinja2 + xhtml2pdf voucher PDF generation.

Renders templates/voucher_pdf.html with voucher data, embedding
QR and pool images as base64 data URIs for self-contained output.
"""

import base64
import io
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from xhtml2pdf import pisa

# Template directory and file
_TEMPLATE_DIR  = Path("templates")
_TEMPLATE_NAME = "voucher_pdf.html"

# Pool photo — embedded as base64 in every PDF
_POOL_IMAGE = Path("assets/Pool.png")


def _encode_image(path: Path) -> str | None:
    """Read an image file and return its base64-encoded content, or None if missing."""
    if not path or not Path(path).exists():
        return None
    return base64.b64encode(Path(path).read_bytes()).decode("utf-8")


def generate_pdf(voucher, folder: Path) -> Path:
    """
    Render the voucher PDF template and convert to a PDF file.

    Steps:
      1. Load the Jinja2 template from templates/voucher_pdf.html
      2. Encode QR and pool images as base64 strings
      3. Render HTML with voucher data
      4. Convert HTML → PDF via xhtml2pdf
      5. Save to folder/voucher.pdf

    Returns the saved PDF path.
    Raises RuntimeError if xhtml2pdf reports an error.
    """
    # Load template
    env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)))
    template = env.get_template(_TEMPLATE_NAME)

    # Encode images — base64 data URIs work reliably inside xhtml2pdf
    qr_image_b64   = _encode_image(Path(voucher.qr_path) if voucher.qr_path else None)
    pool_image_b64 = _encode_image(_POOL_IMAGE)

    # Render HTML
    html = template.render(
        voucher=voucher,
        qr_image_b64=qr_image_b64,
        pool_image_b64=pool_image_b64,
    )

    # Convert HTML → PDF
    pdf_path = folder / "voucher.pdf"
    with open(pdf_path, "wb") as pdf_file:
        result = pisa.CreatePDF(
            src=html,
            dest=pdf_file,
            encoding="utf-8",
        )

    if result.err:
        raise RuntimeError(
            f"שגיאה ביצירת PDF לשובר {voucher.voucher_id} "
            f"({result.err} שגיאות)"
        )

    return pdf_path
