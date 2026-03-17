"""Shared utilities."""
from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return current UTC time as a naive datetime (SQLite-compatible)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
