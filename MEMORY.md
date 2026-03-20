# Watsu Gift Voucher System — MEMORY

## What This Project Is
Local Python (FastAPI) app for creating, sending, and tracking Watsu gift vouchers.
V1 = local-only, manual accounting, no external APIs.

## Status
- V1 in active development — Steps 1-7 complete (structure, models, rules, API, QR, PDF, frontend)
- Latest commit: converted frontend to pure Python form handling (2026-03-17)
- All 48 tests passing as of last commit
- Branch: master (main branch exists but master is active)

## Servers
- **Local only** — localhost:8000 (FastAPI + uvicorn)
- No production server yet

## Files and Purpose

### Root
| File | Purpose |
|------|---------|
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
| __init__.py | FastAPI app factory |
| database.py | SQLAlchemy engine, session, Base |
| models.py | SQLAlchemy models: Holder, Voucher, Sending |
| schemas.py | Pydantic schemas for validation |
| rules.py | Business rules engine (cement, send, resend, mark used) |
| utils.py | Utility functions (Fernet key, voucher ID generation) |
| qr_module.py | QR code generation with Fernet encryption |
| pdf_module.py | PDF generation via xhtml2pdf |

### app/routers/ — API Routes
| File | Purpose |
|------|---------|
| holders.py | Holder CRUD endpoints |
| vouchers.py | Voucher CRUD + send/resend/mark-used endpoints |
| reports.py | Report/listing endpoints |
| pages.py | HTML page routes (frontend) |

### templates/ — Jinja2 HTML Templates
| File | Purpose |
|------|---------|
| base.html | Base layout (RTL Hebrew) |
| home.html | Dashboard / home page |
| holder.html | Holder detail + voucher list |
| voucher_view.html | Single voucher view |
| voucher_pdf.html | PDF template for xhtml2pdf |
| report.html | Reports page |

### tests/
| File | Purpose |
|------|---------|
| test_rules.py | Rules engine unit tests (21 tests) |
| test_api.py | API endpoint tests (27 tests) |

### assets/
| File | Purpose |
|------|---------|
| Pool.png | Oval center photo for voucher design |
| voucher-bg.png | Background reference image |

## What Was Done This Session
- No changes made this session — /save triggered at session start

## Next Steps to Resume
- Review definitions #5.docx (untracked file) for any new requirements
- Continue V1 development — frontend testing, end-to-end flow
- Consider adding main.py entry point if not present in __init__.py

## Current Stack
| Discipline | Item | Version |
|---|---|---|
| BACKEND | FastAPI | >=0.115.6 |
| BACKEND | uvicorn | >=0.32.1 |
| DATABASE | SQLite | via SQLAlchemy >=2.0.36 |
| FRONTEND | Jinja2 | >=3.1.4 |
| FRONTEND | HTML/CSS | RTL Hebrew |
| LIBS | xhtml2pdf | >=0.2.16 |
| LIBS | qrcode | >=8.0 |
| LIBS | Pillow | >=11.1.0 |
| LIBS | cryptography | >=43.0.3 |
| LIBS | aiofiles | >=24.1.0 |
| LIBS | python-multipart | >=0.0.12 |
| LANGUAGE | Python | 3.14.3 (3.12+ compatible) |
| DEVOPS | Git | local, no remote |
