"""Models for circuit-level rail maps and electrical analysis reports."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RailStatus = Literal["unconfirmed", "confirmed", "unknown"]
RailSource = Literal["operator"]

CheckStatus = Literal[
    "passed",
    "violation",
    "inconclusive",
    "not_performed",
    "warning",
]

Assessment = Literal[
    "violations_detected",
    "no_violations_found_within_scope",
    "inconclusive",
    "error",
]


class RailEntry(BaseModel):
    """One supply candidate / operator-confirmed rail."""

    net_name: str
    value_v: float | None = None
    reference_net: str | None = None
    status: RailStatus = "unconfirmed"
    source: RailSource = "operator"
    suggested: bool = False
    suggestion_reason: str | None = None


class RailMap(BaseModel):
    schematic_file_id: str
    rails: list[RailEntry] = Field(default_factory=list)


class RailMapUpdate(BaseModel):
    """PUT body: operator rail confirmations (values never inferred from net names)."""

    rails: list[RailEntry] = Field(default_factory=list)


class EvidenceRef(BaseModel):
    fact_id: str | None = None
    evidence_id: str | None = None
    page_number: int | None = None
    excerpt: str | None = None
    fact_type: str | None = None
    qualifiers: list[str] = Field(default_factory=list)


class CircuitCheckFinding(BaseModel):
    check_id: str
    status: CheckStatus
    explanation: str
    component_refs: list[str] = Field(default_factory=list)
    nets: list[str] = Field(default_factory=list)
    assumed_conditions: list[str] = Field(default_factory=list)
    limits: list[str] = Field(default_factory=list)
    evidence_references: list[EvidenceRef] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ComponentInventoryItem(BaseModel):
    reference: str
    value: str | None = None
    lib_id: str | None = None
    footprint: str | None = None
    datasheet_linked: bool = False
    link_id: str | None = None
    document_id: str | None = None
    content_sha256: str | None = None
    identity_status: Literal["linked", "unresolved"] = "unresolved"
    connected_nets: list[str] = Field(default_factory=list)


class CircuitAnalysisCounts(BaseModel):
    components_total: int = 0
    components_evaluated: int = 0
    components_unresolved: int = 0
    checks_passed: int = 0
    checks_violations: int = 0
    checks_inconclusive: int = 0
    checks_not_performed: int = 0
    checks_warnings: int = 0


class CircuitAnalysisReport(BaseModel):
    assessment: Assessment
    schematic_file_id: str
    scope: str
    limitations: list[str] = Field(default_factory=list)
    checks_not_performed: list[str] = Field(default_factory=list)
    counts: CircuitAnalysisCounts = Field(default_factory=CircuitAnalysisCounts)
    rails: list[RailEntry] = Field(default_factory=list)
    components: list[ComponentInventoryItem] = Field(default_factory=list)
    findings: list[CircuitCheckFinding] = Field(default_factory=list)
    failure_reason: str | None = None


class CircuitAnalyzeRequest(BaseModel):
    """Optional rail map override for analysis (still operator-sourced)."""

    rails: list[RailEntry] | None = None
    device_variants: dict[str, str] = Field(
        default_factory=dict,
        description="Optional per-reference exact device_variant for multi-variant datasheets.",
    )
