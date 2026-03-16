# Watsu Gift Voucher System — Project Instructions for Claude

## Version Roadmap
- **V1** — Local Python app, manual accounting, no external APIs ← current
- **V2** — Green Invoice API integration
- **V3** — JS/browser version

## Tech Stack
- Python 3.12
- FastAPI (web framework) — localhost:8000
- SQLite (database via SQLAlchemy)
- xhtml2pdf (PDF generation — Windows-compatible, no GTK)
- qrcode + Pillow (QR generation)
- Jinja2 (HTML templates)
- cryptography/Fernet (QR payload encryption)

## Key Terminology

| Term | Meaning |
|------|---------|
| **Holder** | Person who receives vouchers (identified by mobile) |
| **Voucher** | A gift voucher document (like a printed cheque) |
| **Cement** | Copy holder details into voucher on first send — frozen forever |
| **QR** | Generated ONCE on first send, reused on all resends |
| **Used** | Final state — completely frozen, no changes allowed |

## Voucher ID Format
`{mobile}-{sequence}` e.g. `0541234567-001`
Sequence = next integer for that mobile, zero-padded to 3 digits.

## Status Flow
```
draft ──[first send]──► sent ──[mark used]──► used
         (cement)              (freeze)
              └──[resend]──► sent (still sent, new sendings row)
```

## Rules Engine — Critical Rules

### First Send (draft → sent)
1. Copy holder details into voucher (cement — never changes again)
2. Set first_sent_at (never changes again)
3. Generate QR (once only — saved to qr.png)
4. Generate PDF
5. Log in sendings table
6. Set status = sent

### Resend (sent → sent)
1. Reuse original QR (NEVER regenerate)
2. Regenerate PDF (same content, same QR)
3. Log NEW row in sendings table
4. Voucher data unchanged

### Mark Used (sent → used)
1. Freeze entire record — no further changes
2. Can still view and print
3. Cannot resend

### Holder Editability
- Allowed if ALL their vouchers are draft or sent
- BLOCKED if ANY voucher is used

## Sending Methods (sent_via field)
| Value | Display | Action |
|-------|---------|--------|
| WA | 📱 וואטסאפ | wa.me link |
| EMAIL | 📧 מייל | mailto link |
| PRINT | 🖨️ הדפסה | window.print() |

## Fernet Key
- Auto-generated on first run
- Saved to: `config/secret.key`
- `config/` is in .gitignore — NEVER commit
- Back up with backup.bat

## File Storage
```
vouchers/
  {mobile}/
    {voucher_id}/
      voucher.pdf
      qr.png
      metadata.json
```

## Assets
- `assets/pool.png` — oval center photo for voucher
- `assets/voucher-bg.png` — background reference

## Coding Standards
- Always add comments in code
- Prefer simple readable code
- Hebrew strings in templates only (not in Python logic)
- All dates stored as ISO format in DB

## Conflict Check Rule
Before changing any config file, model, or rule — read it first,
identify conflicts, present them, wait for approval.
