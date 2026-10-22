"""
Vouchers router — /vouchers endpoints

POST   /vouchers                  → create new draft
GET    /vouchers                  → list all vouchers (filterable)
GET    /vouchers/{id}             → full voucher details
PUT    /vouchers/{id}             → update receipt number / date / notes
PUT    /vouchers/{id}/price       → change list price / discount / price (before payment)
PUT    /vouchers/{id}/request-payment → send payment request (draft → awaiting_payment)
PUT    /vouchers/{id}/mark-paid   → manual payment recorded (→ paid)
PUT    /vouchers/{id}/send        → send ticket (cement + QR + PDF + log → active)
PUT    /vouchers/{id}/resend      → resend (reuse QR + new PDF + log)
PUT    /vouchers/{id}/use         → consume one entry directly (legacy "mark used")
GET    /vouchers/{id}/entries     → entries (treatment slots) of the ticket
POST   /vouchers/{id}/entries/hold            → reserve an entry (שריון)
PUT    /vouchers/{id}/entries/{eid}/consume   → held → consumed
PUT    /vouchers/{id}/entries/{eid}/cancel    → held → cancelled
POST   /vouchers/{id}/entries/consume         → walk-in: consume without a hold
GET    /vouchers/{id}/pdf         → serve PDF file
GET    /vouchers/{id}/qr          → serve QR image
GET    /vouchers/{id}/sendings    → full sending history
"""

from pathlib import Path
from typing import Optional
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from app import auth as auth_module

from app.database import get_db
from app.models import Voucher, Sending
from app.schemas import (
    VoucherCreate, VoucherUpdate, VoucherOut,
    VoucherListItem, SendRequest, SendingOut,
    MarkPaidRequest, PriceUpdate, HoldRequest, EntryActionRequest, EntryOut,
)
from app import rules

router = APIRouter(prefix="/vouchers", tags=["vouchers"])


# ── Create ────────────────────────────────────────────────────────────────────

@router.post("", response_model=VoucherOut, status_code=status.HTTP_201_CREATED)
def create_voucher(body: VoucherCreate, db: Session = Depends(get_db)):
    """
    Create a new draft ticket (voucher or pass).
    The holder must already exist (use POST /holders first).
    """
    try:
        voucher = rules.create_voucher(
            db,
            mobile=body.mobile,
            voucher_type=body.voucher_type,
            valid_until=body.valid_until,
            receipt_number=body.receipt_number,
            receipt_date=body.receipt_date,
            notes=body.notes,
            display_name=body.display_name,
            greeting=body.greeting,
            location=body.location,
            kind=body.kind,
            entries_total=body.entries_total,
            list_price=body.list_price,
            discount=body.discount,
            price=body.price,
            terms=body.terms,
            language=body.language,
        )
    except rules.RulesError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail=str(e))

    return VoucherOut.model_validate(voucher)


# ── List (with filters) ───────────────────────────────────────────────────────

@router.get("", response_model=list[VoucherListItem])
def list_vouchers(
    status_filter: Optional[str]  = Query(None, alias="status"),
    mobile:        Optional[str]  = Query(None),
    voucher_type:  Optional[str]  = Query(None),
    kind:          Optional[str]  = Query(None),
    receipt_number:Optional[str]  = Query(None),
    date_from:     Optional[date] = Query(None),
    date_to:       Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    """
    List all tickets with optional filters.
    Results ordered by issued_at descending (newest first).
    """
    q = db.query(Voucher)

    if status_filter:
        q = q.filter(Voucher.status == status_filter)
    if mobile:
        q = q.filter(Voucher.mobile == mobile)
    if voucher_type:
        q = q.filter(Voucher.voucher_type == voucher_type)
    if kind:
        q = q.filter(Voucher.kind == kind.upper())
    if receipt_number:
        q = q.filter(Voucher.receipt_number.ilike(f"%{receipt_number}%"))
    if date_from:
        q = q.filter(Voucher.issued_at >= date_from)
    if date_to:
        q = q.filter(Voucher.issued_at <= date_to)

    vouchers = q.order_by(Voucher.issued_at.desc()).all()
    return [VoucherListItem.model_validate(v) for v in vouchers]


# ── Get single ────────────────────────────────────────────────────────────────

@router.get("/{voucher_id}", response_model=VoucherOut)
def get_voucher(voucher_id: str, db: Session = Depends(get_db)):
    """Return full voucher details including sending history."""
    voucher = db.get(Voucher, voucher_id)
    if not voucher:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"כרטיס לא נמצא: {voucher_id}")
    return VoucherOut.model_validate(voucher)


