"""Orchestrate circuit-level electrical compatibility analysis."""

from __future__ import annotations

from app.circuit.identity import build_component_inventory
from app.circuit.models import (
    CircuitAnalysisReport,
    CircuitAnalyzeRequest,
    RailEntry,
    RailMap,
)
from app.circuit.rails import load_rail_map, merge_suggested_rails
from app.circuit.rules.engine import DEFAULT_LIMITATIONS, SCOPE, aggregate_assessment
from app.circuit.rules.pin_voltage import run_pin_voltage_checks
from app.circuit.rules.supply import run_supply_checks
from app.circuit.rules.unsupported import run_unsupported_stubs
from app.circuit.topology import build_topology
from app.datasheets.store import list_links_for_schematic
from app.schematics.kicad_parser import KiCadParseError, parse_kicad_sch
from app.schematics.netlist import build_netlist_report
from app.schematics.storage import FILE_ID_RE, resolve_upload_id


def run_circuit_analysis(
    schematic_file_id: str,
    request: CircuitAnalyzeRequest | None = None,
) -> CircuitAnalysisReport:
    req = request or CircuitAnalyzeRequest()
    file_id = (schematic_file_id or "").strip().lower()
    if not FILE_ID_RE.fullmatch(file_id):
        return CircuitAnalysisReport(
            assessment="error",
            schematic_file_id=file_id,
            scope=SCOPE,
            failure_reason="schematic_file_id must be a 32-hex upload id.",
            limitations=list(DEFAULT_LIMITATIONS),
        )

    path = resolve_upload_id(file_id)
    if path is None:
        return CircuitAnalysisReport(
            assessment="error",
            schematic_file_id=file_id,
            scope=SCOPE,
            failure_reason="Schematic upload not found.",
            limitations=list(DEFAULT_LIMITATIONS),
        )

    try:
        parsed = parse_kicad_sch(path.read_bytes())
    except KiCadParseError as exc:
        return CircuitAnalysisReport(
            assessment="error",
            schematic_file_id=file_id,
            scope=SCOPE,
            failure_reason=f"Unable to parse schematic: {exc}",
            limitations=list(DEFAULT_LIMITATIONS),
        )

    netlist = build_netlist_report(schematic_path=path)
    topology = build_topology(symbols=parsed["symbols"], netlist=netlist)
    links = list_links_for_schematic(file_id)
    inventory = build_component_inventory(
        topology, schematic_file_id=file_id, links=links
    )

    stored = load_rail_map(file_id)
    if req.rails is not None:
        override = RailMap(schematic_file_id=file_id, rails=list(req.rails))
        merged = merge_suggested_rails(topology, override, file_id)
        by_name = {r.net_name: r for r in merged.rails}
        for r in req.rails:
            by_name[r.net_name] = r
        rails: list[RailEntry] = sorted(by_name.values(), key=lambda x: x.net_name)
    else:
        rails = merge_suggested_rails(topology, stored, file_id).rails

    findings = []
    findings.extend(
        run_supply_checks(
            topology=topology,
            inventory=inventory,
            rails=rails,
            device_variants=req.device_variants,
        )
    )
    findings.extend(
        run_pin_voltage_checks(
            topology=topology,
            inventory=inventory,
            rails=rails,
            device_variants=req.device_variants,
        )
    )
    findings.extend(run_unsupported_stubs())

    unresolved = [
        c
        for c in inventory
        if c.identity_status == "unresolved"
        and not (c.lib_id or "").lower().startswith("power:")
    ]
    assessment, counts, not_performed = aggregate_assessment(
        findings, has_unresolved_linked_targets=False
    )
    counts.components_total = len(inventory)
    counts.components_unresolved = len(unresolved)
    counts.components_evaluated = sum(
        1
        for f in findings
        if f.check_id == "supply_rail_vs_recommended" and f.status in {"passed", "violation"}
    )

    limitations = list(DEFAULT_LIMITATIONS)
    limitations.extend(topology.limitations)

    return CircuitAnalysisReport(
        assessment=assessment,
        schematic_file_id=file_id,
        scope=SCOPE,
        limitations=limitations,
        checks_not_performed=not_performed,
        counts=counts,
        rails=rails,
        components=inventory,
        findings=findings,
    )
