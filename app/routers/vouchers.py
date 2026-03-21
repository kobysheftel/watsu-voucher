"""
Vouchers router — /vouchers endpoints

POST   /vouchers                  → create new draft
GET    /vouchers                  → list all vouchers (filterable)
GET    /vouchers/{id}             → full voucher details
PUT    /vouchers/{id}             → update receipt number / date / notes
PUT    /vouchers/{id}/send        → first send (cement + QR + PDF + log)
PUT    /vouchers/{id}/resend      → resend (reuse QR + new PDF + log)
PUT    /vouchers/{id}/use         → mark used (freeze)
GET    /vouchers/{id}/pdf         → serve PDF file
GET    /vouchers/{id}/qr          → serve QR image
GET    /vouchers/{id}/sendings    → full sending history
"""

from pathlib import Path
from typing import Optional
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from app import auth as auth_module

from app.database import get_db
from app.models import Voucher, Sending
from app.schemas import (
    VoucherCreate, VoucherUpdate, VoucherOut,
    VoucherListItem, SendRequest, SendingOut,
)
from app import rules

router = APIRouter(prefix="/vouchers", tags=["vouchers"])


# ── Create ────────────────────────────────────────────────────────────────────

@router.post("", response_model=VoucherOut, status_code=status.HTTP_201_CREATED)
def create_voucher(body: VoucherCreate, db: Session = Depends(get_db)):
    """
    Create a new draft voucher.
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
    receipt_number:Optional[str]  = Query(None),
    date_from:     Optional[date] = Query(None),
    date_to:       Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    """
    List all vouchers with optional filters.
    Results ordered by issued_at descending (newest first).
    """
    q = db.query(Voucher)

    if status_filter:
        q = q.filter(Voucher.status == status_filter)
    if mobile:
        q = q.filter(Voucher.mobile == mobile)
    if voucher_type:
        q = q.filter(Voucher.voucher_type == voucher_type)
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
                            detail=f"שובר לא נמצא: {voucher_id}")
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
        )
    except rules.RulesError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return VoucherOut.model_validate(voucher)


# ── First send ────────────────────────────────────────────────────────────────

@router.put("/{voucher_id}/send", response_model=VoucherOut)
def send_voucher(voucher_id: str, body: SendRequest,
                 request: Request, db: Session = Depends(get_db)):
    """
    First send: cement holder details, generate QR + PDF, log, set status=sent.
    Can only be called on a draft voucher.
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
                               performed_by=username)
    except rules.RulesError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return VoucherOut.model_validate(voucher)


# ── Mark used ─────────────────────────────────────────────────────────────────

@router.put("/{voucher_id}/use", response_model=VoucherOut)
def use_voucher(voucher_id: str, db: Session = Depends(get_db)):
    """
    Mark voucher as used (fully frozen).
    Can only be called on a sent voucher.
    """
    try:
        voucher = rules.mark_used(db, voucher_id)
    except rules.RulesError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return VoucherOut.model_validate(voucher)


# ── Serve PDF ─────────────────────────────────────────────────────────────────

@router.get("/{voucher_id}/pdf")
def get_pdf(voucher_id: str, db: Session = Depends(get_db)):
    """Serve the voucher PDF file."""
    voucher = db.get(Voucher, voucher_id)
    if not voucher:
        raise HTTPException(status_code=404, detail=f"שובר לא נמצא: {voucher_id}")
    if not voucher.pdf_path or not Path(voucher.pdf_path).exists():
        raise HTTPException(status_code=404, detail="קובץ PDF לא נמצא — יש לשלוח תחילה")
    return FileResponse(
        path=voucher.pdf_path,
        media_type="application/pdf",
        filename=f"{voucher_id}.pdf",
    )


# ── Serve QR image ────────────────────────────────────────────────────────────

@router.get("/{voucher_id}/qr")
def get_qr(voucher_id: str, db: Session = Depends(get_db)):
    """Serve the voucher QR code image."""
    voucher = db.get(Voucher, voucher_id)
    if not voucher:
        raise HTTPException(status_code=404, detail=f"שובר לא נמצא: {voucher_id}")
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
        raise HTTPException(status_code=404, detail=f"שובר לא נמצא: {voucher_id}")
    return [SendingOut.model_validate(s) for s in voucher.sendings]
