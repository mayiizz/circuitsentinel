"""Ingest PDF datasheets into provenance-preserving raw evidence records.

Uses local ``pypdf`` text extraction only. Does not run OCR, match components,
or derive electrical conclusions.
"""

from __future__ import annotations

import hashlib
import re
from io import BytesIO

from pypdf import PdfReader

from app.datasheets.models import (
    DatasheetIngestReport,
    DatasheetPageText,
    DatasheetSource,
    RawDatasheetEvidence,
)
from app.datasheets.normalize import PHASE3B_LIMITATIONS, normalize_raw_evidence

PHASE3A_LIMITATIONS = [
    "Phase 3A extracts raw PDF text only; no OCR for scanned pages.",
    "No figures, tables-as-structure, or pinout diagrams are interpreted.",
    "Filename and approximate text matches are not treated as verified component identity.",
    "Raw evidence records are distinct from normalized facts.",
]

_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")


class DatasheetIngestError(ValueError):
    """Raised only for programmer misuse; malformed PDFs return an error report."""


def _stable_document_id(data: bytes, *, document_id: str | None, filename: str | None) -> str:
    """Prefer caller-supplied id; otherwise derive a stable content-based id."""
    if document_id is not None:
        cleaned = _SAFE_ID_RE.sub("-", document_id.strip()).strip("-")
        if cleaned:
            return cleaned
    digest = hashlib.sha256(data).hexdigest()[:16]
    if filename:
        stem = _SAFE_ID_RE.sub("-", _filename_stem(filename)).strip("-")
        if stem:
            return f"{stem}-{digest}"
    return digest


def _filename_stem(filename: str) -> str:
    name = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if "." in name:
        return name.rsplit(".", 1)[0]
    return name


def _evidence_id(document_id: str, page_number: int) -> str:
    return f"{document_id}:raw:page:{page_number}:pypdf_extract_text"


def ingest_datasheet_pdf(
    data: bytes,
    *,
    filename: str | None = None,
    document_id: str | None = None,
) -> DatasheetIngestReport:
    """Extract page text from a datasheet PDF into typed raw evidence.

    Empty or scanned-like PDFs are reported explicitly (``status=empty``).
    Malformed PDFs return ``status=error`` without inventing text.
    """
    if not data:
        return DatasheetIngestReport(
            status="error",
            failure_reason="Datasheet PDF bytes are empty.",
            limitations=list(PHASE3A_LIMITATIONS),
            facts=[],
            unresolved=[],
            claims=[],
        )

    # Hash the original upload bytes before any parsing or normalization.
    content_sha256 = hashlib.sha256(data).hexdigest()
    doc_id = _stable_document_id(data, document_id=document_id, filename=filename)

    try:
        reader = PdfReader(BytesIO(data))
    except Exception as exc:  # noqa: BLE001 — surface as honest failure
        return DatasheetIngestReport(
            status="error",
            source=DatasheetSource(
                document_id=doc_id,
                filename=filename,
                content_sha256=content_sha256,
                page_count=0,
                byte_length=len(data),
            ),
            failure_reason=f"Unable to read datasheet PDF: {type(exc).__name__}: {exc}",
            limitations=list(PHASE3A_LIMITATIONS),
            facts=[],
            unresolved=[],
            claims=[],
        )

    try:
        page_count = len(reader.pages)
    except Exception as exc:  # noqa: BLE001
        return DatasheetIngestReport(
            status="error",
            source=DatasheetSource(
                document_id=doc_id,
                filename=filename,
                content_sha256=content_sha256,
                page_count=0,
                byte_length=len(data),
            ),
            failure_reason=f"Unable to enumerate PDF pages: {type(exc).__name__}: {exc}",
            limitations=list(PHASE3A_LIMITATIONS),
            facts=[],
            unresolved=[],
            claims=[],
        )

    pages: list[DatasheetPageText] = []
    raw_evidence: list[RawDatasheetEvidence] = []
    extraction_errors = 0

    for index, page in enumerate(reader.pages):
        # User-facing page numbers are 1-based (PDF page 1 == index 0).
        page_number = index + 1
        try:
            extracted = page.extract_text()
            if extracted is None:
                extracted = ""
            else:
                extracted = str(extracted)
        except Exception:
            extracted = ""
            extraction_errors += 1

        # Preserve exact extractor output when the page has any non-whitespace text.
        # Whitespace-only pages are recorded as empty (not OCR'd).
        has_text = bool(extracted.strip())
        text = extracted if has_text else ""
        pages.append(
            DatasheetPageText(
                page_number=page_number,
                text=text if has_text else "",
                char_count=len(text) if has_text else 0,
                has_text=has_text,
            )
        )
        if has_text:
            raw_evidence.append(
                RawDatasheetEvidence(
                    id=_evidence_id(doc_id, page_number),
                    document_id=doc_id,
                    page_number=page_number,
                    text=text,
                    extraction_method="pypdf_extract_text",
                    provenance="datasheet_pdf",
                )
            )

    source = DatasheetSource(
        document_id=doc_id,
        filename=filename,
        content_sha256=content_sha256,
        page_count=page_count,
        byte_length=len(data),
    )
    nonempty = sum(1 for p in pages if p.has_text)
    likely_scanned = page_count > 0 and nonempty == 0
    limitations = list(PHASE3A_LIMITATIONS)

    if page_count == 0:
        return DatasheetIngestReport(
            status="empty",
            source=source,
            pages=pages,
            raw_evidence=[],
            facts=[],
            unresolved=[],
            claims=[],
            likely_scanned=False,
            failure_reason="PDF opened but contains no pages.",
            limitations=limitations,
        )

    if nonempty == 0:
        limitations.append(
            "No extractable text was found on any page; the PDF may be scanned or image-only. "
            "CircuitSentinel did not run OCR and did not invent text."
        )
        if extraction_errors:
            limitations.append(
                f"Text extraction raised errors on {extraction_errors} page(s); "
                "those pages are treated as having no extractable text."
            )
        return DatasheetIngestReport(
            status="empty",
            source=source,
            pages=pages,
            raw_evidence=[],
            facts=[],
            unresolved=[],
            claims=[],
            likely_scanned=likely_scanned,
            failure_reason=(
                "No extractable text in datasheet PDF (likely scanned or image-only)."
            ),
            limitations=limitations,
        )

    if nonempty < page_count:
        status = "partial"
        limitations.append(
            f"Extractable text found on {nonempty} of {page_count} page(s); "
            "pages without text are not treated as OCR successes."
        )
    else:
        status = "ok"

    # Phase 3B: normalize from immutable raw evidence (never mutates raw_evidence).
    facts, unresolved = normalize_raw_evidence(
        raw_evidence,
        source_content_sha256=content_sha256,
        document_id=doc_id,
    )
    for item in PHASE3B_LIMITATIONS:
        if item not in limitations:
            limitations.append(item)

    return DatasheetIngestReport(
        status=status,
        source=source,
        pages=pages,
        raw_evidence=raw_evidence,
        facts=facts,
        unresolved=unresolved,
        claims=[],
        likely_scanned=False,
        failure_reason=None,
        limitations=limitations,
    )
