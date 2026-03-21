"""
Auth router — login, setup, WebAuthn registration/authentication endpoints.

Routes:
  GET  /auth/login              → login page (biometric + PIN)
  POST /auth/login/pin          → PIN login
  GET  /auth/setup              → first-time setup page
  POST /auth/setup              → save PIN + redirect to biometric registration
  GET  /auth/logout             → clear session, redirect to login
  POST /auth/webauthn/register/options  → generate registration options
  POST /auth/webauthn/register/verify   → verify registration response
  POST /auth/webauthn/login/options     → generate authentication options
  POST /auth/webauthn/login/verify      → verify authentication response
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

# Single user info
USER_ID = b"admin"
USER_NAME = "admin"
USER_DISPLAY_NAME = "Admin"


# ── GET: Login page ──────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    """Show login page with biometric + PIN fallback."""
    # If already authenticated, redirect to home
    if auth.is_authenticated(request):
        return RedirectResponse(url="/all-vouchers/view", status_code=303)

    # If not set up yet, redirect to setup
    if not auth.is_setup_complete():
        return RedirectResponse(url="/auth/setup", status_code=303)

    has_biometric = len(auth.get_webauthn_credentials()) > 0
    return templates.TemplateResponse("login.html", {
        "request": request,
        "has_biometric": has_biometric,
        "error": request.query_params.get("error"),
    })


# ── POST: PIN login ──────────────────────────────────────────────────────────

@router.post("/login/pin")
def login_pin(request: Request, pin: str = Form(...)):
    """Verify PIN and create session."""
    if auth.check_pin(pin):
        response = RedirectResponse(url="/all-vouchers/view", status_code=303)
        auth.create_session(response)
        return response
    return RedirectResponse(url="/auth/login?error=pin", status_code=303)


# ── GET: Setup page ──────────────────────────────────────────────────────────

@router.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request):
    """First-time setup — set PIN code."""
    # If already set up, redirect to login
    if auth.is_setup_complete():
        return RedirectResponse(url="/auth/login", status_code=303)

    return templates.TemplateResponse("setup.html", {
        "request": request,
        "step": "pin",
        "error": request.query_params.get("error"),
    })


# ── POST: Save PIN ───────────────────────────────────────────────────────────

@router.post("/setup")
def setup_save_pin(request: Request, pin: str = Form(...), pin_confirm: str = Form(...)):
    """Save the PIN and redirect to biometric registration."""
    # Validate PIN: 4-6 digits
    if not pin.isdigit() or not (4 <= len(pin) <= 6):
        return RedirectResponse(url="/auth/setup?error=format", status_code=303)
    if pin != pin_confirm:
        return RedirectResponse(url="/auth/setup?error=mismatch", status_code=303)

    auth.save_pin(pin)
    # Create session so user is logged in after setup
    response = RedirectResponse(url="/auth/setup/biometric", status_code=303)
    auth.create_session(response)
    return response


# ── GET: Biometric registration page (after PIN setup) ────────────────────────

@router.get("/setup/biometric", response_class=HTMLResponse)
def setup_biometric_page(request: Request):
    """Page to register biometric credential after PIN setup."""
    if not auth.is_authenticated(request):
        return RedirectResponse(url="/auth/login", status_code=303)

    return templates.TemplateResponse("setup.html", {
        "request": request,
        "step": "biometric",
    })


# ── GET: Logout ───────────────────────────────────────────────────────────────

@router.get("/logout")
def logout_route(request: Request):
    """Clear session and redirect to login."""
    response = RedirectResponse(url="/auth/login", status_code=303)
    auth.logout(response)
    return response


# ── WebAuthn: Registration Options ────────────────────────────────────────────

@router.post("/webauthn/register/options")
def webauthn_register_options(request: Request):
    """Generate WebAuthn registration options."""
    if not auth.is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    # Get existing credential IDs to exclude
    existing = auth.get_webauthn_credentials()
    exclude_credentials = [
        PublicKeyCredentialDescriptor(id=base64.urlsafe_b64decode(c["credential_id"] + "=="))
        for c in existing
    ]

    options = generate_registration_options(
        rp_id=RP_ID,
        rp_name=RP_NAME,
        user_id=USER_ID,
        user_name=USER_NAME,
        user_display_name=USER_DISPLAY_NAME,
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

    # Save challenge for verification
    auth.save_webauthn_challenge(
        base64.urlsafe_b64encode(options.challenge).decode().rstrip("=")
    )

    return JSONResponse(json.loads(options_to_json(options)))


# ── WebAuthn: Registration Verify ─────────────────────────────────────────────

@router.post("/webauthn/register/verify")
async def webauthn_register_verify(request: Request):
    """Verify WebAuthn registration response and save credential."""
    if not auth.is_authenticated(request):
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    body = await request.json()
    challenge_b64 = auth.get_webauthn_challenge()
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

        # Save the credential
        credential_data = {
            "credential_id": base64.urlsafe_b64encode(
                verification.credential_id
            ).decode().rstrip("="),
            "public_key": base64.urlsafe_b64encode(
                verification.credential_public_key
            ).decode().rstrip("="),
            "sign_count": verification.sign_count,
        }
        auth.save_webauthn_credential(credential_data)
        auth.clear_webauthn_challenge()

        return JSONResponse({"status": "ok"})

    except Exception as e:
        auth.clear_webauthn_challenge()
        return JSONResponse({"error": str(e)}, status_code=400)


# ── WebAuthn: Authentication Options ──────────────────────────────────────────

@router.post("/webauthn/login/options")
def webauthn_login_options(request: Request):
    """Generate WebAuthn authentication options."""
    credentials = auth.get_webauthn_credentials()
    if not credentials:
        return JSONResponse({"error": "No credentials registered"}, status_code=400)

    allow_credentials = [
        PublicKeyCredentialDescriptor(
            id=base64.urlsafe_b64decode(c["credential_id"] + "==")
        )
        for c in credentials
    ]

    options = generate_authentication_options(
        rp_id=RP_ID,
        allow_credentials=allow_credentials,
        user_verification=UserVerificationRequirement.PREFERRED,
    )

    # Save challenge for verification
    auth.save_webauthn_challenge(
        base64.urlsafe_b64encode(options.challenge).decode().rstrip("=")
    )

    return JSONResponse(json.loads(options_to_json(options)))


# ── WebAuthn: Authentication Verify ───────────────────────────────────────────

@router.post("/webauthn/login/verify")
async def webauthn_login_verify(request: Request):
    """Verify WebAuthn authentication response and create session."""
    body = await request.json()
    challenge_b64 = auth.get_webauthn_challenge()
    if not challenge_b64:
        return JSONResponse({"error": "No challenge found"}, status_code=400)

    credentials = auth.get_webauthn_credentials()

    # Find the matching credential
    credential_id_b64 = body.get("id", "")
    matched_cred = None
    for c in credentials:
        if c["credential_id"] == credential_id_b64:
            matched_cred = c
            break

    if not matched_cred:
        auth.clear_webauthn_challenge()
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

        # Update sign count
        matched_cred["sign_count"] = verification.new_sign_count
        data = auth._load_auth_data()
        for i, c in enumerate(data.get("webauthn_credentials", [])):
            if c["credential_id"] == credential_id_b64:
                data["webauthn_credentials"][i]["sign_count"] = verification.new_sign_count
                break
        auth._save_auth_data(data)
        auth.clear_webauthn_challenge()

        # Create session
        response = JSONResponse({"status": "ok"})
        auth.create_session(response)
        return response

    except Exception as e:
        auth.clear_webauthn_challenge()
        return JSONResponse({"error": str(e)}, status_code=400)
