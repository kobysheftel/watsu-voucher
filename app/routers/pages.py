"""
Pages router — HTML UI routes (server-side rendered with Jinja2).

GET  /home                       → dashboard (stats + search + recent)
GET  /holders/{mobile}/view      → holder detail page
GET  /vouchers/{id}/view         → voucher detail page
GET  /report/view                → filterable report page

POST /form/holders/new           → create holder, redirect to holder page
POST /form/holders/{mobile}/edit → update holder name/email, redirect back
POST /form/vouchers/new          → create voucher draft, redirect to voucher page
POST /form/vouchers/{id}/send    → send ticket OR resend (checks status), redirect back
POST /form/vouchers/{id}/request-payment → payment request sent (draft → awaiting_payment)
POST /form/vouchers/{id}/mark-paid       → manual payment (→ paid)
POST /form/vouchers/{id}/price           → change price / discount (before payment)
POST /form/vouchers/{id}/use     → consume one entry directly (legacy mark used)
POST /form/vouchers/{id}/entries/hold            → reserve an entry
POST /form/vouchers/{id}/entries/{eid}/consume   → held → consumed
POST /form/vouchers/{id}/entries/{eid}/cancel    → held → cancelled
POST /form/vouchers/{id}/notes   → update receipt/notes, redirect back
GET  /settings/view              → price list + terms + defaults
POST /form/settings              → save settings

All POST handlers use HTML form data (not JSON) and follow POST-Redirect-GET.
Flash messages are passed as ?flash=...&flash_type=success/danger/warning in the URL.
"""

from datetime import date, datetime, timedelta
from typing import Optional, List
import json
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (Holder, Voucher, KIND_VOUCHER, KIND_PASS,
                        STATUS_DRAFT, STATUS_AWAITING, STATUS_PAID,
                        STATUS_ACTIVE, STATUS_USED, PAYMENT_METHODS)
from app import rules
from app import images
from app import settings
from app import auth as auth_module

router    = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="templates")


# ── Helper ────────────────────────────────────────────────────────────────────

def _flash(url: str, msg: str, t: str = "success") -> RedirectResponse:
    """Build a POST-Redirect-GET response with a flash message in the URL."""
    sep = "&" if "?" in url else "?"
    redirect_url = f"{url}{sep}flash={quote(msg)}&flash_type={t}"
    return RedirectResponse(redirect_url, status_code=303)


# ── GET: Home / dashboard ─────────────────────────────────────────────────────

@router.get("/home", response_class=HTMLResponse)
def home_page(
    request: Request,
    db: Session = Depends(get_db),
    q: Optional[str] = Query(None),
):
    """Dashboard: stats + search for orderer by name/phone/email."""
    total   = db.query(Voucher).count()
    drafts  = db.query(Voucher).filter(
        Voucher.status.in_([STATUS_DRAFT, STATUS_AWAITING, STATUS_PAID])).count()
    sent    = db.query(Voucher).filter_by(status=STATUS_ACTIVE).count()
    used    = db.query(Voucher).filter_by(status=STATUS_USED).count()
    holders_count = db.query(Holder).count()

    search_results = None
    found_holders  = None

    if q:
        # Search for orderers (holders) by name, phone, or email
        term = f"%{q}%"
        found_holders = (
            db.query(Holder)
            .filter(or_(
                Holder.name.ilike(term),
                Holder.mobile.ilike(term),
                Holder.email.ilike(term),
            ))
            .order_by(Holder.name)
            .all()
        )
        search_results = True  # flag that a search was performed

    return templates.TemplateResponse("home.html", {
        "request":        request,
        "stats":          {"total": total, "draft": drafts, "sent": sent,
                           "used": used, "holders": holders_count},
        "search_q":       q or "",
        "search_results": search_results,
        "found_holders":  found_holders,
    })


# ── GET: Holder detail page ───────────────────────────────────────────────────

