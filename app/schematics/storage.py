"""Persist uploads under a dedicated directory with UUID filenames."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from app.schematics.config import SUPPORTED_EXTENSIONS, UPLOAD_DIR, ensure_upload_dir

FILE_ID_RE = re.compile(r"^[a-f0-9]{32}$")
PREVIEW_DIR_NAME = "previews"
CONTENT_TYPE_BY_EXT: dict[str, str] = {
    ".kicad_sch": "application/x-kicad-schematic",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}


def ensure_preview_dir() -> Path:
    path = ensure_upload_dir() / PREVIEW_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def store_upload(data: bytes, extension: str) -> Path:
    """Write bytes to uploads/<uuid><extension>. Never uses the client path."""
    upload_dir = ensure_upload_dir()
    safe_ext = extension.lower() if extension.startswith(".") else f".{extension.lower()}"
    stored_name = f"{uuid.uuid4().hex}{safe_ext}"
    destination = upload_dir / stored_name
    resolved = destination.resolve()
    if not str(resolved).startswith(str(upload_dir.resolve())):
        raise RuntimeError("Refusing to write outside the upload directory.")
    resolved.write_bytes(data)
    return resolved


def file_id_from_path(path: Path) -> str:
    """Return the 32-hex stem used as the public file id."""
    stem = path.stem
    if not FILE_ID_RE.fullmatch(stem):
        raise ValueError(f"Unexpected stored filename: {path.name}")
    return stem


def resolve_upload_id(file_id: str) -> Path | None:
    """Resolve a public file id to an original upload under uploads/.

    Accepts only a 32-hex id. Never trusts client path segments.
    """
    if not FILE_ID_RE.fullmatch(file_id or ""):
        return None

    upload_root = ensure_upload_dir().resolve()
    for ext in sorted(SUPPORTED_EXTENSIONS, key=len, reverse=True):
        candidate = (upload_root / f"{file_id}{ext}").resolve()
        if not str(candidate).startswith(str(upload_root)):
            return None
        if candidate.is_file():
            return candidate
    return None


def resolve_preview_path(file_id: str) -> Path | None:
    """Return the SVG preview path for a file id when it exists."""
    if not FILE_ID_RE.fullmatch(file_id or ""):
        return None
    upload_root = ensure_upload_dir().resolve()
    preview = (upload_root / PREVIEW_DIR_NAME / f"{file_id}.svg").resolve()
    preview_root = (upload_root / PREVIEW_DIR_NAME).resolve()
    if str(preview).startswith(str(preview_root)) and preview.is_file():
        return preview
    return None


def content_type_for_path(path: Path) -> str:
    return CONTENT_TYPE_BY_EXT.get(path.suffix.lower(), "application/octet-stream")
