# Changelog — Watsu Gift Voucher System

## [Unreleased — V1 in progress]

| Date | Discipline | Item | Old | New | Why | Revert |
|---|---|---|---|---|---|---|
| 2026-03-16 | BACKEND | PDF library | WeasyPrint | xhtml2pdf 0.2.17 | Windows compat, no GTK | pip install WeasyPrint |
| 2026-03-17 | LANGUAGE | Python | 3.12 (planned) | 3.14.3 (installed) | Only version on machine | install py 3.12 from python.org |
| 2026-03-17 | LIBS | Pillow | ==11.0.0 | >=11.1.0 (12.1.1) | No 3.14 wheel for 11.0.0 | pin to ==11.0.0 on Python 3.12 |

### 2026-03-16 — Step 1: Project Structure
- Created full project folder structure
- requirements.txt with all dependencies
- .gitignore (excludes config/, vouchers/, *.db)
- CLAUDE.md with project rules and terminology
- CHANGELOG.md (this file)
- main.py skeleton

### PDF Library Decision
**Switched from WeasyPrint to xhtml2pdf**
- Reason: Windows compatibility — WeasyPrint requires GTK runtime
- xhtml2pdf works on Windows 11 with no extra system installs
- Trade-off: slightly less CSS support, acceptable for this use case

### Heebo Font
- Fetched from Google Fonts at PDF generation time (online)
- V2 will add local TTF for offline use

### Fernet Key
- Auto-generated on first run
- Stored in config/secret.key
- config/ excluded from git