@router.get("/holders/{mobile}/view", response_class=HTMLResponse)
def holder_page(mobile: str, request: Request, db: Session = Depends(get_db)):
    """Holder detail: info card, vouchers table, edit and new-voucher modals."""
    holder = db.get(Holder, mobile)
    if not holder:
        raise HTTPException(status_code=404, detail=f"מחזיק לא נמצא: {mobile}")

    return templates.TemplateResponse("holder.html", {
        "request":  request,
        "holder":   holder,
        "can_edit": rules.can_edit_holder(db, mobile),
        "vouchers": holder.vouchers,
        "today":          date.today().isoformat(),
        "default_expiry": (date.today() + timedelta(days=182)).isoformat(),
    })


# ── GET: All orderers page ───────────────────────────────────────────────────

@router.get("/orderers/view", response_class=HTMLResponse)
def orderers_page(request: Request, db: Session = Depends(get_db)):
    """All orderers with voucher counts."""
    orderers = db.query(Holder).order_by(Holder.name).all()
    return templates.TemplateResponse("orderers.html", {
        "request":  request,
        "orderers": orderers,
    })


# ── GET: New voucher page ────────────────────────────────────────────────────

@router.get("/vouchers/new/view", response_class=HTMLResponse)
def new_voucher_page(request: Request, db: Session = Depends(get_db),
                     mobile: Optional[str] = Query(None),
                     kind: Optional[str] = Query(None)):
    """
    Full-page new ticket form with orderer search/create.
    ?mobile= prefills an existing orderer (from the orderer page);
    ?kind=PASS preselects the pass kind.
    """
    all_holders = db.query(Holder).order_by(Holder.name).all()
    prefill = db.get(Holder, mobile) if mobile else None
    return templates.TemplateResponse("new_voucher.html", {
        "request":        request,
        "all_holders":    all_holders,
        "prefill":        prefill,
        "preselect_kind": (kind or KIND_VOUCHER).upper(),
        "today":          date.today().isoformat(),
        "default_expiry": (date.today() + timedelta(days=182)).isoformat(),
        "default_location": settings.get_default_location(),
        "default_location_en": settings.get_default_location_en(),
        "price_list_json": json.dumps(settings.get_price_list(), ensure_ascii=False),
        "default_terms":  settings.get_default_terms(),
        "default_terms_en": settings.get_default_terms_en(),
    })


# ── GET: Settings page ────────────────────────────────────────────────────────

@router.get("/settings/view", response_class=HTMLResponse)
def settings_page(request: Request):
    """Price list, default terms and default locations (Hebrew / English tickets)."""
    return templates.TemplateResponse("settings.html", {
        "request":          request,
        "price_list":       settings.get_price_list(),
        "default_terms":    settings.get_default_terms(),
        "default_terms_en": settings.get_default_terms_en(),
        "default_location": settings.get_default_location(),
        "default_location_en": settings.get_default_location_en(),
    })


@router.post("/form/settings")
async def form_save_settings(
    default_terms:    str = Form(""),
    default_terms_en: str = Form(""),
    default_location: str = Form(""),
    default_location_en: str = Form(""),
    pl_kind:    List[str] = Form([]),
    pl_type:    List[str] = Form([]),
    pl_entries: List[str] = Form([]),
    pl_price:   List[str] = Form([]),
):
    """Save the settings page. Price list rows arrive as parallel lists."""
    try:
        rows = []
        for k, t, n, p in zip(pl_kind, pl_type, pl_entries, pl_price):
            if not (n or "").strip() and not (p or "").strip():
                continue   # blank row from the "add row" template
            rows.append({"kind": k, "voucher_type": t, "entries": n, "price": p})
        settings.set_price_list(rows)
        settings.set_default_terms(default_terms)
        settings.set_default_terms_en(default_terms_en)
        if default_location.strip():
            settings.set_default_location(default_location)
        if default_location_en.strip():
            settings.set_default_location_en(default_location_en)
        return _flash("/settings/view", "ההגדרות נשמרו")
    except ValueError as e:
        return _flash("/settings/view", str(e), "danger")


