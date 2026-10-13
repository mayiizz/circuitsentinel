"""Validate schematic uploads: extension, MIME type, and size."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from app.schematics.config import (
    ALLOWED_MIME_BY_EXT,
    SUPPORTED_EXTENSIONS,
    max_upload_bytes,
)


@dataclass
class ValidatedUpload:
    extension: str
    format: str  # kicad_sch | pdf | image
    original_basename: str


class UploadValidationError(ValueError):
    """Raised when an upload fails server-side validation."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _safe_basename(filename: str | None) -> str:
    if not filename or not filename.strip():
        raise UploadValidationError("Missing filename.")
    # Never trust path components from the client.
    name = PurePosixPath(filename.replace("\\", "/")).name
    if not name or name in {".", ".."}:
        raise UploadValidationError("Invalid filename.")
    return name


def _extension_of(basename: str) -> str:
    lower = basename.lower()
    for ext in sorted(SUPPORTED_EXTENSIONS, key=len, reverse=True):
        if lower.endswith(ext):
            return ext
    return PurePosixPath(lower).suffix


def _format_for_extension(extension: str) -> str:
    if extension == ".kicad_sch":
        return "kicad_sch"
    if extension == ".pdf":
        return "pdf"
    return "image"


def validate_upload(
    *,
    filename: str | None,
    content_type: str | None,
    size_bytes: int,
) -> ValidatedUpload:
    basename = _safe_basename(filename)
    extension = _extension_of(basename)
    if extension not in SUPPORTED_EXTENSIONS:
        raise UploadValidationError(
            f"Unsupported file extension. Allowed: {', '.join(sorted(SUPPORTED_EXTENSIONS))}."
        )

    limit = max_upload_bytes()
    if size_bytes < 0:
        raise UploadValidationError("Invalid file size.")
    if size_bytes == 0:
        raise UploadValidationError("Empty file is not allowed.")
    if size_bytes > limit:
        raise UploadValidationError(
            f"File exceeds the maximum upload size of {limit // (1024 * 1024)} MB.",
            status_code=413,
        )

    mime = (content_type or "application/octet-stream").split(";")[0].strip().lower()
    allowed = ALLOWED_MIME_BY_EXT[extension]
    if mime not in allowed:
        raise UploadValidationError(
            f"MIME type '{mime}' is not allowed for {extension} files."
        )

    return ValidatedUpload(
        extension=extension,
        format=_format_for_extension(extension),
        original_basename=basename,
    )
