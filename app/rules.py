"""
Rules Engine — all business logic for the ticket lifecycle.

This module is the single source of truth for:
  - Status transitions
        draft → awaiting_payment → paid → active → used
        (a free ticket goes draft → active directly)
  - Cementing holder details into a ticket
  - Generating / reusing QR codes
  - Generating PDFs
  - Logging send events (ticket sends and payment requests)
  - Entries: hold / consume / cancel (the pass counter)
  - Holder editability rules

Nothing in here knows about HTTP — it only receives a DB session
and returns updated ORM objects. Routers call these functions.
"""

from datetime import datetime, date
from app.utils import utcnow
from pathlib import Path
from sqlalchemy.orm import Session

from app.models import (
    Holder, Voucher, Sending, Entry,
    KIND_VOUCHER, KIND_PASS, VALID_KINDS,
    STATUS_DRAFT, STATUS_AWAITING, STATUS_PAID, STATUS_ACTIVE, STATUS_USED,
    ENTRY_HELD, ENTRY_CONSUMED, ENTRY_CANCELLED, PAYMENT_METHODS,
)
from app import qr_module, pdf_module, images, settings, mailer


# ── Exceptions ────────────────────────────────────────────────────────────────

class RulesError(Exception):
    """Raised when a business rule is violated."""
    pass


# ── Holder rules ──────────────────────────────────────────────────────────────

