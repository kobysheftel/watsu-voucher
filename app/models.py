"""
ORM Models — SQLAlchemy
Tables: holders, vouchers (= tickets), entries, sendings

Key design decisions:
- holders.mobile is the primary key (Israeli format 05X-XXXXXXX)
- vouchers.mobile is a plain text reference, NOT a live FK
  (so holder deletion — if ever added — doesn't break voucher history)
- cemented_* fields on vouchers are the frozen snapshot of holder data
  copied on first send and never changed again
- sendings records every send/resend action with sent_via and timestamp

Phase A (2026-09-13) — "Ticket" generalisation:
- The `vouchers` table now holds every ticket. `kind` says whether it is a
  gift VOUCHER (שובר) or a self-use PASS (כרטיסיה). Both are multi-entry:
  `entries_total` treatments are included (a classic voucher has 1).
- `entries` rows track each treatment: held (שריון) → consumed (מימוש), or
  held → cancelled. Counters are derived from the rows, never stored.
- Payment fields (price, paid_at, payment_method, ...) are filled either by
  the manual "mark paid" action or — in phase B — by the Green Invoice webhook.
"""

from datetime import datetime, date
from app.utils import utcnow
from sqlalchemy import (
    Column, Text, Integer, Float, Date, DateTime, ForeignKey, String
)
from sqlalchemy.orm import relationship
from app.database import Base


# ── Constants shared by rules / schemas / templates ───────────────────────────

KIND_VOUCHER = "VOUCHER"     # gift for a third party (שובר מתנה)
KIND_PASS    = "PASS"        # bought for self use (כרטיסיה)
VALID_KINDS  = {KIND_VOUCHER, KIND_PASS}

# Hebrew display labels for the ticket kinds (used in templates and PDFs)
KIND_DISPLAY = {
    KIND_VOUCHER: "שובר",
    KIND_PASS:    "כרטיסיה",
}

# Ticket status values (see docs/DESIGN-V2-TICKETS.md §2)
STATUS_DRAFT    = "draft"              # created, nothing sent yet
STATUS_AWAITING = "awaiting_payment"   # payment request sent, waiting for money
STATUS_PAID     = "paid"               # money received, ticket not sent yet
STATUS_ACTIVE   = "active"             # ticket sent (cemented + QR); entries usable
STATUS_USED     = "used"               # all entries consumed — frozen
VALID_STATUSES  = {STATUS_DRAFT, STATUS_AWAITING, STATUS_PAID,
                   STATUS_ACTIVE, STATUS_USED}

STATUS_DISPLAY = {
    STATUS_DRAFT:    "טיוטה",
    STATUS_AWAITING: "ממתין לתשלום",
    STATUS_PAID:     "שולם",
    STATUS_ACTIVE:   "פעיל",
    STATUS_USED:     "מומש",
}

# Entry status values
ENTRY_HELD      = "held"
ENTRY_CONSUMED  = "consumed"
ENTRY_CANCELLED = "cancelled"

ENTRY_DISPLAY = {
    ENTRY_HELD:      "משוריין",
    ENTRY_CONSUMED:  "מומש",
    ENTRY_CANCELLED: "בוטל",
}

# Manual payment methods (Green Invoice adds "GI" in phase B)
PAYMENT_METHODS = {
    "CASH":     "מזומן",
    "BIT":      "ביט",
    "TRANSFER": "העברה בנקאית",
    "CARD":     "אשראי",
    "GI":       "חשבונית ירוקה",
    "FREE":     "ללא תשלום",
    "manual":   "ידני",          # legacy rows migrated from V1
}


