"""
Reports router — search and reporting endpoints

GET /search?q=        → search by name / mobile / email / voucher_id
GET /report           → full filterable report, optional CSV export
GET /home             → home page data (recent activity + stats)
"""

import csv
import io
from typing import Optional
from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.database import get_db
from app.models import Voucher, Holder
from app.schemas import SearchResult, VoucherListItem

router = APIRouter(tags=["reports"])


# ── Search ────────────────────────────────────────────────────────────────────

@router.get("/search", response_model=list[SearchResult])
def search(
    q: str = Query(..., min_length=1, description="חיפוש חופשי"),
    db: Session = Depends(get_db),
):
    """
    Full-text search across: holder name, mobile, email, voucher_id.
    Returns matching vouchers with their cemented holder snapshot.
    Drafts are included (they show holder live data, cemented fields are null).
    """
    term = f"%{q}%"

    # Search both cemented fields (sent/used vouchers) and live holder data (drafts)
    results = (
        db.query(Voucher)
        .outerjoin(Holder, Holder.mobile == Voucher.mobile)
        .filter(
            or_(
                Voucher.voucher_id.ilike(term),
                Voucher.holder_name.ilike(term),       # cemented
                Voucher.holder_mobile.ilike(term),     # cemented
                Voucher.holder_email.ilike(term),      # cemented
                Holder.name.ilike(term),               # live (covers drafts)
                Holder.mobile.ilike(term),
                Holder.email.ilike(term),
            )
        )
        .order_by(Voucher.issued_at.desc())
        .all()
    )

    # For drafts without cemented data, fill from live holder
    output = []
    for v in results:
        item = SearchResult(
            voucher_id     = v.voucher_id,
            holder_name    = v.holder_name  or (v.holder_ref.name   if v.holder_ref else None),
            holder_mobile  = v.holder_mobile or (v.holder_ref.mobile if v.holder_ref else None),
            holder_email   = v.holder_email  or (v.holder_ref.email  if v.holder_ref else None),
            voucher_type   = v.voucher_type,
            valid_until    = v.valid_until,
            status         = v.status,
            receipt_number = v.receipt_number,
            issued_at      = v.issued_at,
            first_sent_at  = v.first_sent_at,
        )
        output.append(item)

    return output


# ── Report ────────────────────────────────────────────────────────────────────

@router.get("/report")
def report(
    status_filter:  Optional[str]  = Query(None, alias="status"),
    voucher_type:   Optional[str]  = Query(None),
    mobile:         Optional[str]  = Query(None),
    date_from:      Optional[date] = Query(None),
    date_to:        Optional[date] = Query(None),
    receipt_number: Optional[str]  = Query(None),
    fmt:            Optional[str]  = Query(None, description="csv — להורדה כ-CSV"),
    db: Session = Depends(get_db),
):
    """
    Full report with filters. Pass fmt=csv to download as CSV file.
    """
    q = db.query(Voucher).outerjoin(Holder, Holder.mobile == Voucher.mobile)

    if status_filter:
        q = q.filter(Voucher.status == status_filter)
    if voucher_type:
        q = q.filter(Voucher.voucher_type == voucher_type)
    if mobile:
        q = q.filter(Voucher.mobile == mobile)
    if receipt_number:
        q = q.filter(Voucher.receipt_number.ilike(f"%{receipt_number}%"))
    if date_from:
        q = q.filter(Voucher.issued_at >= date_from)
    if date_to:
        q = q.filter(Voucher.issued_at <= date_to)

    vouchers = q.order_by(Voucher.issued_at.desc()).all()

    # Build rows (merge cemented + live holder data for display)
    rows = []
    for v in vouchers:
        rows.append({
            "voucher_id":     v.voucher_id,
            "status":         v.status,
            "voucher_type":   v.voucher_type,
            "holder_name":    v.holder_name  or (v.holder_ref.name   if v.holder_ref else ""),
            "holder_mobile":  v.holder_mobile or (v.holder_ref.mobile if v.holder_ref else ""),
            "holder_email":   v.holder_email  or (v.holder_ref.email  if v.holder_ref else ""),
            "valid_until":    str(v.valid_until),
            "issued_at":      str(v.issued_at)[:16],
            "first_sent_at":  str(v.first_sent_at)[:16] if v.first_sent_at else "",
            "receipt_number": v.receipt_number or "",
            "receipt_date":   str(v.receipt_date) if v.receipt_date else "",
            "notes":          v.notes or "",
        })

    # ── CSV export ────────────────────────────────────────────────────────────
    if fmt == "csv":
        output = io.StringIO()
        # UTF-8 BOM so Excel opens Hebrew correctly
        output.write("\ufeff")

        headers = [
            "מספר שובר", "סטטוס", "סוג", "שם מקבל", "טלפון", "אימייל",
            "תוקף עד", "הונפק", "נשלח ראשון", "מספר קבלה", "תאריך קבלה", "הערות"
        ]
        writer = csv.DictWriter(
            output,
            fieldnames=list(rows[0].keys()) if rows else [],
            extrasaction="ignore",
        )

        # Write Hebrew header row manually
        output.write(",".join(headers) + "\n")
        for row in rows:
            writer.writerow(row)

        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=vouchers_report.csv"},
        )

    # ── JSON response ─────────────────────────────────────────────────────────
    return {
        "count": len(rows),
        "rows":  rows,
    }


# ── Home page stats ───────────────────────────────────────────────────────────

@router.get("/home/data")
def home_data(db: Session = Depends(get_db)):
    """
    Summary stats + recent activity for the home page.
    """
    total     = db.query(Voucher).count()
    drafts    = db.query(Voucher).filter_by(status="draft").count()
    sent      = db.query(Voucher).filter_by(status="sent").count()
    used      = db.query(Voucher).filter_by(status="used").count()
    holders   = db.query(Holder).count()

    # 10 most recently issued vouchers
    recent = (
        db.query(Voucher)
        .order_by(Voucher.issued_at.desc())
        .limit(10)
        .all()
    )

    return {
        "stats": {
            "total":   total,
            "draft":   drafts,
            "sent":    sent,
            "used":    used,
            "holders": holders,
        },
        "recent": [VoucherListItem.model_validate(v) for v in recent],
    }
