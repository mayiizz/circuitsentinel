"""Upload and analysis configuration from the environment."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
UPLOAD_DIR = PROJECT_ROOT / "uploads"

DEFAULT_MAX_UPLOAD_MB = 20

SUPPORTED_EXTENSIONS = frozenset(
    {".kicad_sch", ".pdf", ".png", ".jpg", ".jpeg", ".webp"}
)

# MIME types accepted for each extension. Clients often send application/octet-stream.
ALLOWED_MIME_BY_EXT: dict[str, frozenset[str]] = {
    ".kicad_sch": frozenset(
        {
            "application/octet-stream",
            "text/plain",
            "application/x-kicad-schematic",
        }
    ),
    ".pdf": frozenset({"application/pdf", "application/octet-stream"}),
    ".png": frozenset({"image/png", "application/octet-stream"}),
    ".jpg": frozenset({"image/jpeg", "application/octet-stream"}),
    ".jpeg": frozenset({"image/jpeg", "application/octet-stream"}),
    ".webp": frozenset({"image/webp", "application/octet-stream"}),
}


def max_upload_bytes() -> int:
    raw = os.environ.get("CIRCUITSENTINEL_MAX_UPLOAD_MB", "").strip()
    try:
        megabytes = float(raw) if raw else DEFAULT_MAX_UPLOAD_MB
    except ValueError:
        megabytes = DEFAULT_MAX_UPLOAD_MB
    if megabytes <= 0:
        megabytes = DEFAULT_MAX_UPLOAD_MB
    return int(megabytes * 1024 * 1024)


def ensure_upload_dir() -> Path:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return UPLOAD_DIR
