# Watsu Gift Voucher System — Project Documentation

**Version:** V1 (Local Python app, manual accounting, no external APIs)
**Generated:** 2026-03-21
**Repository:** [kobysheftel/watsu-voucher](https://github.com/kobysheftel/watsu-voucher)
**Production URL:** https://vouchers.soulwaves.org

---

## Table of Contents

1. [Project Overview & Purpose](#1-project-overview--purpose)
2. [High-Level Architecture & Tech Stack](#2-high-level-architecture--tech-stack)
3. [Setup & Installation](#3-setup--installation)
4. [Configuration & Environment](#4-configuration--environment)
5. [Module / Code-Level Documentation](#5-module--code-level-documentation)
6. [HTML Templates & UI](#6-html-templates--ui)
7. [Data & Storage](#7-data--storage)
8. [API Reference](#8-api-reference)
9. [Testing](#9-testing)
10. [Deployment & Operations](#10-deployment--operations)
11. [Security, Performance & Limitations](#11-security-performance--limitations)
12. [Known Issues, Roadmap & Future Work](#12-known-issues-roadmap--future-work)
13. [Glossary & External References](#13-glossary--external-references)

---

## 1. Project Overview & Purpose

### What the System Does

The Watsu Gift Voucher System is a web application for creating, managing, sending, and tracking gift vouchers for **"גלים ונפש" (Waves & Soul)** — a Watsu (water Shiatsu) therapy business in Israel.

### Real-World Problem

The business owner (Avigal) needs to:
- Create gift vouchers for customers (orderers) who buy them for others
- Send vouchers via WhatsApp, email, or print
- Track which vouchers have been sent, redeemed, and by whom
- Generate PDF voucher documents with Hebrew text, QR codes, and branding
- Manage basic accounting (receipt numbers, dates)

### Main User Flow

```
1. Admin logs in (PIN or biometric)
2. Creates an orderer (by mobile number)
3. Creates a draft voucher for that orderer
4. Sends the voucher (via WA/email/print) → cements holder data, generates QR + PDF
5. Can resend the voucher at any time
6. Marks voucher as "used" when redeemed → fully frozen
```

### Key Features

- **Orderer management:** Create and edit orderers identified by Israeli mobile numbers
- **Voucher lifecycle:** draft → sent → used, with strict business rules
- **PDF generation:** Beautiful A5 water-blue gradient voucher with Hebrew text, pool photo, QR code
- **QR codes:** Fernet-encrypted payload for future scanning/redemption
- **WhatsApp sharing:** Native share API on mobile, wa.me fallback on desktop
- **Biometric auth:** WebAuthn + PIN login with 15-minute inactivity lock
- **PWA:** Installable on smartphones (manifest + service worker)
- **Reports:** Filterable report with CSV export (UTF-8 BOM for Excel Hebrew support)
- **RTL Hebrew UI:** Bootstrap 5 RTL with full Hebrew interface

---

## 2. High-Level Architecture & Tech Stack

### Architecture Diagram

```
                    ┌───────────────────────────┐
                    │   Browser (Hebrew RTL)     │
                    │   Jinja2 HTML templates    │
                    │   Bootstrap 5 RTL (CDN)    │
                    └───────────┬───────────────┘
                                │ HTTP
                    ┌───────────┴───────────────┐
                    │   FastAPI (main.py)        │
                    │   AuthMiddleware           │
                    │   uvicorn ASGI server      │
                    ├───────────────────────────┤
                    │   Routers:                 │
                    │     auth, holders,          │
                    │     vouchers, reports,      │
                    │     pages                   │
                    ├───────────────────────────┤
                    │   Rules Engine (rules.py)  │
                    │   Business logic layer      │
                    ├───────────────────────────┤
                    │   SQLAlchemy ORM           │
                    │   SQLite (vouchers.db)     │
                    ├───────────────────────────┤
                    │   PDF (reportlab + bidi)   │
                    │   QR (qrcode + Fernet)     │
                    └───────────────────────────┘
                                │
                    ┌───────────┴───────────────┐
                    │   File System              │
                    │   vouchers/{mobile}/{id}/   │
                    │     voucher.pdf, qr.png     │
                    └───────────────────────────┘
```

### What Runs Where

| Component | Local Dev | Production (Hetzner) |
|-----------|-----------|---------------------|
| Python | 3.14 | 3.12 (venv) |
| Web server | uvicorn direct | nginx → uvicorn:8100 |
| Database | SQLite file | SQLite file |
| SSL | None (HTTP) | certbot (HTTPS) |
| Service | manual | systemd |

### Full Tech Stack

| Discipline | Item | Version |
|---|---|---|
| BACKEND | FastAPI | >= 0.115.6 |
| BACKEND | uvicorn | >= 0.32.1 |
| DATABASE | SQLite | via SQLAlchemy >= 2.0.36 |
| FRONTEND | Jinja2 | >= 3.1.4 |
| FRONTEND | Bootstrap 5 RTL | 5.3.2 (CDN) |
| LIBS | reportlab | >= 4.0 |
| LIBS | python-bidi | >= 0.6.0 |
| LIBS | qrcode | >= 8.0 |
| LIBS | Pillow | >= 11.1.0 |
| LIBS | cryptography | >= 43.0.3 |
| LIBS | webauthn (py_webauthn) | >= 2.0.0 |
| LIBS | aiofiles | >= 24.1.0 |
| LIBS | python-multipart | >= 0.0.12 |
| AUTH | WebAuthn + PIN | 15-min inactivity timeout |
| PWA | manifest + service worker | network-first caching |
| LANGUAGE | Python | 3.12 (server), 3.14 (local) |
| DEVOPS | Git + GitHub | kobysheftel/watsu-voucher |
| DEVOPS | systemd + nginx | Hetzner Ubuntu |
| DEVOPS | certbot | SSL auto-renew |

---

## 3. Setup & Installation

### Prerequisites

- Python 3.12+ installed
- Git
- pip (Python package manager)

### Local Development Setup

```bash
# 1. Clone the repository
git clone https://github.com/kobysheftel/watsu-voucher.git
cd watsu-voucher

# 2. Create and activate virtual environment
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the development server
uvicorn main:app --reload --port 8000

# 5. Open browser
# http://localhost:8000
# First run: you'll be redirected to /auth/setup to create a PIN
```

### Required Asset Files

The following files must exist in `assets/`:

| File | Purpose |
|------|---------|
| `Pool.png` | Pool photo embedded in voucher PDF |
| `voucher-bg.png` | Background reference image |
| `fonts/Heebo-Variable.ttf` | Hebrew font for PDF generation |

### Auto-Generated on First Run

| File | Location | Purpose |
|------|----------|---------|
| `secret.key` | `config/` | Fernet encryption key for QR codes |
| `auth.json` | `config/` | PIN hash + WebAuthn credentials |
| `vouchers.db` | project root | SQLite database |

---

## 4. Configuration & Environment

### Config Files

| File | Location | Git-tracked | Purpose |
|------|----------|-------------|---------|
| `config/secret.key` | `config/` | NO (.gitignore) | Fernet encryption key — auto-generated |
| `config/auth.json` | `config/` | NO (.gitignore) | PIN hash, WebAuthn credentials, sessions |
| `vouchers.db` | project root | NO (.gitignore) | SQLite database |
| `requirements.txt` | project root | YES | Python dependencies |

### Database URL

Hardcoded in `app/database.py`:
```python
DATABASE_URL = "sqlite:///./vouchers.db"
```

### WebAuthn Configuration

Hardcoded in `app/routers/auth.py`:
```python
RP_ID = "vouchers.soulwaves.org"
RP_NAME = "Watsu Vouchers"
ORIGIN = "https://vouchers.soulwaves.org"
```

> **Note:** WebAuthn only works on the production domain (HTTPS required). For local development, use PIN login only.

### Session Configuration

In `app/auth.py`:
```python
SESSION_MAX_AGE = 15 * 60  # 15 minutes inactivity timeout
SESSION_COOKIE_NAME = "voucher_session"
```

Sessions are stored in-memory (single-user, single-process design). Server restart clears all sessions.

---

## 5. Module / Code-Level Documentation

### `main.py` — Application Entry Point

**Purpose:** FastAPI app factory with middleware, router registration, and static file mounts.

**Key components:**
- `AuthMiddleware` — redirects unauthenticated requests to `/auth/login`
- Public paths: `/auth/*`, `/static/*`, `/assets/*`, `/docs`, `/openapi.json`
- Root `/` redirects to `/all-vouchers/view`
- Static file mounts: `/static`, `/assets`, `/files` (voucher PDFs/QR images)

**Run command:**
```bash
uvicorn main:app --reload --port 8000
```

---

### `app/database.py` — Database Setup

**Purpose:** SQLAlchemy engine, session factory, and DB initialization.

**Key functions:**

| Function | Parameters | Returns | Description |
|----------|-----------|---------|-------------|
| `init_db()` | None | None | Creates all tables via `Base.metadata.create_all()`. Called on app startup. |
| `get_db()` | None | `Session` (generator) | FastAPI dependency — yields a DB session, closes when done. |

---

### `app/models.py` — ORM Models

**Purpose:** SQLAlchemy table definitions for the three core tables.

#### `Holder` — Orderer/Customer

| Column | Type | Description |
|--------|------|-------------|
| `mobile` | Text (PK) | Israeli mobile 05X-XXXXXXX (10 digits) |
| `name` | Text | Full name |
| `email` | Text (nullable) | Email address |
| `created_at` | DateTime | Creation timestamp |
| `updated_at` | DateTime | Last update timestamp |

**Relationship:** `vouchers` — all vouchers linked to this holder (via mobile text match).

**Editability rule:** Editable while all vouchers are draft/sent. Locked if any voucher is `used`.

#### `Voucher` — Gift Voucher

| Column | Type | Description |
|--------|------|-------------|
| `voucher_id` | Text (PK) | Format: `{mobile}-{sequence:03d}` e.g. `0541234567-001` |
| `mobile` | Text | Reference to holder's mobile (not a live FK) |
| `sequence` | Integer | Position in holder's voucher sequence |
| `voucher_type` | Text | `"יחיד"` (single) or `"זוגי"` (couple) |
| `valid_until` | Date | Expiry date |
| `issued_at` | DateTime | Creation timestamp |
| `first_sent_at` | DateTime (nullable) | Set once on first send, never changes |
| `status` | Text | `"draft"` / `"sent"` / `"used"` |
| `display_name` | Text (nullable) | Custom name on PDF (if empty, shows generic text) |
| `receipt_number` | Text (nullable) | Manual accounting field |
| `receipt_date` | Date (nullable) | Manual accounting field |
| `notes` | Text (nullable) | Free-text notes |
| `qr_path` | Text (nullable) | Path to QR PNG file (set on first send) |
| `pdf_path` | Text (nullable) | Path to PDF file (updated every send/resend) |
| `holder_name` | Text (nullable) | Cemented snapshot — copied from Holder on first send |
| `holder_mobile` | Text (nullable) | Cemented snapshot |
| `holder_email` | Text (nullable) | Cemented snapshot |

**Properties:**
- `is_frozen` — True when status == "used"
- `is_cemented` — True when first_sent_at is not None

#### `Sending` — Send/Resend Event Log

| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer (PK) | Auto-increment |
| `voucher_id` | Text (FK) | References vouchers.voucher_id |
| `sent_at` | DateTime | Timestamp of send event |
| `sent_via` | Text | `"WA"` / `"EMAIL"` / `"PRINT"` |
| `note` | Text (nullable) | Optional note about the send |

**Never updated — only inserted.** Each send/resend creates a new row.

**Display labels:**
| Value | Display |
|-------|---------|
| `WA` | 📱 וואטסאפ |
| `EMAIL` | 📧 מייל |
| `PRINT` | 🖨️ הדפסה |

---

### `app/schemas.py` — Pydantic Validation Schemas

**Purpose:** Request/response validation for all API endpoints.

**Key schemas:**

| Schema | Type | Description |
|--------|------|-------------|
| `HolderCreate` | Request | mobile (validated Israeli format), name, email |
| `HolderUpdate` | Request | name, email (optional) |
| `HolderOut` | Response | Full holder data + `can_edit` flag |
| `VoucherCreate` | Request | mobile, voucher_type (יחיד/זוגי), valid_until (not in past) |
| `VoucherUpdate` | Request | receipt_number, receipt_date, notes |
| `VoucherOut` | Response | Full voucher + cemented data + computed flags + sendings list |
| `VoucherListItem` | Response | Compact row for table views |
| `SendRequest` | Request | sent_via (WA/EMAIL/PRINT), note |
| `SendingOut` | Response | Single sending event with display label |
| `SearchResult` | Response | Flat row for search/report results |

**Mobile validation:** Strips separators, validates `05XXXXXXXX` (10 digits).

---

### `app/rules.py` — Business Rules Engine

**Purpose:** Single source of truth for all business logic. HTTP-agnostic — receives a DB session, returns ORM objects.

**Key functions:**

| Function | Parameters | Returns | Description |
|----------|-----------|---------|-------------|
| `can_edit_holder(db, mobile)` | Session, str | bool | True if no vouchers are "used" |
| `get_or_create_holder(db, mobile, name, email)` | Session, str, str, str\|None | (Holder, bool) | Creates or retrieves holder |
| `update_holder(db, mobile, name, email)` | Session, str, str\|None, str\|None | Holder | Updates holder; raises RulesError if locked |
| `next_sequence(db, mobile)` | Session, str | int | Next sequence number for a mobile |
| `create_voucher(db, mobile, type, valid_until, ...)` | Session, ... | Voucher | Creates draft voucher |
| `first_send(db, voucher_id, sent_via, note)` | Session, str, str, str\|None | Voucher | Full first-send sequence (cement + QR + PDF + log) |
| `resend(db, voucher_id, sent_via, note)` | Session, str, str, str\|None | Voucher | Resend (reuse QR, new PDF, new log entry) |
| `mark_used(db, voucher_id)` | Session, str | Voucher | Freeze voucher permanently |
| `update_voucher_fields(db, voucher_id, ...)` | Session, str, ... | Voucher | Update receipt/notes (blocked if used) |

**Status transition rules:**

```
draft ──[first_send]──► sent ──[mark_used]──► used
                          │                    (frozen)
                          └──[resend]──► sent
```

**Cementing:** On first send, holder details (name, mobile, email) are copied into the voucher's `cemented_*` fields. These never change again, even if the holder is later edited.

**Custom exception:** `RulesError` — raised for all business rule violations.

---

### `app/qr_module.py` — QR Code Generation

**Purpose:** Generate Fernet-encrypted QR codes for voucher verification.

**Payload format:**
```json
{"id": "0541234567-001", "ts": "2026-03-21 12:00:00"}
```

**Key functions:**

| Function | Parameters | Returns | Description |
|----------|-----------|---------|-------------|
| `generate_qr(voucher, folder)` | Voucher, Path | Path | Generates encrypted QR PNG. Called ONCE per voucher. |
| `decrypt_qr(token)` | str | dict | Decrypts a QR token back to `{id, ts}` payload |

**Encryption:**
- Fernet symmetric encryption (from `cryptography` library)
- Key auto-generated on first run, saved to `config/secret.key`
- QR image: auto-sized, M-level error correction, 6px box size

---

### `app/pdf_module.py` — PDF Generation

**Purpose:** Generate A5 voucher PDFs with Hebrew text using reportlab + python-bidi.

> **Design decision:** xhtml2pdf was abandoned because it cannot render Hebrew glyphs. Reportlab with python-bidi handles RTL text correctly.

**Layout (top to bottom):**
1. Water-blue gradient background (3-color blend)
2. "גלים ונפש" header in teal (30pt)
3. "טיפולי וואטסו" subtitle (14pt)
4. Wavy decorative line
5. Pool photo (rounded, centered, with white frame)
6. Personalized or anonymous title:
   - With `display_name`: "איזה כיף / {name} מזמין אותך לטיפול [זוגי]"
   - Without: "איזה כיף קיבלת שובר מתנה / טיפול וואטסו {type}"
7. Ornamental divider (lines + diamond)
8. Treatment description (3 lines)
9. Contact info: "אביגל 050-4014696"
10. Expiry date
11. QR code (small, centered)
12. Voucher ID + receipt number (bottom, 6pt)

**Key function:**

| Function | Parameters | Returns | Description |
|----------|-----------|---------|-------------|
| `generate_pdf(voucher, folder)` | Voucher, Path | Path | Generates A5 PDF, returns saved path |

**Font:** Heebo (Hebrew variable font) from `assets/fonts/Heebo-Variable.ttf`. Registered once per process.

**Color palette:**

| Name | Hex | Usage |
|------|-----|-------|
| TEAL | #2a7f8e | Main title |
| TEAL_DARK | #1a5f6e | Subtitles, emphasis |
| WARM | #5a4a3a | Body text |
| GREY | #666666 | Secondary text |
| LGREY | #999999 | Footer text |
| BG_TOP | #d4eef2 | Gradient top |
| BG_MID | #e8f4f0 | Gradient middle |
| BG_BOT | #dce8e4 | Gradient bottom |
| ORNAMENT | #7ab5b0 | Decorative elements |

---

### `app/auth.py` — Authentication Module

**Purpose:** PIN + WebAuthn biometric authentication for single-user admin access.

**Key functions:**

| Function | Parameters | Returns | Description |
|----------|-----------|---------|-------------|
| `hash_pin(pin)` | str | dict | Creates salted SHA-256 hash |
| `verify_pin(pin, pin_data)` | str, dict | bool | Verifies PIN against stored hash |
| `is_setup_complete()` | None | bool | True if PIN has been configured |
| `save_pin(pin)` | str | None | Hash and store PIN to auth.json |
| `check_pin(pin)` | str | bool | Verify PIN against stored credentials |
| `get_webauthn_credentials()` | None | list | Get stored WebAuthn credentials |
| `save_webauthn_credential(cred)` | dict | None | Add a WebAuthn credential |
| `create_session(response)` | Response | str | Create session + set cookie |
| `is_authenticated(request)` | Request | bool | Check session validity (sliding window) |
| `logout(response)` | Response | None | Clear session |

**Session design:**
- In-memory dict (`_sessions: dict[str, float]`)
- Sliding window: timeout resets on every authenticated request
- 15-minute inactivity timeout
- Cookie: `voucher_session`, httponly, samesite=lax

---

### `app/utils.py` — Utilities

**Purpose:** Shared utility functions.

| Function | Returns | Description |
|----------|---------|-------------|
| `utcnow()` | `datetime` | Current UTC time as naive datetime (SQLite-compatible) |

---

## 6. HTML Templates & UI

All templates use Jinja2 with Bootstrap 5 RTL (CDN). The UI is fully in Hebrew (RTL).

### `templates/base.html` — Base Layout

- Bootstrap 5.3.2 RTL (CDN)
- PWA manifest link + service worker registration
- Inactivity lock (15-minute JS timer, redirects to `/auth/logout`)
- Top navbar with navigation and logout button
- Flash message display (from URL params `?flash=...&flash_type=...`)
- POST-Redirect-GET pattern throughout

### `templates/all_vouchers.html` — Main Screen

- All vouchers table with sortable/filterable columns
- Excel-like column filters (status, type, orderer)
- "שובר חדש" (new voucher) button
- Inline status badges (color-coded)
- Links to voucher detail pages

### `templates/home.html` — Dashboard

- Stats cards (total, draft, sent, used, orderers)
- Orderer search form (by name, phone, or email)
- Search results list with links to orderer pages

### `templates/new_voucher.html` — New Voucher (Full Page)

- Smart orderer search: phone lookup, pick from list, or create new
- Voucher form: type (יחיד/זוגי), expiry (default: 6 months), display name, receipt number, receipt date, notes
- Creates orderer if needed + creates draft voucher in one flow

### `templates/holder.html` — Orderer Detail

- Orderer info card (name, mobile, email) with edit capability
- All vouchers for this orderer in a table
- Inline actions per voucher
- New voucher modal for this orderer

### `templates/voucher_view.html` — Voucher Detail

- Full voucher info: ID, status, type, dates, cemented holder data
- Action buttons (context-sensitive based on status):
  - Draft: Send (WA/Email/Print)
  - Sent: Resend, Mark Used, View PDF
  - Used: View PDF (read-only)
- WhatsApp sharing: `navigator.share()` on mobile, `wa.me` link on desktop
- Sending history table
- Receipt/notes edit form (blocked when used)
- QR code display

### `templates/orderers.html` — All Orderers

- List of all orderers with voucher counts
- Links to individual orderer pages

### `templates/report.html` — Filterable Report

- Filter by: status, type, date range, receipt number
- Results table
- CSV export button (UTF-8 BOM for Excel Hebrew)

### `templates/login.html` — Login Page

- Biometric login button (WebAuthn, if credential registered)
- PIN fallback (4-6 digits)
- Error messages

### `templates/setup.html` — First-Time Setup

- Step 1: PIN creation (4-6 digits with confirmation)
- Step 2: Biometric registration (optional WebAuthn)

### `templates/voucher_pdf.html` — PDF Template (Reference Only)

Reference HTML template — not actually used (reportlab generates PDFs directly).

---

## 7. Data & Storage

### Database Schema

```
┌──────────────┐     ┌──────────────────────┐     ┌──────────────┐
│   holders     │     │      vouchers         │     │   sendings    │
├──────────────┤     ├──────────────────────┤     ├──────────────┤
│ mobile (PK)  │◄─ ─ │ mobile (text ref)     │     │ id (PK)      │
│ name         │     │ voucher_id (PK)       │◄────│ voucher_id   │
│ email        │     │ sequence              │     │ sent_at      │
│ created_at   │     │ voucher_type          │     │ sent_via     │
│ updated_at   │     │ valid_until           │     │ note         │
│              │     │ issued_at             │     └──────────────┘
│              │     │ first_sent_at         │
│              │     │ status                │
│              │     │ display_name          │
│              │     │ receipt_number        │
│              │     │ receipt_date          │
│              │     │ notes                 │
│              │     │ qr_path              │
│              │     │ pdf_path             │
│              │     │ holder_name (cemented)│
│              │     │ holder_mobile (cem.)  │
│              │     │ holder_email (cem.)   │
│              │     └──────────────────────┘
└──────────────┘
```

> **Design note:** `vouchers.mobile` is a plain text reference to `holders.mobile`, NOT a live foreign key. This ensures voucher history survives even if holder deletion is ever added.

### File Storage

```
vouchers/
  {mobile}/
    {voucher_id}/
      voucher.pdf      # Generated on every send/resend
      qr.png           # Generated ONCE on first send, reused forever
```

### Data Flow

```
Browser form → POST → FastAPI router → rules.py → SQLAlchemy → SQLite
                                          │
                                          ├─► qr_module.py → qr.png
                                          └─► pdf_module.py → voucher.pdf
                                                                │
                                                     response ◄─┘
```

---

## 8. API Reference

### JSON API Endpoints

#### Holders

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/holders` | Create or retrieve holder by mobile |
| `GET` | `/holders/{mobile}` | Holder details + all vouchers |
| `PUT` | `/holders/{mobile}` | Update name/email (blocked if has used voucher) |

#### Vouchers

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/vouchers` | Create new draft voucher |
| `GET` | `/vouchers` | List all vouchers (filterable: status, mobile, type, receipt, dates) |
| `GET` | `/vouchers/{id}` | Full voucher details + sending history |
| `PUT` | `/vouchers/{id}` | Update receipt/notes (blocked if used) |
| `PUT` | `/vouchers/{id}/send` | First send (cement + QR + PDF + log) |
| `PUT` | `/vouchers/{id}/resend` | Resend (reuse QR, new PDF, new log) |
| `PUT` | `/vouchers/{id}/use` | Mark used (freeze) |
| `GET` | `/vouchers/{id}/pdf` | Serve PDF file |
| `GET` | `/vouchers/{id}/qr` | Serve QR image |
| `GET` | `/vouchers/{id}/sendings` | Full sending history |

#### Reports & Search

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/search?q=...` | Search by name, mobile, email, voucher ID |
| `GET` | `/report` | Full report with filters; `?fmt=csv` for CSV export |
| `GET` | `/home/data` | Dashboard stats (total, draft, sent, used, holders) |

### HTML Form Endpoints (POST-Redirect-GET)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/form/holders/new` | Create holder via form |
| `POST` | `/form/holders/{mobile}/edit` | Update holder via form |
| `POST` | `/form/vouchers/new` | Create voucher (holder must exist) |
| `POST` | `/form/vouchers/new-full` | Create orderer + voucher in one step |
| `POST` | `/form/vouchers/{id}/send` | Send or resend (auto-detects status) |
| `POST` | `/form/vouchers/{id}/use` | Mark used |
| `POST` | `/form/vouchers/{id}/notes` | Update receipt/notes |

### Auth Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/auth/login` | Login page |
| `POST` | `/auth/login/pin` | PIN login |
| `GET` | `/auth/setup` | First-time setup page |
| `POST` | `/auth/setup` | Save PIN |
| `GET` | `/auth/setup/biometric` | Biometric registration page |
| `GET` | `/auth/logout` | Logout |
| `POST` | `/auth/webauthn/register/options` | WebAuthn registration options |
| `POST` | `/auth/webauthn/register/verify` | WebAuthn registration verify |
| `POST` | `/auth/webauthn/login/options` | WebAuthn login options |
| `POST` | `/auth/webauthn/login/verify` | WebAuthn login verify |

### Interactive API Docs

FastAPI auto-generates Swagger UI at `/docs` (accessible without auth).

---

## 9. Testing

### Test Suite

- **48 tests total** (21 rules engine + 27 API endpoint tests)
- All tests use in-memory SQLite — no files touched on disk
- API tests include auth fixture (auto-creates PIN + session)

### Running Tests

```bash
# All tests
python -m pytest tests/ -v

# Rules engine only
python -m pytest tests/test_rules.py -v

# API endpoints only
python -m pytest tests/test_api.py -v
```

### Test Files

#### `tests/test_rules.py` — Rules Engine Tests (21 tests)

Tests business logic directly via `rules.py` functions:

- Holder CRUD: create, retrieve, update, blocked-when-used
- Voucher creation: sequential IDs, no-holder error
- First send: cementing, logging, draft-only, cement survives holder edit
- Resend: new log row, first_sent_at unchanged, blocked on draft/used
- Mark used: status change, draft-blocked, double-use blocked
- Update fields: receipt update, blocked-when-used

#### `tests/test_api.py` — API Endpoint Tests (27 tests)

Tests HTTP endpoints via FastAPI TestClient:

- Holder endpoints: create, retrieve, get-with-vouchers, not-found, update, blocked, validation
- Voucher CRUD: create, no-holder, list, filter, get, not-found, receipt update, blocked
- Send/resend/use: first send, resend, mark used, resend-after-used blocked
- Sending history: multiple sends, display labels
- Search & report: by name, no results, JSON, CSV, home data

### Manual Testing

1. Start the server: `uvicorn main:app --reload --port 8000`
2. Open `http://localhost:8000` in a browser
3. Complete initial setup (PIN)
4. Create a holder → create a voucher → send → resend → mark used
5. Test WhatsApp sharing from a mobile device connected to the same network

---

## 10. Deployment & Operations

### Production Server

- **Host:** Hetzner Cloud (Ubuntu)
- **Domain:** vouchers.soulwaves.org
- **SSH:** `ssh -i ~/.ssh/Hetzner_new root@iceland.soulwaves.org`
- **App path:** `/var/www/sites/vouchers/`
- **Python venv:** `/var/www/sites/vouchers/venv/`
- **Service:** systemd (`vouchers`)
- **Reverse proxy:** nginx → uvicorn on port 8100
- **SSL:** certbot with auto-renewal

### Deploy Workflow

```bash
# 1. Push changes locally
git push origin master

# 2. SSH to server
ssh -i ~/.ssh/Hetzner_new root@iceland.soulwaves.org

# 3. Pull and restart
cd /var/www/sites/vouchers
git pull
systemctl restart vouchers

# 4. For DB schema changes: run ALTER TABLE before restart
```

### Backup

**Daily backup script:** `backup.bat` (Windows scheduled task at 23:00)

Backs up:
- `vouchers/` directory (PDFs, QR images) → `backup/vouchers/`
- `*.db` (SQLite database) → `backup/`

```batch
robocopy "%SRC%\vouchers" "%DST%\vouchers" /MIR
robocopy "%SRC%" "%DST%" *.db
```

### Logs

- **uvicorn logs:** stdout (captured by systemd journal on production)
- **View server logs:** `journalctl -u vouchers -f`
- **Backup log:** `backup/backup.log`

### Common Operations

| Task | Command |
|------|---------|
| Start dev server | `uvicorn main:app --reload --port 8000` |
| Restart production | `systemctl restart vouchers` |
| View production logs | `journalctl -u vouchers -f` |
| Check production status | `systemctl status vouchers` |
| Run tests | `python -m pytest tests/ -v` |

---

## 11. Security, Performance & Limitations

### Security

- **Authentication:** PIN (4-6 digits, salted SHA-256) + WebAuthn biometric
- **Session:** HTTP-only cookie, samesite=lax, 15-minute sliding timeout
- **QR encryption:** Fernet symmetric encryption (prevents token forgery)
- **Sensitive files:** `config/`, `vouchers/`, `*.db` excluded from git
- **HTTPS:** enforced on production via certbot
- **Session storage:** in-memory (cleared on server restart)

### Performance

- **SQLite:** adequate for single-user, low-volume use case
- **In-memory sessions:** O(1) lookup, no DB overhead
- **PDF generation:** reportlab is fast (~100ms per voucher)
- **Service worker:** network-first strategy with offline fallback
- **CDN:** Bootstrap loaded from CDN (reduces server load)

### Known Limitations

- **Single user:** designed for one admin user; no multi-user support
- **In-memory sessions:** lost on server restart (user must re-login)
- **WebAuthn:** requires HTTPS (production only; PIN for local dev)
- **No email sending:** records email as a sending method but doesn't actually send emails
- **SQLite:** not suitable for concurrent writes (adequate for single-user)
- **No API authentication:** JSON API endpoints share session auth (no API keys/tokens)
- **Hardcoded WebAuthn origin:** `vouchers.soulwaves.org` is hardcoded; local dev cannot use biometric

---

## 12. Known Issues, Roadmap & Future Work

### Current Issues

- No actual email sending (records only)
- WebAuthn configuration hardcoded to production domain
- PDF design may need further polish

### Roadmap

| Version | Description |
|---------|-------------|
| **V1** (current) | Local Python app, manual accounting, no external APIs |
| **V2** | Green Invoice API integration (automated invoicing) |
| **V3** | JS/browser version (client-side, no Python backend) |

### Planned Improvements

- Voucher ID = receipt number integration
- PDF design polish (additional branding, logo/wave graphics)
- QR code scanning for redemption
- Actual email sending capability
- Configuration file for WebAuthn RP_ID/ORIGIN (dev vs. production)

---

## 13. Glossary & External References

### Key Terms

| Term (Hebrew) | English | Description |
|-------|---------|-------------|
| מזמין | Orderer | Person who buys/orders vouchers |
| שובר | Voucher | Gift voucher document |
| צימנט (Cement) | Cement | Copy holder details into voucher on first send — frozen forever |
| טיוטה (Draft) | Draft | Initial voucher state before sending |
| נשלח (Sent) | Sent | Voucher has been sent at least once |
| מומש (Used) | Used/Redeemed | Final state — completely frozen |
| יחיד | Single | Single-person treatment voucher |
| זוגי | Couple | Couple treatment voucher |
| וואטסו | Watsu | Water Shiatsu — aquatic therapy |
| גלים ונפש | Waves & Soul | Business name |

### External References

| Resource | URL |
|----------|-----|
| FastAPI docs | https://fastapi.tiangolo.com/ |
| SQLAlchemy docs | https://docs.sqlalchemy.org/ |
| reportlab user guide | https://docs.reportlab.com/ |
| python-bidi | https://pypi.org/project/python-bidi/ |
| py_webauthn | https://pypi.org/project/webauthn/ |
| Fernet encryption | https://cryptography.io/en/latest/fernet/ |
| Bootstrap 5 RTL | https://getbootstrap.com/docs/5.3/getting-started/rtl/ |
| PWA docs | https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps |
