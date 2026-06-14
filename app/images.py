"""
Image library — manages the gallery of images that can appear on vouchers.

Storage layout:
    assets/voucher_images/
        library.json        ← manifest: default image + history list
        Pool.png            ← seed image (copied from assets/Pool.png)
        <uploaded files...>

The manifest is the single source of truth for:
  - which image is the current default (used by NEW vouchers)
  - the full history/gallery of available images (for re-selection / revert)

All reads and writes go through this module so callers never touch the
manifest directly. The folder is served publicly at /assets/voucher_images/
(see the /assets mount in main.py), so templates can show thumbnails.
"""

import json
import re
import shutil
from pathlib import Path

from PIL import Image  # used only to validate uploaded files are real images

from app.utils import utcnow

# ── Paths ──────────────────────────────────────────────────────────────────────
_LIB_DIR     = Path("assets/voucher_images")          # gallery folder
_MANIFEST    = _LIB_DIR / "library.json"              # manifest file
_SEED_IMAGE  = Path("assets/Pool.png")                # original default image
_FALLBACK    = Path("assets/Pool.png")                # last-resort image path

# Upload constraints
_MAX_BYTES   = 8 * 1024 * 1024                         # 8 MB cap per image
_ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp"}      # accepted extensions


# ── Bootstrap ────────────────────────────────────────────────────────────────

def _ensure_lib() -> None:
    """
    Create the library folder + manifest on first use.
    Seeds the gallery with the existing assets/Pool.png as the default.
    Idempotent — safe to call on every access.
    """
    _LIB_DIR.mkdir(parents=True, exist_ok=True)

    # Copy the seed image into the library if it is not there yet.
    seed_name = "Pool.png"
    seed_dest = _LIB_DIR / seed_name
    if not seed_dest.exists() and _SEED_IMAGE.exists():
        shutil.copyfile(_SEED_IMAGE, seed_dest)

    # Create the manifest if missing.
    if not _MANIFEST.exists():
        manifest = {
            "default": seed_name,
            "images": [
                {
                    "file": seed_name,
                    "label": "ברירת מחדל",
                    "added_at": utcnow().isoformat(),
                }
            ],
        }
        _write_manifest(manifest)


def _read_manifest() -> dict:
    """Read and return the manifest dict (bootstraps the library first)."""
    _ensure_lib()
    return json.loads(_MANIFEST.read_text(encoding="utf-8"))


def _write_manifest(manifest: dict) -> None:
    """Write the manifest dict back to disk (pretty-printed, UTF-8)."""
    _MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ── Public API ──────────────────────────────────────────────────────────────

def list_images() -> list[dict]:
    """Return the gallery/history list (each item: file, label, added_at)."""
    return _read_manifest().get("images", [])


def get_default() -> str:
    """Return the filename of the current default image."""
    return _read_manifest().get("default", "Pool.png")


def set_default(file: str) -> None:
    """
    Make an existing library image the new default (for future vouchers).
    Raises ValueError if the file is not in the library.
    """
    manifest = _read_manifest()
    known = {img["file"] for img in manifest.get("images", [])}
    if file not in known:
        raise ValueError(f"תמונה לא קיימת בספרייה: {file}")
    manifest["default"] = file
    _write_manifest(manifest)


def image_path(file: str | None) -> Path:
    """
    Return the filesystem path for a library image filename.
    Falls back to assets/Pool.png if the file is missing/unknown.
    """
    if file:
        p = _LIB_DIR / file
        if p.exists():
            return p
    return _FALLBACK


def add_image(data: bytes, orig_name: str, label: str | None = None) -> str:
    """
    Validate and store an uploaded image, append it to the manifest history.
    Returns the stored filename.

    Validation:
      - size <= _MAX_BYTES
      - extension in _ALLOWED_EXT
      - Pillow can actually open it (real image, not a renamed file)
      - filename sanitised (no path traversal) and de-duplicated
    """
    if not data:
        raise ValueError("קובץ ריק")
    if len(data) > _MAX_BYTES:
        raise ValueError("הקובץ גדול מדי (מקסימום 8MB)")

    ext = Path(orig_name).suffix.lower()
    if ext not in _ALLOWED_EXT:
        raise ValueError("סוג קובץ לא נתמך — יש להעלות PNG / JPG / WEBP")

    # Verify the bytes are a real, decodable image.
    import io
    try:
        Image.open(io.BytesIO(data)).verify()
    except Exception:
        raise ValueError("הקובץ אינו תמונה תקינה")

    _ensure_lib()

    # Sanitise the base name: keep only safe chars, strip any path parts.
    stem = Path(orig_name).stem
    safe = re.sub(r"[^A-Za-z0-9_\-]", "_", stem) or "image"
    filename = f"{safe}{ext}"

    # De-duplicate against existing files in the folder.
    dest = _LIB_DIR / filename
    counter = 1
    while dest.exists():
        filename = f"{safe}_{counter}{ext}"
        dest = _LIB_DIR / filename
        counter += 1

    dest.write_bytes(data)

    # Append to the manifest history.
    manifest = _read_manifest()
    manifest.setdefault("images", []).append({
        "file": filename,
        "label": label or stem,
        "added_at": utcnow().isoformat(),
    })
    _write_manifest(manifest)

    return filename
