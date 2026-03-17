"""
Holders router — /holders endpoints

POST   /holders              → create or retrieve by mobile
GET    /holders/{mobile}     → holder details + all their vouchers
PUT    /holders/{mobile}     → update name/email (blocked if has used voucher)
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Holder
from app.schemas import HolderCreate, HolderUpdate, HolderOut, VoucherListItem
from app import rules

router = APIRouter(prefix="/holders", tags=["holders"])


@router.post("", response_model=HolderOut, status_code=status.HTTP_200_OK)
def create_or_get_holder(body: HolderCreate, db: Session = Depends(get_db)):
    """
    Create a new holder or return an existing one by mobile.
    If mobile already exists, the existing record is returned (name/email ignored).
    Status 200 in both cases — caller checks the 'created' field if needed.
    """
    holder, created = rules.get_or_create_holder(
        db, body.mobile, body.name, body.email
    )
    can_edit = rules.can_edit_holder(db, holder.mobile)
    out = HolderOut.model_validate(holder)
    out.can_edit = can_edit
    return out


@router.get("/{mobile}", response_model=dict)
def get_holder(mobile: str, db: Session = Depends(get_db)):
    """
    Return holder details plus all their vouchers (newest first).
    """
    holder = db.get(Holder, mobile)
    if not holder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"מחזיק לא נמצא: {mobile}",
        )

    can_edit = rules.can_edit_holder(db, mobile)

    holder_data = HolderOut.model_validate(holder)
    holder_data.can_edit = can_edit

    vouchers = [VoucherListItem.model_validate(v) for v in holder.vouchers]

    return {
        "holder":   holder_data,
        "vouchers": vouchers,
    }


@router.put("/{mobile}", response_model=HolderOut)
def update_holder(mobile: str, body: HolderUpdate,
                  db: Session = Depends(get_db)):
    """
    Update holder name and/or email.
    Returns 409 if the holder has any used vouchers.
    """
    try:
        holder = rules.update_holder(db, mobile, body.name, body.email)
    except rules.RulesError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )

    can_edit = rules.can_edit_holder(db, mobile)
    out = HolderOut.model_validate(holder)
    out.can_edit = can_edit
    return out
