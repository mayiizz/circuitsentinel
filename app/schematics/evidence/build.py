"""Build a Circuit Evidence Graph from confirmed parser + ERC + KiCad netlist.

Deterministic and read-only. Does not invent nets, pins, components, or citations.
Phase 2 adds net nodes and pin→net edges only from verified kicadxml export.
"""

from __future__ import annotations

from app.schematics.evidence.models import EvidenceEdge, EvidenceGraph, EvidenceNode
from app.schematics.models import (
    ConfirmedFindings,
    ErcFinding,
    ErcReport,
    NetlistReport,
    SymbolFinding,
)

PHASE1_LIMITATIONS = [
    "Phase 1 Circuit Evidence Graph includes only confirmed placed symbols and KiCad ERC findings.",
    "No nets are reconstructed; wire/junction parser hints are not electrical connectivity.",
    "No datasheet facts or citations are included until source ingestion and verification exist.",
    "Pin nodes appear only when an ERC finding explicitly names a pin; no pin connectivity is inferred.",
    "The graph is structural evidence linkage only — not a complete electrical model or safety certification.",
]

PHASE2_LIMITATIONS = [
    "Phase 2 adds net nodes and pin-to-net links only from KiCad kicadxml netlist export.",
    "No nets are reconstructed from wire counts, junctions, labels alone, or visual coordinates.",
    "Missing or failed netlist export does not imply unconnected pins.",
    "Pins listed under netlist components but absent from exported nets are not asserted as open.",
    "Explicit net names (labels, globals, power) are distinguished from KiCad-generated Net-(…) / unconnected-(…) identifiers.",
    "No datasheet facts or electrical conclusions are derived from connectivity.",
    "Citations remain empty until verified source ingestion exists.",
]


def _scope_prefix(scope_id: str | None) -> str:
    """Stable analysis scope so node IDs do not collide across uploads."""
    cleaned = (scope_id or "unscoped").strip()
    return cleaned or "unscoped"


def _component_node_id(scope: str, symbol: SymbolFinding, index: int) -> str:
    if symbol.uuid:
        return f"{scope}:component:{symbol.uuid}"
    # Fallback when uuid is missing: include index for uniqueness within the analysis.
    ref = symbol.reference or "noref"
    lib = symbol.lib_id or "nolib"
    return f"{scope}:component:{ref}:{lib}:{index}"


def resolve_component_node_id(
    symbols: list[SymbolFinding],
    reference: str,
    *,
    scope_id: str | None,
) -> str | None:
    """Return the Evidence Graph component node id for an exact reference match.

    Uses the same ID scheme as ``build_evidence_graph`` (first matching symbol).
    """
    scope = _scope_prefix(scope_id)
    for index, symbol in enumerate(symbols):
        if symbol.reference == reference:
            return _component_node_id(scope, symbol, index)
    return None


def _finding_node_id(scope: str, index: int) -> str:
    return f"{scope}:finding:{index}"


def _pin_node_id(scope: str, reference: str, pin: str) -> str:
    return f"{scope}:pin:{reference}:{pin}"


def _net_node_id(scope: str, code: str) -> str:
    return f"{scope}:net:{code}"


def _component_label(symbol: SymbolFinding) -> str:
    ref = symbol.reference or "(no ref)"
    value = symbol.value or ""
    if value:
        return f"{ref} · {value}"
    return ref


def _symbol_attrs(symbol: SymbolFinding) -> dict:
    attrs: dict = {}
    if symbol.reference is not None:
        attrs["reference"] = symbol.reference
    if symbol.value is not None:
        attrs["value"] = symbol.value
    if symbol.lib_id is not None:
        attrs["lib_id"] = symbol.lib_id
    if symbol.unit is not None:
        attrs["unit"] = symbol.unit
    if symbol.uuid is not None:
        attrs["uuid"] = symbol.uuid
    if symbol.at_x is not None:
        attrs["at_x"] = symbol.at_x
    if symbol.at_y is not None:
        attrs["at_y"] = symbol.at_y
    if symbol.at_angle is not None:
        attrs["at_angle"] = symbol.at_angle
    return attrs


def _finding_attrs(finding: ErcFinding) -> dict:
    attrs: dict = {
        "rule_id": finding.rule_id,
        "severity": finding.severity,
        "description": finding.description,
        "source": finding.source,
    }
    if finding.reference is not None:
        attrs["reference"] = finding.reference
    if finding.pin is not None:
        attrs["pin"] = finding.pin
    if finding.x_mm is not None:
        attrs["x_mm"] = finding.x_mm
    if finding.y_mm is not None:
        attrs["y_mm"] = finding.y_mm
    if finding.item_description is not None:
        attrs["item_description"] = finding.item_description
    return attrs


def _net_label(name: str, name_kind: str) -> str:
    cleaned = (name or "").strip()
    if cleaned:
        return cleaned
    return f"({name_kind} net)"


def _merge_limitations(netlist: NetlistReport | None) -> list[str]:
    """Use Phase-2 wording only when netlist export actually ran; otherwise Phase 1."""
    if netlist is not None and netlist.ran:
        limitations = list(PHASE2_LIMITATIONS)
        for item in netlist.limitations:
            if item not in limitations:
                limitations.append(item)
        return limitations

    limitations = list(PHASE1_LIMITATIONS)
    if netlist is not None and not netlist.ran:
        limitations.append(
            netlist.failure_reason
            or "KiCad netlist export did not run; no net nodes were added."
        )
    return limitations


