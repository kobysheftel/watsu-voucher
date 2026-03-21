# Watsu Gift Voucher System — MEMORY

## What This Project Is
Web app for creating, sending, and tracking Watsu gift vouchers for "גלים ונפש" (Waves & Soul).
Deployed at https://vouchers.soulwaves.org. Code on GitHub: kobysheftel/watsu-voucher.

## Status
- V1 complete and deployed to production
- 48 tests passing
- Branch: master, remote: origin (GitHub public repo)
- Biometric auth (WebAuthn + PIN) implemented
- PWA installable on smartphones

## Servers
- **Production** — https://vouchers.soulwaves.org (Hetzner server)
  - SSH: `ssh -i "C:\Users\yacov\.ssh\Hetzner_new" root@iceland.soulwaves.org`
  - App path: `/var/www/sites/vouchers/`
  - Service: `systemctl restart vouchers`
  - Python 3.12, venv at `/var/www/sites/vouchers/venv/`
  - Nginx reverse proxy → uvicorn on port 8100
  - SSL via certbot (auto-renew)
- **Local dev** — localhost:8000 (Python 3.14)

## Deploy Workflow
1. Edit locally → `git push origin master`
2. SSH to server → `cd /var/www/sites/vouchers && git pull && systemctl restart vouchers`
3. For DB schema changes: run ALTER TABLE on server before restart

## Files and Purpose

### Root
| File | Purpose |
|------|---------|
| main.py | FastAPI app entry point, auth middleware, router registration |
| CLAUDE.md | Project instructions for Claude |
| CHANGELOG.md | Technology change log |
| MEMORY.md | This file — session state |
| requirements.txt | Python dependencies |
| voucher.html | Original standalone HTML prototype |
| backup.bat | Backup script |
| .gitignore | Excludes config/, vouchers/, *.db, __pycache__ |

### app/ — Application Code
| File | Purpose |
|------|---------|
| __init__.py | Package init |
| auth.py | PIN hashing, WebAuthn credentials, session management (15-min sliding) |
| database.py | SQLAlchemy engine, session, Base |
| models.py | SQLAlchemy models: Holder, Voucher (with display_name), Sending |
| schemas.py | Pydantic schemas for validation (types: יחיד, זוגי) |
| rules.py | Business rules engine (cement, send, resend, mark used) |
| utils.py | Utility functions (utcnow) |
| qr_module.py | QR code generation with Fernet encryption |
| pdf_module.py | PDF generation via reportlab + bidi (Hebrew support, water-blue design) |

### app/routers/
| File | Purpose |
|------|---------|
| auth.py | Auth routes: login, setup, WebAuthn register/verify, logout |
| holders.py | Holder CRUD API endpoints |
| vouchers.py | Voucher CRUD + send/resend/mark-used API + PDF/QR serving |
| reports.py | Report/listing/search/CSV export endpoints |
| pages.py | HTML page routes: home, orderers, vouchers, new voucher, holder, voucher detail |

### templates/ — Jinja2 HTML Templates
| File | Purpose |
|------|---------|
| base.html | Base layout (RTL Hebrew, Bootstrap 5, PWA, inactivity lock, logout) |
| home.html | Search orderer page |
| holder.html | Orderer detail + voucher list with inline actions |
| voucher_view.html | Voucher detail: fields, action buttons (WA/email/print), send history |
| new_voucher.html | New voucher: orderer search/create + voucher form (full page) |
| all_vouchers.html | Main screen: all vouchers table, sortable/filterable, + שובר חדש |
| orderers.html | All orderers with voucher counts |
| voucher_pdf.html | PDF template (reference only — reportlab used instead) |
| report.html | Filterable report with CSV export |
| login.html | Biometric + PIN login page |
| setup.html | First-time PIN setup + biometric registration |

### static/ — PWA Assets
| File | Purpose |
|------|---------|
| manifest.json | PWA manifest (installable app) |
| sw.js | Service worker (network-first, auto-update) |
| icon-192.png | PWA icon 192x192 |
| icon-512.png | PWA icon 512x512 |

### assets/
| File | Purpose |
|------|---------|
| Pool.png | Watsu pool photo for voucher PDF |
| voucher-bg.png | Background reference image |
| fonts/Heebo-Variable.ttf | Hebrew font for PDF generation |

### tests/
| File | Purpose |
|------|---------|
| test_rules.py | Rules engine unit tests (21 tests) |
| test_api.py | API endpoint tests (27 tests, with auth fixture) |

### config/ (git-ignored)
| File | Purpose |
|------|---------|
| secret.key | Fernet encryption key for QR codes |
| auth.json | PIN hash + WebAuthn credentials |

## What Was Done This Session (2026-03-21)
- V1 completed: all features working end-to-end
- Fixed PDF Hebrew rendering: switched from xhtml2pdf to reportlab + python-bidi
- Redesigned voucher PDF: water-blue gradient, pool photo, personalized text
- Simplified UX: orderer-centric flow (search → create → manage vouchers)
- Added sortable/filterable tables with Excel-like column filters
- New voucher page: smart orderer search (phone lookup, pick from list, create new)
- WhatsApp sharing: navigator.share() on mobile, wa.me fallback on desktop
- Terminology: מחזיק → מזמין, ליחיד → יחיד, לזוג → זוגי
- Defaults: expiry 6 months, receipt date today
- Added display_name field: custom name on voucher (or anonymous if empty)
- Biometric auth: WebAuthn + PIN, 15-min inactivity lock
- PWA: installable on smartphone
- Deployed to https://vouchers.soulwaves.org (Hetzner, nginx, SSL)
- GitHub repo: kobysheftel/watsu-voucher (public)
- Added Shift+Enter keybinding for newline in Claude Code
- Updated global CLAUDE.md: always respond in English

## Next Steps to Resume
- Voucher ID = receipt number (נח"ש) — Koby needs to confirm if known at creation time
- PDF design polish (Koby said "at the end")
- QR code on voucher (Koby said "last")
- Logo/wave graphics for PDF header (when assets available)
- Test biometric auth on phone
- Consider adding email sending (currently just records, doesn't actually send)

## Current Stack
| Discipline | Item | Version |
|---|---|---|
| BACKEND | FastAPI | >=0.115.6 |
| BACKEND | uvicorn | >=0.32.1 |
| DATABASE | SQLite | via SQLAlchemy >=2.0.36 |
| FRONTEND | Jinja2 | >=3.1.4 |
| FRONTEND | Bootstrap 5 RTL | 5.3.2 (CDN) |
| LIBS | reportlab | >=4.0 |
| LIBS | python-bidi | >=0.6.0 |
| LIBS | qrcode | >=8.0 |
| LIBS | Pillow | >=11.1.0 |
| LIBS | cryptography | >=43.0.3 |
| LIBS | webauthn | >=2.0.0 |
| LIBS | aiofiles | >=24.1.0 |
| LANGUAGE | Python | 3.12 (server), 3.14 (local) |
| DEVOPS | Git + GitHub | kobysheftel/watsu-voucher |
| DEVOPS | systemd + nginx | Hetzner Ubuntu |
| DEVOPS | certbot | SSL auto-renew |
| AUTH | WebAuthn + PIN | 15-min inactivity timeout |
| PWA | manifest + SW | network-first caching |
