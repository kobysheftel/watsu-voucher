"""
API endpoint tests — uses in-memory SQLite, never touches the real DB.
Run with: python -m pytest tests/test_api.py -v
"""

import pytest
from datetime import date, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool   # keeps all connections on the same in-memory DB

from main import app
from app.database import Base, get_db

FUTURE = str(date.today() + timedelta(days=180))


# ── In-memory DB override ─────────────────────────────────────────────────────

@pytest.fixture
def client():
    """TestClient with a fresh in-memory DB for every test.
    StaticPool ensures all connections share the same in-memory database,
    so tables created here are visible to the request-handling sessions.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_holder(client, mobile="0541234567", name="שרה כהן", email="sara@test.com"):
    r = client.post("/holders", json={"mobile": mobile, "name": name, "email": email})
    assert r.status_code == 200, r.text
    return r.json()

def make_voucher(client, mobile="0541234567"):
    r = client.post("/vouchers", json={
        "mobile": mobile,
        "voucher_type": "יחיד",
        "valid_until": FUTURE,
    })
    assert r.status_code == 201, r.text
    return r.json()


# ── Holder endpoints ──────────────────────────────────────────────────────────

def test_create_holder(client):
    h = make_holder(client)
    assert h["mobile"] == "0541234567"
    assert h["name"]   == "שרה כהן"
    assert h["can_edit"] is True

def test_get_existing_holder_returns_same(client):
    make_holder(client)
    r = client.post("/holders", json={"mobile": "0541234567", "name": "שם אחר"})
    assert r.json()["name"] == "שרה כהן"   # original unchanged

def test_get_holder_with_vouchers(client):
    make_holder(client)
    make_voucher(client)
    r = client.get("/holders/0541234567")
    assert r.status_code == 200
    assert len(r.json()["vouchers"]) == 1

def test_get_holder_not_found(client):
    r = client.get("/holders/0599999999")
    assert r.status_code == 404

def test_update_holder(client):
    make_holder(client)
    r = client.put("/holders/0541234567", json={"name": "שרה לוי"})
    assert r.status_code == 200
    assert r.json()["name"] == "שרה לוי"

def test_update_holder_blocked_when_used(client):
    make_holder(client)
    v = make_voucher(client)
    vid = v["voucher_id"]
    client.put(f"/vouchers/{vid}/send", json={"sent_via": "WA"})
    client.put(f"/vouchers/{vid}/use")
    r = client.put("/holders/0541234567", json={"name": "שם חדש"})
    assert r.status_code == 409

def test_invalid_mobile_rejected(client):
    r = client.post("/holders", json={"mobile": "123", "name": "test"})
    assert r.status_code == 422


# ── Voucher CRUD ──────────────────────────────────────────────────────────────

def test_create_voucher(client):
    make_holder(client)
    v = make_voucher(client)
    assert v["voucher_id"] == "0541234567-001"
    assert v["status"]     == "draft"

def test_create_voucher_no_holder(client):
    r = client.post("/vouchers", json={
        "mobile": "0599999999",
        "voucher_type": "יחיד",
        "valid_until": FUTURE,
    })
    assert r.status_code in (422, 422)   # HTTP_422_UNPROCESSABLE_CONTENT

def test_list_vouchers_empty(client):
    r = client.get("/vouchers")
    assert r.status_code == 200
    assert r.json() == []

def test_list_vouchers(client):
    make_holder(client)
    make_voucher(client)
    r = client.get("/vouchers")
    assert len(r.json()) == 1

def test_list_filter_by_status(client):
    make_holder(client)
    v = make_voucher(client)
    client.put(f"/vouchers/{v['voucher_id']}/send", json={"sent_via": "WA"})

    r = client.get("/vouchers?status=sent")
    assert len(r.json()) == 1

    r = client.get("/vouchers?status=draft")
    assert len(r.json()) == 0

def test_get_voucher(client):
    make_holder(client)
    v = make_voucher(client)
    r = client.get(f"/vouchers/{v['voucher_id']}")
    assert r.status_code == 200
    assert r.json()["voucher_id"] == v["voucher_id"]

def test_get_voucher_not_found(client):
    r = client.get("/vouchers/FAKE-999")
    assert r.status_code == 404

def test_update_receipt(client):
    make_holder(client)
    v = make_voucher(client)
    r = client.put(f"/vouchers/{v['voucher_id']}", json={
        "receipt_number": "IL-2026-001",
    })
    assert r.status_code == 200
    assert r.json()["receipt_number"] == "IL-2026-001"

def test_update_receipt_blocked_when_used(client):
    make_holder(client)
    v = make_voucher(client)
    vid = v["voucher_id"]
    client.put(f"/vouchers/{vid}/send", json={"sent_via": "WA"})
    client.put(f"/vouchers/{vid}/use")
    r = client.put(f"/vouchers/{vid}", json={"notes": "לא אמור לעבוד"})
    assert r.status_code == 409


# ── Send / Resend / Use ───────────────────────────────────────────────────────

def test_first_send(client):
    make_holder(client)
    v = make_voucher(client)
    r = client.put(f"/vouchers/{v['voucher_id']}/send", json={"sent_via": "WA"})
    assert r.status_code == 200
    data = r.json()
    assert data["status"]       == "sent"
    assert data["holder_name"]  == "שרה כהן"    # cemented
    assert data["is_cemented"]  is True

def test_resend(client):
    make_holder(client)
    v = make_voucher(client)
    vid = v["voucher_id"]
    client.put(f"/vouchers/{vid}/send",   json={"sent_via": "WA"})
    r = client.put(f"/vouchers/{vid}/resend", json={"sent_via": "EMAIL"})
    assert r.status_code == 200
    assert r.json()["status"] == "sent"

def test_mark_used(client):
    make_holder(client)
    v = make_voucher(client)
    vid = v["voucher_id"]
    client.put(f"/vouchers/{vid}/send", json={"sent_via": "WA"})
    r = client.put(f"/vouchers/{vid}/use")
    assert r.status_code == 200
    assert r.json()["status"]    == "used"
    assert r.json()["is_frozen"] is True

def test_resend_after_used_blocked(client):
    make_holder(client)
    v = make_voucher(client)
    vid = v["voucher_id"]
    client.put(f"/vouchers/{vid}/send",   json={"sent_via": "WA"})
    client.put(f"/vouchers/{vid}/use")
    r = client.put(f"/vouchers/{vid}/resend", json={"sent_via": "WA"})
    assert r.status_code == 409


# ── Sending history ───────────────────────────────────────────────────────────

def test_sendings_history(client):
    make_holder(client)
    v = make_voucher(client)
    vid = v["voucher_id"]
    client.put(f"/vouchers/{vid}/send",   json={"sent_via": "WA",    "note": "first"})
    client.put(f"/vouchers/{vid}/resend", json={"sent_via": "EMAIL", "note": "second"})
    client.put(f"/vouchers/{vid}/resend", json={"sent_via": "PRINT"})

    r = client.get(f"/vouchers/{vid}/sendings")
    assert r.status_code == 200
    sendings = r.json()
    assert len(sendings) == 3
    vias = {s["sent_via"] for s in sendings}
    assert vias == {"WA", "EMAIL", "PRINT"}

def test_sending_display_labels(client):
    make_holder(client)
    v = make_voucher(client)
    vid = v["voucher_id"]
    client.put(f"/vouchers/{vid}/send", json={"sent_via": "WA"})

    r = client.get(f"/vouchers/{vid}/sendings")
    s = r.json()[0]
    assert s["sent_via_display"] == "📱 וואטסאפ"


# ── Search & Report ───────────────────────────────────────────────────────────

def test_search_by_name(client):
    make_holder(client)
    make_voucher(client)
    r = client.get("/search?q=שרה")
    assert r.status_code == 200
    assert len(r.json()) == 1

def test_search_no_results(client):
    make_holder(client)
    r = client.get("/search?q=nomatch999")
    assert r.json() == []

def test_report_json(client):
    make_holder(client)
    make_voucher(client)
    r = client.get("/report")
    assert r.status_code == 200
    assert r.json()["count"] == 1

def test_report_csv(client):
    make_holder(client)
    make_voucher(client)
    r = client.get("/report?fmt=csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "שרה כהן" in r.text

def test_home_data(client):
    make_holder(client)
    make_voucher(client)
    r = client.get("/home/data")
    assert r.status_code == 200
    stats = r.json()["stats"]
    assert stats["total"]   == 1
    assert stats["draft"]   == 1
    assert stats["holders"] == 1