# ── Update receipt / notes ────────────────────────────────────────────────────

@router.put("/{voucher_id}", response_model=VoucherOut)
def update_voucher(voucher_id: str, body: VoucherUpdate,
                   db: Session = Depends(get_db)):
    """
    Update receipt number, receipt date, or notes.
    Blocked if voucher is used.
    """
    try:
        voucher = rules.update_voucher_fields(
            db, voucher_id,
            receipt_number=body.receipt_number,
            receipt_date=body.receipt_date,
            notes=body.notes,
            greeting=body.greeting,
            location=body.location,
            language=body.language,
        )
    except rules.RulesError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return VoucherOut.model_validate(voucher)


# ── Price ─────────────────────────────────────────────────────────────────────

@router.put("/{voucher_id}/price", response_model=VoucherOut)
def update_price(voucher_id: str, body: PriceUpdate,
                 db: Session = Depends(get_db)):
    """Change pricing. Allowed only before payment (draft / awaiting_payment)."""
    try:
        voucher = rules.set_price(db, voucher_id, body.list_price,
                                  body.discount, body.price)
    except rules.RulesError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return VoucherOut.model_validate(voucher)


# ── Payment request ───────────────────────────────────────────────────────────

@router.put("/{voucher_id}/request-payment", response_model=VoucherOut)
def request_payment(voucher_id: str, body: SendRequest,
                    request: Request, db: Session = Depends(get_db)):
    """
    Record that a payment request was sent (draft → awaiting_payment).
    Resending while awaiting payment is allowed (status unchanged).
    """
    username = auth_module.get_current_user(request)
    try:
        voucher = rules.request_payment(db, voucher_id, body.sent_via, body.note,
                                        performed_by=username, language=body.language)
    except rules.RulesError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return VoucherOut.model_validate(voucher)


@router.get("/{voucher_id}/payment-text")
def payment_text(voucher_id: str, lang: Optional[str] = Query(None),
                 db: Session = Depends(get_db)):
    """The plain-text payment request message (product, price, terms, link). ?lang=he|en"""
    voucher = db.get(Voucher, voucher_id)
    if not voucher:
        raise HTTPException(status_code=404, detail=f"כרטיס לא נמצא: {voucher_id}")
    try:
        return {"text": rules.payment_request_text(voucher, _lang(lang))}
    except rules.RulesError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e))


# ── Mark paid (manual) ────────────────────────────────────────────────────────

@router.put("/{voucher_id}/mark-paid", response_model=VoucherOut)
def mark_paid(voucher_id: str, body: MarkPaidRequest,
              request: Request, db: Session = Depends(get_db)):
    """Record a manual payment (cash / Bit / transfer / card) → status paid."""
    username = auth_module.get_current_user(request)
    try:
        voucher = rules.mark_paid(db, voucher_id, body.method,
                                  receipt_number=body.receipt_number,
                                  performed_by=username)
    except rules.RulesError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return VoucherOut.model_validate(voucher)


# ── Send ticket (first send) ──────────────────────────────────────────────────

@router.put("/{voucher_id}/send", response_model=VoucherOut)
def send_voucher(voucher_id: str, body: SendRequest,
                 request: Request, db: Session = Depends(get_db)):
    """
    Send the ticket: cement holder details, generate QR + PDF, log, status=active.
    Allowed on a paid ticket, or a free draft.
    """
    username = auth_module.get_current_user(request)
    try:
        voucher = rules.first_send(db, voucher_id, body.sent_via, body.note,
                                   performed_by=username)
    except rules.RulesError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return VoucherOut.model_validate(voucher)


