"""Unsupported electrical checks — always not_performed with explicit reasons."""

from __future__ import annotations

from app.circuit.models import CircuitCheckFinding
from app.circuit.rules.base import finding

CHECK_CURRENT = "current_limit_compatibility"
CHECK_POWER = "power_dissipation"


def run_unsupported_stubs() -> list[CircuitCheckFinding]:
    return [
        finding(
            check_id=CHECK_CURRENT,
            status="not_performed",
            explanation=(
                "Current-limit compatibility is not performed: CircuitSentinel has no "
                "trustworthy load-current or driver-capability analysis in v1."
            ),
            limitations=[
                "Requires current/load analysis not available from schematic connectivity alone."
            ],
            missing_information=["Reliable current/load analysis capability"],
        ),
        finding(
            check_id=CHECK_POWER,
            status="not_performed",
            explanation=(
                "Power dissipation checks are not performed: no reliable dissipation or "
                "thermal model is implemented in v1."
            ),
            limitations=[
                "Requires power/thermal analysis not available from schematic connectivity alone."
            ],
            missing_information=["Reliable power dissipation / thermal analysis capability"],
        ),
    ]
