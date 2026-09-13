# Watsu Gift Voucher System — MEMORY

## What This Project Is
Web app for creating, selling, sending and tracking Watsu tickets — gift vouchers (שובר) and multi-session passes (כרטיסיה) — for "גלים ונפש" (Waves & Soul).
Deployed at https://vouchers.soulwaves.org. Code on GitHub: kobysheftel/watsu-voucher.

## Status
- V1 complete and deployed to production; phase 2 started 2026-09-09 (new voucher design)
- **V2 phase A (tickets + entries + manual payment) implemented locally 2026-09-13 — NOT yet deployed.** Design: `docs/DESIGN-V2-TICKETS.md`
- 82 tests passing (`venv\Scripts\python -m pytest -q`) — 53 legacy + 29 in tests/test_tickets.py
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
| models.py | SQLAlchemy models: Holder, Voucher (= ticket: kind VOUCHER/PASS, entries_total, pricing + payment fields), Entry (held/consumed/cancelled), Sending (kind TICKET/PAYMENT_LINK). Status/kind constants + Hebrew labels live here |
| schemas.py | Pydantic schemas (VoucherCreate with kind/entries/prices, EntryOut, MarkPaidRequest, HoldRequest, PriceUpdate) |
| rules.py | Business rules engine: create, request_payment, mark_paid, first_send (send ticket), resend, hold_entry / consume_entry / cancel_hold / consume_direct, mark_used (legacy = consume one), set_price, holder lock (any consumed entry) |
| utils.py | Utility functions (utcnow) |
| qr_module.py | QR code generation with Fernet encryption |
| pdf_module.py | PDF + JPEG generation via reportlab + bidi + PyMuPDF. 2026-09 design: watercolor bg, brand header image, oval photo, QR + voucher ID at bottom. `render_preview()` = on-the-fly draft render |
| images.py | Voucher image library (assets/voucher_images + library.json): default + history, upload/validate |
| settings.py | config/settings.json — default location, notify_email, default_terms, price_list (kind × יחיד/זוגי × entries → price) |
| database.py | engine + `_migrate()`: adds missing columns, `sent`→`active`, legacy paid rows, back-fills one consumed entry per used ticket (idempotent, runs on every startup) |

### app/routers/
| File | Purpose |
|------|---------|
| auth.py | Auth routes: login, setup, WebAuthn register/verify, logout |
| holders.py | Holder CRUD API endpoints |
| vouchers.py | Ticket CRUD + price / request-payment / payment-text / mark-paid / send / resend / use + entries (hold, consume, cancel, direct) + PDF/JPEG/QR serving |
| reports.py | Report/listing/search/CSV export endpoints (kind, entries, price, payment columns) |
| pages.py | HTML page routes + form handlers: home, orderers, tickets list, new ticket (?mobile= &kind=), holder, ticket detail, report, settings (/settings/view) |

### templates/ — Jinja2 HTML Templates
| File | Purpose |
|------|---------|
| base.html | Base layout (RTL Hebrew, Bootstrap 5, PWA, inactivity lock, logout) |
| home.html | Search orderer page |
| holder.html | Orderer detail + voucher list with inline actions |
| voucher_view.html | Ticket detail: fields, payment card (price/discount, send payment request WA/email/copy, mark paid), entries card (hold / consume / cancel / walk-in), action buttons per status, send history |
| new_voucher.html | New ticket: kind toggle (שובר/כרטיסיה), entries presets, price list lookup + discount, terms, orderer search/create |
| all_vouchers.html | Main screen: all tickets table (kind, entries x/N, price, status), + שובר / + כרטיסיה |
| settings.html | Price list rows + default terms + default location |
| _macros.html | status_badge / kind_badge / entries_badge / price_text Jinja macros |
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
| test_tickets.py | Phase A: passes, pricing, payment flow, entries, holder lock, legacy-DB migration, API flow, page rendering, settings form (29 tests) |