# ── Resend ────────────────────────────────────────────────────────────────────

@router.put("/{voucher_id}/resend", response_model=VoucherOut)
def resend_voucher(voucher_id: str, body: SendRequest,
                   request: Request, db: Session = Depends(get_db)):
    """
    Resend: reuse original QR, regenerate PDF, log new send event.
    Can only be called on a sent voucher.
    """
    username = auth_module.get_current_user(request)
    try:
        voucher = rules.resend(db, voucher_id, body.sent_via, body.note,
                               performed_by=username, language=body.language)
    except rules.RulesError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return VoucherOut.model_validate(voucher)


# ── Mark used ─────────────────────────────────────────────────────────────────

@router.put("/{voucher_id}/use", response_model=VoucherOut)
def use_voucher(voucher_id: str, request: Request, db: Session = Depends(get_db)):
    """
    Consume one entry directly (legacy "mark used").
    A single-entry ticket becomes used (fully frozen).
    """
    username = auth_module.get_current_user(request)
    try:
        voucher = rules.mark_used(db, voucher_id, performed_by=username)
    except rules.RulesError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return VoucherOut.model_validate(voucher)


# ── Entries (treatment slots) ─────────────────────────────────────────────────

@router.get("/{voucher_id}/entries", response_model=list[EntryOut])
def list_entries(voucher_id: str, db: Session = Depends(get_db)):
    """All entries of a ticket, oldest first (cancelled rows included)."""
    voucher = db.get(Voucher, voucher_id)
    if not voucher:
        raise HTTPException(status_code=404, detail=f"כרטיס לא נמצא: {voucher_id}")
    return [EntryOut.model_validate(e) for e in voucher.entries]


@router.post("/{voucher_id}/entries/hold", response_model=EntryOut,
             status_code=status.HTTP_201_CREATED)
def hold_entry(voucher_id: str, body: HoldRequest,
               request: Request, db: Session = Depends(get_db)):
    """Reserve an entry for a scheduled treatment (שריון)."""
    username = auth_module.get_current_user(request)
    try:
        entry = rules.hold_entry(db, voucher_id, body.scheduled_for, body.note,
                                 performed_by=username)
    except rules.RulesError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return EntryOut.model_validate(entry)


@router.put("/{voucher_id}/entries/{entry_id}/consume", response_model=EntryOut)
def consume_entry(voucher_id: str, entry_id: int, body: EntryActionRequest,
                  request: Request, db: Session = Depends(get_db)):
    """The scheduled treatment took place: held → consumed."""
    username = auth_module.get_current_user(request)
    try:
        entry = rules.consume_entry(db, voucher_id, entry_id, body.note,
                                    performed_by=username)
    except rules.RulesError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return EntryOut.model_validate(entry)


@router.put("/{voucher_id}/entries/{entry_id}/cancel", response_model=EntryOut)
def cancel_entry(voucher_id: str, entry_id: int, body: EntryActionRequest,
                 request: Request, db: Session = Depends(get_db)):
    """The scheduled treatment was cancelled: held → cancelled."""
    username = auth_module.get_current_user(request)
    try:
        entry = rules.cancel_hold(db, voucher_id, entry_id, body.note,
                                  performed_by=username)
    except rules.RulesError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return EntryOut.model_validate(entry)


@router.post("/{voucher_id}/entries/consume", response_model=VoucherOut)
def consume_direct(voucher_id: str, body: EntryActionRequest,
                   request: Request, db: Session = Depends(get_db)):
    """Walk-in: consume one entry without a prior hold."""
    username = auth_module.get_current_user(request)
    try:
        voucher = rules.consume_direct(db, voucher_id, body.note,
                                       performed_by=username)
    except rules.RulesError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return VoucherOut.model_validate(voucher)


# ── Serve PDF ─────────────────────────────────────────────────────────────────

def _lang(lang: Optional[str]) -> Optional[str]:
    """Validate an optional ?lang= query value (he / en); None = ticket default."""
    if not lang:
        return None
    lang = lang.lower()
    if lang not in ("he", "en"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail="lang חייב להיות he או en")
    return lang