def build_evidence_graph(
    confirmed: ConfirmedFindings,
    erc: ErcReport,
    *,
    scope_id: str | None = None,
    netlist: NetlistReport | None = None,
) -> EvidenceGraph:
    """Construct an evidence graph from confirmed symbols, ERC, and optional netlist."""
    scope = _scope_prefix(scope_id)
    nodes: list[EvidenceNode] = []
    edges: list[EvidenceEdge] = []

    # reference -> first component node id (matching ERC/netlist refs; duplicates keep first)
    components_by_ref: dict[str, str] = {}
    component_ids: list[str] = []

    for index, symbol in enumerate(confirmed.symbols):
        node_id = _component_node_id(scope, symbol, index)
        component_ids.append(node_id)
        nodes.append(
            EvidenceNode(
                id=node_id,
                kind="component",
                label=_component_label(symbol),
                attrs=_symbol_attrs(symbol),
                provenance="parser",
            )
        )
        if symbol.reference and symbol.reference not in components_by_ref:
            components_by_ref[symbol.reference] = node_id

    # pin_id -> created (reuse same pin node if ERC and netlist share ref+pin)
    pins_created: dict[str, str] = {}
    edge_index = 0

    def _ensure_pin(
        *,
        reference: str,
        pin: str,
        provenance: str,
        extra_attrs: dict | None = None,
        attach_has_pin: bool,
    ) -> str:
        nonlocal edge_index
        pin_id = _pin_node_id(scope, reference, pin)
        if pin_id not in pins_created:
            attrs: dict = {"reference": reference, "pin": pin}
            if extra_attrs:
                attrs.update(extra_attrs)
            nodes.append(
                EvidenceNode(
                    id=pin_id,
                    kind="pin",
                    label=f"{reference} pin {pin}",
                    attrs=attrs,
                    provenance=provenance,  # type: ignore[arg-type]
                )
            )
            pins_created[pin_id] = pin_id
            if attach_has_pin and reference in components_by_ref:
                edges.append(
                    EvidenceEdge(
                        id=f"{scope}:edge:{edge_index}",
                        source_id=components_by_ref[reference],
                        target_id=pin_id,
                        kind="has_pin",
                        provenance=provenance,  # type: ignore[arg-type]
                    )
                )
                edge_index += 1
        elif attach_has_pin and reference in components_by_ref:
            # Pin may already exist from ERC without has_pin; add has_pin once.
            already = any(
                e.kind == "has_pin"
                and e.source_id == components_by_ref[reference]
                and e.target_id == pin_id
                for e in edges
            )
            if not already:
                edges.append(
                    EvidenceEdge(
                        id=f"{scope}:edge:{edge_index}",
                        source_id=components_by_ref[reference],
                        target_id=pin_id,
                        kind="has_pin",
                        provenance=provenance,  # type: ignore[arg-type]
                    )
                )
                edge_index += 1
        return pin_id

    for finding_index, finding in enumerate(erc.findings):
        finding_id = _finding_node_id(scope, finding_index)
        nodes.append(
            EvidenceNode(
                id=finding_id,
                kind="finding",
                label=f"{finding.severity}: {finding.rule_id}",
                attrs=_finding_attrs(finding),
                provenance="kicad_erc",
            )
        )

        # Link finding → component only when reference matches a confirmed symbol.
        comp_id = None
        if finding.reference and finding.reference in components_by_ref:
            comp_id = components_by_ref[finding.reference]
            edges.append(
                EvidenceEdge(
                    id=f"{scope}:edge:{edge_index}",
                    source_id=finding_id,
                    target_id=comp_id,
                    kind="mentions_component",
                    provenance="kicad_erc",
                )
            )
            edge_index += 1

        # Pin node only when ERC explicitly provides pin identity (and a reference to scope it).
        if finding.reference and finding.pin:
            pin_id = _ensure_pin(
                reference=finding.reference,
                pin=finding.pin,
                provenance="kicad_erc",
                attach_has_pin=comp_id is not None,
            )
            edges.append(
                EvidenceEdge(
                    id=f"{scope}:edge:{edge_index}",
                    source_id=finding_id,
                    target_id=pin_id,
                    kind="mentions_pin",
                    provenance="kicad_erc",
                )
            )
            edge_index += 1

    # Phase 2: net nodes + pin→net only from verified netlist export.
    if netlist is not None and netlist.ran:
        for net in netlist.nets:
            net_id = _net_node_id(scope, net.code)
            nodes.append(
                EvidenceNode(
                    id=net_id,
                    kind="net",
                    label=_net_label(net.name, net.name_kind),
                    attrs={
                        "code": net.code,
                        "name": net.name,
                        "name_kind": net.name_kind,
                        **({"net_class": net.net_class} if net.net_class else {}),
                        "node_count": len(net.nodes),
                    },
                    provenance="kicad_netlist",
                )
            )
            for node in net.nodes:
                pin_attrs: dict = {}
                if node.pintype:
                    pin_attrs["pintype"] = node.pintype
                if node.pinfunction:
                    pin_attrs["pinfunction"] = node.pinfunction
                pin_id = _ensure_pin(
                    reference=node.reference,
                    pin=node.pin,
                    provenance="kicad_netlist",
                    extra_attrs=pin_attrs or None,
                    attach_has_pin=node.reference in components_by_ref,
                )
                edges.append(
                    EvidenceEdge(
                        id=f"{scope}:edge:{edge_index}",
                        source_id=pin_id,
                        target_id=net_id,
                        kind="connected_to",
                        provenance="kicad_netlist",
                    )
                )
                edge_index += 1

    return EvidenceGraph(
        nodes=nodes,
        edges=edges,
        citations=[],
        limitations=_merge_limitations(netlist),
    )