# ── GET: All vouchers page ──────────────────────────────────────────────────

@router.get("/all-vouchers/view", response_class=HTMLResponse)
def all_vouchers_page(request: Request, db: Session = Depends(get_db)):
    """All vouchers with orderer names and inline actions."""
    vouchers = (
        db.query(Voucher)
        .order_by(Voucher.issued_at.desc())
        .all()
    )
    all_holders = db.query(Holder).order_by(Holder.name).all()
    return templates.TemplateResponse("all_vouchers.html", {
        "request":        request,
        "vouchers":       vouchers,
        "all_holders":    all_holders,
        "today":          date.today().isoformat(),
        "default_expiry": (date.today() + timedelta(days=182)).isoformat(),
    })


# ── GET: Voucher detail page ──────────────────────────────────────────────────

@router.get("/vouchers/{voucher_id}/view", response_class=HTMLResponse)
def voucher_page(voucher_id: str, request: Request, db: Session = Depends(get_db)):
    """Voucher detail: info, actions, QR, sending history, receipt fields."""
    voucher = db.get(Voucher, voucher_id)
    if not voucher:
        raise HTTPException(status_code=404, detail=f"כרטיס לא נמצא: {voucher_id}")

    holder = db.get(Holder, voucher.mobile) if voucher.mobile else None

    # Image library for the image-management card (gallery + current selection).
    gallery = images.list_images()
    current_image = voucher.image_file or images.get_default()

    # Location: current value (per-voucher override or default in the ticket's language).
    current_location = voucher.location or settings.default_location_for(voucher.language)

    # Manual payment methods offered in the "mark paid" form (no GI / FREE / legacy)
    manual_methods = {k: v for k, v in PAYMENT_METHODS.items()
                      if k in ("CASH", "BIT", "TRANSFER", "CARD")}

    return templates.TemplateResponse("voucher_view.html", {
        "request":          request,
        "voucher":          voucher,
        "holder":           holder,
        "today":            date.today().isoformat(),
        "gallery":          gallery,
        "current_image":    current_image,
        "current_location": current_location,
        "manual_methods":   manual_methods,
        # Payment message in both languages — the page toggle picks one
        "payment_text":     rules.payment_request_text(voucher),
        "payment_text_he":  rules.payment_request_text(voucher, "he"),
        "payment_text_en":  rules.payment_request_text(voucher, "en"),
    })


# ── GET: Report page ──────────────────────────────────────────────────────────

@router.get("/report/view", response_class=HTMLResponse)
def report_page(
    request: Request,
    db: Session = Depends(get_db),
    status:         Optional[str]  = Query(None),
    voucher_type:   Optional[str]  = Query(None),
    kind:           Optional[str]  = Query(None),
    date_from:      Optional[date] = Query(None),
    date_to:        Optional[date] = Query(None),
    receipt_number: Optional[str]  = Query(None),
):
    """Filterable report with CSV export link."""
    filters = {
        "status":         status,
        "voucher_type":   voucher_type,
        "kind":           kind,
        "date_from":      str(date_from) if date_from else "",
        "date_to":        str(date_to)   if date_to   else "",
        "receipt_number": receipt_number or "",
        "has_any":        any([status, voucher_type, kind, date_from, date_to, receipt_number]),
    }

    q = db.query(Voucher)
    if status:         q = q.filter(Voucher.status == status)
    if voucher_type:   q = q.filter(Voucher.voucher_type == voucher_type)
    if kind:           q = q.filter(Voucher.kind == kind.upper())
    if receipt_number: q = q.filter(Voucher.receipt_number.ilike(f"%{receipt_number}%"))
    if date_from:      q = q.filter(Voucher.issued_at >= date_from)
    if date_to:        q = q.filter(Voucher.issued_at <= date_to)

    vouchers = q.order_by(Voucher.issued_at.desc()).all()

    csv_params = {k: v for k, v in {
        "status": status, "voucher_type": voucher_type, "kind": kind,
        "date_from": str(date_from) if date_from else None,
        "date_to":   str(date_to)   if date_to   else None,
        "receipt_number": receipt_number, "fmt": "csv",
    }.items() if v}

    return templates.TemplateResponse("report.html", {
        "request":   request,
        "vouchers":  vouchers,
        "filters":   filters,
        "filter_qs": urlencode(csv_params),
    })


