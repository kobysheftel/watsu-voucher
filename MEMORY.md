# Watsu Gift Voucher System — MEMORY

## What This Project Is
Web app for creating, selling, sending and tracking Watsu tickets — gift vouchers (שובר) and multi-session passes (כרטיסיה) — for "גלים ונפש" (Waves & Soul).
Deployed at https://vouchers.soulwaves.org. Code on GitHub: kobysheftel/watsu-voucher.

## Status
- V1 complete and deployed to production; phase 2 started 2026-09-09 (new voucher design)
- V2 phase A (tickets + entries + manual payment) implemented 2026-09-13, deployed 2026-10-22. Design: `docs/DESIGN-V2-TICKETS.md`
- **V2 phase A + English tickets DEPLOYED to production 2026-10-22 11:50** (commit 425a7a6; pre-deploy backups on server: `vouchers.db.bak-20261022-*`, `config/settings.json.bak-20261022-*`). Migration verified: 3 active tickets, `language` column present.
- **Bilingual documents deployed 2026-10-22 (second deploy of the day)**: `language` = default document language (he unless set), editable until used; the other language is produced on demand (`voucher.<lang>.pdf/.jpg`, same QR); `sendings.language` logged; ticket page has a document-language toggle.
- System default ticket language on /settings/view (`default_language`, deployed 2026-10-22, third deploy): new tickets start in it; explicit per-ticket choice still wins.
- 94 tests passing (`venv\Scripts\python -m pytest -q`) — 53 legacy + 41 in tests/test_tickets.py
- Branch: master, remote: origin (GitHub public repo) — local = GitHub = production at every deploy
- Biometric auth (WebAuthn + PIN) — two users, Koby + Avigal (seed PINs in app/auth.py). Avigal PIN changed 2026-10-10 (value in app/auth.py; local + production auth.json both rehashed; `init_auth` only seeds when auth.json is missing, so a PIN change always needs the out-of-band rehash on the server)
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
| pdf_module.py | PDF + JPEG generation via reportlab + bidi + PyMuPDF. `_STRINGS` = printed text per ticket language (he/en). 2026-09 design: watercolor bg, brand header image, oval photo, QR + voucher ID at bottom. `render_preview()` = on-the-fly draft render |
| images.py | Voucher image library (assets/voucher_images + library.json): default + history, upload/validate |
| settings.py | config/settings.json — default_language (he/en), default location (+ default_location_en), notify_email, default_terms (+ default_terms_en), price_list (kind × יחיד/זוגי × entries → price) |
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
| voucher_view.html | Ticket detail: fields (incl. ticket language — select while unsent, read-only after), payment card (price/discount, send payment request WA/email/copy, mark paid), entries card (hold / consume / cancel / walk-in), action buttons per status, send history |
| new_voucher.html | New ticket: kind toggle (שובר/כרטיסיה), language toggle (עברית/English — swaps location + terms defaults), entries presets, price list lookup + discount, terms, orderer search/create |
| all_vouchers.html | Main screen: all tickets table (kind, entries x/N, price, status), + שובר / + כרטיסיה |
| settings.html | Price list rows + default ticket language + default terms (HE + EN) + default location (HE + EN) |
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
| test_tickets.py | Phase A: passes, pricing, payment flow, entries, holder lock, legacy-DB migration, API flow, page rendering, settings form (30 tests) + English tickets: creation, validation, payment text, language freeze, English PDF, API, HTML form (7 tests) |

### config/ (git-ignored)
| File | Purpose |
|------|---------|
| secret.key | Fernet encryption key for QR codes |
| auth.json | PIN hashes + WebAuthn credentials (per user) |
| settings.json | Default voucher location |

## What Was Done This Session (2026-10-22, part 2) — one ticket, two languages
- Koby: "allow producing an existing voucher in a different language. the metadata is the same, document in the 2 languages, default is hebrew".
- `vouchers.language` is now the DEFAULT document language, editable until used (changing it on a sent ticket deletes the old voucher*.pdf/jpg and re-renders the default; QR untouched).
- Files: `voucher.pdf`/`voucher.jpg` = default language (pdf_path always points here); the other language = `voucher.<lang>.pdf`/`.jpg` (`pdf_module.document_names`), rendered on first request by `rules.ensure_document`, refreshed on every consume together with the default (`_regenerate_pdf`).
- Routes: `/vouchers/{id}/pdf?lang=`, `/image?lang=`, `/payment-text?lang=` (422 on bad value); `SendRequest.language` on /resend and /request-payment; first send always uses the default language. New nullable `sendings.language` (startup migration) + `language_display`, shown as a badge in the send history.
- Payment message in the other language uses that language's default terms from settings (the ticket's stored terms are used only when they match).
- Ticket page: "שפת המסמך" toggle (עברית/English, starts on the default) next to the image/PDF toggle; drives preview/PDF links (`a.doc-link`), WA share file, share title, payment text and the language posted with send/resend/payment request. Inline JS syntax-checked with node after render.
- Tests: 93 (second-language document + consume refresh, default language change after send, payment text in other language, ?lang= API routes + resend logging).
- Config backup to OneDrive (/backup) run 2026-10-22 18:43 — no failures.
- Part 3 (same day): system-wide default language on the settings page (`settings.get_default_language`, radio עברית/English). `rules._clean_language(None)` and the new-ticket form / API fall back to it; the form starts with the matching location + terms defaults. 94 tests.

