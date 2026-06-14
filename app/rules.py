"""
Rules Engine — all business logic for voucher lifecycle.

This module is the single source of truth for:
  - Status transitions (draft → sent → used)
  - Cementing holder details into a voucher
  - Generating / reusing QR codes
  - Generating PDFs
  - Logging send events
  - Holder editability rules

Nothing in here knows about HTTP — it only receives a DB session
and returns updated ORM objects. Routers call these functions.
"""

from datetime import datetime, date
from app.utils import utcnow
from pathlib import Path
from sqlalchemy.orm import Session

from app.models import Holder, Voucher, Sending
from app import qr_module, pdf_module, images, settings   # implemented in Steps 7 and 6


# ── Exceptions ────────────────────────────────────────────────────────────────

class RulesError(Exception):
    """Raised when a business rule is violated."""
    pass


# ── Holder rules ──────────────────────────────────────────────────────────────

def can_edit_holder(db: Session, mobile: str) -> bool:
    """
    A holder can be edited only if none of their vouchers are 'used'.
    Returns True (editable) or False (locked).
    """
    used_count = (
        db.query(Voucher)
        .filter(Voucher.mobile == mobile, Voucher.status == "used")
        .count()
    )
    return used_count == 0


def get_or_create_holder(db: Session, mobile: str, name: str,
                          email: str | None) -> tuple[Holder, bool]:
    """
    Retrieve an existing holder by mobile, or create a new one.
    Returns (holder, created) where created=True if a new row was inserted.
    """
    holder = db.get(Holder, mobile)
    if holder:
        return holder, False

    holder = Holder(
        mobile=mobile,
        name=name,
        email=email,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(holder)
    db.commit()
    db.refresh(holder)
    return holder, True


def update_holder(db: Session, mobile: str,
                  name: str | None, email: str | None) -> Holder:
    """
    Update holder fields.
    Raises RulesError if the holder has any used vouchers.
    """
    holder = db.get(Holder, mobile)
    if not holder:
        raise RulesError(f"מזמין לא נמצא: {mobile}")

    if not can_edit_holder(db, mobile):
        raise RulesError(
            "לא ניתן לערוך פרטי מזמין — קיים שובר מומש על שמו"
        )

    if name is not None:
        holder.name = name
    if email is not None:
        holder.email = email
    holder.updated_at = utcnow()

    db.commit()
    db.refresh(holder)
    return holder


# ── Voucher creation ──────────────────────────────────────────────────────────

def next_sequence(db: Session, mobile: str) -> int:
    """
    Return the next sequence number for a given mobile.
    e.g. if 0541234567 already has vouchers 001 and 002, returns 3.
    """
    max_seq = (
        db.query(Voucher.sequence)
        .filter(Voucher.mobile == mobile)
        .order_by(Voucher.sequence.desc())
        .first()
    )
    return (max_seq[0] + 1) if max_seq else 1


def create_voucher(db: Session, mobile: str, voucher_type: str,
                   valid_until: date, receipt_number: str | None = None,
                   receipt_date: date | None = None,
                   notes: str | None = None,
                   display_name: str | None = None,
                   greeting: str | None = None,
                   location: str | None = None) -> Voucher:
    """
    Create a new draft voucher for an existing holder.
    Raises RulesError if holder does not exist.
    """
    holder = db.get(Holder, mobile)
    if not holder:
        raise RulesError(f"מזמין לא נמצא: {mobile}")

    seq = next_sequence(db, mobile)
    voucher_id = f"{mobile}-{seq:03d}"

    voucher = Voucher(
        voucher_id=voucher_id,
        mobile=mobile,
        sequence=seq,
        voucher_type=voucher_type,
        valid_until=valid_until,
        issued_at=utcnow(),
        status="draft",
        receipt_number=receipt_number,
        receipt_date=receipt_date,
        notes=notes,
        display_name=display_name,
        greeting=greeting,
        location=location,
    )
    db.add(voucher)
    db.commit()
    db.refresh(voucher)
    return voucher


# ── Cement ────────────────────────────────────────────────────────────────────

def _cement(db: Session, voucher: Voucher) -> None:
    """
    Copy holder's current details into the voucher's cemented fields.
    Called ONCE on first send — never again.
    These fields are the permanent record of who held the voucher at send time.
    """
    holder = db.get(Holder, voucher.mobile)
    if not holder:
        raise RulesError(
            f"לא ניתן לצמנט — מזמין לא נמצא: {voucher.mobile}"
        )

    voucher.holder_name   = holder.name
    voucher.holder_mobile = holder.mobile
    voucher.holder_email  = holder.email
    # Do NOT commit here — caller controls the transaction


# ── File paths ────────────────────────────────────────────────────────────────

def _voucher_dir(voucher: Voucher) -> Path:
    """Return (and create) the storage folder for this voucher's files."""
    folder = Path("vouchers") / voucher.mobile / voucher.voucher_id
    folder.mkdir(parents=True, exist_ok=True)
    return folder


# ── First send (draft → sent) ─────────────────────────────────────────────────

def first_send(db: Session, voucher_id: str,
               sent_via: str, note: str | None = None,
               performed_by: str | None = None) -> Voucher:
    """
    Execute the full first-send sequence:
      1. Validate state (must be draft)
      2. Cement holder details
      3. Set first_sent_at
      4. Generate QR (once — saved to file)
      5. Generate PDF
      6. Log in sendings
      7. Set status = sent
    """
    voucher = db.get(Voucher, voucher_id)
    if not voucher:
        raise RulesError(f"שובר לא נמצא: {voucher_id}")
    if voucher.status != "draft":
        raise RulesError(
            f"שובר {voucher_id} אינו בטיוטה — סטטוס נוכחי: {voucher.status}"
        )

    # 1. Cement
    _cement(db, voucher)

    # 2. Set first_sent_at (never changes again)
    now = utcnow()
    voucher.first_sent_at = now

    # 3. Prepare file folder
    folder = _voucher_dir(voucher)

    # Freeze the image: if no per-voucher image was chosen, cement the current
    # library default so later default changes never alter this sent voucher.
    if not voucher.image_file:
        voucher.image_file = images.get_default()

    # Freeze the location the same way (cement current default if unset).
    if not voucher.location:
        voucher.location = settings.get_default_location()

    # 4. Generate QR — saved to qr.png, path stored on voucher
    qr_path = qr_module.generate_qr(voucher, folder)
    voucher.qr_path = str(qr_path)

    # 5. Generate PDF — saved to voucher.pdf
    pdf_path = pdf_module.generate_pdf(voucher, folder)
    voucher.pdf_path = str(pdf_path)

    # 6. Set status
    voucher.status = "sent"

    # 7. Log send event
    sending = Sending(
        voucher_id=voucher_id,
        sent_at=now,
        sent_via=sent_via,
        note=note,
        performed_by=performed_by,
    )
    db.add(sending)

    db.commit()
    db.refresh(voucher)
    return voucher


# ── Resend (sent → sent) ──────────────────────────────────────────────────────

def resend(db: Session, voucher_id: str,
           sent_via: str, note: str | None = None,
           performed_by: str | None = None) -> Voucher:
    """
    Resend a voucher that has already been sent:
      1. Validate state (must be sent, not used)
      2. Reuse original QR (never regenerate)
      3. Regenerate PDF (same content, fresh render)
      4. Log new row in sendings
      Voucher data itself does not change.
    """
    voucher = db.get(Voucher, voucher_id)
    if not voucher:
        raise RulesError(f"שובר לא נמצא: {voucher_id}")
    if voucher.status == "draft":
        raise RulesError(
            f"שובר {voucher_id} טרם נשלח — השתמש בשליחה ראשונה"
        )
    if voucher.status == "used":
        raise RulesError(
            f"שובר {voucher_id} מומש — לא ניתן לשלוח מחדש"
        )

    folder = _voucher_dir(voucher)

    # Reuse QR — do NOT call qr_module.generate_qr again
    # qr_path is already set and the file already exists

    # Regenerate PDF (same QR embedded)
    pdf_path = pdf_module.generate_pdf(voucher, folder)
    voucher.pdf_path = str(pdf_path)

    # Log new send event
    sending = Sending(
        voucher_id=voucher_id,
        sent_at=utcnow(),
        sent_via=sent_via,
        note=note,
        performed_by=performed_by,
    )
    db.add(sending)

    db.commit()
    db.refresh(voucher)
    return voucher


# ── Mark used (sent → used) ───────────────────────────────────────────────────

def mark_used(db: Session, voucher_id: str) -> Voucher:
    """
    Mark a voucher as used (fully frozen).
    Only sent vouchers can be marked used.
    After this: no edits, no resends — view and print only.
    """
    voucher = db.get(Voucher, voucher_id)
    if not voucher:
        raise RulesError(f"שובר לא נמצא: {voucher_id}")
    if voucher.status == "draft":
        raise RulesError(
            f"שובר {voucher_id} הוא טיוטה — יש לשלוח לפני מימוש"
        )
    if voucher.status == "used":
        raise RulesError(f"שובר {voucher_id} כבר מומש")

    voucher.status = "used"
    db.commit()
    db.refresh(voucher)
    return voucher


# ── Update receipt / notes (editable until used) ──────────────────────────────

def update_voucher_fields(db: Session, voucher_id: str,
                          receipt_number: str | None = None,
                          receipt_date: date | None = None,
                          notes: str | None = None,
                          greeting: str | None = None,
                          location: str | None = None) -> Voucher:
    """
    Update the manually-entered accounting fields on a voucher.
    Allowed at any status except used.
    """
    voucher = db.get(Voucher, voucher_id)
    if not voucher:
        raise RulesError(f"שובר לא נמצא: {voucher_id}")
    if voucher.is_frozen:
        raise RulesError(
            f"שובר {voucher_id} מומש — לא ניתן לערוך"
        )

    if receipt_number is not None:
        voucher.receipt_number = receipt_number
    if receipt_date is not None:
        voucher.receipt_date = receipt_date
    if notes is not None:
        voucher.notes = notes
    if greeting is not None:
        # Empty string clears the greeting; non-empty sets it.
        voucher.greeting = greeting or None
    if location is not None:
        # Empty string clears the per-voucher location (falls back to default).
        voucher.location = location or None

    db.commit()
    db.refresh(voucher)
    return voucher


# ── Voucher location (one-time per voucher, or set as future default) ─────────

def set_voucher_location(db: Session, voucher_id: str, location: str,
                         make_default: bool = False) -> Voucher:
    """
    Set the location/venue printed on a voucher.

    - make_default=True also stores it as the default for FUTURE vouchers.
    - Blocked if the voucher is used. Regenerates PDF+PNG if already sent.
    """
    voucher = db.get(Voucher, voucher_id)
    if not voucher:
        raise RulesError(f"שובר לא נמצא: {voucher_id}")
    if voucher.is_frozen:
        raise RulesError(f"שובר {voucher_id} מומש — לא ניתן לשנות מיקום")

    voucher.location = (location or "").strip() or None

    if make_default and voucher.location:
        settings.set_default_location(voucher.location)

    if voucher.pdf_path:
        folder = _voucher_dir(voucher)
        pdf_path = pdf_module.generate_pdf(voucher, folder)
        voucher.pdf_path = str(pdf_path)

    db.commit()
    db.refresh(voucher)
    return voucher


# ── Voucher image (one-time per voucher, or set as future default) ────────────

def set_voucher_image(db: Session, voucher_id: str, image_file: str,
                      make_default: bool = False) -> Voucher:
    """
    Set the image used on a voucher.

    - image_file: a filename that already exists in the image library.
    - make_default=True also sets it as the library default for FUTURE
      vouchers (this voucher gets it either way).

    Blocked if the voucher is used. If the voucher was already sent (has a
    PDF), the PDF + PNG are regenerated immediately so the change is visible —
    WITHOUT logging a new sending event.
    """
    voucher = db.get(Voucher, voucher_id)
    if not voucher:
        raise RulesError(f"שובר לא נמצא: {voucher_id}")
    if voucher.is_frozen:
        raise RulesError(f"שובר {voucher_id} מומש — לא ניתן לשנות תמונה")

    # Validate the image exists in the library.
    known = {img["file"] for img in images.list_images()}
    if image_file not in known:
        raise RulesError(f"תמונה לא קיימת בספרייה: {image_file}")

    voucher.image_file = image_file

    if make_default:
        images.set_default(image_file)

    # Regenerate output only if the voucher has already been rendered (sent).
    if voucher.pdf_path:
        folder = _voucher_dir(voucher)
        pdf_path = pdf_module.generate_pdf(voucher, folder)
        voucher.pdf_path = str(pdf_path)

    db.commit()
    db.refresh(voucher)
    return voucher
