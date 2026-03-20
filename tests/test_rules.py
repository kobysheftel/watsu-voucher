"""
End-to-end rules engine tests.
Uses an in-memory SQLite database — no files touched on disk.
Run with: python -m pytest tests/test_rules.py -v
"""

import pytest
from datetime import date, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Holder, Voucher, Sending
from app import rules


# ── In-memory DB fixture ──────────────────────────────────────────────────────

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


MOBILE  = "0541234567"
MOBILE2 = "0521112222"
FUTURE  = date.today() + timedelta(days=180)


# ── Holder tests ──────────────────────────────────────────────────────────────

def test_create_holder(db):
    holder, created = rules.get_or_create_holder(db, MOBILE, "שרה כהן", "sara@test.com")
    assert created is True
    assert holder.mobile == MOBILE
    assert holder.name == "שרה כהן"

def test_retrieve_existing_holder(db):
    rules.get_or_create_holder(db, MOBILE, "שרה כהן", None)
    holder, created = rules.get_or_create_holder(db, MOBILE, "שם שונה", None)
    assert created is False
    assert holder.name == "שרה כהן"   # original name unchanged

def test_can_edit_holder_no_vouchers(db):
    rules.get_or_create_holder(db, MOBILE, "שרה כהן", None)
    assert rules.can_edit_holder(db, MOBILE) is True

def test_update_holder(db):
    rules.get_or_create_holder(db, MOBILE, "שרה כהן", None)
    holder = rules.update_holder(db, MOBILE, name="שרה לוי", email=None)
    assert holder.name == "שרה לוי"

def test_update_holder_blocked_when_used(db):
    """Holder edit blocked if any voucher is used."""
    rules.get_or_create_holder(db, MOBILE, "שרה כהן", None)
    v = rules.create_voucher(db, MOBILE, "יחיד", FUTURE)
    # Force status to used directly (bypassing rules for this test)
    v.status = "used"
    db.commit()
    with pytest.raises(rules.RulesError, match="מומש"):
        rules.update_holder(db, MOBILE, name="שם אחר", email=None)


# ── Voucher creation ──────────────────────────────────────────────────────────

def test_create_voucher(db):
    rules.get_or_create_holder(db, MOBILE, "שרה כהן", None)
    v = rules.create_voucher(db, MOBILE, "יחיד", FUTURE)
    assert v.voucher_id == f"{MOBILE}-001"
    assert v.sequence == 1
    assert v.status == "draft"

def test_sequence_increments(db):
    rules.get_or_create_holder(db, MOBILE, "שרה כהן", None)
    v1 = rules.create_voucher(db, MOBILE, "יחיד", FUTURE)
    v2 = rules.create_voucher(db, MOBILE, "זוגי",  FUTURE)
    assert v1.voucher_id == f"{MOBILE}-001"
    assert v2.voucher_id == f"{MOBILE}-002"

def test_create_voucher_no_holder(db):
    with pytest.raises(rules.RulesError, match="לא נמצא"):
        rules.create_voucher(db, "0599999999", "יחיד", FUTURE)


# ── First send ────────────────────────────────────────────────────────────────

def test_first_send_cements_holder(db):
    rules.get_or_create_holder(db, MOBILE, "שרה כהן", "sara@test.com")
    v = rules.create_voucher(db, MOBILE, "יחיד", FUTURE)
    v = rules.first_send(db, v.voucher_id, "WA")

    assert v.status == "sent"
    assert v.holder_name   == "שרה כהן"
    assert v.holder_mobile == MOBILE
    assert v.holder_email  == "sara@test.com"
    assert v.first_sent_at is not None
    assert v.is_cemented is True

def test_first_send_logs_sending(db):
    rules.get_or_create_holder(db, MOBILE, "שרה כהן", None)
    v = rules.create_voucher(db, MOBILE, "יחיד", FUTURE)
    v = rules.first_send(db, v.voucher_id, "EMAIL", note="נשלח בדוא״ל")

    sendings = db.query(Sending).filter_by(voucher_id=v.voucher_id).all()
    assert len(sendings) == 1
    assert sendings[0].sent_via == "EMAIL"
    assert sendings[0].note == "נשלח בדוא״ל"

def test_first_send_only_from_draft(db):
    rules.get_or_create_holder(db, MOBILE, "שרה כהן", None)
    v = rules.create_voucher(db, MOBILE, "יחיד", FUTURE)
    rules.first_send(db, v.voucher_id, "WA")
    with pytest.raises(rules.RulesError, match="אינו בטיוטה"):
        rules.first_send(db, v.voucher_id, "WA")   # second call must fail

