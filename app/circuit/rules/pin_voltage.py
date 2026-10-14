"""Evidence-based pin_voltage_compatibility checks.

Signal voltages are only taken from:
  (1) a pin hard-tied to an operator-confirmed supply rail, or
  (2) an operator-confirmed voltage on that same net (rail map entry).

Connectivity alone never invents a signal voltage.
"""

from __future__ import annotations

from app.circuit.models import CircuitCheckFinding, ComponentInventoryItem, RailEntry
from app.circuit.rails import confirmed_rail_voltage
from app.circuit.rules.base import evidence_from_fact, finding
from app.circuit.topology import CircuitTopology, PinNet
from app.datasheets.store import load_ingest_report
from app.datasheets.supply_compare import (
    compare_stated_to_range,
    fact_matches_exact_variant,
    input_voltage_facts,
)

CHECK_PIN = "pin_voltage_compatibility"

_DRIVER_HINTS = ("output", "out", "bidirectional", "tri_state", "power_out")
_RECEIVER_HINTS = ("input", "in", "bidirectional", "passive")


def _looks_driver(pn: PinNet) -> bool:
    pt = (pn.pintype or "").lower()
    return any(h in pt for h in _DRIVER_HINTS)


def _looks_receiver(pn: PinNet) -> bool:
    pt = (pn.pintype or "").lower()
    return any(h in pt for h in _RECEIVER_HINTS) or pt == ""


