"""
Phase A — ticket generalisation tests (vouchers + passes, entries, payment).
Uses an in-memory SQLite database — no files touched on disk except the
voucher folder written by first_send (same as the existing rules tests).
Run with: python -m pytest tests/test_tickets.py -v
"""

import pytest
from datetime import date, datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.database import Base, get_db, _migrate
from app.models import Holder, Voucher, Sending, Entry
from app import rules
from main import app


# ── In-memory DB fixture (rules level) ────────────────────────────────────────

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


MOBILE = "0541234567"
FUTURE = date.today() + timedelta(days=180)


def _holder(db):
    rules.get_or_create_holder(db, MOBILE, "שרה כהן", "sara@test.com")


def _pass(db, entries=5, price=1000):
    """Create a priced pass with N entries."""
    return rules.create_voucher(db, MOBILE, "יחיד", FUTURE,
                                kind="PASS", entries_total=entries, price=price)


def _active_pass(db, entries=5):
    """Pass that was paid and sent → active, ready for holds."""
    v = _pass(db, entries)
    rules.mark_paid(db, v.voucher_id, "BIT")
    return rules.first_send(db, v.voucher_id, "WA")


# ── Creation ──────────────────────────────────────────────────────────────────

def test_create_pass(db):
    _holder(db)
    v = _pass(db, entries=10, price=1800)
    assert v.kind == "PASS"
    assert v.entries_total == 10
    assert v.price == 1800
    assert v.status == "draft"
    assert v.is_pass is True
    assert v.product_title == "כרטיסיה ל-10 טיפולי וואטסו ליחיד"
    assert v.terms                      # default terms copied at creation


def test_create_voucher_defaults(db):
    """A plain voucher is a 1-entry VOUCHER with no price (free)."""
    _holder(db)
    v = rules.create_voucher(db, MOBILE, "זוגי", FUTURE)
    assert v.kind == "VOUCHER"
    assert v.entries_total == 1
    assert v.is_free is True
    assert v.product_title == "שובר מתנה לטיפול וואטסו זוגי"


def test_multi_entry_voucher(db):
    """Vouchers may also be multi-entry (Koby's decision 7)."""
    _holder(db)
    v = rules.create_voucher(db, MOBILE, "יחיד", FUTURE, kind="VOUCHER",
                             entries_total=3, greeting="מזל טוב")
    assert v.entries_total == 3
    assert v.greeting == "מזל טוב"
    assert v.product_title == "שובר מתנה ל-3 טיפולי וואטסו ליחיד"


def test_pass_drops_greeting(db):
    _holder(db)
    v = rules.create_voucher(db, MOBILE, "יחיד", FUTURE, kind="PASS",
                             entries_total=5, greeting="לא רלוונטי")
    assert v.greeting is None


def test_price_from_list_and_discount(db):
    _holder(db)
    v = rules.create_voucher(db, MOBILE, "יחיד", FUTURE, kind="PASS",
                             entries_total=5, list_price=1000, discount=150)
    assert v.price == 850


def test_invalid_kind_and_entries(db):
    _holder(db)
    with pytest.raises(rules.RulesError):
        rules.create_voucher(db, MOBILE, "יחיד", FUTURE, kind="TICKET")
    with pytest.raises(rules.RulesError):
        rules.create_voucher(db, MOBILE, "יחיד", FUTURE, entries_total=0)
    with pytest.raises(rules.RulesError):
        rules.create_voucher(db, MOBILE, "יחיד", FUTURE, price=-5)


# ── Payment flow ──────────────────────────────────────────────────────────────

def test_priced_ticket_cannot_be_sent_before_payment(db):
    _holder(db)
    v = _pass(db)
    with pytest.raises(rules.RulesError, match="טרם שולם"):
        rules.first_send(db, v.voucher_id, "WA")


