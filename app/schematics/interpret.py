"""Heuristic (non-verified) explanations for KiCad ERC findings.

These are NOT KiCad output and MUST stay visually separate from ERC facts.
They never claim a root cause as proven and never imply the design is safe.
"""

from __future__ import annotations

from app.schematics.models import ErcFinding, ErcReport, FindingInterpretation

_DISCLAIMER = (
    "Heuristic guidance only — not a verified root cause. "
    "CircuitSentinel does not modify the schematic or certify electrical safety."
)


def _power_pin_not_driven(finding: ErcFinding) -> FindingInterpretation:
    ref = finding.reference or "the flagged symbol"
    pin = f" pin {finding.pin}" if finding.pin else ""
    return FindingInterpretation(
        rule_id=finding.rule_id,
        severity=finding.severity,
        reference=finding.reference,
        pin=finding.pin,
        kicad_description=finding.description,
        explanation=(
            f"KiCad reports that a power-input pin on {ref}{pin} is not driven by any "
            "power-output pin on the nets KiCad currently sees. Plausible causes include "
            "a missing PWR_FLAG, an unconnected power rail, a symbol power pin typed as "
            "input without a matching output, or a simulation-only symbol that does not "
            "model supply pins the way ERC expects. This is a plausible reading of the "
            "rule — not a confirmed wiring fault."
        ),
        inspection_steps=[
            "Open the schematic at the reported coordinates and inspect the flagged pin.",
            "Confirm the net name on that pin and whether a power symbol or PWR_FLAG drives it.",
            "For sim SPICE op-amps, check whether V+/V− pins are intentional or need flags.",
            "Re-run ERC in KiCad after any schematic change; do not treat this note as a fix.",
        ],
        disclaimer=_DISCLAIMER,
    )


def _lib_symbol_mismatch(finding: ErcFinding) -> FindingInterpretation:
    ref = finding.reference or "the flagged symbol"
    return FindingInterpretation(
        rule_id=finding.rule_id,
        severity=finding.severity,
        reference=finding.reference,
        pin=finding.pin,
        kicad_description=finding.description,
        explanation=(
            f"KiCad warns that the placed symbol for {ref} does not match the current "
            "library copy. Plausible causes include an outdated embedded symbol, a library "
            "update after placement, or a intentionally customized local symbol. This does "
            "not by itself prove an electrical error."
        ),
        inspection_steps=[
            "Compare the placed symbol against the library entry named in the KiCad message.",
            "Decide whether to update from the library or keep the local copy intentionally.",
            "Re-run ERC after any library sync; absence of this warning is not a safety pass.",
        ],
        disclaimer=_DISCLAIMER,
    )


def _generic(finding: ErcFinding) -> FindingInterpretation:
    return FindingInterpretation(
        rule_id=finding.rule_id,
        severity=finding.severity,
        reference=finding.reference,
        pin=finding.pin,
        kicad_description=finding.description,
        explanation=(
            f"KiCad reported rule `{finding.rule_id}` at "
            f"{finding.reference or '(no reference)'}"
            f"{f' pin {finding.pin}' if finding.pin else ''}. "
            "Treat the KiCad description as the factual finding; any cause listed elsewhere "
            "is speculative until confirmed in the schematic or by further checks."
        ),
        inspection_steps=[
            "Locate the finding in the schematic using the reported reference and coordinates.",
            "Read the KiCad rule documentation for this rule_id before changing the design.",
            "Verify connectivity and symbol properties manually; do not auto-edit from this UI.",
        ],
        disclaimer=_DISCLAIMER,
    )


_HANDLERS = {
    "power_pin_not_driven": _power_pin_not_driven,
    "lib_symbol_mismatch": _lib_symbol_mismatch,
}


def interpret_erc_findings(erc: ErcReport) -> list[FindingInterpretation]:
    """Build cautious explanations for each KiCad finding. Empty if ERC did not run."""
    if not erc.ran:
        return []
    notes: list[FindingInterpretation] = []
    for finding in erc.findings:
        handler = _HANDLERS.get(finding.rule_id, _generic)
        notes.append(handler(finding))
    return notes
