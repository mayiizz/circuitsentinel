"""Datasheet models — Phase 3A raw evidence + Phase 3B normalized facts.

Raw evidence remains immutable and separate from normalized facts.
Normalized facts are text-grounded scalars only — not engineering judgments.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schematics.evidence.models import EvidenceGraph

FactType = Literal[
    "supply_voltage_max",
    "supply_voltage_min",
    "input_voltage_max",
    "input_voltage_min",
]


class DatasheetSource(BaseModel):
    """Identity of the ingested PDF. Filename alone does not imply a part match."""

    document_id: str
    filename: str | None = None
    content_sha256: str = Field(
        description="SHA-256 hex digest of the original PDF bytes (before parsing)."
    )
    page_count: int = 0
    byte_length: int = 0


class DatasheetPageText(BaseModel):
    """Per-page extraction result. Empty text is reported honestly.

    ``page_number`` is 1-based (first page is 1), matching user-facing PDF page refs.
    """

    page_number: int = Field(ge=1, description="1-based page index (first page is 1).")
    text: str
    char_count: int
    has_text: bool


class RawDatasheetEvidence(BaseModel):
    """One provenance-preserving raw excerpt from the PDF.

    ``text`` is the exact extracted string supporting this record — not a paraphrase.
    ``page_number`` is 1-based.
    """

    id: str
    kind: Literal["page_text"] = "page_text"
    document_id: str
    page_number: int = Field(ge=1, description="1-based page index (first page is 1).")
    text: str
    extraction_method: Literal["pypdf_extract_text"] = "pypdf_extract_text"
    provenance: Literal["datasheet_pdf"] = "datasheet_pdf"


class NormalizedDatasheetFact(BaseModel):
    """One text-grounded scalar electrical fact from datasheet page text.

    Always links to supporting raw evidence. Never a circuit pass/fail judgment.
    """

    id: str
    fact_type: FactType
    value: float
    unit: str
    qualifiers: list[str] = Field(default_factory=list)
    source_content_sha256: str
    page_number: int = Field(ge=1, description="1-based page index of supporting text.")
    supporting_evidence_id: str
    supporting_excerpt: str = Field(
        description="Exact substring from raw evidence text that supports this fact."
    )
    provenance: Literal["datasheet_normalized"] = "datasheet_normalized"


class UnresolvedNormalization(BaseModel):
    """Explicit record when a candidate line cannot be normalized without guessing."""

    id: str
    reason: str
    attempted_fact_type: FactType | None = None
    page_number: int | None = Field(
        default=None, description="1-based page when known."
    )
    supporting_evidence_id: str | None = None
    candidate_text: str | None = None


class NormalizedClaim(BaseModel):
    """Deprecated Phase 3A stub. Kept empty; use NormalizedDatasheetFact instead."""

    id: str
    claim_type: str
    statement: str
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    confidence: str | None = None


class DatasheetIngestReport(BaseModel):
    """Result of datasheet PDF ingestion + optional text-grounded normalization."""

    status: Literal["ok", "partial", "empty", "error"]
    source: DatasheetSource | None = None
    pages: list[DatasheetPageText] = Field(default_factory=list)
    raw_evidence: list[RawDatasheetEvidence] = Field(default_factory=list)
    facts: list[NormalizedDatasheetFact] = Field(default_factory=list)
    unresolved: list[UnresolvedNormalization] = Field(default_factory=list)
    claims: list[NormalizedClaim] = Field(
        default_factory=list,
        description="Unused Phase 3A stub; always empty. Prefer ``facts``.",
    )
    likely_scanned: bool = False
    failure_reason: str | None = None
    limitations: list[str] = Field(default_factory=list)


class DatasheetComponentLink(BaseModel):
    """User-confirmed association between a datasheet document and a schematic component.

    Never inferred from filename, fuzzy text, or unverified part numbers.
    """

    id: str
    schematic_file_id: str
    component_reference: str
    document_id: str
    content_sha256: str
    provenance: Literal["user_confirmed"] = "user_confirmed"
    created_at: str
    status: Literal["active"] = "active"


class DatasheetComponentLinkRequest(BaseModel):
    """Explicit link request. All identity fields are required; nothing is inferred."""

    schematic_file_id: str = Field(
        min_length=32,
        max_length=32,
        pattern=r"^[a-fA-F0-9]{32}$",
        description="32-hex schematic upload id from /api/schematics/analyze.",
    )
    component_reference: str = Field(min_length=1, max_length=64)
    document_id: str = Field(min_length=1, max_length=128)
    content_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-fA-F0-9]{64}$",
        description="SHA-256 hex of the original datasheet PDF bytes.",
    )


class DatasheetComponentLinkResponse(BaseModel):
    """Result of an explicit datasheet↔component link attempt."""

    status: Literal["ok", "duplicate", "error"]
    link: DatasheetComponentLink | None = None
    facts: list[NormalizedDatasheetFact] = Field(default_factory=list)
    raw_evidence: list[RawDatasheetEvidence] = Field(
        default_factory=list,
        description="Supporting raw page evidence for returned facts (immutable copies).",
    )
    evidence_graph_additions: EvidenceGraph | None = None
    failure_reason: str | None = None
    limitations: list[str] = Field(default_factory=list)