class Holder(Base):
    """
    A person who orders tickets, identified by mobile number.
    Editable freely while none of their tickets has a consumed entry.
    Locked (no edits) once any entry was consumed.
    Never deleted.
    """
    __tablename__ = "holders"

    mobile      = Column(Text, primary_key=True)  # e.g. 0541234567
    name        = Column(Text, nullable=False)
    email       = Column(Text, nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at  = Column(DateTime, default=datetime.utcnow,
                         onupdate=datetime.utcnow, nullable=False)

    # Relationship: all vouchers linked to this holder (via mobile text match)
    vouchers    = relationship(
        "Voucher",
        primaryjoin="Holder.mobile == foreign(Voucher.mobile)",
        back_populates="holder_ref",
        order_by="Voucher.issued_at.desc()",
    )

    def __repr__(self):
        return f"<Holder mobile={self.mobile} name={self.name}>"


class Voucher(Base):
    """
    A ticket document — gift voucher (kind=VOUCHER) or pass (kind=PASS).

    Status lifecycle:
        draft → awaiting_payment (payment request sent)
              → paid             (money received: webhook or manual)
              → active           (ticket sent: cement + QR + PDF generated)
              → used             (all entries consumed: fully frozen)
        A ticket without a price skips the payment steps: draft → active.

    Once active:
        - cemented_* fields never change (snapshot of holder at send time)
        - first_sent_at never changes
        - qr_path never changes (QR reused on all resends)
        - receipt_number and receipt_date can still be edited until used
    """
    __tablename__ = "vouchers"

    # Primary key: {mobile}-{sequence:03d}  e.g. 0541234567-001
    voucher_id      = Column(Text, primary_key=True)

    # Plain text reference to the holder's mobile (not a live FK by design)
    mobile          = Column(Text, nullable=False, index=True)

    # Position in this holder's voucher sequence (1, 2, 3, ...)
    sequence        = Column(Integer, nullable=False)

    # Ticket kind: VOUCHER (gift) / PASS (self use)
    kind            = Column(Text, nullable=False, default=KIND_VOUCHER)

    # Number of treatments included (1 = classic single voucher)
    entries_total   = Column(Integer, nullable=False, default=1)

    # Voucher content
    voucher_type    = Column(Text, nullable=False)   # יחיד / זוגי
    valid_until     = Column(Date, nullable=False)

    # Timestamps
    issued_at       = Column(DateTime, default=datetime.utcnow, nullable=False)
    first_sent_at   = Column(DateTime, nullable=True)   # set once on first send

    # Status: draft / awaiting_payment / paid / active / used
    status          = Column(Text, nullable=False, default=STATUS_DRAFT)

    # Display name on voucher PDF (optional — if empty, uses holder_name)
    display_name    = Column(Text, nullable=True)

    # Optional greeting / blessing printed on the voucher (editable until used)
    greeting        = Column(Text, nullable=True)

    # Location / venue printed on the voucher. NULL = use the default at render;
    # cemented on first send so sent vouchers keep their location.
    location        = Column(Text, nullable=True)

    # Image shown on the voucher. NULL = use the library default at render time.
    # Set (cemented) on first send so already-sent vouchers keep their image
    # even if the library default later changes.
    image_file      = Column(Text, nullable=True)

    # === Pricing (phase A) ===
    list_price      = Column(Float, nullable=True)   # from the price list at creation
    discount        = Column(Float, nullable=True)   # amount in ₪ taken off the list price
    price           = Column(Float, nullable=True)   # final agreed price (None/0 = free)
    terms           = Column(Text,  nullable=True)   # terms text copied at creation

    # === Payment (phase A manual, phase B Green Invoice) ===
    payment_method  = Column(Text, nullable=True)    # CASH / BIT / TRANSFER / CARD / GI / FREE
    payment_url     = Column(Text, nullable=True)    # Green Invoice hosted payment page
    gi_document_id  = Column(Text, nullable=True)    # Green Invoice document id
    paid_at         = Column(DateTime, nullable=True)

    # Manual accounting fields (editable until status=used)
    receipt_number  = Column(Text, nullable=True)
    receipt_date    = Column(Date, nullable=True)
    notes           = Column(Text, nullable=True)

    # Generated file paths
    qr_path         = Column(Text, nullable=True)   # set on first send, never changes
    pdf_path        = Column(Text, nullable=True)   # updated on every send/resend

    # === Cemented holder snapshot ===
    # Copied from Holder on first send. Never modified after that.
    holder_name     = Column(Text, nullable=True)
    holder_mobile   = Column(Text, nullable=True)
    holder_email    = Column(Text, nullable=True)

    # Back-reference to holder (non-enforced, for convenience queries)
    holder_ref      = relationship(
        "Holder",
        primaryjoin="foreign(Voucher.mobile) == Holder.mobile",
        back_populates="vouchers",
    )

    # All sending events for this voucher
    sendings        = relationship(
        "Sending",
        back_populates="voucher",
        order_by="Sending.sent_at.desc()",
        cascade="all, delete-orphan",
    )

    # All entries (treatment slots) of this ticket, oldest first
    entries         = relationship(
        "Entry",
        back_populates="voucher",
        order_by="Entry.seq.asc()",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<Voucher {self.voucher_id} kind={self.kind} status={self.status}>"

    # ── Convenience properties ────────────────────────────────────────────────

    @property
    def is_frozen(self):
        """Used vouchers are completely frozen — no changes allowed."""
        return self.status == STATUS_USED

    @property
    def is_cemented(self):
        """True once first send has happened (holder snapshot is frozen)."""
        return self.first_sent_at is not None

    @property
    def is_pass(self):
        """True for a self-use pass (כרטיסיה)."""
        return self.kind == KIND_PASS

    @property
    def kind_display(self):
        return KIND_DISPLAY.get(self.kind, self.kind)

    @property
    def status_display(self):
        return STATUS_DISPLAY.get(self.status, self.status)

    @property
    def payment_method_display(self):
        return PAYMENT_METHODS.get(self.payment_method or "", self.payment_method or "")

    @property
    def is_free(self):
        """A ticket with no price skips the payment steps."""
        return not self.price or self.price <= 0

    @property
    def is_paid(self):
        """True once payment was recorded (or the ticket is free and sent)."""
        return self.paid_at is not None

    # Derived entry counters — never stored, always computed from the rows
    @property
    def entries_consumed(self) -> int:
        return sum(1 for e in self.entries if e.status == ENTRY_CONSUMED)

    @property
    def entries_held(self) -> int:
        return sum(1 for e in self.entries if e.status == ENTRY_HELD)

    @property
    def entries_available(self) -> int:
        return (self.entries_total or 0) - self.entries_consumed - self.entries_held

    @property
    def product_title(self) -> str:
        """
        Hebrew product description used on the PDF, in messages and e-mails.
        e.g. "שובר מתנה לטיפול וואטסו ליחיד", "כרטיסיה ל-5 טיפולי וואטסו זוגי".
        """
        couple = self.voucher_type in ("זוגי", "לזוג")
        type_word = "זוגי" if couple else "ליחיד"
        n = self.entries_total or 1
        head = "כרטיסיה" if self.is_pass else "שובר מתנה"
        if n == 1:
            return f"{head} לטיפול וואטסו {type_word}"
        return f"{head} ל-{n} טיפולי וואטסו {type_word}"

    @property
    def entries_badge(self) -> str:
        """Compact 'consumed/total' text, with '+held' when a hold exists."""
        text = f"{self.entries_consumed}/{self.entries_total or 0}"
        if self.entries_held:
            text += f" +{self.entries_held}"
        return text


class Entry(Base):
    """
    One treatment slot of a ticket. Rows are created lazily:
      - hold()            → status=held (a treatment was scheduled)
      - consume()         → held → consumed (the treatment took place)
      - cancel_hold()     → held → cancelled (row kept for audit, count released)
      - consume_direct()  → created directly as consumed (walk-in)
    """
    __tablename__ = "entries"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    voucher_id    = Column(Text, ForeignKey("vouchers.voucher_id"),
                           nullable=False, index=True)
    seq           = Column(Integer, nullable=False)      # 1..N within the ticket
    status        = Column(Text, nullable=False, default=ENTRY_HELD)
    scheduled_for = Column(DateTime, nullable=True)      # planned treatment time
    held_at       = Column(DateTime, nullable=True)
    consumed_at   = Column(DateTime, nullable=True)
    cancelled_at  = Column(DateTime, nullable=True)
    note          = Column(Text, nullable=True)
    performed_by  = Column(Text, nullable=True)          # username of the last action

    voucher       = relationship("Voucher", back_populates="entries")

    @property
    def status_display(self):
        return ENTRY_DISPLAY.get(self.status, self.status)

    def __repr__(self):
        return f"<Entry {self.id} ticket={self.voucher_id} seq={self.seq} {self.status}>"


class Sending(Base):
    """
    One row per send or resend event.
    Never updated — only inserted.

    kind values:
        TICKET        = the ticket itself (PDF / image) was sent
        PAYMENT_LINK  = a payment request (price + terms + link) was sent

    sent_via values:
        WA     = WhatsApp
        EMAIL  = Email
        PRINT  = Printed physically
    """
    __tablename__ = "sendings"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    voucher_id  = Column(Text, ForeignKey("vouchers.voucher_id"), nullable=False)
    sent_at     = Column(DateTime, default=datetime.utcnow, nullable=False)
    sent_via    = Column(Text, nullable=False)   # WA / EMAIL / PRINT
    kind        = Column(Text, nullable=False, default="TICKET")  # TICKET / PAYMENT_LINK
    note        = Column(Text, nullable=True)
    performed_by = Column(Text, nullable=True)   # Username who performed the action

    voucher     = relationship("Voucher", back_populates="sendings")

    # Human-readable display labels (used in templates)
    DISPLAY = {
        "WA":    "📱 וואטסאפ",
        "EMAIL": "📧 מייל",
        "PRINT": "🖨️ הדפסה",
    }
    KIND_DISPLAY = {
        "TICKET":       "כרטיס",
        "PAYMENT_LINK": "בקשת תשלום",
    }

    @property
    def sent_via_display(self):
        return self.DISPLAY.get(self.sent_via, self.sent_via)

    @property
    def kind_display(self):
        return self.KIND_DISPLAY.get(self.kind or "TICKET", self.kind)

    def __repr__(self):
        return f"<Sending {self.id} voucher={self.voucher_id} via={self.sent_via}>"