def test_cement_survives_holder_edit(db):
    """Editing holder after send must NOT change cemented data."""
    rules.get_or_create_holder(db, MOBILE, "שרה כהן", "sara@test.com")
    v = rules.create_voucher(db, MOBILE, "יחיד", FUTURE)
    v = rules.first_send(db, v.voucher_id, "WA")

    # Now edit the holder
    rules.update_holder(db, MOBILE, name="שרה לוי", email="new@test.com")

    # Cemented data on voucher must stay the same
    db.refresh(v)
    assert v.holder_name  == "שרה כהן"
    assert v.holder_email == "sara@test.com"


# ── Resend ────────────────────────────────────────────────────────────────────

def test_resend_logs_new_row(db):
    rules.get_or_create_holder(db, MOBILE, "שרה כהן", None)
    v = rules.create_voucher(db, MOBILE, "יחיד", FUTURE)
    rules.first_send(db, v.voucher_id, "WA")
    rules.resend(db, v.voucher_id, "PRINT", note="הדפסה חוזרת")

    sendings = db.query(Sending).filter_by(voucher_id=v.voucher_id).all()
    assert len(sendings) == 2
    assert sendings[0].sent_via in ("WA", "PRINT")

def test_resend_does_not_change_first_sent_at(db):
    rules.get_or_create_holder(db, MOBILE, "שרה כהן", None)
    v = rules.create_voucher(db, MOBILE, "יחיד", FUTURE)
    v = rules.first_send(db, v.voucher_id, "WA")
    first_ts = v.first_sent_at
    rules.resend(db, v.voucher_id, "EMAIL")
    db.refresh(v)
    assert v.first_sent_at == first_ts

def test_resend_blocked_on_draft(db):
    rules.get_or_create_holder(db, MOBILE, "שרה כהן", None)
    v = rules.create_voucher(db, MOBILE, "יחיד", FUTURE)
    with pytest.raises(rules.RulesError, match="טרם נשלח"):
        rules.resend(db, v.voucher_id, "WA")

def test_resend_blocked_on_used(db):
    rules.get_or_create_holder(db, MOBILE, "שרה כהן", None)
    v = rules.create_voucher(db, MOBILE, "יחיד", FUTURE)
    rules.first_send(db, v.voucher_id, "WA")
    rules.mark_used(db, v.voucher_id)
    with pytest.raises(rules.RulesError, match="מומש"):
        rules.resend(db, v.voucher_id, "WA")


# ── Mark used ─────────────────────────────────────────────────────────────────

def test_mark_used(db):
    rules.get_or_create_holder(db, MOBILE, "שרה כהן", None)
    v = rules.create_voucher(db, MOBILE, "יחיד", FUTURE)
    rules.first_send(db, v.voucher_id, "WA")
    v = rules.mark_used(db, v.voucher_id)
    assert v.status == "used"
    assert v.is_frozen is True

def test_mark_used_blocks_draft(db):
    rules.get_or_create_holder(db, MOBILE, "שרה כהן", None)
    v = rules.create_voucher(db, MOBILE, "יחיד", FUTURE)
    with pytest.raises(rules.RulesError, match="טיוטה"):
        rules.mark_used(db, v.voucher_id)

def test_mark_used_twice_fails(db):
    rules.get_or_create_holder(db, MOBILE, "שרה כהן", None)
    v = rules.create_voucher(db, MOBILE, "יחיד", FUTURE)
    rules.first_send(db, v.voucher_id, "WA")
    rules.mark_used(db, v.voucher_id)
    with pytest.raises(rules.RulesError, match="כבר מומש"):
        rules.mark_used(db, v.voucher_id)


# ── Update fields ─────────────────────────────────────────────────────────────

def test_update_receipt(db):
    rules.get_or_create_holder(db, MOBILE, "שרה כהן", None)
    v = rules.create_voucher(db, MOBILE, "יחיד", FUTURE)
    v = rules.update_voucher_fields(db, v.voucher_id,
                                    receipt_number="IL-2026-001",
                                    receipt_date=date.today())
    assert v.receipt_number == "IL-2026-001"

def test_update_receipt_blocked_when_used(db):
    rules.get_or_create_holder(db, MOBILE, "שרה כהן", None)
    v = rules.create_voucher(db, MOBILE, "יחיד", FUTURE)
    rules.first_send(db, v.voucher_id, "WA")
    rules.mark_used(db, v.voucher_id)
    with pytest.raises(rules.RulesError, match="מומש"):
        rules.update_voucher_fields(db, v.voucher_id, notes="נסיון עריכה")
