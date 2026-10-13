"""Extract available text and page structure from PDF schematics."""

from __future__ import annotations

from io import BytesIO
from typing import Any

from pypdf import PdfReader


class PdfInspectError(ValueError):
    """Raised when a PDF cannot be opened."""


def inspect_pdf(data: bytes) -> dict[str, Any]:
    try:
        reader = PdfReader(BytesIO(data))
    except Exception as exc:
        raise PdfInspectError(f"Unable to read PDF: {exc}") from exc

    page_count = len(reader.pages)
    page_texts: list[str] = []
    for index, page in enumerate(reader.pages):
        try:
            extracted = page.extract_text() or ""
        except Exception:
            extracted = ""
        page_texts.append(extracted.strip())

    combined = "\n\n".join(
        f"[page {i + 1}]\n{text}" for i, text in enumerate(page_texts) if text
    ).strip()
    nonempty_pages = sum(1 for text in page_texts if text)
    return {
        "pages": page_count,
        "pdf_text": combined or None,
        "nonempty_text_pages": nonempty_pages,
        "likely_scanned": page_count > 0 and nonempty_pages == 0,
    }