def run_pin_voltage_checks(
    *,
    topology: CircuitTopology,
    inventory: list[ComponentInventoryItem],
    rails: list[RailEntry],
    device_variants: dict[str, str],
) -> list[CircuitCheckFinding]:
    results: list[CircuitCheckFinding] = []
    if not topology.netlist_available:
        results.append(
            finding(
                check_id=CHECK_PIN,
                status="inconclusive",
                explanation=(
                    "Pin-level voltage compatibility cannot run without KiCad netlist "
                    "connectivity."
                ),
                missing_information=["KiCad netlist pin↔net connectivity"],
            )
        )
        return results

    inv_by_ref = {c.reference: c for c in inventory}

    for net_name, nodes in topology.nets_by_name.items():
        if len(nodes) < 2:
            continue
        # Skip pure power distribution nets for pin checks when all pins are power_*.
        if all(
            (n.pintype or "").lower().startswith("power") for n in nodes if n.pintype
        ):
            continue

        drivers = [n for n in nodes if _looks_driver(n)]
        receivers = [n for n in nodes if _looks_receiver(n) and n not in drivers]
        if not drivers or not receivers:
            continue

        signal_v = confirmed_rail_voltage(rails, net_name)
        signal_source = (
            f"Operator-confirmed node/rail voltage on net {net_name!r} = {signal_v} V"
            if signal_v is not None
            else None
        )

        # Also accept driver hard-tied to a confirmed supply rail: driver pin's
        # component has another pin? Simpler: if the *driver pin itself* sits on
        # a confirmed rail net, that voltage is the driven level (hard tie).
        for drv in drivers:
            drv_v = signal_v
            drv_assumed = signal_source
            if drv_v is None:
                # Hard-tie: this driver pin's net is itself a confirmed rail.
                rail_v = confirmed_rail_voltage(rails, drv.net_name)
                if rail_v is not None:
                    drv_v = rail_v
                    drv_assumed = (
                        f"Driver pin {drv.reference}.{drv.pin} hard-tied to "
                        f"operator-confirmed rail {drv.net_name!r} = {rail_v} V"
                    )

            for rcv in receivers:
                if rcv.reference == drv.reference:
                    continue
                rcv_comp = inv_by_ref.get(rcv.reference)
                if rcv_comp is None or not rcv_comp.datasheet_linked or not rcv_comp.content_sha256:
                    results.append(
                        finding(
                            check_id=CHECK_PIN,
                            status="inconclusive",
                            explanation=(
                                f"Net {net_name}: receiver {rcv.reference} has no "
                                "confirmed datasheet link; pin voltage check skipped."
                            ),
                            component_refs=[drv.reference, rcv.reference],
                            nets=[net_name],
                            missing_information=[
                                f"Datasheet link for receiver {rcv.reference}"
                            ],
                        )
                    )
                    continue

                if drv_v is None:
                    results.append(
                        finding(
                            check_id=CHECK_PIN,
                            status="inconclusive",
                            explanation=(
                                f"Net {net_name}: no operator-confirmed signal voltage "
                                f"for driver {drv.reference}.{drv.pin} → "
                                f"{rcv.reference}.{rcv.pin}. Connectivity alone does "
                                "not establish a voltage."
                            ),
                            component_refs=[drv.reference, rcv.reference],
                            nets=[net_name],
                            missing_information=[
                                f"Operator-confirmed voltage on net {net_name} "
                                "(or hard-tie of driver to a confirmed rail)"
                            ],
                        )
                    )
                    continue

                report = load_ingest_report(rcv_comp.content_sha256)
                if report is None:
                    results.append(
                        finding(
                            check_id=CHECK_PIN,
                            status="inconclusive",
                            explanation=f"Missing ingest report for {rcv.reference}.",
                            component_refs=[rcv.reference],
                            nets=[net_name],
                            missing_information=["datasheet ingest report"],
                        )
                    )
                    continue

                variant = device_variants.get(rcv.reference)
                iv_facts = input_voltage_facts(report.facts, recommended_only=False)
                if variant:
                    scoped = [
                        f for f in iv_facts if fact_matches_exact_variant(f, variant)
                    ] or [
                        f for f in iv_facts if not any(
                            q.startswith("variant:") for q in f.qualifiers
                        )
                    ]
                else:
                    scoped = iv_facts

                mins = [f for f in scoped if f.fact_type == "input_voltage_min"]
                maxs = [f for f in scoped if f.fact_type == "input_voltage_max"]
                if not mins and not maxs:
                    results.append(
                        finding(
                            check_id=CHECK_PIN,
                            status="inconclusive",
                            explanation=(
                                f"Receiver {rcv.reference} lacks normalized "
                                "input_voltage_min/max facts for pin-level check."
                            ),
                            component_refs=[drv.reference, rcv.reference],
                            nets=[net_name],
                            assumed_conditions=[drv_assumed or ""],
                            missing_information=[
                                "input_voltage_min/max datasheet facts for receiver"
                            ],
                        )
                    )
                    continue

                if len({f.value for f in mins}) > 1 or len({f.value for f in maxs}) > 1:
                    results.append(
                        finding(
                            check_id=CHECK_PIN,
                            status="inconclusive",
                            explanation=(
                                f"Conflicting input voltage limits for {rcv.reference}."
                            ),
                            component_refs=[rcv.reference],
                            nets=[net_name],
                            evidence_references=[evidence_from_fact(f) for f in scoped],
                            missing_information=["Unambiguous input voltage range"],
                        )
                    )
                    continue

                vmin = mins[0].value if mins else None
                vmax = maxs[0].value if maxs else None
                outcome = compare_stated_to_range(drv_v, min_v=vmin, max_v=vmax)
                limits = []
                if vmin is not None:
                    limits.append(f"input_min={vmin} V")
                if vmax is not None:
                    limits.append(f"input_max={vmax} V")
                assumed = [drv_assumed or f"signal={drv_v} V"]
                if outcome == "potential_violation":
                    results.append(
                        finding(
                            check_id=CHECK_PIN,
                            status="violation",
                            explanation=(
                                f"Driven level {drv_v} V on net {net_name} from "
                                f"{drv.reference}.{drv.pin} is outside input limits of "
                                f"{rcv.reference} ({', '.join(limits)})."
                            ),
                            component_refs=[drv.reference, rcv.reference],
                            nets=[net_name],
                            assumed_conditions=assumed,
                            limits=limits,
                            evidence_references=[evidence_from_fact(f) for f in scoped],
                        )
                    )
                else:
                    results.append(
                        finding(
                            check_id=CHECK_PIN,
                            status="passed",
                            explanation=(
                                f"Driven level {drv_v} V on net {net_name} from "
                                f"{drv.reference}.{drv.pin} is within input limits of "
                                f"{rcv.reference} ({', '.join(limits)}). "
                                "Pin check only — not whole-circuit certification."
                            ),
                            component_refs=[drv.reference, rcv.reference],
                            nets=[net_name],
                            assumed_conditions=assumed,
                            limits=limits,
                            evidence_references=[evidence_from_fact(f) for f in scoped],
                        )
                    )

    if not results:
        results.append(
            finding(
                check_id=CHECK_PIN,
                status="inconclusive",
                explanation=(
                    "No pin-level driver→receiver pairs had both confirmed signal "
                    "voltage conditions and receiver input limits. No pin checks passed "
                    "by default."
                ),
                missing_information=[
                    "Operator-confirmed node voltages and/or linked input_voltage facts"
                ],
            )
        )
    return results
