# Database setup — fully implemented in Step 2
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = "sqlite:///./vouchers.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass

def init_db():
    """Create all tables on startup. Implemented fully in Step 2."""
    from app import models  # noqa: F401 — import triggers table registration
    Base.metadata.create_all(bind=engine)
    _migrate()


def _migrate():
    """
    Lightweight, idempotent column migration for SQLite.

    Base.metadata.create_all() creates missing tables but never adds new
    columns to an existing table. This adds any new voucher columns that the
    current model defines but the on-disk DB is missing.
    """
    # New columns added over time: name -> SQL type
    new_columns = {
        "greeting":   "TEXT",
        "image_file": "TEXT",
        "location":   "TEXT",
    }
    with engine.connect() as conn:
        # Existing column names on the vouchers table
        existing = {
            row[1]  # row = (cid, name, type, notnull, dflt_value, pk)
            for row in conn.exec_driver_sql("PRAGMA table_info(vouchers)")
        }
        for col, col_type in new_columns.items():
            if col not in existing:
                conn.exec_driver_sql(
                    f"ALTER TABLE vouchers ADD COLUMN {col} {col_type}"
                )
        conn.commit()

def get_db():
    """FastAPI dependency: yield a DB session, close when done."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
