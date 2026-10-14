"""Phase 4B: minimal evidence-grounded engineering check.

Check id: ``recommended_supply_vs_stated_rail``

Why not net-based supply compatibility:
  Netlist connectivity and net names (e.g. V+, GND) do not carry verified
  voltage values. Treating pin-to-net links or names as volts would invent
  electrical facts. This check therefore compares only:
    (1) a user-stated operating supply rail (explicit assumption), against
    (2) linked datasheet facts classified as recommended_operating supply limits.

Absolute-maximum ratings are never treated as recommended operating limits.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.datasheets.models import NormalizedDatasheetFact
from app.datasheets.store import load_ingest_report, load_link, make_link_id
from app.datasheets.supply_compare import (
    compare_stated_to_range,
    fact_matches_exact_variant,
    normalize_variant_name,
    resolve_recommended_supply_range,
    split_supply_facts,
    variant_names_on_fact,
)

# Compatibility aliases for existing unit tests.
_fact_matches_exact_variant = fact_matches_exact_variant
_normalize_variant_name = normalize_variant_name
_variant_names_on_fact = variant_names_on_fact
_supply_facts = split_supply_facts
from app.schematics.kicad_parser import KiCadParseError, parse_kicad_sch
from app.schematics.storage import FILE_ID_RE, resolve_upload_id

CHECK_ID = "recommended_supply_vs_stated_rail"

CheckOutcome = Literal[
    "potential_violation",
    "no_violation_detected",
    "inconclusive",
    "error",
]

PHASE4B_LIMITATIONS = [
    "Phase 4B runs only recommended_supply_vs_stated_rail — not a complete ERC suite.",
    "Circuit net names and pin-to-net links are never treated as voltage measurements.",
    "Absolute-maximum datasheet ratings are never used as recommended operating limits.",
    "A no_violation_detected result is not a claim that the whole circuit is safe or correct.",
    "Stated supply voltage is a user-provided assumption; CircuitSentinel does not measure rails.",
    "When multiple device-variant recommended ranges exist, an explicit device_variant "
    "selection is required; variants are never inferred from reference, symbol, or filename.",
]

class StatedSupplyVoltage(BaseModel):
    """User-asserted operating supply for the linked component (not inferred from nets)."""

    value_v: float = Field(description="Operating supply in volts (user-stated).")
    note: str | None = Field(
        default=None,
        description="Optional human note describing how this rail was obtained.",
    )


class EngineeringCheckRequest(BaseModel):
    """Request for the Phase 4B recommended-supply check."""

    schematic_file_id: str = Field(pattern=r"^[a-fA-F0-9]{32}$")
    component_reference: str = Field(min_length=1, max_length=64)
    document_id: str = Field(min_length=1, max_length=128)
    content_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    stated_supply: StatedSupplyVoltage | None = None
    device_variant: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "Explicit datasheet device variant (e.g. LM358). Matched exactly against "
            "variant: qualifiers on normalized facts — never inferred."
        ),
    )


class EvidenceReference(BaseModel):
    fact_id: str | None = None
    evidence_id: str | None = None
    page_number: int | None = None
    excerpt: str | None = None
    fact_type: str | None = None
    qualifiers: list[str] = Field(default_factory=list)


class EngineeringCheckFinding(BaseModel):
    check_id: str = CHECK_ID
    outcome: CheckOutcome
    component_reference: str
    explanation: str
    assumptions: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    evidence_references: list[EvidenceReference] = Field(default_factory=list)
    link_id: str | None = None
    stated_supply_v: float | None = None
    datasheet_supply_min_v: float | None = None
    datasheet_supply_max_v: float | None = None
    selected_device_variant: str | None = None


class EngineeringCheckResponse(BaseModel):
    status: CheckOutcome
    finding: EngineeringCheckFinding | None = None
    failure_reason: str | None = None
    limitations: list[str] = Field(default_factory=list)


def _ref_from_fact(fact: NormalizedDatasheetFact) -> EvidenceReference:
    return EvidenceReference(
        fact_id=fact.id,
        evidence_id=fact.supporting_evidence_id,
        page_number=fact.page_number,
        excerpt=fact.supporting_excerpt,
        fact_type=fact.fact_type,
        qualifiers=list(fact.qualifiers),
    )


def run_recommended_supply_check(
    request: EngineeringCheckRequest,
) -> EngineeringCheckResponse:
    """Compare user-stated supply vs recommended-operating datasheet limits."""
    limitations = list(PHASE4B_LIMITATIONS)
    file_id = request.schematic_file_id.strip().lower()
    reference = request.component_reference.strip()
    document_id = request.document_id.strip()
    sha = request.content_sha256.strip().lower()

    if not FILE_ID_RE.fullmatch(file_id):
        return EngineeringCheckResponse(
            status="error",
            failure_reason="schematic_file_id must be a 32-hex upload id.",
            limitations=limitations,
        )

    link_id = make_link_id(
        schematic_file_id=file_id,
        component_reference=reference,
        content_sha256=sha,
    )
    link = load_link(link_id)
    if link is None:
        return EngineeringCheckResponse(
            status="error",
            failure_reason=(
                "No user-confirmed datasheet link for this schematic, component, "
                "and datasheet hash. Create one via /api/datasheets/links first."
            ),
            limitations=limitations,
        )
    if link.document_id != document_id:
        return EngineeringCheckResponse(
            status="error",
            failure_reason=(
                f"document_id mismatch with stored link: request {document_id!r}, "
                f"link {link.document_id!r}."
            ),
            limitations=limitations,
        )
    if link.component_reference != reference:
        return EngineeringCheckResponse(
            status="error",
            failure_reason="component_reference does not match the stored link.",
            limitations=limitations,
        )
    if link.content_sha256.lower() != sha:
        return EngineeringCheckResponse(
            status="error",
            failure_reason="content_sha256 does not match the stored link.",
            limitations=limitations,
        )

    schematic_path = resolve_upload_id(file_id)
    if schematic_path is None:
        return EngineeringCheckResponse(
            status="error",
            failure_reason=(
                "Schematic upload not found (stale analysis scope, deleted, "
                "or replaced upload)."
            ),
            limitations=limitations,
        )
    try:
        parsed = parse_kicad_sch(schematic_path.read_bytes())
    except KiCadParseError as exc:
        return EngineeringCheckResponse(
            status="error",
            failure_reason=f"Unable to parse schematic: {exc}",
            limitations=limitations,
        )
    refs = {s.reference for s in parsed["symbols"] if s.reference}
    if reference not in refs:
        return EngineeringCheckResponse(
            status="error",
            failure_reason=(
                f"Component {reference!r} is no longer present in the schematic "
                "(stale link)."
            ),
            limitations=limitations,
        )

    report = load_ingest_report(sha)
    if report is None or report.source is None:
        return EngineeringCheckResponse(
            status="error",
            failure_reason="Stored datasheet ingest report missing for content_sha256.",
            limitations=limitations,
        )
    if report.source.document_id != document_id:
        return EngineeringCheckResponse(
            status="error",
            failure_reason=(
                f"Datasheet identity mismatch: request document_id {document_id!r}, "
                f"stored ingest {report.source.document_id!r}."
            ),
            limitations=limitations,
        )

    recommended, abs_only, unclassified = split_supply_facts(report.facts)
    selected_variant_raw = (request.device_variant or "").strip() or None
    selected_variant = (
        normalize_variant_name(selected_variant_raw)
        if selected_variant_raw
        else None
    )
    assumptions = [
        "Pin-to-net connectivity and net names were not used as voltage evidence.",
        "Only datasheet facts tagged recommended_operating are treated as operating limits.",
    ]
    if request.stated_supply is not None:
        assumptions.append(
            f"User-stated operating supply is {request.stated_supply.value_v} V"
            + (
                f" ({request.stated_supply.note})"
                if request.stated_supply.note
                else " (explicit request assumption)."
            )
        )
    if selected_variant is not None:
        assumptions.append(
            f"User-selected device variant is {selected_variant} "
            "(exact match on variant: qualifiers; not inferred)."
        )

    # Missing stated supply → inconclusive (do not invent from nets).
    if request.stated_supply is None:
        finding = EngineeringCheckFinding(
            outcome="inconclusive",
            component_reference=reference,
            explanation=(
                "No user-stated operating supply voltage was provided. "
                "CircuitSentinel does not infer rail voltage from net names or "
                "pin connectivity, so the check is inconclusive."
            ),
            assumptions=assumptions,
            missing_information=[
                "stated_supply.value_v (user-asserted operating supply in volts)",
                "Verified circuit rail voltage measurement (not available from netlist)",
            ],
            evidence_references=[
                _ref_from_fact(f) for f in recommended + abs_only + unclassified
            ],
            link_id=link.id,
            selected_device_variant=selected_variant,
        )
        return EngineeringCheckResponse(
            status="inconclusive", finding=finding, limitations=limitations
        )

    stated = request.stated_supply.value_v

    if not recommended:
        missing = [
            "recommended_operating supply_voltage_min and/or supply_voltage_max "
            "with volt units and page-backed evidence"
        ]
        if abs_only:
            missing.append(
                "Operating limits distinct from absolute-maximum ratings "
                "(absolute-maximum facts were present but not used)"
            )
            explanation = (
                f"Datasheet for {reference} only provides absolute-maximum supply "
                "ratings (or lacks recommended_operating classification). "
                "Absolute-maximum values are not interpreted as recommended "
                "operating limits, so no supply comparison was performed."
            )
        elif unclassified:
            missing.append(
                "recommended_operating classification on existing supply facts "
                "(unclassified supply facts were present but not used)"
            )
            explanation = (
                f"Datasheet for {reference} has supply voltage text that was "
                "normalized without a recommended_operating (or absolute_maximum) "
                "section qualifier. Unclassified facts are not used as operating "
                "limits, so the check is inconclusive."
            )
        else:
            explanation = (
                f"No recommended_operating supply voltage facts are available for "
                f"linked component {reference}. The check is inconclusive."
            )
        finding = EngineeringCheckFinding(
            outcome="inconclusive",
            component_reference=reference,
            explanation=explanation,
            assumptions=assumptions,
            missing_information=missing,
            evidence_references=[
                _ref_from_fact(f) for f in abs_only + unclassified
            ],
            link_id=link.id,
            stated_supply_v=stated,
            selected_device_variant=selected_variant,
        )
        return EngineeringCheckResponse(
            status="inconclusive", finding=finding, limitations=limitations
        )

    range_result = resolve_recommended_supply_range(
        report.facts, device_variant=selected_variant
    )
    if range_result.outcome == "inconclusive":
        finding = EngineeringCheckFinding(
            outcome="inconclusive",
            component_reference=reference,
            explanation=range_result.reason,
            assumptions=assumptions,
            missing_information=range_result.missing_information,
            evidence_references=[_ref_from_fact(f) for f in range_result.scoped_facts]
            or [_ref_from_fact(f) for f in recommended],
            link_id=link.id,
            stated_supply_v=stated,
            datasheet_supply_min_v=range_result.min_v,
            datasheet_supply_max_v=range_result.max_v,
            selected_device_variant=range_result.selected_variant,
        )
        return EngineeringCheckResponse(
            status="inconclusive", finding=finding, limitations=limitations
        )

    ds_min = range_result.min_v
    ds_max = range_result.max_v
    selected_variant = range_result.selected_variant
    refs = [_ref_from_fact(f) for f in range_result.scoped_facts]
    missing = list(range_result.missing_information)

    if selected_variant is not None and (ds_min is None or ds_max is None):
        finding = EngineeringCheckFinding(
            outcome="inconclusive",
            component_reference=reference,
            explanation=(
                f"Selected device variant {selected_variant} does not have a "
                "complete, unambiguous recommended_operating supply minimum and "
                "maximum. The check is inconclusive."
            ),
            assumptions=assumptions,
            missing_information=missing
            or [
                "recommended_operating supply_voltage_min and supply_voltage_max "
                f"for variant:{selected_variant}"
            ],
            evidence_references=refs,
            link_id=link.id,
            stated_supply_v=stated,
            selected_device_variant=selected_variant,
            datasheet_supply_min_v=ds_min,
            datasheet_supply_max_v=ds_max,
        )
        return EngineeringCheckResponse(
            status="inconclusive", finding=finding, limitations=limitations
        )

    bound_outcome = compare_stated_to_range(stated, min_v=ds_min, max_v=ds_max)
    variant_clause = (
        f" for variant {selected_variant}" if selected_variant else ""
    )

    if bound_outcome == "potential_violation":
        parts = []
        if ds_min is not None and stated < ds_min:
            parts.append(f"below recommended minimum {ds_min} V")
        if ds_max is not None and stated > ds_max:
            parts.append(f"above recommended maximum {ds_max} V")
        explanation = (
            f"User-stated supply {stated} V for {reference}{variant_clause} is "
            f"{' and '.join(parts)} per linked datasheet recommended_operating facts. "
            "This is a potential_violation of the stated operating limits — "
            "not a full-circuit safety certification."
        )
        finding = EngineeringCheckFinding(
            outcome="potential_violation",
            component_reference=reference,
            explanation=explanation,
            assumptions=assumptions,
            missing_information=missing,
            evidence_references=refs,
            link_id=link.id,
            stated_supply_v=stated,
            datasheet_supply_min_v=ds_min,
            datasheet_supply_max_v=ds_max,
            selected_device_variant=selected_variant,
        )
        return EngineeringCheckResponse(
            status="potential_violation", finding=finding, limitations=limitations
        )

    range_desc = []
    if ds_min is not None:
        range_desc.append(f"min {ds_min} V")
    if ds_max is not None:
        range_desc.append(f"max {ds_max} V")
    explanation = (
        f"User-stated supply {stated} V for {reference}{variant_clause} is within "
        f"the linked datasheet recommended_operating supply limits "
        f"({', '.join(range_desc)}). "
        "no_violation_detected for this single check only — not a claim that the "
        "entire circuit is correct or safe."
    )
    finding = EngineeringCheckFinding(
        outcome="no_violation_detected",
        component_reference=reference,
        explanation=explanation,
        assumptions=assumptions,
        missing_information=missing,
        evidence_references=refs,
        link_id=link.id,
        stated_supply_v=stated,
        datasheet_supply_min_v=ds_min,
        datasheet_supply_max_v=ds_max,
        selected_device_variant=selected_variant,
    )
    return EngineeringCheckResponse(
        status="no_violation_detected", finding=finding, limitations=limitations
    )


__all__ = [
    "CHECK_ID",
    "PHASE4B_LIMITATIONS",
    "EngineeringCheckFinding",
    "EngineeringCheckRequest",
    "EngineeringCheckResponse",
    "StatedSupplyVoltage",
    "run_recommended_supply_check",
]
