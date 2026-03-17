"""
Pages router — HTML UI routes (server-side rendered with Jinja2).

GET /home                    → dashboard (stats + recent vouchers + search)
GET /holders/{mobile}/view   → holder detail page
GET /vouchers/{id}/view      → voucher detail page
GET /report/view             → filterable report page
"""

from datetime import date
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Holder, Voucher
from app import rules

router    = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="templates")


# ── Home / dashboard ──────────────────────────────────────────────────────────

@router.get("/home", response_class=HTMLResponse)
def home_page(request: Request, db: Session = Depends(get_db)):
    """Dashboard: stats, search box, and 10 most recent vouchers."""
    total   = db.query(Voucher).count()
    drafts  = db.query(Voucher).filter_by(status="draft").count()
    sent    = db.query(Voucher).filter_by(status="sent").count()
    used    = db.query(Voucher).filter_by(status="used").count()
    holders = db.query(Holder).count()

    recent = (
        db.query(Voucher)
        .order_by(Voucher.issued_at.desc())
        .limit(10)
        .all()
    )

    return templates.TemplateResponse("home.html", {
        "request": request,
        "stats": {
            "total":   total,
            "draft":   drafts,
            "sent":    sent,
            "used":    used,
            "holders": holders,
        },
        "recent": recent,
    })


# ── Holder detail page ────────────────────────────────────────────────────────

@router.get("/holders/{mobile}/view", response_class=HTMLResponse)
def holder_page(mobile: str, request: Request, db: Session = Depends(get_db)):
    """Holder detail: info card + vouchers table + create/edit modals."""
    holder = db.get(Holder, mobile)
    if not holder:
        raise HTTPException(status_code=404, detail=f"מחזיק לא נמצא: {mobile}")

    can_edit = rules.can_edit_holder(db, mobile)

    return templates.TemplateResponse("holder.html", {
        "request":  request,
        "holder":   holder,
        "can_edit": can_edit,
        "vouchers": holder.vouchers,   # relationship ordered by issued_at desc
    })


# ── Voucher detail page ───────────────────────────────────────────────────────

@router.get("/vouchers/{voucher_id}/view", response_class=HTMLResponse)
def voucher_page(
    voucher_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Voucher detail: info, holder snapshot, receipt fields, actions, QR, history."""
    voucher = db.get(Voucher, voucher_id)
    if not voucher:
        raise HTTPException(status_code=404, detail=f"שובר לא נמצא: {voucher_id}")

    # Load live holder record for navigation link (may be None if deleted)
    holder = db.get(Holder, voucher.mobile) if voucher.mobile else None

    return templates.TemplateResponse("voucher_view.html", {
        "request": request,
        "voucher": voucher,
        "holder":  holder,
    })


# ── Report page ───────────────────────────────────────────────────────────────

@router.get("/report/view", response_class=HTMLResponse)
def report_page(
    request: Request,
    db: Session = Depends(get_db),
    status:         Optional[str]  = Query(None),
    voucher_type:   Optional[str]  = Query(None),
    date_from:      Optional[date] = Query(None),
    date_to:        Optional[date] = Query(None),
    receipt_number: Optional[str]  = Query(None),
):
    """Full report with filters and CSV-export link."""
    filters = {
        "status":         status,
        "voucher_type":   voucher_type,
        "date_from":      str(date_from) if date_from else None,
        "date_to":        str(date_to)   if date_to   else None,
        "receipt_number": receipt_number,
        "has_any":        any([status, voucher_type, date_from, date_to, receipt_number]),
    }

    q = db.query(Voucher)
    if status:
        q = q.filter(Voucher.status == status)
    if voucher_type:
        q = q.filter(Voucher.voucher_type == voucher_type)
    if receipt_number:
        q = q.filter(Voucher.receipt_number.ilike(f"%{receipt_number}%"))
    if date_from:
        q = q.filter(Voucher.issued_at >= date_from)
    if date_to:
        q = q.filter(Voucher.issued_at <= date_to)

    vouchers = q.order_by(Voucher.issued_at.desc()).all()

    # Build query string for the CSV export link (passes same filters to /report?fmt=csv)
    csv_params = {k: v for k, v in {
        "status":         status,
        "voucher_type":   voucher_type,
        "date_from":      str(date_from) if date_from else None,
        "date_to":        str(date_to)   if date_to   else None,
        "receipt_number": receipt_number,
        "fmt":            "csv",
    }.items() if v}
    filter_qs = urlencode(csv_params)

    return templates.TemplateResponse("report.html", {
        "request":   request,
        "vouchers":  vouchers,
        "filters":   filters,
        "filter_qs": filter_qs,
    })