def test_request_payment_then_mark_paid_then_send(db):
    _holder(db)
    v = _pass(db)

    v = rules.request_payment(db, v.voucher_id, "WA", performed_by="Koby")
    assert v.status == "awaiting_payment"
    s = db.query(Sending).filter_by(voucher_id=v.voucher_id).one()
    assert s.kind == "PAYMENT_LINK"

    # Resend of the payment request keeps the status, adds a row
    rules.request_payment(db, v.voucher_id, "EMAIL")
    assert db.query(Sending).filter_by(voucher_id=v.voucher_id).count() == 2

    # Still cannot send the ticket
    with pytest.raises(rules.RulesError, match="ממתין לתשלום"):
        rules.first_send(db, v.voucher_id, "WA")

    v = rules.mark_paid(db, v.voucher_id, "CASH", receipt_number="R-1")
    assert v.status == "paid"
    assert v.payment_method == "CASH"
    assert v.paid_at is not None
    assert v.receipt_number == "R-1"

    v = rules.first_send(db, v.voucher_id, "WA")
    assert v.status == "active"
    assert v.is_cemented
    ticket_sends = [x for x in v.sendings if x.kind == "TICKET"]
    assert len(ticket_sends) == 1


def test_free_ticket_skips_payment(db):
    _holder(db)
    v = rules.create_voucher(db, MOBILE, "יחיד", FUTURE)     # no price
    with pytest.raises(rules.RulesError, match="ללא מחיר"):
        rules.request_payment(db, v.voucher_id, "WA")
    v = rules.first_send(db, v.voucher_id, "WA")
    assert v.status == "active"
    assert v.payment_method == "FREE"


def test_mark_paid_invalid_method(db):
    _holder(db)
    v = _pass(db)
    with pytest.raises(rules.RulesError):
        rules.mark_paid(db, v.voucher_id, "GOLD")


def test_mark_paid_twice_fails(db):
    _holder(db)
    v = _pass(db)
    rules.mark_paid(db, v.voucher_id, "BIT")
    with pytest.raises(rules.RulesError, match="כבר שולם"):
        rules.mark_paid(db, v.voucher_id, "BIT")


def test_set_price_before_payment_only(db):
    _holder(db)
    v = _pass(db)
    v = rules.set_price(db, v.voucher_id, list_price=1200, discount=200)
    assert v.price == 1000
    rules.mark_paid(db, v.voucher_id, "BIT")
    with pytest.raises(rules.RulesError, match="כבר שולם"):
        rules.set_price(db, v.voucher_id, price=1)


def test_payment_request_text_contains_price_and_terms(db):
    _holder(db)
    v = _pass(db, entries=5, price=1000)
    text = rules.payment_request_text(v)
    assert "1,000" in text
    assert "כרטיסיה ל-5 טיפולי וואטסו ליחיד" in text
    assert v.terms.splitlines()[0] in text


# ── Entries: hold / consume / cancel ──────────────────────────────────────────

def test_hold_and_consume(db):
    _holder(db)
    v = _active_pass(db, entries=3)
    assert v.entries_available == 3

    e = rules.hold_entry(db, v.voucher_id, datetime(2026, 10, 1, 10, 0), "ראשון")
    assert e.status == "held"
    assert e.seq == 1
    db.refresh(v)
    assert v.entries_held == 1
    assert v.entries_available == 2

    e = rules.consume_entry(db, v.voucher_id, e.id, performed_by="Avigal")
    assert e.status == "consumed"
    assert e.consumed_at is not None
    db.refresh(v)
    assert v.entries_consumed == 1
    assert v.entries_held == 0
    assert v.entries_available == 2
    assert v.status == "active"           # not exhausted yet


def test_cancel_hold_releases_entry(db):
    _holder(db)
    v = _active_pass(db, entries=2)
    e = rules.hold_entry(db, v.voucher_id)
    e = rules.cancel_hold(db, v.voucher_id, e.id, note="הלקוח ביטל")
    assert e.status == "cancelled"
    db.refresh(v)
    assert v.entries_available == 2
    assert len(v.entries) == 1           # row kept for audit
    # Next hold gets a new running number
    e2 = rules.hold_entry(db, v.voucher_id)
    assert e2.seq == 2


def test_exhaustion_marks_used(db):
    _holder(db)
    v = _active_pass(db, entries=2)
    rules.consume_direct(db, v.voucher_id)
    db.refresh(v)
    assert v.status == "active"
    v = rules.consume_direct(db, v.voucher_id)
    assert v.status == "used"
    assert v.is_frozen
    with pytest.raises(rules.RulesError):
        rules.consume_direct(db, v.voucher_id)
    with pytest.raises(rules.RulesError):
        rules.hold_entry(db, v.voucher_id)


