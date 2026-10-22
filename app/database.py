# Database setup — SQLAlchemy engine, session factory, startup migration
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = "sqlite:///./vouchers.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass

def init_db():
    """Create all tables on startup, then apply the lightweight migration."""
    from app import models  # noqa: F401 — import triggers table registration
    Base.metadata.create_all(bind=engine)
    _migrate(engine)


def _migrate(target_engine=None):
    """
    Lightweight, idempotent column migration for SQLite.

    Base.metadata.create_all() creates missing tables but never adds new
    columns to an existing table. This adds any new columns that the current
    models define but the on-disk DB is missing, then applies the one-off
    data fixes of the phase A ticket generalisation (2026-09-13):
      - status 'sent' → 'active'
      - legacy active/used tickets get payment_method='manual'
      - every used ticket gets one consumed entry (so counters add up)
    Safe to run on every startup — each step checks before it writes.
    """
    eng = target_engine or engine

    # New columns added over time: table -> {column: SQL type/default}
    new_columns = {
        "vouchers": {
            "greeting":       "TEXT",
            "image_file":     "TEXT",
            "location":       "TEXT",
            # phase A — ticket generalisation
            "kind":           "TEXT NOT NULL DEFAULT 'VOUCHER'",
            "entries_total":  "INTEGER NOT NULL DEFAULT 1",
            "list_price":     "REAL",
            "discount":       "REAL",
            "price":          "REAL",
            "terms":          "TEXT",
            "payment_method": "TEXT",
            "payment_url":    "TEXT",
            "gi_document_id": "TEXT",
            "paid_at":        "DATETIME",
            # 2026-10-22 — English tickets
            "language":       "TEXT NOT NULL DEFAULT 'he'",
        },
        "sendings": {
            "kind":           "TEXT NOT NULL DEFAULT 'TICKET'",
        },
    }

    with eng.connect() as conn:
        added_payment_method = False
        for table, columns in new_columns.items():
            existing = {
                row[1]  # row = (cid, name, type, notnull, dflt_value, pk)
                for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")
            }
            for col, col_type in columns.items():
                if col not in existing:
                    conn.exec_driver_sql(
                        f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"
                    )
                    if table == "vouchers" and col == "payment_method":
                        added_payment_method = True

        # Legacy status: 'sent' (V1) means the ticket is out → 'active'
        conn.exec_driver_sql(
            "UPDATE vouchers SET status = 'active' WHERE status = 'sent'"
        )

        # Legacy tickets were paid by hand before the app tracked payment
        if added_payment_method:
            conn.exec_driver_sql(
                "UPDATE vouchers SET payment_method = 'manual', "
                "paid_at = COALESCE(first_sent_at, issued_at) "
                "WHERE status IN ('active', 'used') AND payment_method IS NULL"
            )

        # Back-fill: every used ticket must have at least one consumed entry
        used_without_entries = conn.exec_driver_sql(
            "SELECT v.voucher_id, COALESCE(v.first_sent_at, v.issued_at) "
            "FROM vouchers v "
            "WHERE v.status = 'used' "
            "AND NOT EXISTS (SELECT 1 FROM entries e WHERE e.voucher_id = v.voucher_id)"
        ).fetchall()
        for voucher_id, when in used_without_entries:
            conn.exec_driver_sql(
                "INSERT INTO entries (voucher_id, seq, status, consumed_at, note) "
                "VALUES (?, 1, 'consumed', ?, 'הוסב מגרסה 1')",
                (voucher_id, when),
            )

        conn.commit()

def get_db():
    """FastAPI dependency: yield a DB session, close when done."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
