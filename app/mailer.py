"""
Mailer — e-mail notification when a new voucher is produced (first send).

Sends "new voucher" e-mails via Gmail SMTP from whereiskoby@gmail.com to the
address in config/settings.json ("notify_email"). Attachments: the voucher
JPEG + PDF that were just generated.

Password lookup order (first hit wins):
  1. env var VOUCHER_SMTP_PASS
  2. config/smtp.json  -> {"password": "..."}  (server; git-ignored, chmod 600)
  3. Windows keyring   -> service "smtp_soulwaves", user whereiskoby@gmail.com
     (local dev — same store the shared T:\\0KOBY\\send_email.py uses)

Sending runs in a background thread so the send request is never delayed,
and any failure is logged only — e-mail must never break a voucher send.
Set VOUCHER_DISABLE_EMAIL=1 to turn it off (tests do this).
"""

import json
import logging
import mimetypes
import os
import smtplib
import ssl
import threading
from email import encoders
from email.header import Header
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

from app import settings

log = logging.getLogger("vouchers.mailer")

# SMTP config — Gmail (same account as the other SoulWaves projects)
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "whereiskoby@gmail.com"
FROM_NAME = "גלים ונפש — שוברים"
KEYRING_SERVICE = "smtp_soulwaves"

_SMTP_FILE = Path("config/smtp.json")


# ── Configuration ─────────────────────────────────────────────────────────────

def is_disabled() -> bool:
    """True when notifications are switched off via VOUCHER_DISABLE_EMAIL=1."""
    return os.environ.get("VOUCHER_DISABLE_EMAIL", "") == "1"


def get_password() -> str | None:
    """Return the Gmail app password, or None if none is configured anywhere."""
    # 1. Environment variable
    pw = os.environ.get("VOUCHER_SMTP_PASS")
    if pw:
        return pw
    # 2. config/smtp.json (server)
    if _SMTP_FILE.exists():
        try:
            pw = json.loads(_SMTP_FILE.read_text(encoding="utf-8")).get("password")
            if pw:
                return pw
        except Exception as e:                       # malformed file — log, keep looking
            log.warning("config/smtp.json unreadable: %s", e)
    # 3. Windows keyring (local dev)
    try:
        import keyring                               # optional dependency
        return keyring.get_password(KEYRING_SERVICE, SMTP_USER)
    except Exception:
        return None


# ── Message building ──────────────────────────────────────────────────────────

def _build_message(to: str, subject: str, body: str,
                   attachments: list[Path]) -> MIMEMultipart:
    """Build a UTF-8 multipart message with file attachments."""
    # Reject newlines in header values — prevents SMTP header injection
    for name, value in (("subject", subject), ("to", to)):
        if "\r" in value or "\n" in value:
            raise ValueError(f"Newline not allowed in {name!r}")

    msg = MIMEMultipart("mixed")
    msg.attach(MIMEText(body, "plain", "utf-8"))

    for p in attachments:
        if not p.is_file():
            continue                                  # skip silently — never block the mail
        ctype, encoding = mimetypes.guess_type(str(p))
        if ctype is None or encoding is not None:
            ctype = "application/octet-stream"
        maintype, subtype = ctype.split("/", 1)
        part = MIMEBase(maintype, subtype)
        part.set_payload(p.read_bytes())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment",
                        filename=("utf-8", "", p.name))
        msg.attach(part)

    # RFC 2047 headers so the Hebrew subject / sender name survive SMTP
    msg["From"] = formataddr((str(Header(FROM_NAME, "utf-8")), SMTP_USER))
    msg["To"] = to
    msg["Subject"] = Header(subject, "utf-8")
    return msg


def send_mail(to: str, subject: str, body: str,
              attachments: list[Path] | None = None) -> None:
    """Send one e-mail synchronously. Raises on failure."""
    password = get_password()
    if not password:
        raise RuntimeError("SMTP password not configured (env / config/smtp.json / keyring)")

    msg = _build_message(to, subject, body, attachments or [])

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
        server.starttls(context=ssl.create_default_context())
        server.login(SMTP_USER, password)
        refused = server.sendmail(SMTP_USER, [to], msg.as_string())
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)


# ── New-voucher notification ──────────────────────────────────────────────────

def _voucher_summary(voucher, sent_via: str, performed_by: str | None) -> str:
    """Plain-text body describing the voucher that was just produced."""
    lines = [
        "הופק שובר חדש במערכת השוברים של גלים ונפש.",
        "",
        f"מס׳ שובר:     {voucher.voucher_id}",
        f"סוג:          {voucher.voucher_type}",
        f"מזמין:        {voucher.holder_name or ''}",
        f"טלפון:        {voucher.holder_mobile or voucher.mobile}",
        f"מייל מזמין:   {voucher.holder_email or ''}",
        f"בתוקף עד:     {voucher.valid_until.strftime('%d/%m/%Y')}",
        f"מיקום:        {voucher.location or ''}",
        f"ברכה:         {voucher.greeting or ''}",
        f"מס׳ קבלה:     {voucher.receipt_number or ''}",
        f"הערות:        {voucher.notes or ''}",
        "",
        f"נשלח באמצעות: {sent_via}",
        f"על ידי:       {performed_by or ''}",
        f"תאריך שליחה:  {voucher.first_sent_at.strftime('%d/%m/%Y %H:%M') if voucher.first_sent_at else ''} (UTC)",
    ]
    return "\n".join(lines)


def notify_new_voucher(voucher, sent_via: str, performed_by: str | None = None) -> None:
    """
    Fire-and-forget e-mail about a voucher that was just produced (first send).

    Called by rules.first_send() after the commit. Never raises: if e-mail is
    disabled or misconfigured, or the SMTP call fails, it only logs.
    """
    if is_disabled():
        return
    to = settings.get_notify_email()
    if not to:
        return

    # Snapshot everything now — the ORM object must not be touched from the thread.
    subject = f"שובר חדש הופק: {voucher.voucher_id} ({voucher.voucher_type}) — {voucher.holder_name or ''}"
    body = _voucher_summary(voucher, sent_via, performed_by)
    attachments: list[Path] = []
    if voucher.pdf_path:
        pdf = Path(voucher.pdf_path)
        attachments.append(pdf.parent / "voucher.jpg")
        attachments.append(pdf)

    def _worker():
        try:
            send_mail(to, subject, body, attachments)
            log.info("new-voucher e-mail sent for %s to %s", voucher.voucher_id, to)
        except Exception as e:
            log.error("new-voucher e-mail FAILED for %s: %s", voucher.voucher_id, e)

    threading.Thread(target=_worker, name="voucher-mail", daemon=True).start()
