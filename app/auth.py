"""
Authentication module — Multi-user PIN + WebAuthn biometric auth.

Two pre-configured users: Koby and Avigal.
Stores credentials in config/auth.json (git-ignored).
Sessions are cookie-based with 15-minute sliding timeout.
No self-registration — users are hardcoded.
"""

import hashlib
import json
import secrets
import time
from pathlib import Path
from typing import Optional

from fastapi import Request, Response

# --- Constants ---
AUTH_FILE = Path("config/auth.json")
SESSION_MAX_AGE = 15 * 60  # 15 minutes inactivity timeout
SESSION_COOKIE_NAME = "voucher_session"

# Pre-configured users (PINs only used for initial seeding)
_SEED_USERS = {
    "Koby": "122156",
    "Avigal": "3004",
}


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


def init_auth() -> None:
    """
    Initialize auth.json with pre-configured users.
    Called on app startup. If file is missing or has old single-user format,
    creates a fresh file with both users' hashed PINs.
    """
    data = _load_auth_data()

    # Check if already in new multi-user format
    if "users" in data:
        return  # Already initialized

    # Create new multi-user structure (replaces any old single-user format)
    users = {}
    for name, pin in _SEED_USERS.items():
        users[name] = {
            "pin": hash_pin(pin),
            "webauthn_credentials": [],
        }

    _save_auth_data({"users": users})


def is_setup_complete() -> bool:
    """Always True — users are pre-configured, no setup needed."""
    return True


def check_pin(pin: str) -> Optional[str]:
    """
    Verify a PIN against all users' stored credentials.
    Returns the username if PIN matches, or None.
    """
    data = _load_auth_data()
    users = data.get("users", {})

    for username, user_data in users.items():
        if "pin" in user_data and verify_pin(pin, user_data["pin"]):
            return username

    return None


# --- WebAuthn Credential Storage (per user) ---

def get_webauthn_credentials_for_user(username: str) -> list:
    """Get stored WebAuthn credentials for a specific user."""
    data = _load_auth_data()
    user_data = data.get("users", {}).get(username, {})
    return user_data.get("webauthn_credentials", [])


def get_all_webauthn_credentials() -> list[tuple[str, dict]]:
    """
    Get ALL WebAuthn credentials from ALL users.
    Returns list of (username, credential_dict) tuples.
    Used for login — we don't know who's logging in yet.
    """
    data = _load_auth_data()
    result = []
    for username, user_data in data.get("users", {}).items():
        for cred in user_data.get("webauthn_credentials", []):
            result.append((username, cred))
    return result


def save_webauthn_credential(username: str, credential: dict) -> None:
    """Add a WebAuthn credential for a specific user."""
    data = _load_auth_data()
    users = data.get("users", {})
    if username not in users:
        return

    if "webauthn_credentials" not in users[username]:
        users[username]["webauthn_credentials"] = []
    users[username]["webauthn_credentials"].append(credential)
    _save_auth_data(data)


# --- Challenge Management (in-memory, per pending request) ---

# Temporary challenge store: challenge_token → {challenge, timestamp}
_pending_challenges: dict[str, dict] = {}


def save_challenge(challenge: str) -> str:
    """
    Save a WebAuthn challenge. Returns a token to retrieve it later.
    Challenges expire after 5 minutes.
    """
    # Clean up old challenges (> 5 min)
    now = time.time()
    expired = [k for k, v in _pending_challenges.items() if now - v["timestamp"] > 300]
    for k in expired:
        _pending_challenges.pop(k, None)

    token = secrets.token_urlsafe(16)
    _pending_challenges[token] = {"challenge": challenge, "timestamp": now}
    return token


def get_challenge(token: str) -> Optional[str]:
    """Retrieve and consume a pending challenge by token."""
    entry = _pending_challenges.pop(token, None)
    if not entry:
        return None
    # Check expiry (5 minutes)
    if time.time() - entry["timestamp"] > 300:
        return None
    return entry["challenge"]


# Legacy compatibility — store challenge in session for authenticated flows
def save_session_challenge(request: Request, challenge: str) -> None:
    """Save a challenge linked to the current session (for registration)."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id and session_id in _sessions:
        _sessions[session_id]["challenge"] = challenge


def get_session_challenge(request: Request) -> Optional[str]:
    """Get and clear the challenge from the current session."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_id or session_id not in _sessions:
        return None
    return _sessions[session_id].pop("challenge", None)


# --- Session Management (cookie-based, multi-user) ---

# Session store: session_id → {timestamp, username, challenge?}
_sessions: dict[str, dict] = {}


def create_session(response: Response, username: str) -> str:
    """Create a new session for a specific user and set the cookie."""
    session_id = secrets.token_urlsafe(32)
    _sessions[session_id] = {
        "timestamp": time.time(),
        "username": username,
    }
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
    session = _sessions.get(session_id)
    if session is None:
        return False
    # Check inactivity timeout
    if time.time() - session["timestamp"] > SESSION_MAX_AGE:
        _sessions.pop(session_id, None)
        return False
    # Refresh: reset the timer on activity
    session["timestamp"] = time.time()
    return True


def get_current_user(request: Request) -> Optional[str]:
    """Get the username of the currently authenticated user, or None."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_id:
        return None
    session = _sessions.get(session_id)
    if session is None:
        return None
    if time.time() - session["timestamp"] > SESSION_MAX_AGE:
        return None
    return session.get("username")


def logout(request: Request, response: Response) -> None:
    """Clear the specific user's session cookie and remove from store."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        _sessions.pop(session_id, None)
    response.delete_cookie(SESSION_COOKIE_NAME)