## What Was Done This Session (2026-10-22) — English tickets
- Koby: "allow english vouchers" — keep the Hebrew brand header image, English payment message too.
- New column `vouchers.language` ('he' default / 'en'), added by `database._migrate()` on startup (no manual ALTER needed on the server). Chosen on the new-ticket form (עברית / English toggle), editable on the ticket page while draft/awaiting/paid, frozen on first send (`rules.update_voucher_fields` raises after cement). "EN" marker next to the kind badge in lists.
- `pdf_module._STRINGS` holds every printed string per language; punch circles fill left-to-right on English tickets; header image stays Hebrew. `Voucher.product_title_en`, `is_english`, `language_display` added.
- `rules.payment_request_text` → English message for English tickets (greeting, product, "Price: N ILS", terms, closing).
- (superseded the same day by part 2: language is no longer frozen on send — see above)
- Settings gained English defaults: `default_location_en` ("Hod HaSharon") and `default_terms_en`, editable on /settings/view; `settings.default_location_for()` / `default_terms_for()` pick by language. New-ticket form swaps location + terms to the language default when the language toggle changes (unless the user typed their own). "Make permanent" location on an English ticket updates the English default.
- Visual check done: English voucher (greeting), English 10-entry pass with 3 used, Hebrew voucher unchanged. Admin UI stays Hebrew; notification e-mail to Koby stays Hebrew.
- Deployed the same day: push → server git pull → `systemctl restart vouchers`. No requirements change, no manual DB step (startup migration added the column).

## What Was Done This Session (2026-10-10) — Avigal PIN change
- Avigal's PIN changed (new value = seed in `app/auth.py`, `tests/test_api.py` updated, local `config/auth.json` rehashed (commit 0e0d091, NOT pushed — pushing would deploy the unreleased V2 phase A code).
- Production: only `config/auth.json` rehashed over SSH (backup `config/auth.json.bak-<timestamp>` left next to it), `systemctl restart vouchers` — no `git pull`, V2 code still undeployed. Old PIN verified dead, new PIN verified live.
- 83 tests passing.

## What Was Done This Session (2026-09-13) — V2 phase A
- Design doc `docs/DESIGN-V2-TICKETS.md` written and approved by Koby (decisions: כרטיסיה spelling, payment link first then ticket, vouchers also via GI, price list + discount, GI creates documents, holder locks on first consumed entry, both kinds multi-entry).
- Ticket lifecycle: draft → awaiting_payment → paid → active → used (free ticket: draft → active). Priced tickets cannot be sent before payment.
- Entries table + rules (hold/consume/cancel/walk-in), derived counters, ticket becomes `used` when all entries consumed.
- Manual payment ("סמן כשולם": CASH/BIT/TRANSFER/CARD) — Green Invoice link/webhook is phase B (not started).
- Payment request message text (product, price, terms) sent by WA/email/copy; logged as sendings.kind=PAYMENT_LINK.
- PDF: pass layout ("כרטיסיה — גלים ונפש", N טיפולי וואטסו, על שם, punch circles); multi-entry voucher gets "N טיפולי וואטסו" + circles. Used treatments fill the circles and are listed with date & time; PDF/JPEG regenerated on every consume. Adaptive layout (photo shrink → gap compression) keeps the QR clear. Verified visually (10-entry pass with 7 used, used single voucher, plain voucher unchanged).
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
- Everything is deployed (2026-10-22, three deploys: V2 phase A + English tickets, bilingual documents, settings default language): local = GitHub = production at the "save 2026-10-22 15:45" commit. Nothing pending in code.
- Koby / Avigal: on https://vouchers.soulwaves.org/settings/view choose the default ticket language, fill the price list, the real terms text (Hebrew AND English) and check both default locations; then test on the phone: create a ticket, send the payment request, mark paid, send, resend in the other language via the "שפת המסמך" toggle.
- ⚠️ Seed PINs live in `app/auth.py` in a PUBLIC GitHub repo (now pushed) — consider moving seeds to config/ (git-ignored).
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
