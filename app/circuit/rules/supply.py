"""Multi-component supply_rail_vs_recommended and absolute_maximum_supply_warning."""

from __future__ import annotations

from app.circuit.models import CircuitCheckFinding, ComponentInventoryItem, RailEntry
from app.circuit.rails import confirmed_rail_voltage
from app.circuit.rules.base import evidence_from_fact, finding
from app.circuit.topology import CircuitTopology, power_nets_for_reference
from app.datasheets.store import load_ingest_report
from app.datasheets.supply_compare import (
    compare_stated_to_range,
    resolve_absolute_maximum_supply_bounds,
    resolve_recommended_supply_range,
)

CHECK_SUPPLY = "supply_rail_vs_recommended"
CHECK_ABSMAX = "absolute_maximum_supply_warning"


def _linked_components(
    inventory: list[ComponentInventoryItem],
) -> list[ComponentInventoryItem]:
    return [c for c in inventory if c.datasheet_linked and c.content_sha256]


def run_supply_checks(
    *,
    topology: CircuitTopology,
    inventory: list[ComponentInventoryItem],
    rails: list[RailEntry],
    device_variants: dict[str, str],
) -> list[CircuitCheckFinding]:
    results: list[CircuitCheckFinding] = []

    if not topology.netlist_available:
        for comp in _linked_components(inventory):
            results.append(
                finding(
                    check_id=CHECK_SUPPLY,
                    status="inconclusive",
                    explanation=(
                        f"Cannot evaluate supply for {comp.reference}: KiCad netlist "
                        "connectivity is unavailable."
                    ),
                    component_refs=[comp.reference],
                    missing_information=["KiCad netlist pin↔net connectivity"],
                )
            )
        return results

    for comp in inventory:
        if not comp.datasheet_linked or not comp.content_sha256:
            # Passive / unlinked parts: skip supply check (identity unresolved).
            lib = (comp.lib_id or "").lower()
            if lib.startswith("power:") or lib.startswith("device:r") or lib.startswith(
                "device:c"
            ):
                continue
            results.append(
                finding(
                    check_id=CHECK_SUPPLY,
                    status="inconclusive",
                    explanation=(
                        f"Component {comp.reference} has no user-confirmed datasheet link; "
                        "supply compatibility cannot be evaluated."
                    ),
                    component_refs=[comp.reference],
                    missing_information=[
                        "User-confirmed datasheet link via /api/datasheets/links"
                    ],
                )
            )
            continue

        report = load_ingest_report(comp.content_sha256)
        if report is None:
            results.append(
                finding(
                    check_id=CHECK_SUPPLY,
                    status="inconclusive",
                    explanation=(
                        f"Stored datasheet ingest missing for linked component "
                        f"{comp.reference}."
                    ),
                    component_refs=[comp.reference],
                    missing_information=["datasheet ingest report"],
                )
            )
            continue

        variant = device_variants.get(comp.reference)
        range_result = resolve_recommended_supply_range(
            report.facts, device_variant=variant
        )
        power_nets = power_nets_for_reference(topology, comp.reference)
        if not power_nets:
            # Fall back to all connected nets that appear in the rail map as candidates.
            power_nets = [
                n
                for n in (comp.connected_nets or [])
                if any(r.net_name == n for r in rails)
            ]

        if not power_nets:
            results.append(
                finding(
                    check_id=CHECK_SUPPLY,
                    status="inconclusive",
                    explanation=(
                        f"No power-typed pins or mapped supply nets found for "
                        f"{comp.reference}; cannot attach a confirmed rail voltage."
                    ),
                    component_refs=[comp.reference],
                    missing_information=[
                        "Power pin connectivity and/or operator-confirmed rail map entry"
                    ],
                    evidence_references=[
                        evidence_from_fact(f) for f in range_result.scoped_facts
                    ],
                )
            )
            continue

        # Dual-supply heuristic: two distinct confirmed rails on power pins.
        confirmed_voltages: list[tuple[str, float]] = []
        unknown_nets: list[str] = []
        for net in power_nets:
            v = confirmed_rail_voltage(rails, net)
            if v is None:
                unknown_nets.append(net)
            else:
                confirmed_voltages.append((net, v))

        if not confirmed_voltages:
            results.append(
                finding(
                    check_id=CHECK_SUPPLY,
                    status="inconclusive",
                    explanation=(
                        f"Supply nets for {comp.reference} "
                        f"({', '.join(power_nets)}) are not operator-confirmed with "
                        "a voltage value. Net names are not treated as volts."
                    ),
                    component_refs=[comp.reference],
                    nets=power_nets,
                    missing_information=[
                        f"Operator-confirmed rail voltage for {n}" for n in power_nets
                    ],
                    evidence_references=[
                        evidence_from_fact(f) for f in range_result.scoped_facts
                    ],
                )
            )
            continue

        if unknown_nets and len(confirmed_voltages) >= 1 and len(power_nets) >= 2:
            # Partial dual-supply knowledge.
            results.append(
                finding(
                    check_id=CHECK_SUPPLY,
                    status="inconclusive",
                    explanation=(
                        f"Component {comp.reference} has multiple power nets; "
                        f"confirmed: {[n for n, _ in confirmed_voltages]}; "
                        f"unknown: {unknown_nets}. Dual-supply evaluation requires "
                        "all applicable rails to be operator-confirmed."
                    ),
                    component_refs=[comp.reference],
                    nets=power_nets,
                    missing_information=[
                        f"Operator-confirmed rail voltage for {n}" for n in unknown_nets
                    ],
                )
            )
            # Still evaluate each confirmed rail individually against span if single-supply facts.
            # For dual_rail_symmetric facts, span is ±mag — compare abs of confirmed rails.

        if range_result.outcome == "inconclusive":
            results.append(
                finding(
                    check_id=CHECK_SUPPLY,
                    status="inconclusive",
                    explanation=(
                        f"{comp.reference}: {range_result.reason}"
                    ),
                    component_refs=[comp.reference],
                    nets=[n for n, _ in confirmed_voltages],
                    missing_information=range_result.missing_information,
                    evidence_references=[
                        evidence_from_fact(f) for f in range_result.scoped_facts
                    ],
                )
            )
        else:
            for net, stated in confirmed_voltages:
                outcome = compare_stated_to_range(
                    stated, min_v=range_result.min_v, max_v=range_result.max_v
                )
                limits = []
                if range_result.min_v is not None:
                    limits.append(f"recommended_min={range_result.min_v} V")
                if range_result.max_v is not None:
                    limits.append(f"recommended_max={range_result.max_v} V")
                assumed = [
                    f"Operator-confirmed rail {net!r} = {stated} V",
                    "Net name was not used as the voltage source.",
                ]
                if outcome == "potential_violation":
                    results.append(
                        finding(
                            check_id=CHECK_SUPPLY,
                            status="violation",
                            explanation=(
                                f"Operator-confirmed supply {stated} V on net {net} for "
                                f"{comp.reference} is outside recommended_operating limits "
                                f"({', '.join(limits)}). This is not a whole-circuit safety claim."
                            ),
                            component_refs=[comp.reference],
                            nets=[net],
                            assumed_conditions=assumed,
                            limits=limits,
                            evidence_references=[
                                evidence_from_fact(f) for f in range_result.scoped_facts
                            ],
                        )
                    )
                else:
                    results.append(
                        finding(
                            check_id=CHECK_SUPPLY,
                            status="passed",
                            explanation=(
                                f"Operator-confirmed supply {stated} V on net {net} for "
                                f"{comp.reference} is within recommended_operating limits "
                                f"({', '.join(limits)}). Passed for this check only."
                            ),
                            component_refs=[comp.reference],
                            nets=[net],
                            assumed_conditions=assumed,
                            limits=limits,
                            evidence_references=[
                                evidence_from_fact(f) for f in range_result.scoped_facts
                            ],
                        )
                    )

        # Absolute-maximum warnings (separate; never a recommended pass).
        abs_min, abs_max, abs_facts = resolve_absolute_maximum_supply_bounds(report.facts)
        if abs_facts and (abs_min is not None or abs_max is not None):
            for net, stated in confirmed_voltages:
                outcome = compare_stated_to_range(stated, min_v=abs_min, max_v=abs_max)
                limits = []
                if abs_min is not None:
                    limits.append(f"abs_max_min={abs_min} V")
                if abs_max is not None:
                    limits.append(f"abs_max_max={abs_max} V")
                if outcome == "potential_violation":
                    results.append(
                        finding(
                            check_id=CHECK_ABSMAX,
                            status="warning",
                            explanation=(
                                f"Operator-confirmed supply {stated} V on {net} for "
                                f"{comp.reference} may exceed absolute-maximum ratings "
                                f"({', '.join(limits)}). Absolute-maximum is not used as "
                                "a recommended operating pass."
                            ),
                            component_refs=[comp.reference],
                            nets=[net],
                            assumed_conditions=[
                                f"Operator-confirmed rail {net!r} = {stated} V"
                            ],
                            limits=limits,
                            evidence_references=[evidence_from_fact(f) for f in abs_facts],
                        )
                    )
                else:
                    results.append(
                        finding(
                            check_id=CHECK_ABSMAX,
                            status="passed",
                            explanation=(
                                f"Operator-confirmed supply {stated} V on {net} for "
                                f"{comp.reference} is within absolute-maximum bounds "
                                f"where stated ({', '.join(limits)}). Warning class only."
                            ),
                            component_refs=[comp.reference],
                            nets=[net],
                            assumed_conditions=[
                                f"Operator-confirmed rail {net!r} = {stated} V"
                            ],
                            limits=limits,
                            evidence_references=[evidence_from_fact(f) for f in abs_facts],
                        )
                    )
        elif abs_facts:
            results.append(
                finding(
                    check_id=CHECK_ABSMAX,
                    status="inconclusive",
                    explanation=(
                        f"Absolute-maximum supply facts for {comp.reference} are present "
                        "but ambiguous; no abs-max warning issued."
                    ),
                    component_refs=[comp.reference],
                    evidence_references=[evidence_from_fact(f) for f in abs_facts],
                    missing_information=["Unambiguous absolute_maximum supply min/max"],
                )
            )

    return results
