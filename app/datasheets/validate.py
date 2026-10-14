"""Validate datasheet PDF uploads: extension, MIME, and size.

In-memory only — CircuitSentinel does not store datasheet uploads in Phase 3A.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from app.schematics.config import max_upload_bytes

ALLOWED_DATASHEET_MIME = frozenset({"application/pdf", "application/octet-stream"})


class DatasheetUploadValidationError(ValueError):
    """Raised when a datasheet upload fails server-side validation."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def validate_datasheet_upload(
    *,
    filename: str | None,
    content_type: str | None,
    size_bytes: int,
) -> str:
    """Return a safe basename after validating PDF extension, MIME, and size."""
    if not filename or not filename.strip():
        raise DatasheetUploadValidationError("Missing filename.")
    basename = PurePosixPath(filename.replace("\\", "/")).name
    if not basename or basename in {".", ".."}:
        raise DatasheetUploadValidationError("Invalid filename.")
    if not basename.lower().endswith(".pdf"):
        raise DatasheetUploadValidationError("Datasheet ingest accepts PDF files only.")

    if size_bytes < 0:
        raise DatasheetUploadValidationError("Invalid file size.")
    if size_bytes == 0:
        raise DatasheetUploadValidationError("Empty file is not allowed.")
    limit = max_upload_bytes()
    if size_bytes > limit:
        raise DatasheetUploadValidationError(
            f"File exceeds the maximum upload size of {limit // (1024 * 1024)} MB.",
            status_code=413,
        )

    mime = (content_type or "application/octet-stream").split(";")[0].strip().lower()
    if mime not in ALLOWED_DATASHEET_MIME:
        raise DatasheetUploadValidationError(
            f"MIME type '{mime}' is not allowed for datasheet PDF uploads."
        )

    return basename