def test_no_more_holds_than_available(db):
    _holder(db)
    v = _active_pass(db, entries=1)
    rules.hold_entry(db, v.voucher_id)
    with pytest.raises(rules.RulesError, match="לא נותרו"):
        rules.hold_entry(db, v.voucher_id)
    with pytest.raises(rules.RulesError, match="לא נותרו"):
        rules.consume_direct(db, v.voucher_id)


def test_consume_requires_held(db):
    _holder(db)
    v = _active_pass(db, entries=2)
    e = rules.hold_entry(db, v.voucher_id)
    rules.cancel_hold(db, v.voucher_id, e.id)
    with pytest.raises(rules.RulesError, match="אינו משוריין"):
        rules.consume_entry(db, v.voucher_id, e.id)


def test_entry_must_belong_to_ticket(db):
    _holder(db)
    a = _active_pass(db, entries=2)
    b = _active_pass(db, entries=2)
    e = rules.hold_entry(db, a.voucher_id)
    with pytest.raises(rules.RulesError):
        rules.consume_entry(db, b.voucher_id, e.id)


def test_entries_blocked_before_active(db):
    _holder(db)
    v = _pass(db)
    with pytest.raises(rules.RulesError, match="אינו פעיל"):
        rules.hold_entry(db, v.voucher_id)


def test_hold_blocked_after_expiry(db):
    _holder(db)
    v = _active_pass(db, entries=2)
    v.valid_until = date.today() - timedelta(days=1)
    db.commit()
    with pytest.raises(rules.RulesError, match="פג תוקף"):
        rules.hold_entry(db, v.voucher_id)


def test_legacy_mark_used_on_single_voucher(db):
    """mark_used on a 1-entry voucher = consume the only entry → used."""
    _holder(db)
    v = rules.create_voucher(db, MOBILE, "יחיד", FUTURE)
    rules.first_send(db, v.voucher_id, "WA")
    v = rules.mark_used(db, v.voucher_id)
    assert v.status == "used"
    assert v.entries_consumed == 1


def test_consume_regenerates_pdf_with_dates(db):
    """After a treatment is consumed the saved PDF is re-rendered and lists it."""
    import fitz
    from pathlib import Path
    _holder(db)
    v = _active_pass(db, entries=3)
    pdf = Path(v.pdf_path)
    before = pdf.stat().st_mtime_ns
    text_before = "".join(p.get_text() for p in fitz.open(str(pdf)))

    e = rules.hold_entry(db, v.voucher_id, datetime(2026, 10, 1, 10, 30))
    rules.consume_entry(db, v.voucher_id, e.id)
    rules.consume_direct(db, v.voucher_id)

    assert pdf.stat().st_mtime_ns > before
    text_after = "".join(p.get_text() for p in fitz.open(str(pdf)))
    assert "01/10/2026 10:30" in text_after          # scheduled time of entry 1
    assert "01/10/2026 10:30" not in text_before
    assert "2. " in text_after                        # walk-in entry listed too


# ── Holder lock (decision 6a) ─────────────────────────────────────────────────

def test_holder_locked_on_first_consumed_entry(db):
    _holder(db)
    v = _active_pass(db, entries=5)
    assert rules.can_edit_holder(db, MOBILE) is True
    e = rules.hold_entry(db, v.voucher_id)
    assert rules.can_edit_holder(db, MOBILE) is True     # a hold does not lock
    rules.consume_entry(db, v.voucher_id, e.id)
    assert rules.can_edit_holder(db, MOBILE) is False
    with pytest.raises(rules.RulesError):
        rules.update_holder(db, MOBILE, "שם אחר", None)


# ── Migration ─────────────────────────────────────────────────────────────────

