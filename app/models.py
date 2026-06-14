"""
ORM Models — SQLAlchemy
Tables: holders, vouchers, sendings

Key design decisions:
- holders.mobile is the primary key (Israeli format 05X-XXXXXXX)
- vouchers.mobile is a plain text reference, NOT a live FK
  (so holder deletion — if ever added — doesn't break voucher history)
- cemented_* fields on vouchers are the frozen snapshot of holder data
  copied on first send and never changed again
- sendings records every send/resend action with sent_via and timestamp
"""

from datetime import datetime, date
from app.utils import utcnow
from sqlalchemy import (
    Column, Text, Integer, Date, DateTime, ForeignKey, String
)
from sqlalchemy.orm import relationship
from app.database import Base


class Holder(Base):
    """
    A person who receives vouchers, identified by mobile number.
    Editable freely while all their vouchers are draft/sent.
    Locked (no edits) if any voucher is marked used.
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
    A gift voucher document.

    Status lifecycle:
        draft → sent (first send: cement + QR + PDF generated)
              → used  (mark used: fully frozen)

    Once sent:
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

    # Voucher content
    voucher_type    = Column(Text, nullable=False)   # יחיד / זוגי
    valid_until     = Column(Date, nullable=False)

    # Timestamps
    issued_at       = Column(DateTime, default=datetime.utcnow, nullable=False)
    first_sent_at   = Column(DateTime, nullable=True)   # set once on first send

    # Status: draft / sent / used
    status          = Column(Text, nullable=False, default="draft")

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

    def __repr__(self):
        return f"<Voucher {self.voucher_id} status={self.status}>"

    @property
    def is_frozen(self):
        """Used vouchers are completely frozen — no changes allowed."""
        return self.status == "used"

    @property
    def is_cemented(self):
        """True once first send has happened (holder snapshot is frozen)."""
        return self.first_sent_at is not None


class Sending(Base):
    """
    One row per send or resend event.
    Never updated — only inserted.

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
    note        = Column(Text, nullable=True)
    performed_by = Column(Text, nullable=True)   # Username who performed the action

    voucher     = relationship("Voucher", back_populates="sendings")

    # Human-readable display labels (used in templates)
    DISPLAY = {
        "WA":    "📱 וואטסאפ",
        "EMAIL": "📧 מייל",
        "PRINT": "🖨️ הדפסה",
    }

    @property
    def sent_via_display(self):
        return self.DISPLAY.get(self.sent_via, self.sent_via)

    def __repr__(self):
        return f"<Sending {self.id} voucher={self.voucher_id} via={self.sent_via}>"
