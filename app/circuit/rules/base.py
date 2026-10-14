"""Shared helpers for circuit check rules."""

from __future__ import annotations

from app.circuit.models import CircuitCheckFinding, EvidenceRef
from app.datasheets.models import NormalizedDatasheetFact


def evidence_from_fact(fact: NormalizedDatasheetFact) -> EvidenceRef:
    return EvidenceRef(
        fact_id=fact.id,
        evidence_id=fact.supporting_evidence_id,
        page_number=fact.page_number,
        excerpt=fact.supporting_excerpt,
        fact_type=fact.fact_type,
        qualifiers=list(fact.qualifiers),
    )


def finding(
    *,
    check_id: str,
    status: str,
    explanation: str,
    component_refs: list[str] | None = None,
    nets: list[str] | None = None,
    assumed_conditions: list[str] | None = None,
    limits: list[str] | None = None,
    evidence_references: list[EvidenceRef] | None = None,
    missing_information: list[str] | None = None,
    limitations: list[str] | None = None,
) -> CircuitCheckFinding:
    return CircuitCheckFinding(
        check_id=check_id,
        status=status,  # type: ignore[arg-type]
        explanation=explanation,
        component_refs=component_refs or [],
        nets=nets or [],
        assumed_conditions=assumed_conditions or [],
        limits=limits or [],
        evidence_references=evidence_references or [],
        missing_information=missing_information or [],
        limitations=limitations or [],
    )
