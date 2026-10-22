"""
Pydantic schemas — request validation and response serialisation.

Naming convention:
  *Create  = body of a POST request (creating a new resource)
  *Update  = body of a PUT request (partial update)
  *Out     = response shape returned to the caller
"""

from datetime import datetime, date
from typing import Optional, List
from pydantic import BaseModel, field_validator
import re


# ── Validators ────────────────────────────────────────────────────────────────

def validate_mobile(v: str) -> str:
    """Israeli mobile: 10 digits starting with 05, no separators stored."""
    # Strip common separators so caller can pass 054-123-4567 or 0541234567
    digits = re.sub(r"[\s\-]", "", v)
    if not re.fullmatch(r"05\d{8}", digits):
        raise ValueError("מספר טלפון לא תקין — נדרש פורמט 05X-XXXXXXX")
    return digits


# ── Holder schemas ────────────────────────────────────────────────────────────

class HolderCreate(BaseModel):
    """Create or retrieve a holder by mobile."""
    mobile: str
    name: str
    email: Optional[str] = None

    @field_validator("mobile")
    @classmethod
    def mobile_format(cls, v):
        return validate_mobile(v)


class HolderUpdate(BaseModel):
    """Update holder details (blocked if holder has a used voucher)."""
    name: Optional[str] = None
    email: Optional[str] = None


class HolderOut(BaseModel):
    """Holder details returned in API responses."""
    mobile: str
    name: str
    email: Optional[str]
    created_at: datetime
    updated_at: datetime
    can_edit: bool = True   # False when any voucher is used

    model_config = {"from_attributes": True}


# ── Voucher schemas ───────────────────────────────────────────────────────────

VALID_TYPES = {"יחיד", "זוגי"}


VALID_KINDS = {"VOUCHER", "PASS"}

VALID_LANGUAGES = {"he", "en"}


class VoucherCreate(BaseModel):
    """Create a new draft ticket (gift voucher or pass)."""
    mobile: str
    voucher_type: str
    valid_until: date
    kind: str = "VOUCHER"            # VOUCHER (gift) / PASS (self use)
    entries_total: int = 1           # treatments included
    language: Optional[str] = None   # he / en; None = the system default (settings)
    list_price: Optional[float] = None
    discount:   Optional[float] = None
    price:      Optional[float] = None   # None + list_price → computed
    terms:      Optional[str] = None     # None → settings default
    display_name: Optional[str] = None
    greeting:     Optional[str] = None
    location:     Optional[str] = None
    receipt_number: Optional[str] = None
    receipt_date: Optional[date] = None
    notes: Optional[str] = None

    @field_validator("kind")
    @classmethod
    def kind_valid(cls, v):
        v = (v or "VOUCHER").upper()
        if v not in VALID_KINDS:
            raise ValueError("סוג כרטיס לא תקין — VOUCHER או PASS")
        return v

    @field_validator("language")
    @classmethod
    def language_valid(cls, v):
        if v is None or v == "":
            return None                      # rules fill in the system default
        v = v.lower()
        if v not in VALID_LANGUAGES:
            raise ValueError("שפת כרטיס לא תקינה — he או en")
        return v

    @field_validator("entries_total")
    @classmethod
    def entries_valid(cls, v):
        if v < 1 or v > 100:
            raise ValueError("כמות טיפולים חייבת להיות בין 1 ל-100")
        return v

    @field_validator("mobile")
    @classmethod
    def mobile_format(cls, v):
        return validate_mobile(v)

    @field_validator("voucher_type")
    @classmethod
    def type_valid(cls, v):
        if v not in VALID_TYPES:
            raise ValueError(f"סוג שובר לא תקין — חייב להיות: {', '.join(VALID_TYPES)}")
        return v

    @field_validator("valid_until")
    @classmethod
    def not_in_past(cls, v):
        if v < date.today():
            raise ValueError("תאריך תוקף לא יכול להיות בעבר")
        return v


class VoucherUpdate(BaseModel):
    """
    Update editable fields on a voucher.
    receipt_number and receipt_date are editable until status=used.
    notes is editable until status=used.
    """
    receipt_number: Optional[str] = None
    receipt_date:   Optional[date] = None
    notes:          Optional[str] = None
    greeting:       Optional[str] = None
    location:       Optional[str] = None
    language:       Optional[str] = None   # he / en — default document language (until used)


class SendingOut(BaseModel):
    """One row from the sendings table."""
    id: int
    voucher_id: str
    sent_at: datetime
    sent_via: str
    sent_via_display: str   # computed property from model
    kind: str = "TICKET"    # TICKET / PAYMENT_LINK
    kind_display: str = ""
    language: Optional[str] = None     # he / en — document language sent
    language_display: str = ""
    note: Optional[str]
    performed_by: Optional[str] = None  # Username who performed the action

    model_config = {"from_attributes": True}


