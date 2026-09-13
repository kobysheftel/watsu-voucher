"""
App settings — small persistent key/value store (config/settings.json).

Currently holds the default voucher location/venue. Kept separate from the
sensitive Fernet key in config/secret.key. config/ is git-ignored but is
backed up by backup.bat, so the chosen default survives across runs.

All access goes through this module so callers never touch the file directly.
"""

import json
from pathlib import Path

_SETTINGS_PATH = Path("config/settings.json")

# Built-in fallback default location (used until the user changes it).
_DEFAULT_LOCATION = "הוד השרון"


def _read() -> dict:
    """Read the settings dict, bootstrapping the file on first use."""
    if not _SETTINGS_PATH.exists():
        _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _write({"default_location": _DEFAULT_LOCATION})
    return json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))


def _write(data: dict) -> None:
    """Write the settings dict back to disk (UTF-8, pretty-printed)."""
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# Address that receives a "new voucher produced" e-mail on every first send.
# Empty string disables the notification.
_DEFAULT_NOTIFY_EMAIL = "kobysheftel@gmail.com"


def get_notify_email() -> str:
    """Return the notification recipient for new vouchers ('' = disabled)."""
    data = _read()
    if "notify_email" not in data:
        # Bootstrap the key so it is visible/editable in config/settings.json
        data["notify_email"] = _DEFAULT_NOTIFY_EMAIL
        _write(data)
    return (data.get("notify_email") or "").strip()


def get_default_location() -> str:
    """Return the current default location for new vouchers."""
    return _read().get("default_location") or _DEFAULT_LOCATION


def set_default_location(value: str) -> None:
    """Set the default location applied to future vouchers."""
    data = _read()
    data["default_location"] = (value or "").strip() or _DEFAULT_LOCATION
    _write(data)


# ── Terms text (phase A) ─────────────────────────────────────────────────────

# Placeholder terms — Koby / Avigal edit the real wording on the settings page.
_DEFAULT_TERMS = (
    "תיאום תור מראש עם אביגל: 050-4014696.\n"
    "ביטול או שינוי טיפול — עד 24 שעות מראש.\n"
    "בתוקף עד התאריך הנקוב בכרטיס."
)


def get_default_terms() -> str:
    """Return the default terms text copied onto every new ticket."""
    data = _read()
    if "default_terms" not in data:
        # Bootstrap the key so it is visible/editable in config/settings.json
        data["default_terms"] = _DEFAULT_TERMS
        _write(data)
    return data.get("default_terms") or ""


def set_default_terms(value: str) -> None:
    """Set the default terms text applied to future tickets."""
    data = _read()
    data["default_terms"] = (value or "").strip()
    _write(data)


# ── Price list (phase A) ─────────────────────────────────────────────────────
#
# Each row: {"kind": "VOUCHER"|"PASS", "voucher_type": "יחיד"|"זוגי",
#            "entries": int, "price": float}
# The new-ticket form looks up (kind, voucher_type, entries) to prefill the
# list price; the final price may then be discounted per ticket.

def get_price_list() -> list[dict]:
    """Return the price list rows (empty list until defined)."""
    data = _read()
    if "price_list" not in data:
        data["price_list"] = []
        _write(data)
    return list(data.get("price_list") or [])


def set_price_list(rows: list[dict]) -> None:
    """
    Replace the price list. Rows are validated and normalised:
    kind must be VOUCHER/PASS, entries a positive int, price a non-negative
    number. Invalid rows raise ValueError so the caller can show a message.
    """
    clean = []
    for row in rows:
        kind = str(row.get("kind", "")).strip().upper()
        vtype = str(row.get("voucher_type", "")).strip()
        try:
            entries = int(row.get("entries", 0))
            price = float(row.get("price", 0))
        except (TypeError, ValueError):
            raise ValueError("מחירון: כמות טיפולים ומחיר חייבים להיות מספרים")
        if kind not in ("VOUCHER", "PASS"):
            raise ValueError(f"מחירון: סוג כרטיס לא תקין: {kind}")
        if entries <= 0:
            raise ValueError("מחירון: כמות טיפולים חייבת להיות גדולה מאפס")
        if price < 0:
            raise ValueError("מחירון: מחיר לא יכול להיות שלילי")
        clean.append({"kind": kind, "voucher_type": vtype,
                      "entries": entries, "price": price})
    data = _read()
    data["price_list"] = clean
    _write(data)


def lookup_price(kind: str, voucher_type: str, entries: int) -> float | None:
    """Return the list price for a product, or None if not in the price list."""
    for row in get_price_list():
        if (row["kind"] == kind and row["voucher_type"] == voucher_type
                and int(row["entries"]) == int(entries)):
            return float(row["price"])
    return None
