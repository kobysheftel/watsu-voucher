# Changelog — Watsu Gift Voucher System

## [Unreleased — V1 in progress]

| Date | Discipline | Item | Old | New | Why | Revert |
|---|---|---|---|---|---|---|
| 2026-03-16 | BACKEND | PDF library | WeasyPrint | xhtml2pdf 0.2.17 | Windows compat, no GTK | pip install WeasyPrint |
| 2026-03-17 | LANGUAGE | Python | 3.12 (planned) | 3.14.3 (installed) | Only version on machine | install py 3.12 from python.org |
| 2026-03-17 | LIBS | Pillow | ==11.0.0 | >=11.1.0 (12.1.1) | No 3.14 wheel for 11.0.0 | pin to ==11.0.0 on Python 3.12 |
| 2026-06-09 | LIBS | All deps | floating `>=` pins | exact pins matching production | Revival: `>=` pulled Starlette 1.2.1, which removed the old `TemplateResponse(name, ctx)` signature → every page 500'd. Pinned to prod set (Starlette 0.52.1 / FastAPI 0.135.1) read from Hetzner; no code changes needed | restore old `requirements.txt` from git history |
| 2026-06-09 | MEDIA | Voucher send format | PDF only | PDF + PNG image (image is default) | New feature: send voucher as image or PDF. PNG is a 3x raster of the existing PDF via PyMuPDF — identical design, scannable QR. New `/vouchers/{id}/image` endpoint + format toggle in voucher view | remove pymupdf, revert pdf_module/vouchers/voucher_view |
| 2026-06-13 | FRONTEND | Voucher PDF text | "איזה כיף קיבלת שובר מתנה" / "{name} מזמין" title; header "גלים ונפש" + "טיפולי וואטסו" | Message "קבלת/קבלתם שובר לטיפול {type}" (auto sing/plural by type); header "גלים ונפש - אביגל מאור" + "וואטסו - פסיכותרפיה - הידרותרפיה - מים פתוחים"; optional per-voucher greeting | Koby's requested content changes 1–3; width-fitting + word-wrap helpers added | git revert pdf_module.py block |
| 2026-06-13 | STORAGE | Voucher image | hardcoded `assets/Pool.png` | Image library `assets/voucher_images/` + `library.json` (default + history); per-voucher one-time override or permanent default; upload/revert UI on voucher page; image cemented on first send | Change 4: changeable voucher image with history; new `app/images.py`, `image_file` column, `set_voucher_image` | git revert; drop `image_file` column; delete assets/voucher_images |
| 2026-06-13 | DATABASE | vouchers table | no greeting/image_file columns | +`greeting`, +`image_file` (TEXT, nullable) via idempotent `_migrate()` in init_db | Support greeting + per-voucher image | `ALTER TABLE vouchers DROP COLUMN greeting; DROP COLUMN image_file` |
| 2026-06-13 | LIBS | pytest + httpx | not in venv | installed (dev/test only) | Needed to run existing test suite (venv lacked them) | pip uninstall pytest httpx |
| 2026-06-14 | NETWORK | Voucher file endpoints cache | default (heuristic browser cache) | `Cache-Control: no-store` on `/{id}/image` + `/{id}/pdf` + `?t=` cache-bust on share fetch | Changing a voucher's image regenerates the PDF/PNG in place at the same URL; browsers/WhatsApp served the stale cached copy, so "changed images" appeared not to apply. Verified backend regen is correct via repro | remove the `headers={"Cache-Control": "no-store"}` args + the `?t=` param |
| 2026-09-09 | MEDIA | Voucher PDF design | reportlab-drawn gradient + rounded photo frame + drawn ornaments + text header | Koby's Word template design: watercolor-wave background image (`assets/voucher-bg-water.png`), brand header image (`assets/header-logo.png`, cut from the original design), oval pool photo (`assets/voucher_images/Pool-oval.png`, new library default), "איזה כיף קיבלת שובר מתנה!" + "טיפול וואטסו ליחיד/זוגי", QR 18 mm centered at the bottom, voucher ID only (no caption) under it. Fonts: David Libre (OFL) added for title/labels, Heebo kept for body | Koby: "this is the format I want for single and couple, add QR, voucher number at the bottom only" | git revert pdf_module.py; set library default back to Pool.png |
| 2026-09-09 | MEDIA | Voucher image send format | voucher.png (PNG raster, ~3 MB with the new watercolor background) | voucher.jpg (JPEG q85, ~300 KB) — `IMAGE_FILENAME` in pdf_module, `/image` endpoint serves image/jpeg, share uses .jpg | WhatsApp-friendly size; PNG cannot compress the watercolor texture | revert generate_image + get_image + voucher_view ext/mime to PNG |

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
