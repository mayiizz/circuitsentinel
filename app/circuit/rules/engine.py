"""Aggregate circuit electrical findings into an assessment."""

from __future__ import annotations

from app.circuit.models import (
    Assessment,
    CircuitAnalysisCounts,
    CircuitCheckFinding,
)

SCOPE = (
    "Verification scope (v1): operator-confirmed rail voltages; "
    "supply_rail_vs_recommended for datasheet-linked components; "
    "absolute_maximum_supply_warning (separate); "
    "pin_voltage_compatibility when signal voltage conditions and input limits exist. "
    "Current and power checks are not performed. "
    "Absence of detected violations is not proof that the complete circuit is safe."
)

DEFAULT_LIMITATIONS = [
    "Net names and power symbols are never treated as verified voltages.",
    "Absolute-maximum ratings are never used as recommended operating limits.",
    "no_violations_found_within_scope is not a whole-circuit safety certification.",
    "Unresolved component identities and unconfirmed rails produce inconclusive results.",
]


def aggregate_assessment(
    findings: list[CircuitCheckFinding],
    *,
    has_unresolved_linked_targets: bool = False,
) -> tuple[Assessment, CircuitAnalysisCounts, list[str]]:
    counts = CircuitAnalysisCounts()
    not_performed_ids: list[str] = []
    for f in findings:
        if f.status == "passed":
            counts.checks_passed += 1
        elif f.status == "violation":
            counts.checks_violations += 1
        elif f.status == "inconclusive":
            counts.checks_inconclusive += 1
        elif f.status == "not_performed":
            counts.checks_not_performed += 1
            not_performed_ids.append(f.check_id)
        elif f.status == "warning":
            counts.checks_warnings += 1

    if counts.checks_violations > 0:
        assessment: Assessment = "violations_detected"
    elif counts.checks_inconclusive > 0 or has_unresolved_linked_targets:
        assessment = "inconclusive"
    elif counts.checks_passed > 0:
        assessment = "no_violations_found_within_scope"
    else:
        assessment = "inconclusive"

    return assessment, counts, sorted(set(not_performed_ids))
