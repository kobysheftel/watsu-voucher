"""
Auth router — multi-user login, WebAuthn registration/authentication.

Routes:
  GET  /auth/login                        → login page (biometric + PIN)
  POST /auth/login/pin                    → PIN login (identifies user by PIN)
  GET  /auth/logout                       → clear session, redirect to login
  GET  /auth/register-biometric           → biometric registration page (after PIN login)
  POST /auth/webauthn/register/options    → generate registration options (per user)
  POST /auth/webauthn/register/verify     → verify registration response (per user)
  POST /auth/webauthn/login/options       → generate authentication options (all users)
  POST /auth/webauthn/login/verify        → verify authentication response (identifies user)
"""

import base64
import json
import secrets
from typing import Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import auth

# py_webauthn imports
from webauthn import (
    generate_registration_options,
    verify_registration_response,
    generate_authentication_options,
    verify_authentication_response,
    options_to_json,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    ResidentKeyRequirement,
    UserVerificationRequirement,
    PublicKeyCredentialDescriptor,
)
from webauthn.helpers.cose import COSEAlgorithmIdentifier

router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory="templates")

# --- WebAuthn Configuration ---
# RP = Relying Party (this app)
RP_ID = "vouchers.soulwaves.org"
RP_NAME = "Watsu Vouchers"
ORIGIN = "https://vouchers.soulwaves.org"


# ── GET: Login page ──────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    """Show login page with biometric + PIN fallback."""
    # If already authenticated, redirect to home
    if auth.is_authenticated(request):
        return RedirectResponse(url="/all-vouchers/view", status_code=303)

    # Check if any user has biometric credentials
    all_creds = auth.get_all_webauthn_credentials()
    has_biometric = len(all_creds) > 0

    return templates.TemplateResponse("login.html", {
        "request": request,
        "has_biometric": has_biometric,
        "error": request.query_params.get("error"),
    })


# ── POST: PIN login ──────────────────────────────────────────────────────────

@router.post("/login/pin")
def login_pin(request: Request, pin: str = Form(...)):
    """Verify PIN — identifies which user by matching the PIN."""
    username = auth.check_pin(pin)
    if username:
        response = RedirectResponse(url="/all-vouchers/view", status_code=303)
        auth.create_session(response, username)
        return response
    return RedirectResponse(url="/auth/login?error=pin", status_code=303)


# ── GET: Biometric registration page (after PIN login) ────────────────────────

@router.get("/register-biometric", response_class=HTMLResponse)
def register_biometric_page(request: Request):
    """Page to register biometric credential for the current user."""
    if not auth.is_authenticated(request):
        return RedirectResponse(url="/auth/login", status_code=303)

    username = auth.get_current_user(request)
    return templates.TemplateResponse("setup.html", {
        "request": request,
        "step": "biometric",
        "username": username,
    })


# ── GET: Setup redirect (no more self-registration) ──────────────────────────

@router.get("/setup", response_class=HTMLResponse)
def setup_redirect(request: Request):
    """Setup is no longer needed — redirect to login."""
    return RedirectResponse(url="/auth/login", status_code=303)


@router.post("/setup")
def setup_post_redirect(request: Request):
    """Setup POST is no longer needed — redirect to login."""
    return RedirectResponse(url="/auth/login", status_code=303)


# ── GET: Logout ───────────────────────────────────────────────────────────────

@router.get("/logout")
def logout_route(request: Request):
    """Clear session and redirect to login."""
    response = RedirectResponse(url="/auth/login", status_code=303)
    auth.logout(request, response)
    return response


# ── WebAuthn: Registration Options ────────────────────────────────────────────

@router.post("/webauthn/register/options")
def webauthn_register_options(request: Request):
    """Generate WebAuthn registration options for the current user."""
    if not auth.is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    username = auth.get_current_user(request)
    if not username:
        return JSONResponse({"error": "No user found"}, status_code=401)

    # Get existing credential IDs for this user only
    existing = auth.get_webauthn_credentials_for_user(username)
    exclude_credentials = [
        PublicKeyCredentialDescriptor(id=base64.urlsafe_b64decode(c["credential_id"] + "=="))
        for c in existing
    ]

    options = generate_registration_options(
        rp_id=RP_ID,
        rp_name=RP_NAME,
        user_id=username.encode("utf-8"),
        user_name=username,
        user_display_name=username,
        exclude_credentials=exclude_credentials,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.DISCOURAGED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        supported_pub_key_algs=[
            COSEAlgorithmIdentifier.ECDSA_SHA_256,
            COSEAlgorithmIdentifier.RSASSA_PKCS1_v1_5_SHA_256,
        ],
    )

    # Save challenge in the session (authenticated user)
    challenge_b64 = base64.urlsafe_b64encode(options.challenge).decode().rstrip("=")
    auth.save_session_challenge(request, challenge_b64)

    return JSONResponse(json.loads(options_to_json(options)))