### config/ (git-ignored)
| File | Purpose |
|------|---------|
| secret.key | Fernet encryption key for QR codes |
| auth.json | PIN hashes + WebAuthn credentials (per user) |
| settings.json | Default voucher location |

## What Was Done This Session (2026-09-13) — V2 phase A
- Design doc `docs/DESIGN-V2-TICKETS.md` written and approved by Koby (decisions: כרטיסיה spelling, payment link first then ticket, vouchers also via GI, price list + discount, GI creates documents, holder locks on first consumed entry, both kinds multi-entry).
- Ticket lifecycle: draft → awaiting_payment → paid → active → used (free ticket: draft → active). Priced tickets cannot be sent before payment.
- Entries table + rules (hold/consume/cancel/walk-in), derived counters, ticket becomes `used` when all entries consumed.
- Manual payment ("סמן כשולם": CASH/BIT/TRANSFER/CARD) — Green Invoice link/webhook is phase B (not started).
- Payment request message text (product, price, terms) sent by WA/email/copy; logged as sendings.kind=PAYMENT_LINK.
- PDF: pass layout ("כרטיסיה — גלים ונפש", N טיפולי וואטסו, על שם, punch circles); multi-entry voucher gets "N טיפולי וואטסו" + circles. Verified visually.
- Settings page: price list + default terms + default location. Terms seed text is a placeholder — Koby/Avigal to edit.
- All templates re-labelled שובר → כרטיס where generic; nav has הגדרות.
- Local dev DB migrated automatically (3 sent → active). Test tickets created during smoke test were deleted. ⚠️ One notification e-mail for test pass 0523281250-004 may have reached kobysheftel@gmail.com — ignore it.

## What Was Done This Session (2026-09-09)
- Read the whole project; startup review found `.gitignore` inline comments broke `config/` + `vouchers/` patterns (auth.json + customer PDFs were tracked in the public repo) → fixed, files untracked locally and on production (prod auth.json untouched, checksum verified). Old commits on GitHub still contain them (history rewrite not done).
- **New voucher design (phase 2, step 1)** from Koby's Word template: watercolor bg image, brand header image, oval pool photo (new library default), "איזה כיף קיבלת שובר מתנה!" + "טיפול וואטסו ליחיד/זוגי", ornament, description, contact, location (small grey), validity, QR 18 mm at bottom, voucher ID only (no caption). David Libre fonts added. Greeting still prints when set.
- Image send format PNG → JPEG q85 (`voucher.jpg`, ~340 KB; PNG of the watercolor was ~3 MB). PDF ~1.4 MB.
- Draft preview: `/vouchers/{id}/image` + `/pdf` render drafts (and sent vouchers with missing files) on the fly via `render_preview()` — no QR, nothing saved. Preview buttons on voucher / list / orderer pages.
- Deployed 3 times (f36a333 design, d1ceeff gitignore, 80bfe20 preview); smoke-tested rendering on the server.
- Deleted ChatGPT original images from assets (clean copies kept).
- Wiped all 6 vouchers + 9 sendings + files on production at Koby's request; 4 orderers kept; backup `/root/vouchers-backup-20260909-1917/`.

## Next Steps to Resume
- **Deploy phase A** (on Koby's request): `git push`, server `git pull && systemctl restart vouchers` — the migration runs itself on startup (no manual ALTER TABLE). Back up `/var/www/sites/vouchers/vouchers.db` first.
- Koby to fill the price list + real terms text on /settings/view (production) and test the flow on the phone.
- **Phase B — Green Invoice**: verify API docs (developers.morning.co / greeninvoice.docs.apiary.io — both failed to load 2026-09-13), then: create payment page in `rules.request_payment`, public webhook route `/api/payments/greeninvoice/notify` (add to `AuthMiddleware.PUBLIC_PREFIXES`), `/pay/thanks` page, credentials in `config/greeninvoice.json`.
- Phase C: QR redeem page, auto-expire stale holds, real e-mail sending to customers.
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