def _needs_preview(voucher: Voucher) -> bool:
    """
    True when the voucher has no rendered files to serve: it is still a
    draft (never sent), or its PDF is missing on disk. In both cases the
    voucher is rendered on the fly instead (no state change, nothing saved).
    """
    return not voucher.pdf_path or not Path(voucher.pdf_path).exists()


@router.get("/{voucher_id}/pdf")
def get_pdf(voucher_id: str, lang: Optional[str] = Query(None),
            db: Session = Depends(get_db)):
    """Serve the voucher PDF (rendered on the fly for drafts). ?lang=he|en picks the language."""
    voucher = db.get(Voucher, voucher_id)
    if not voucher:
        raise HTTPException(status_code=404, detail=f"כרטיס לא נמצא: {voucher_id}")
    lang = _lang(lang)

    if _needs_preview(voucher):
        from app import pdf_module
        pdf_bytes, _ = pdf_module.render_preview(voucher, lang)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'inline; filename="{voucher_id}.pdf"',
                "Cache-Control": "no-store",   # draft content changes as fields are edited
            },
        )

    # Sent ticket: the stored document in the requested language (rendered
    # on first request for the non-default language).
    pdf_path, _ = rules.ensure_document(voucher, lang)
    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=f"{voucher_id}.pdf",
        # The PDF is regenerated in place when the image/greeting/location
        # changes (same URL), so disable caching to avoid serving a stale copy.
        headers={"Cache-Control": "no-store"},
    )


# ── Serve voucher image (PNG) ─────────────────────────────────────────────────

@router.get("/{voucher_id}/image")
def get_image(voucher_id: str, lang: Optional[str] = Query(None),
              db: Session = Depends(get_db)):
    """Serve the voucher JPEG (the default send format; on the fly for drafts). ?lang=he|en"""
    voucher = db.get(Voucher, voucher_id)
    if not voucher:
        raise HTTPException(status_code=404, detail=f"כרטיס לא נמצא: {voucher_id}")
    lang = _lang(lang)

    from app import pdf_module

    if _needs_preview(voucher):
        _, jpg_bytes = pdf_module.render_preview(voucher, lang)
        return Response(
            content=jpg_bytes,
            media_type="image/jpeg",
            headers={
                "Content-Disposition": f'inline; filename="{voucher_id}.jpg"',
                "Cache-Control": "no-store",   # draft content changes as fields are edited
            },
        )

    # The image lives next to the PDF in the same voucher folder; rendered
    # now when missing (older voucher, or first request of the other language).
    _, img_path = rules.ensure_document(voucher, lang)

    return FileResponse(
        path=str(img_path),
        media_type="image/jpeg",
        filename=f"{voucher_id}.jpg",
        # The image is regenerated in place when the photo/greeting/location
        # changes (same URL), so disable caching to avoid serving a stale copy.
        headers={"Cache-Control": "no-store"},
    )


# ── Serve QR image ────────────────────────────────────────────────────────────

@router.get("/{voucher_id}/qr")
def get_qr(voucher_id: str, db: Session = Depends(get_db)):
    """Serve the voucher QR code image."""
    voucher = db.get(Voucher, voucher_id)
    if not voucher:
        raise HTTPException(status_code=404, detail=f"כרטיס לא נמצא: {voucher_id}")
    if not voucher.qr_path or not Path(voucher.qr_path).exists():
        raise HTTPException(status_code=404, detail="QR לא נמצא — יש לשלוח תחילה")
    return FileResponse(
        path=voucher.qr_path,
        media_type="image/png",
        filename=f"{voucher_id}_qr.png",
    )


# ── Sending history ───────────────────────────────────────────────────────────

@router.get("/{voucher_id}/sendings", response_model=list[SendingOut])
def get_sendings(voucher_id: str, db: Session = Depends(get_db)):
    """Return the full sending history for a voucher (newest first)."""
    voucher = db.get(Voucher, voucher_id)
    if not voucher:
        raise HTTPException(status_code=404, detail=f"כרטיס לא נמצא: {voucher_id}")
    return [SendingOut.model_validate(s) for s in voucher.sendings]
