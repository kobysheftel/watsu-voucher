"""
Authentication module — PIN + WebAuthn biometric auth for single-user admin.

Stores credentials in config/auth.json (git-ignored).
Sessions are cookie-based with 24-hour expiry.
"""

import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Optional

from fastapi import Request, Response

# --- Constants ---
AUTH_FILE = Path("config/auth.json")
SESSION_MAX_AGE = 15 * 60  # 15 minutes inactivity timeout
SESSION_COOKIE_NAME = "voucher_session"


# --- PIN Hashing ---

def _hash_pin(pin: str, salt: str) -> str:
    """Hash a PIN with salt using SHA-256."""
    return hashlib.sha256(f"{salt}:{pin}".encode()).hexdigest()


def hash_pin(pin: str) -> dict:
    """Create a salted hash for a PIN. Returns {salt, hash}."""
    salt = secrets.token_hex(16)
    return {"salt": salt, "hash": _hash_pin(pin, salt)}


def verify_pin(pin: str, pin_data: dict) -> bool:
    """Verify a PIN against stored salt+hash."""
    return _hash_pin(pin, pin_data["salt"]) == pin_data["hash"]


# --- Auth Data File (config/auth.json) ---

def _load_auth_data() -> dict:
    """Load auth data from config/auth.json. Returns empty dict if not found."""
    if AUTH_FILE.exists():
        return json.loads(AUTH_FILE.read_text(encoding="utf-8"))
    return {}


def _save_auth_data(data: dict) -> None:
    """Save auth data to config/auth.json."""
    AUTH_FILE.parent.mkdir(exist_ok=True)
    AUTH_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def is_setup_complete() -> bool:
    """Check if initial setup (PIN) has been done."""
    data = _load_auth_data()
    return "pin" in data


def save_pin(pin: str) -> None:
    """Hash and save a PIN to auth data."""
    data = _load_auth_data()
    data["pin"] = hash_pin(pin)
    _save_auth_data(data)


def check_pin(pin: str) -> bool:
    """Verify a PIN against stored credentials."""
    data = _load_auth_data()
    if "pin" not in data:
        return False
    return verify_pin(pin, data["pin"])


# --- WebAuthn Credential Storage ---

def get_webauthn_credentials() -> list:
    """Get stored WebAuthn credentials."""
    data = _load_auth_data()
    return data.get("webauthn_credentials", [])


def save_webauthn_credential(credential: dict) -> None:
    """Add a WebAuthn credential to storage."""
    data = _load_auth_data()
    if "webauthn_credentials" not in data:
        data["webauthn_credentials"] = []
    data["webauthn_credentials"].append(credential)
    _save_auth_data(data)


def get_webauthn_challenge() -> Optional[str]:
    """Get current WebAuthn challenge (for verification)."""
    data = _load_auth_data()
    return data.get("current_challenge")


def save_webauthn_challenge(challenge: str) -> None:
    """Save current WebAuthn challenge for verification."""
    data = _load_auth_data()
    data["current_challenge"] = challenge
    _save_auth_data(data)


def clear_webauthn_challenge() -> None:
    """Clear the current WebAuthn challenge after use."""
    data = _load_auth_data()
    data.pop("current_challenge", None)
    _save_auth_data(data)


# --- Session Management (cookie-based) ---

# In-memory session store (simple dict — single-user, single-process)
_sessions: dict[str, float] = {}


def create_session(response: Response) -> str:
    """Create a new session and set the cookie on the response."""
    session_id = secrets.token_urlsafe(32)
    _sessions[session_id] = time.time()
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=False,  # Allow HTTP for local dev/tests; HTTPS enforced by nginx
    )
    return session_id


def is_authenticated(request: Request) -> bool:
    """Check if the request has a valid session cookie.
    Uses sliding window — resets timeout on every activity."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_id:
        return False
    last_activity = _sessions.get(session_id)
    if last_activity is None:
        return False
    # Check inactivity timeout
    if time.time() - last_activity > SESSION_MAX_AGE:
        _sessions.pop(session_id, None)
        return False
    # Refresh: reset the timer on activity
    _sessions[session_id] = time.time()
    return True


def logout(response: Response) -> None:
    """Clear the session cookie and remove from store."""
    response.delete_cookie(SESSION_COOKIE_NAME)
    # Clean up all sessions (single user — just clear everything)
    _sessions.clear()
