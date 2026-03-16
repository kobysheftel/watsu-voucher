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

def get_db():
    """FastAPI dependency: yield a DB session, close when done."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
