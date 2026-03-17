"""
QR module — Fernet-encrypted QR code generation.

Payload: JSON {"id": voucher_id, "ts": issued_at_iso}
Encrypted with Fernet (config/secret.key), then encoded as a QR image.

Rules:
- generate_qr() is called ONCE on first send — never again for the same voucher.
- decrypt_qr() can be used by a future redemption scanner.
- The key file is auto-created on first run and stored in config/ (git-ignored).
"""

import json
from pathlib import Path

import qrcode
from cryptography.fernet import Fernet

# Key file location — excluded from git
_KEY_FILE = Path("config/secret.key")


def _get_fernet() -> Fernet:
    """Load or create the Fernet encryption key from config/secret.key."""
    if _KEY_FILE.exists():
        key = _KEY_FILE.read_bytes().strip()
    else:
        # First run — generate key and persist it
        _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        _KEY_FILE.write_bytes(key)
    return Fernet(key)


def generate_qr(voucher, folder: Path) -> Path:
    """
    Generate a Fernet-encrypted QR code for the voucher.
    Payload: {"id": voucher_id, "ts": issued_at_iso_string}
    Saves to folder/qr.png. Returns the saved path.

    Called ONCE on first send — must never be called again for the same voucher.
    """
    fernet = _get_fernet()

    # Build the plaintext payload
    payload = json.dumps({
        "id": voucher.voucher_id,
        "ts": str(voucher.issued_at),
    }).encode("utf-8")

    # Encrypt — result is a URL-safe base64 token
    token = fernet.encrypt(payload)

    # Build the QR image
    qr = qrcode.QRCode(
        version=None,                                       # auto-pick smallest version
        error_correction=qrcode.constants.ERROR_CORRECT_M, # ~15% recovery
        box_size=6,
        border=4,
    )
    qr.add_data(token.decode("utf-8"))
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    qr_path = folder / "qr.png"
    img.save(str(qr_path))
    return qr_path


def decrypt_qr(token: str) -> dict:
    """
    Decrypt a QR token. Returns {"id": voucher_id, "ts": ...}.
    Raises cryptography.fernet.InvalidToken if tampered or wrong key.
    """
    fernet = _get_fernet()
    payload = fernet.decrypt(token.encode("utf-8"))
    return json.loads(payload.decode("utf-8"))
