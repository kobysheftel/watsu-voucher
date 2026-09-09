# Watsu Gift Voucher System — MEMORY

## What This Project Is
Web app for creating, sending, and tracking Watsu gift vouchers for "גלים ונפש" (Waves & Soul).
Deployed at https://vouchers.soulwaves.org. Code on GitHub: kobysheftel/watsu-voucher.

## Status
- V1 complete and deployed to production; phase 2 started 2026-09-09 (new voucher design)
- 53 tests passing (`venv\Scripts\python -m pytest -q`)
- Branch: master, remote: origin (GitHub public repo) — local = GitHub = production at every deploy
- Biometric auth (WebAuthn + PIN) — two users, Koby + Avigal (seed PINs in app/auth.py)
- PWA installable on smartphones
- Production DB wiped of vouchers on 2026-09-09 (orderers kept); backup at `/root/vouchers-backup-20260909-1917/` on Hetzner

## Servers
- **Production** — https://vouchers.soulwaves.org (Hetzner server)
  - SSH: `ssh -i "C:\Users\yacov\.ssh\Hetzner_new" root@iceland.soulwaves.org`
  - App path: `/var/www/sites/vouchers/`
  - Service: `systemctl restart vouchers`
  - Python 3.12, venv at `/var/www/sites/vouchers/venv/`
  - Nginx reverse proxy → uvicorn on port 8100
  - SSL via certbot (auto-renew)
- **Local dev** — localhost:8000 (venv Python 3.12.10; start: `venv\Scripts\python -m uvicorn main:app --port 8000`)

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
| pdf_module.py | PDF + JPEG generation via reportlab + bidi + PyMuPDF. 2026-09 design: watercolor bg, brand header image, oval photo, QR + voucher ID at bottom. `render_preview()` = on-the-fly draft render |
| images.py | Voucher image library (assets/voucher_images + library.json): default + history, upload/validate |
| settings.py | config/settings.json — default voucher location (הוד השרון) |