def can_edit_holder(db: Session, mobile: str) -> bool:
    """
    A holder can be edited only while no treatment was consumed on any of
    their tickets (decision 6a). A fully used ticket also locks, which covers
    legacy rows that were marked used before entries existed.
    Returns True (editable) or False (locked).
    """
    used_count = (
        db.query(Voucher)
        .filter(Voucher.mobile == mobile, Voucher.status == STATUS_USED)
        .count()
    )
    if used_count:
        return False
    consumed = (
        db.query(Entry)
        .join(Voucher, Voucher.voucher_id == Entry.voucher_id)
        .filter(Voucher.mobile == mobile, Entry.status == ENTRY_CONSUMED)
        .count()
    )
    return consumed == 0


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
    Raises RulesError if the holder is locked (a treatment was consumed).
    """
    holder = db.get(Holder, mobile)
    if not holder:
        raise RulesError(f"מזמין לא נמצא: {mobile}")

    if not can_edit_holder(db, mobile):
        raise RulesError(
            "לא ניתן לערוך פרטי מזמין — קיים טיפול שמומש על שמו"
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


def _clean_money(value, label: str) -> float | None:
    """Validate an optional money amount (None / '' → None, negative → error)."""
    if value is None or value == "":
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        raise RulesError(f"{label}: ערך לא תקין")
    if amount < 0:
        raise RulesError(f"{label}: לא יכול להיות שלילי")
    return amount


def create_voucher(db: Session, mobile: str, voucher_type: str,
                   valid_until: date, receipt_number: str | None = None,
                   receipt_date: date | None = None,
                   notes: str | None = None,
                   display_name: str | None = None,
                   greeting: str | None = None,
                   location: str | None = None,
                   kind: str = KIND_VOUCHER,
                   entries_total: int = 1,
                   list_price=None, discount=None, price=None,
                   terms: str | None = None) -> Voucher:
    """
    Create a new draft ticket for an existing holder.

    - kind: VOUCHER (gift) or PASS (self use); both may have many entries.
    - list_price / discount / price: if price is not given it is computed as
      list_price - discount (when a list price is known). None = free ticket.
    - terms: copied from the settings default when not given, so later edits
      to the default never change tickets already created.
    Raises RulesError if the holder does not exist or a value is invalid.
    """
    holder = db.get(Holder, mobile)
    if not holder:
        raise RulesError(f"מזמין לא נמצא: {mobile}")

    kind = (kind or KIND_VOUCHER).upper()
    if kind not in VALID_KINDS:
        raise RulesError(f"סוג כרטיס לא תקין: {kind}")

    try:
        # None / '' → 1 (classic voucher); an explicit 0 is invalid
        entries_total = 1 if entries_total in (None, "") else int(entries_total)
    except (TypeError, ValueError):
        raise RulesError("כמות טיפולים לא תקינה")
    if entries_total < 1 or entries_total > 100:
        raise RulesError("כמות טיפולים חייבת להיות בין 1 ל-100")

    list_price = _clean_money(list_price, "מחיר מחירון")
    discount   = _clean_money(discount, "הנחה")
    price      = _clean_money(price, "מחיר")
    if price is None and list_price is not None:
        price = max(list_price - (discount or 0), 0)

    if terms is None:
        terms = settings.get_default_terms() or None

    seq = next_sequence(db, mobile)
    voucher_id = f"{mobile}-{seq:03d}"

    voucher = Voucher(
        voucher_id=voucher_id,
        mobile=mobile,
        sequence=seq,
        kind=kind,
        entries_total=entries_total,
        voucher_type=voucher_type,
        valid_until=valid_until,
        issued_at=utcnow(),
        status=STATUS_DRAFT,
        receipt_number=receipt_number,
        receipt_date=receipt_date,
        notes=notes,
        display_name=display_name,
        greeting=greeting if kind == KIND_VOUCHER else None,
        location=location,
        list_price=list_price,
        discount=discount,
        price=price,
        terms=terms,
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


def _get_voucher(db: Session, voucher_id: str) -> Voucher:
    """Load a ticket or raise RulesError."""
    voucher = db.get(Voucher, voucher_id)
    if not voucher:
        raise RulesError(f"כרטיס לא נמצא: {voucher_id}")
    return voucher


# ── Payment request (draft → awaiting_payment) ────────────────────────────────

def payment_request_text(voucher: Voucher) -> str:
    """
    Plain-text message sent to the customer with the payment request:
    product, price, terms and (phase B) the payment link.
    """
    holder_name = voucher.holder_name or (
        voucher.holder_ref.name if voucher.holder_ref else "")
    lines = [f"שלום {holder_name}," if holder_name else "שלום,",
             "",
             f"{voucher.product_title} — גלים ונפש",
             f"מחיר: {voucher.price:,.0f} ₪" if voucher.price else "",
             ""]
    if voucher.terms:
        lines += ["תנאים:", voucher.terms, ""]
    if voucher.payment_url:
        lines += ["לתשלום מאובטח:", voucher.payment_url, ""]
    lines += ["לאחר התשלום נשלח לך את הכרטיס.", "תודה, אביגל"]
    return "\n".join(lines)


def request_payment(db: Session, voucher_id: str, sent_via: str,
                    note: str | None = None,
                    performed_by: str | None = None) -> Voucher:
    """
    Send (or resend) the payment request for a ticket.
      - Allowed from draft (moves to awaiting_payment) or awaiting_payment
        (resend — status unchanged).
      - The ticket must have a price; free tickets are sent directly.
      - Logs a sendings row of kind PAYMENT_LINK.
    Phase B will create the Green Invoice payment page here and store its URL.
    """
    voucher = _get_voucher(db, voucher_id)
    if voucher.status not in (STATUS_DRAFT, STATUS_AWAITING):
        raise RulesError(
            f"כרטיס {voucher_id} — לא ניתן לשלוח בקשת תשלום בסטטוס {voucher.status_display}"
        )
    if voucher.is_free:
        raise RulesError(
            f"כרטיס {voucher_id} ללא מחיר — ניתן לשלוח אותו ישירות"
        )

    voucher.status = STATUS_AWAITING
    db.add(Sending(
        voucher_id=voucher_id,
        sent_at=utcnow(),
        sent_via=sent_via,
        kind="PAYMENT_LINK",
        note=note,
        performed_by=performed_by,
    ))
    db.commit()
    db.refresh(voucher)
    return voucher


# ── Mark paid (draft / awaiting_payment → paid) ───────────────────────────────

def mark_paid(db: Session, voucher_id: str, method: str,
              receipt_number: str | None = None,
              gi_document_id: str | None = None,
              performed_by: str | None = None) -> Voucher:
    """
    Record that the ticket was paid.
      - Manual methods: CASH / BIT / TRANSFER / CARD (Avigal presses the button)
      - GI: set by the Green Invoice webhook (phase B)
    Allowed from draft or awaiting_payment. Sets paid_at, payment_method and,
    when given, the receipt number (from GI or typed by hand).
    """
    voucher = _get_voucher(db, voucher_id)
    if voucher.status not in (STATUS_DRAFT, STATUS_AWAITING):
        raise RulesError(
            f"כרטיס {voucher_id} כבר שולם או נשלח (סטטוס {voucher.status_display})"
        )
    method = (method or "").upper()
    if method not in PAYMENT_METHODS or method in ("FREE", "MANUAL"):
        raise RulesError(f"אמצעי תשלום לא תקין: {method}")

    now = utcnow()
    voucher.status = STATUS_PAID
    voucher.payment_method = method
    voucher.paid_at = now
    if receipt_number:
        voucher.receipt_number = receipt_number
        voucher.receipt_date = voucher.receipt_date or now.date()
    if gi_document_id:
        voucher.gi_document_id = gi_document_id

    db.commit()
    db.refresh(voucher)
    return voucher


# ── Send ticket (paid / free draft → active) ──────────────────────────────────

def first_send(db: Session, voucher_id: str,
               sent_via: str, note: str | None = None,
               performed_by: str | None = None) -> Voucher:
    """
    Execute the full first-send (send ticket) sequence:
      1. Validate state (paid, or a free draft)
      2. Cement holder details
      3. Set first_sent_at
      4. Generate QR (once — saved to file)
      5. Generate PDF
      6. Log in sendings (kind TICKET)
      7. Set status = active
    """
    voucher = _get_voucher(db, voucher_id)
    if voucher.status == STATUS_DRAFT and not voucher.is_free:
        raise RulesError(
            f"כרטיס {voucher_id} טרם שולם — יש לשלוח בקשת תשלום או לסמן כשולם"
        )
    if voucher.status == STATUS_AWAITING:
        raise RulesError(
            f"כרטיס {voucher_id} ממתין לתשלום — יש לסמן כשולם לפני השליחה"
        )
    if voucher.status not in (STATUS_DRAFT, STATUS_PAID):
        raise RulesError(
            f"כרטיס {voucher_id} כבר נשלח — סטטוס נוכחי: {voucher.status_display}"
        )

    # 1. Cement
    _cement(db, voucher)

    # 2. Set first_sent_at (never changes again)
    now = utcnow()
    voucher.first_sent_at = now

    # A free ticket records that no payment was needed
    if voucher.status == STATUS_DRAFT and voucher.is_free:
        voucher.payment_method = voucher.payment_method or "FREE"

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
    voucher.status = STATUS_ACTIVE

    # 7. Log send event
    sending = Sending(
        voucher_id=voucher_id,
        sent_at=now,
        sent_via=sent_via,
        kind="TICKET",
        note=note,
        performed_by=performed_by,
    )
    db.add(sending)

    db.commit()
    db.refresh(voucher)

    # 8. Notify by e-mail that a new ticket was produced (background, never raises)
    try:
        mailer.notify_new_voucher(voucher, sent_via, performed_by)
    except Exception:
        pass   # e-mail must never break a send

    return voucher


# ── Resend (active → active) ──────────────────────────────────────────────────

def resend(db: Session, voucher_id: str,
           sent_via: str, note: str | None = None,
           performed_by: str | None = None) -> Voucher:
    """
    Resend a ticket that has already been sent:
      1. Validate state (must be active, not used)
      2. Reuse original QR (never regenerate)
      3. Regenerate PDF (same content, fresh render)
      4. Log new row in sendings
      Voucher data itself does not change.
    """
    voucher = _get_voucher(db, voucher_id)
    if voucher.status == STATUS_USED:
        raise RulesError(
            f"כרטיס {voucher_id} מומש — לא ניתן לשלוח מחדש"
        )
    if voucher.status != STATUS_ACTIVE:
        raise RulesError(
            f"כרטיס {voucher_id} טרם נשלח — השתמש בשליחה ראשונה"
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
        kind="TICKET",
        note=note,
        performed_by=performed_by,
    )
    db.add(sending)

    db.commit()
    db.refresh(voucher)
    return voucher


# ── Entries: hold / consume / cancel ──────────────────────────────────────────

def _require_active(voucher: Voucher) -> None:
    """Entries can only change on an active ticket."""
    if voucher.status == STATUS_USED:
        raise RulesError(f"כרטיס {voucher.voucher_id} מומש במלואו")
    if voucher.status != STATUS_ACTIVE:
        raise RulesError(
            f"כרטיס {voucher.voucher_id} אינו פעיל — יש לשלוח אותו תחילה"
        )


def _require_available(voucher: Voucher) -> None:
    """There must be an unused, unheld entry left."""
    if voucher.entries_available <= 0:
        raise RulesError(
            f"כרטיס {voucher.voucher_id} — לא נותרו טיפולים פנויים"
        )


def _next_entry_seq(voucher: Voucher) -> int:
    """Running number for the next entry row (cancelled rows count too)."""
    return max((e.seq for e in voucher.entries), default=0) + 1


def _close_if_exhausted(voucher: Voucher) -> None:
    """Freeze the ticket once every entry was consumed."""
    if voucher.entries_consumed >= (voucher.entries_total or 0):
        voucher.status = STATUS_USED


def _regenerate_pdf(voucher: Voucher) -> None:
    """
    Re-render PDF + image of an already-sent ticket so the printed copy shows
    the treatments used so far. QR is reused; no sendings row is added.
    """
    if not voucher.pdf_path:
        return
    folder = _voucher_dir(voucher)
    voucher.pdf_path = str(pdf_module.generate_pdf(voucher, folder))


def hold_entry(db: Session, voucher_id: str,
               scheduled_for: datetime | None = None,
               note: str | None = None,
               performed_by: str | None = None) -> Entry:
    """
    Reserve one entry for a scheduled treatment (שריון).
    Requires: active ticket, an available entry, not past valid_until.
    """
    voucher = _get_voucher(db, voucher_id)
    _require_active(voucher)
    _require_available(voucher)
    if voucher.valid_until and voucher.valid_until < date.today():
        raise RulesError(
            f"כרטיס {voucher_id} פג תוקף ב-{voucher.valid_until.strftime('%d/%m/%Y')}"
        )

    entry = Entry(
        voucher_id=voucher_id,
        seq=_next_entry_seq(voucher),
        status=ENTRY_HELD,
        scheduled_for=scheduled_for,
        held_at=utcnow(),
        note=note,
        performed_by=performed_by,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def _get_entry(db: Session, voucher_id: str, entry_id: int) -> Entry:
    """Load an entry that belongs to the given ticket, or raise."""
    entry = db.get(Entry, entry_id)
    if not entry or entry.voucher_id != voucher_id:
        raise RulesError(f"טיפול {entry_id} לא נמצא בכרטיס {voucher_id}")
    return entry


def consume_entry(db: Session, voucher_id: str, entry_id: int,
                  note: str | None = None,
                  performed_by: str | None = None) -> Entry:
    """The scheduled treatment took place: held → consumed."""
    voucher = _get_voucher(db, voucher_id)
    _require_active(voucher)
    entry = _get_entry(db, voucher_id, entry_id)
    if entry.status != ENTRY_HELD:
        raise RulesError(f"טיפול {entry.seq} אינו משוריין — סטטוס: {entry.status_display}")

    entry.status = ENTRY_CONSUMED
    entry.consumed_at = utcnow()
    if note:
        entry.note = note
    entry.performed_by = performed_by or entry.performed_by

    db.flush()
    db.refresh(voucher)
    _close_if_exhausted(voucher)
    _regenerate_pdf(voucher)        # ticket now lists this treatment's date
    db.commit()
    db.refresh(entry)
    return entry


def cancel_hold(db: Session, voucher_id: str, entry_id: int,
                note: str | None = None,
                performed_by: str | None = None) -> Entry:
    """The scheduled treatment was cancelled: held → cancelled (count released)."""
    voucher = _get_voucher(db, voucher_id)
    _require_active(voucher)
    entry = _get_entry(db, voucher_id, entry_id)
    if entry.status != ENTRY_HELD:
        raise RulesError(f"טיפול {entry.seq} אינו משוריין — סטטוס: {entry.status_display}")

    entry.status = ENTRY_CANCELLED
    entry.cancelled_at = utcnow()
    if note:
        entry.note = note
    entry.performed_by = performed_by or entry.performed_by

    db.commit()
    db.refresh(entry)
    return entry


def consume_direct(db: Session, voucher_id: str,
                   note: str | None = None,
                   performed_by: str | None = None) -> Voucher:
    """
    A treatment took place without a prior hold (walk-in): create the entry
    directly as consumed. On a 1-entry ticket this is the old "mark used".
    """
    voucher = _get_voucher(db, voucher_id)
    _require_active(voucher)
    _require_available(voucher)

    now = utcnow()
    db.add(Entry(
        voucher_id=voucher_id,
        seq=_next_entry_seq(voucher),
        status=ENTRY_CONSUMED,
        held_at=now,
        consumed_at=now,
        note=note,
        performed_by=performed_by,
    ))
    db.flush()
    db.refresh(voucher)
    _close_if_exhausted(voucher)
    _regenerate_pdf(voucher)        # ticket now lists this treatment's date
    db.commit()
    db.refresh(voucher)
    return voucher


# ── Mark used (legacy name — consumes one entry) ─────────────────────────────

def mark_used(db: Session, voucher_id: str,
              performed_by: str | None = None) -> Voucher:
    """
    Legacy API kept for V1 callers: consume one entry directly.
    On a classic single voucher the ticket becomes used (fully frozen).
    Only active tickets can be marked used.
    """
    voucher = _get_voucher(db, voucher_id)
    if voucher.status in (STATUS_DRAFT, STATUS_AWAITING, STATUS_PAID):
        raise RulesError(
            f"כרטיס {voucher_id} טרם נשלח — יש לשלוח לפני מימוש"
        )
    if voucher.status == STATUS_USED:
        raise RulesError(f"כרטיס {voucher_id} כבר מומש")
    return consume_direct(db, voucher_id, performed_by=performed_by)


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
    voucher = _get_voucher(db, voucher_id)
    if voucher.is_frozen:
        raise RulesError(
            f"כרטיס {voucher_id} מומש — לא ניתן לערוך"
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


# ── Update price (editable until paid) ────────────────────────────────────────

def set_price(db: Session, voucher_id: str,
              list_price=None, discount=None, price=None) -> Voucher:
    """
    Change the pricing of a ticket. Allowed only before payment
    (draft / awaiting_payment). price=None with a list price recomputes
    list_price - discount; both None = free ticket.
    """
    voucher = _get_voucher(db, voucher_id)
    if voucher.status not in (STATUS_DRAFT, STATUS_AWAITING):
        raise RulesError(
            f"כרטיס {voucher_id} כבר שולם — לא ניתן לשנות מחיר"
        )

    voucher.list_price = _clean_money(list_price, "מחיר מחירון")
    voucher.discount   = _clean_money(discount, "הנחה")
    final = _clean_money(price, "מחיר")
    if final is None and voucher.list_price is not None:
        final = max(voucher.list_price - (voucher.discount or 0), 0)
    voucher.price = final

    # A ticket that became free while awaiting payment goes back to draft
    if voucher.is_free and voucher.status == STATUS_AWAITING:
        voucher.status = STATUS_DRAFT

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
    voucher = _get_voucher(db, voucher_id)
    if voucher.is_frozen:
        raise RulesError(f"כרטיס {voucher_id} מומש — לא ניתן לשנות מיקום")

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
    voucher = _get_voucher(db, voucher_id)
    if voucher.is_frozen:
        raise RulesError(f"כרטיס {voucher_id} מומש — לא ניתן לשנות תמונה")

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