class EntryOut(BaseModel):
    """One treatment slot of a ticket."""
    id: int
    voucher_id: str
    seq: int
    status: str            # held / consumed / cancelled
    status_display: str
    scheduled_for: Optional[datetime] = None
    held_at: Optional[datetime] = None
    consumed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    note: Optional[str] = None
    performed_by: Optional[str] = None

    model_config = {"from_attributes": True}


class VoucherOut(BaseModel):
    """Full voucher detail — returned by GET /vouchers/{id}."""
    voucher_id: str
    mobile: str
    sequence: int
    kind: str = "VOUCHER"
    kind_display: str = ""
    entries_total: int = 1
    language: str = "he"
    language_display: str = ""
    voucher_type: str
    product_title: str = ""
    valid_until: date
    issued_at: datetime
    first_sent_at: Optional[datetime]
    status: str
    status_display: str = ""
    receipt_number: Optional[str]
    receipt_date: Optional[date]
    notes: Optional[str]
    greeting: Optional[str] = None
    location: Optional[str] = None
    image_file: Optional[str] = None
    qr_path: Optional[str]
    pdf_path: Optional[str]

    # Pricing + payment
    list_price: Optional[float] = None
    discount:   Optional[float] = None
    price:      Optional[float] = None
    terms:      Optional[str] = None
    payment_method: Optional[str] = None
    payment_url:    Optional[str] = None
    gi_document_id: Optional[str] = None
    paid_at:        Optional[datetime] = None

    # Entry counters (derived)
    entries_consumed:  int = 0
    entries_held:      int = 0
    entries_available: int = 0
    entries: List[EntryOut] = []

    # Cemented holder snapshot
    holder_name:   Optional[str]
    holder_mobile: Optional[str]
    holder_email:  Optional[str]

    # Computed flags
    is_frozen:   bool
    is_cemented: bool

    # Sending history
    sendings: List[SendingOut] = []

    model_config = {"from_attributes": True}


class VoucherListItem(BaseModel):
    """Compact voucher row for list/table views."""
    voucher_id: str
    mobile: str
    holder_name: Optional[str]
    kind: str = "VOUCHER"
    entries_total: int = 1
    entries_consumed: int = 0
    entries_held: int = 0
    price: Optional[float] = None
    voucher_type: str
    valid_until: date
    issued_at: datetime
    first_sent_at: Optional[datetime]
    status: str
    receipt_number: Optional[str]

    model_config = {"from_attributes": True}


# ── Send / Resend / Use schemas ───────────────────────────────────────────────

class SendRequest(BaseModel):
    """Body for PUT /vouchers/{id}/send, /resend and /request-payment."""
    sent_via: str   # WA / EMAIL / PRINT
    note: Optional[str] = None
    language: Optional[str] = None   # he / en — document language; None = the ticket's default

    @field_validator("language")
    @classmethod
    def language_valid(cls, v):
        if v is None or v == "":
            return None
        v = v.lower()
        if v not in VALID_LANGUAGES:
            raise ValueError("שפת מסמך לא תקינה — he או en")
        return v

    @field_validator("sent_via")
    @classmethod
    def via_valid(cls, v):
        allowed = {"WA", "EMAIL", "PRINT"}
        if v not in allowed:
            raise ValueError(f"sent_via חייב להיות אחד מ: {', '.join(allowed)}")
        return v


class MarkPaidRequest(BaseModel):
    """Body for PUT /vouchers/{id}/mark-paid (manual payment)."""
    method: str                       # CASH / BIT / TRANSFER / CARD
    receipt_number: Optional[str] = None

    @field_validator("method")
    @classmethod
    def method_valid(cls, v):
        allowed = {"CASH", "BIT", "TRANSFER", "CARD"}
        v = (v or "").upper()
        if v not in allowed:
            raise ValueError(f"אמצעי תשלום חייב להיות אחד מ: {', '.join(sorted(allowed))}")
        return v


class PriceUpdate(BaseModel):
    """Body for PUT /vouchers/{id}/price (before payment only)."""
    list_price: Optional[float] = None
    discount:   Optional[float] = None
    price:      Optional[float] = None


class HoldRequest(BaseModel):
    """Body for POST /vouchers/{id}/entries/hold."""
    scheduled_for: Optional[datetime] = None
    note: Optional[str] = None


class EntryActionRequest(BaseModel):
    """Body for consume / cancel / direct-consume actions."""
    note: Optional[str] = None


# ── Search / Report schemas ───────────────────────────────────────────────────

class SearchResult(BaseModel):
    """Flat result row for search and report."""
    voucher_id: str
    holder_name: Optional[str]
    holder_mobile: Optional[str]
    holder_email: Optional[str]
    kind: str = "VOUCHER"
    entries_total: int = 1
    voucher_type: str
    valid_until: date
    status: str
    receipt_number: Optional[str]
    issued_at: datetime
    first_sent_at: Optional[datetime]

    model_config = {"from_attributes": True}