### app/routers/
| File | Purpose |
|------|---------|
| auth.py | Auth routes: login, setup, WebAuthn register/verify, logout |
| holders.py | Holder CRUD API endpoints |
| vouchers.py | Voucher CRUD + send/resend/mark-used API + PDF/JPEG/QR serving (drafts + missing files rendered on the fly, no-store) |
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
| voucher-bg-water.jpg | Full-page watercolor background (from Koby's ChatGPT image, JPEG q88) |
| header-logo.png | Brand header "גלים ✦ ונפש / טיפולי וואטסו" cut from the original design, transparent bg |
| ornament.png | Small brand swirl divider (transparent) |
| voucher_images/Pool-oval.png | Oval pool photo — current library default (RGBA, 800 px) |
| voucher_images/Pool.png | Old rectangular pool photo (kept in library history) |
| voucher_images/library.json | Image library manifest (default + history) |
| Pool.png | Original pool photo (seed for the library) |
| voucher-bg.png | Original full design reference (source of header-logo/ornament crops) |
| fonts/Heebo-Variable.ttf | Body font (OFL) |
| fonts/DavidLibre-Regular.ttf, DavidLibre-Bold.ttf | Title / label font (OFL) |

### Design references (root, Word)
| File | Purpose |
|------|---------|
| Voucher.docx | Koby's manual voucher template (single) — the design the app now reproduces |
| Voucher Couple.docx | Same with "טיפול וואטסו זוגי" overlay |
| 2026-05-29#1 Voucher.docx | Earlier manual voucher example |
| definitions #5.docx | Original project spec |

### tests/
| File | Purpose |
|------|---------|
| test_rules.py | Rules engine unit tests (21 tests) |
| test_api.py | API endpoint tests (32 tests incl. auth + draft preview, with auth fixture) |

### config/ (git-ignored)
| File | Purpose |
|------|---------|
| secret.key | Fernet encryption key for QR codes |
| auth.json | PIN hashes + WebAuthn credentials (per user) |
| settings.json | Default voucher location |

## What Was Done This Session (2026-09-09)
- Read the whole project; startup review found `.gitignore` inline comments broke `config/` + `vouchers/` patterns (auth.json + customer PDFs were tracked in the public repo) → fixed, files untracked locally and on production (prod auth.json untouched, checksum verified). Old commits on GitHub still contain them (history rewrite not done).
- **New voucher design (phase 2, step 1)** from Koby's Word template: watercolor bg image, brand header image, oval pool photo (new library default), "איזה כיף קיבלת שובר מתנה!" + "טיפול וואטסו ליחיד/זוגי", ornament, description, contact, location (small grey), validity, QR 18 mm at bottom, voucher ID only (no caption). David Libre fonts added. Greeting still prints when set.
- Image send format PNG → JPEG q85 (`voucher.jpg`, ~340 KB; PNG of the watercolor was ~3 MB). PDF ~1.4 MB.
- Draft preview: `/vouchers/{id}/image` + `/pdf` render drafts (and sent vouchers with missing files) on the fly via `render_preview()` — no QR, nothing saved. Preview buttons on voucher / list / orderer pages.
- Deployed 3 times (f36a333 design, d1ceeff gitignore, 80bfe20 preview); smoke-tested rendering on the server.
- Deleted ChatGPT original images from assets (clean copies kept).
- Wiped all 6 vouchers + 9 sendings + files on production at Koby's request; 4 orderers kept; backup `/root/vouchers-backup-20260909-1917/`.

## Next Steps to Resume
- Ask Koby what phase 2 continues with: Green Invoice API (roadmap V2), QR redemption scan page, real email sending, or more design tweaks (drop location/greeting lines?).
- Optional: rewrite GitHub history to purge old auth.json / voucher PDFs (needs force push — ask first).
- Open since March: voucher ID = receipt number decision; WebAuthn RP_ID hardcoded to production.

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

## Next Steps (as of 2026-03-21, kept for history)
- Voucher ID = receipt number (נח"ש) — Koby needs to confirm if known at creation time
- PDF design polish (Koby said "at the end")
- QR code on voucher (Koby said "last")
- Logo/wave graphics for PDF header (when assets available)
- Test biometric auth on phone
- Consider adding email sending (currently just records, doesn't actually send)

## Current Stack
| Discipline | Item | Version |
|---|---|---|
| BACKEND | FastAPI | 0.135.1 (pinned) |
| BACKEND | Starlette | 0.52.1 (pinned — 1.x breaks TemplateResponse) |
| BACKEND | uvicorn | 0.42.0 |
| DATABASE | SQLite via SQLAlchemy | 2.0.48 |
| FRONTEND | Jinja2 | 3.1.6 |
| FRONTEND | Bootstrap 5 RTL | 5.3.2 (CDN) |
| MEDIA | reportlab | 4.4.10 |
| MEDIA | PyMuPDF (PDF→JPEG raster) | 1.27.2.3 |
| MEDIA | python-bidi | 0.6.7 |
| MEDIA | Fonts | Heebo (body), David Libre (title) — OFL, in assets/fonts |
| LIBS | qrcode | 8.2 |
| LIBS | Pillow | 12.1.1 |
| LIBS | cryptography | 46.0.5 |
| LIBS | webauthn | 2.7.1 |
| LANGUAGE | Python | 3.12.3 (server), 3.12.10 (local venv) |
| DEVOPS | Git + GitHub | kobysheftel/watsu-voucher (public) |
| DEVOPS | systemd + nginx | Hetzner Ubuntu, uvicorn :8100 |
| DEVOPS | certbot | SSL auto-renew (single cert for all soulwaves.org domains) |
| AUTH | WebAuthn + PIN | 2 users, 15-min inactivity timeout |
| PWA | manifest + SW | network-first caching |