# ── WebAuthn: Registration Verify ─────────────────────────────────────────────

@router.post("/webauthn/register/verify")
async def webauthn_register_verify(request: Request):
    """Verify WebAuthn registration response and save credential for current user."""
    if not auth.is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    username = auth.get_current_user(request)
    if not username:
        return JSONResponse({"error": "No user found"}, status_code=401)

    body = await request.json()
    challenge_b64 = auth.get_session_challenge(request)
    if not challenge_b64:
        return JSONResponse({"error": "No challenge found"}, status_code=400)

    try:
        # Pad base64 if needed
        padded = challenge_b64 + "=" * (4 - len(challenge_b64) % 4)
        expected_challenge = base64.urlsafe_b64decode(padded)

        verification = verify_registration_response(
            credential=body,
            expected_challenge=expected_challenge,
            expected_origin=ORIGIN,
            expected_rp_id=RP_ID,
        )

        # Save the credential for this user
        credential_data = {
            "credential_id": base64.urlsafe_b64encode(
                verification.credential_id
            ).decode().rstrip("="),
            "public_key": base64.urlsafe_b64encode(
                verification.credential_public_key
            ).decode().rstrip("="),
            "sign_count": verification.sign_count,
        }
        auth.save_webauthn_credential(username, credential_data)

        return JSONResponse({"status": "ok"})

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# ── WebAuthn: Authentication Options ──────────────────────────────────────────

@router.post("/webauthn/login/options")
def webauthn_login_options(request: Request):
    """Generate WebAuthn authentication options (all users' credentials)."""
    all_creds = auth.get_all_webauthn_credentials()
    if not all_creds:
        return JSONResponse({"error": "No credentials registered"}, status_code=400)

    allow_credentials = [
        PublicKeyCredentialDescriptor(
            id=base64.urlsafe_b64decode(cred["credential_id"] + "==")
        )
        for _, cred in all_creds
    ]

    options = generate_authentication_options(
        rp_id=RP_ID,
        allow_credentials=allow_credentials,
        user_verification=UserVerificationRequirement.PREFERRED,
    )

    # Save challenge in pending store (no session yet — user is logging in)
    challenge_b64 = base64.urlsafe_b64encode(options.challenge).decode().rstrip("=")
    token = auth.save_challenge(challenge_b64)

    # Return options + challenge token for verification
    opts_json = json.loads(options_to_json(options))
    opts_json["_challenge_token"] = token
    return JSONResponse(opts_json)


# ── WebAuthn: Authentication Verify ───────────────────────────────────────────

@router.post("/webauthn/login/verify")
async def webauthn_login_verify(request: Request):
    """Verify WebAuthn authentication response and create session for matched user."""
    body = await request.json()

    # Retrieve challenge using token
    challenge_token = body.pop("_challenge_token", None)
    if not challenge_token:
        return JSONResponse({"error": "No challenge token"}, status_code=400)

    challenge_b64 = auth.get_challenge(challenge_token)
    if not challenge_b64:
        return JSONResponse({"error": "Challenge expired or not found"}, status_code=400)

    # Find which user owns this credential
    credential_id_b64 = body.get("id", "")
    all_creds = auth.get_all_webauthn_credentials()

    matched_username = None
    matched_cred = None
    for username, cred in all_creds:
        if cred["credential_id"] == credential_id_b64:
            matched_username = username
            matched_cred = cred
            break

    if not matched_cred:
        return JSONResponse({"error": "Unknown credential"}, status_code=400)

    try:
        padded = challenge_b64 + "=" * (4 - len(challenge_b64) % 4)
        expected_challenge = base64.urlsafe_b64decode(padded)

        padded_pk = matched_cred["public_key"] + "=" * (4 - len(matched_cred["public_key"]) % 4)

        verification = verify_authentication_response(
            credential=body,
            expected_challenge=expected_challenge,
            expected_origin=ORIGIN,
            expected_rp_id=RP_ID,
            credential_public_key=base64.urlsafe_b64decode(padded_pk),
            credential_current_sign_count=matched_cred["sign_count"],
        )

        # Update sign count in auth.json
        data = auth._load_auth_data()
        user_creds = data.get("users", {}).get(matched_username, {}).get("webauthn_credentials", [])
        for c in user_creds:
            if c["credential_id"] == credential_id_b64:
                c["sign_count"] = verification.new_sign_count
                break
        auth._save_auth_data(data)

        # Create session for the matched user
        response = JSONResponse({"status": "ok", "username": matched_username})
        auth.create_session(response, matched_username)
        return response

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)