def test_migrate_legacy_db():
    """
    A V1 database (status 'sent', no ticket columns, no entries table)
    migrates in place: columns added, sent → active, used gets one entry.
    """
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    with engine.connect() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE holders (mobile TEXT PRIMARY KEY, name TEXT NOT NULL,
                email TEXT, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)""")
        conn.exec_driver_sql("""
            CREATE TABLE vouchers (voucher_id TEXT PRIMARY KEY, mobile TEXT NOT NULL,
                sequence INTEGER NOT NULL, voucher_type TEXT NOT NULL, valid_until DATE NOT NULL,
                issued_at DATETIME NOT NULL, first_sent_at DATETIME, status TEXT NOT NULL,
                display_name TEXT, receipt_number TEXT, receipt_date DATE, notes TEXT,
                qr_path TEXT, pdf_path TEXT, holder_name TEXT, holder_mobile TEXT, holder_email TEXT)""")
        conn.exec_driver_sql("""
            CREATE TABLE sendings (id INTEGER PRIMARY KEY AUTOINCREMENT, voucher_id TEXT NOT NULL,
                sent_at DATETIME NOT NULL, sent_via TEXT NOT NULL, note TEXT, performed_by TEXT)""")
        conn.exec_driver_sql(
            "INSERT INTO vouchers (voucher_id, mobile, sequence, voucher_type, valid_until, "
            "issued_at, first_sent_at, status) VALUES "
            "('0541234567-001','0541234567',1,'יחיד','2027-01-01','2026-01-01 10:00:00','2026-01-02 10:00:00','sent'),"
            "('0541234567-002','0541234567',2,'זוגי','2027-01-01','2026-01-01 10:00:00','2026-01-02 10:00:00','used'),"
            "('0541234567-003','0541234567',3,'יחיד','2027-01-01','2026-01-01 10:00:00',NULL,'draft')")
        conn.commit()

    Base.metadata.create_all(engine)     # adds the entries table
    _migrate(engine)

    Session = sessionmaker(bind=engine)
    s = Session()
    v1 = s.get(Voucher, "0541234567-001")
    v2 = s.get(Voucher, "0541234567-002")
    v3 = s.get(Voucher, "0541234567-003")
    assert v1.status == "active" and v1.kind == "VOUCHER" and v1.entries_total == 1
    assert v1.payment_method == "manual" and v1.paid_at is not None
    assert v2.status == "used" and v2.entries_consumed == 1
    assert v3.status == "draft" and v3.payment_method is None
    # Idempotent: running again changes nothing
    _migrate(engine)
    s.expire_all()
    assert s.get(Voucher, "0541234567-002").entries_consumed == 1
    s.close()


# ── API level ─────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    from app import auth as _auth
    _auth.init_auth()
    with TestClient(app) as c:
        c.post("/auth/login/pin", data={"pin": "122156"})
        yield c
    app.dependency_overrides.clear()
    _auth._sessions.clear()


def test_api_pass_full_flow(client):
    client.post("/holders", json={"mobile": MOBILE, "name": "שרה כהן"})
    r = client.post("/vouchers", json={
        "mobile": MOBILE, "voucher_type": "יחיד", "valid_until": str(FUTURE),
        "kind": "PASS", "entries_total": 2, "list_price": 500, "discount": 50,
    })
    assert r.status_code == 201, r.text
    v = r.json()
    vid = v["voucher_id"]
    assert v["kind"] == "PASS" and v["price"] == 450

    # Ticket send blocked before payment
    r = client.put(f"/vouchers/{vid}/send", json={"sent_via": "WA"})
    assert r.status_code == 409

    r = client.put(f"/vouchers/{vid}/request-payment", json={"sent_via": "WA"})
    assert r.status_code == 200 and r.json()["status"] == "awaiting_payment"

    r = client.get(f"/vouchers/{vid}/payment-text")
    assert "450" in r.json()["text"]

    r = client.put(f"/vouchers/{vid}/mark-paid", json={"method": "BIT"})
    assert r.status_code == 200 and r.json()["status"] == "paid"

    r = client.put(f"/vouchers/{vid}/send", json={"sent_via": "WA"})
    assert r.status_code == 200 and r.json()["status"] == "active"

    r = client.post(f"/vouchers/{vid}/entries/hold",
                    json={"scheduled_for": "2026-10-01T10:00:00", "note": "x"})
    assert r.status_code == 201, r.text
    eid = r.json()["id"]

    r = client.put(f"/vouchers/{vid}/entries/{eid}/consume", json={})
    assert r.status_code == 200 and r.json()["status"] == "consumed"

    r = client.post(f"/vouchers/{vid}/entries/consume", json={"note": "walk-in"})
    assert r.status_code == 200 and r.json()["status"] == "used"

    r = client.get(f"/vouchers/{vid}/entries")
    assert len(r.json()) == 2

    r = client.get(f"/vouchers/{vid}")
    assert r.json()["entries_consumed"] == 2
    assert r.json()["entries_available"] == 0


def test_api_list_filter_by_kind(client):
    client.post("/holders", json={"mobile": MOBILE, "name": "שרה כהן"})
    client.post("/vouchers", json={"mobile": MOBILE, "voucher_type": "יחיד",
                                   "valid_until": str(FUTURE)})
    client.post("/vouchers", json={"mobile": MOBILE, "voucher_type": "יחיד",
                                   "valid_until": str(FUTURE), "kind": "PASS",
                                   "entries_total": 5})
    assert len(client.get("/vouchers?kind=PASS").json()) == 1
    assert len(client.get("/vouchers?kind=VOUCHER").json()) == 1


def test_api_invalid_kind_rejected(client):
    client.post("/holders", json={"mobile": MOBILE, "name": "שרה כהן"})
    r = client.post("/vouchers", json={"mobile": MOBILE, "voucher_type": "יחיד",
                                       "valid_until": str(FUTURE), "kind": "OTHER"})
    assert r.status_code == 422


def test_pages_render(client):
    """The rewritten templates render for every status without errors."""
    client.post("/holders", json={"mobile": MOBILE, "name": "שרה כהן"})
    r = client.post("/vouchers", json={"mobile": MOBILE, "voucher_type": "יחיד",
                                       "valid_until": str(FUTURE), "kind": "PASS",
                                       "entries_total": 3, "price": 900})
    vid = r.json()["voucher_id"]

    def all_pages_ok():
        for url in (f"/vouchers/{vid}/view", "/all-vouchers/view",
                    f"/holders/{MOBILE}/view", "/report/view", "/home",
                    "/vouchers/new/view?kind=PASS&mobile=" + MOBILE,
                    "/settings/view", "/orderers/view"):
            r = client.get(url)
            assert r.status_code == 200, (url, r.status_code)

    all_pages_ok()                                        # draft
    client.put(f"/vouchers/{vid}/request-payment", json={"sent_via": "WA"})
    all_pages_ok()                                        # awaiting_payment
    client.put(f"/vouchers/{vid}/mark-paid", json={"method": "CASH"})
    all_pages_ok()                                        # paid
    client.put(f"/vouchers/{vid}/send", json={"sent_via": "WA"})
    client.post(f"/vouchers/{vid}/entries/hold", json={})
    all_pages_ok()                                        # active with a hold
    r = client.get(f"/vouchers/{vid}/pdf")                # pass PDF renders
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"


def test_settings_form_round_trip(client, tmp_path, monkeypatch):
    """Price list + terms saved through the form are read back by the new-ticket page."""
    from app import settings as _settings
    monkeypatch.setattr(_settings, "_SETTINGS_PATH", tmp_path / "settings.json")
    r = client.post("/form/settings", data={
        "default_terms": "תנאים לבדיקה",
        "default_location": "תל אביב",
        "pl_kind": ["PASS", "VOUCHER"],
        "pl_type": ["יחיד", "זוגי"],
        "pl_entries": ["5", "1"],
        "pl_price": ["1000", "400"],
    }, follow_redirects=False)
    assert r.status_code == 303 and "danger" not in r.headers["location"]
    assert _settings.lookup_price("PASS", "יחיד", 5) == 1000
    assert _settings.lookup_price("VOUCHER", "זוגי", 1) == 400
    assert _settings.lookup_price("PASS", "זוגי", 5) is None
    assert _settings.get_default_terms() == "תנאים לבדיקה"
    r = client.get("/vouchers/new/view")
    assert "תנאים לבדיקה" in r.text