# ── POST: Create holder ───────────────────────────────────────────────────────

@router.post("/form/holders/new")
async def form_create_holder(
    mobile: str           = Form(...),
    name:   str           = Form(...),
    email:  Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Create or retrieve a holder, then redirect to their detail page."""
    try:
        holder, _ = rules.get_or_create_holder(db, mobile, name, email or None)
        return _flash(f"/holders/{holder.mobile}/view", "המחזיק נשמר בהצלחה")
    except Exception as e:
        return _flash("/home", str(e), "danger")


# ── POST: Update holder ───────────────────────────────────────────────────────

@router.post("/form/holders/{mobile}/edit")
async def form_update_holder(
    mobile: str,
    name:   Optional[str] = Form(None),
    email:  Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Update holder name/email and redirect back."""
    try:
        rules.update_holder(db, mobile, name or None, email or None)
        return _flash(f"/holders/{mobile}/view", "הפרטים עודכנו")
    except rules.RulesError as e:
        return _flash(f"/holders/{mobile}/view", str(e), "danger")


# ── POST: Create voucher ──────────────────────────────────────────────────────

@router.post("/form/vouchers/new")
async def form_create_voucher(
    mobile:         str           = Form(...),
    voucher_type:   str           = Form(...),
    valid_until:    str           = Form(...),          # "YYYY-MM-DD" from date input
    kind:           str           = Form("VOUCHER"),
    entries_total:  str           = Form("1"),
    price:          Optional[str] = Form(None),
    receipt_number: Optional[str] = Form(None),
    receipt_date:   Optional[str] = Form(None),
    notes:          Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Create a draft ticket for a known orderer and redirect to its page."""
    try:
        parsed_date = date.fromisoformat(valid_until)
        if parsed_date < date.today():
            return _flash(f"/holders/{mobile}/view",
                          "תאריך תוקף לא יכול להיות בעבר", "danger")

        v = rules.create_voucher(
            db,
            mobile       = mobile,
            voucher_type = voucher_type,
            valid_until  = parsed_date,
            kind         = kind,
            entries_total = entries_total,
            price        = price or None,
            receipt_number = receipt_number or None,
            receipt_date   = date.fromisoformat(receipt_date) if receipt_date else None,
            notes          = notes or None,
        )
        return _flash(f"/vouchers/{v.voucher_id}/view", "הכרטיס נוצר בהצלחה")
    except rules.RulesError as e:
        return _flash(f"/holders/{mobile}/view", str(e), "danger")
    except ValueError as e:
        return _flash(f"/holders/{mobile}/view", f"תאריך לא תקין: {e}", "danger")


# ── POST: Create voucher (full flow — creates orderer if needed) ─────────────

@router.post("/form/vouchers/new-full")
async def form_create_voucher_full(
    mobile:         str           = Form(...),
    voucher_type:   str           = Form(...),
    valid_until:    str           = Form(...),
    receipt_number: Optional[str] = Form(None),
    receipt_date:   Optional[str] = Form(None),
    notes:          Optional[str] = Form(None),
    display_name:   Optional[str] = Form(None),
    greeting:       Optional[str] = Form(None),
    location:       Optional[str] = Form(None),
    kind:           str           = Form("VOUCHER"),
    entries_total:  str           = Form("1"),
    language:       str           = Form("he"),
    list_price:     Optional[str] = Form(None),
    discount:       Optional[str] = Form(None),
    price:          Optional[str] = Form(None),
    terms:          Optional[str] = Form(None),
    is_new_orderer: str           = Form("0"),
    new_name:       Optional[str] = Form(None),
    new_email:      Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Create orderer (if new) + draft ticket, redirect to ticket detail."""
    try:
        # Create orderer if needed
        if is_new_orderer == "1" and new_name:
            rules.get_or_create_holder(db, mobile, new_name, new_email or None)

        # Validate date
        parsed_date = date.fromisoformat(valid_until)
        if parsed_date < date.today():
            return _flash("/vouchers/new/view",
                          "תאריך תוקף לא יכול להיות בעבר", "danger")

        v = rules.create_voucher(
            db,
            mobile       = mobile,
            voucher_type = voucher_type,
            valid_until  = parsed_date,
            receipt_number = receipt_number or None,
            receipt_date   = date.fromisoformat(receipt_date) if receipt_date else None,
            notes          = notes or None,
            display_name   = display_name or None,
            greeting       = greeting or None,
            location       = location or None,
            kind           = kind,
            entries_total  = entries_total,
            list_price     = list_price or None,
            discount       = discount or None,
            price          = price or None,
            terms          = (terms if terms is not None and terms.strip() else None),
            language       = language,
        )
        return _flash(f"/vouchers/{v.voucher_id}/view", "הכרטיס נוצר בהצלחה")
    except rules.RulesError as e:
        return _flash("/vouchers/new/view", str(e), "danger")
    except ValueError as e:
        return _flash("/vouchers/new/view", f"שגיאה: {e}", "danger")


# ── POST: Send / Resend voucher ───────────────────────────────────────────────

@router.post("/form/vouchers/{voucher_id}/send")
async def form_send_voucher(
    voucher_id: str,
    request:    Request,
    sent_via:   str           = Form(...),
    note:       Optional[str] = Form(None),
    language:   Optional[str] = Form(None),   # he / en — document language (resend)
    db: Session = Depends(get_db),
):
    """First-send or resend depending on current voucher status."""
    voucher = db.get(Voucher, voucher_id)
    if not voucher:
        return _flash("/home", f"כרטיס לא נמצא: {voucher_id}", "danger")
    username = auth_module.get_current_user(request)
    try:
        if voucher.status in (STATUS_DRAFT, STATUS_PAID, STATUS_AWAITING):
            rules.first_send(db, voucher_id, sent_via, note or None,
                             performed_by=username)
            msg = "הכרטיס נשלח בהצלחה"
        else:
            rules.resend(db, voucher_id, sent_via, note or None,
                         performed_by=username, language=language or None)
            msg = "הכרטיס נשלח מחדש"

        # Refresh voucher to get cemented mobile
        db.refresh(voucher)

        # For WhatsApp: redirect to voucher page with wa_open flag
        # so the browser opens wa.me automatically
        if sent_via == "WA":
            mobile = voucher.holder_mobile or voucher.mobile
            return _flash(
                f"/vouchers/{voucher_id}/view?wa_open={mobile}",
                msg,
            )

        return _flash(f"/vouchers/{voucher_id}/view", msg)
    except rules.RulesError as e:
        return _flash(f"/vouchers/{voucher_id}/view", str(e), "danger")


# ── POST: Mark voucher used ───────────────────────────────────────────────────

@router.post("/form/vouchers/{voucher_id}/use")
async def form_mark_used(
    voucher_id: str,
    db: Session = Depends(get_db),
):
    """Consume one entry directly (legacy mark used) and redirect back."""
    try:
        rules.mark_used(db, voucher_id)
        return _flash(f"/vouchers/{voucher_id}/view", "הטיפול סומן כמומש ✅")
    except rules.RulesError as e:
        return _flash(f"/vouchers/{voucher_id}/view", str(e), "danger")


# ── POST: Payment request sent ────────────────────────────────────────────────

@router.post("/form/vouchers/{voucher_id}/request-payment")
async def form_request_payment(
    voucher_id: str,
    request:    Request,
    sent_via:   str           = Form(...),
    note:       Optional[str] = Form(None),
    language:   Optional[str] = Form(None),   # he / en — message language
    db: Session = Depends(get_db),
):
    """Record a payment request send (draft → awaiting_payment) and redirect back."""
    username = auth_module.get_current_user(request)
    try:
        rules.request_payment(db, voucher_id, sent_via, note or None,
                              performed_by=username, language=language or None)
        return _flash(f"/vouchers/{voucher_id}/view", "בקשת התשלום נרשמה")
    except rules.RulesError as e:
        return _flash(f"/vouchers/{voucher_id}/view", str(e), "danger")


# ── POST: Mark paid (manual) ──────────────────────────────────────────────────

@router.post("/form/vouchers/{voucher_id}/mark-paid")
async def form_mark_paid(
    voucher_id:     str,
    request:        Request,
    method:         str           = Form(...),
    receipt_number: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Record a manual payment and redirect back."""
    username = auth_module.get_current_user(request)
    try:
        rules.mark_paid(db, voucher_id, method,
                        receipt_number=receipt_number or None,
                        performed_by=username)
        return _flash(f"/vouchers/{voucher_id}/view", "התשלום נרשם — אפשר לשלוח את הכרטיס")
    except rules.RulesError as e:
        return _flash(f"/vouchers/{voucher_id}/view", str(e), "danger")


# ── POST: Update price ────────────────────────────────────────────────────────

@router.post("/form/vouchers/{voucher_id}/price")
async def form_update_price(
    voucher_id: str,
    list_price: Optional[str] = Form(None),
    discount:   Optional[str] = Form(None),
    price:      Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Change list price / discount / final price (before payment only)."""
    try:
        rules.set_price(db, voucher_id, list_price or None, discount or None,
                        price or None)
        return _flash(f"/vouchers/{voucher_id}/view", "המחיר עודכן")
    except rules.RulesError as e:
        return _flash(f"/vouchers/{voucher_id}/view", str(e), "danger")


# ── POST: Entries — hold / consume / cancel / direct ──────────────────────────

@router.post("/form/vouchers/{voucher_id}/entries/hold")
async def form_hold_entry(
    voucher_id:    str,
    request:       Request,
    scheduled_for: Optional[str] = Form(None),   # "YYYY-MM-DDTHH:MM" from datetime-local
    note:          Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Reserve an entry for a scheduled treatment."""
    username = auth_module.get_current_user(request)
    try:
        when = datetime.fromisoformat(scheduled_for) if scheduled_for else None
        rules.hold_entry(db, voucher_id, when, note or None, performed_by=username)
        return _flash(f"/vouchers/{voucher_id}/view", "הטיפול שוריין")
    except rules.RulesError as e:
        return _flash(f"/vouchers/{voucher_id}/view", str(e), "danger")
    except ValueError as e:
        return _flash(f"/vouchers/{voucher_id}/view", f"תאריך לא תקין: {e}", "danger")


@router.post("/form/vouchers/{voucher_id}/entries/{entry_id}/consume")
async def form_consume_entry(
    voucher_id: str, entry_id: int, request: Request,
    note: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """The scheduled treatment took place."""
    username = auth_module.get_current_user(request)
    try:
        rules.consume_entry(db, voucher_id, entry_id, note or None,
                            performed_by=username)
        return _flash(f"/vouchers/{voucher_id}/view", "הטיפול מומש ✅")
    except rules.RulesError as e:
        return _flash(f"/vouchers/{voucher_id}/view", str(e), "danger")


@router.post("/form/vouchers/{voucher_id}/entries/{entry_id}/cancel")
async def form_cancel_entry(
    voucher_id: str, entry_id: int, request: Request,
    note: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """The scheduled treatment was cancelled — the entry is released."""
    username = auth_module.get_current_user(request)
    try:
        rules.cancel_hold(db, voucher_id, entry_id, note or None,
                          performed_by=username)
        return _flash(f"/vouchers/{voucher_id}/view", "השריון בוטל")
    except rules.RulesError as e:
        return _flash(f"/vouchers/{voucher_id}/view", str(e), "danger")


@router.post("/form/vouchers/{voucher_id}/entries/consume")
async def form_consume_direct(
    voucher_id: str, request: Request,
    note: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Walk-in: consume one entry without a prior hold."""
    username = auth_module.get_current_user(request)
    try:
        rules.consume_direct(db, voucher_id, note or None, performed_by=username)
        return _flash(f"/vouchers/{voucher_id}/view", "הטיפול מומש ✅")
    except rules.RulesError as e:
        return _flash(f"/vouchers/{voucher_id}/view", str(e), "danger")


# ── POST: Update receipt / notes ──────────────────────────────────────────────

@router.post("/form/vouchers/{voucher_id}/notes")
async def form_update_notes(
    voucher_id:     str,
    receipt_number: Optional[str] = Form(None),
    receipt_date:   Optional[str] = Form(None),
    notes:          Optional[str] = Form(None),
    greeting:       Optional[str] = Form(None),
    language:       Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Update receipt number, receipt date, notes, greeting and default language; redirect back."""
    try:
        rules.update_voucher_fields(
            db,
            voucher_id,
            receipt_number = receipt_number or None,
            receipt_date   = date.fromisoformat(receipt_date) if receipt_date else None,
            notes          = notes or None,
            greeting       = greeting if greeting is not None else None,
            language       = language or None,
        )
        return _flash(f"/vouchers/{voucher_id}/view", "נשמר בהצלחה")
    except rules.RulesError as e:
        return _flash(f"/vouchers/{voucher_id}/view", str(e), "danger")
    except ValueError as e:
        return _flash(f"/vouchers/{voucher_id}/view", f"תאריך לא תקין: {e}", "danger")


# ── POST: Set voucher image (one-time, or as future default) ──────────────────

@router.post("/form/vouchers/{voucher_id}/image")
async def form_set_image(
    voucher_id: str,
    image_file: str = Form(...),
    mode:       str = Form("once"),   # "once" = this voucher only, "permanent" = also default
    db: Session = Depends(get_db),
):
    """Set the voucher's image; 'permanent' also makes it the future default."""
    try:
        rules.set_voucher_image(
            db, voucher_id, image_file,
            make_default=(mode == "permanent"),
        )
        msg = "התמונה נשמרה כברירת מחדל" if mode == "permanent" else "התמונה עודכנה"
        return _flash(f"/vouchers/{voucher_id}/view", msg)
    except rules.RulesError as e:
        return _flash(f"/vouchers/{voucher_id}/view", str(e), "danger")


# ── POST: Upload a new image into the library ─────────────────────────────────

@router.post("/form/vouchers/{voucher_id}/image/upload")
async def form_upload_image(
    voucher_id: str,
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Add an uploaded image to the library, then return to the voucher page."""
    try:
        data = await image.read()
        images.add_image(data, image.filename or "image.png")
        return _flash(f"/vouchers/{voucher_id}/view", "התמונה נוספה לספרייה")
    except ValueError as e:
        return _flash(f"/vouchers/{voucher_id}/view", str(e), "danger")


# ── POST: Set voucher location (one-time, or as future default) ───────────────

@router.post("/form/vouchers/{voucher_id}/location")
async def form_set_location(
    voucher_id: str,
    location:   str = Form(""),
    mode:       str = Form("once"),   # "once" = this voucher only, "permanent" = also default
    db: Session = Depends(get_db),
):
    """Set the voucher's location; 'permanent' also makes it the future default."""
    try:
        rules.set_voucher_location(
            db, voucher_id, location,
            make_default=(mode == "permanent"),
        )
        msg = "המיקום נשמר כברירת מחדל" if mode == "permanent" else "המיקום עודכן"
        return _flash(f"/vouchers/{voucher_id}/view", msg)
    except rules.RulesError as e:
        return _flash(f"/vouchers/{voucher_id}/view", str(e), "danger")
