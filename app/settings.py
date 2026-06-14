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


def get_default_location() -> str:
    """Return the current default location for new vouchers."""
    return _read().get("default_location") or _DEFAULT_LOCATION


def set_default_location(value: str) -> None:
    """Set the default location applied to future vouchers."""
    data = _read()
    data["default_location"] = (value or "").strip() or _DEFAULT_LOCATION
    _write(data)
