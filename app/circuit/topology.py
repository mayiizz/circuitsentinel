"""Build circuit topology hints from KiCad netlist + parser symbols.

Candidate supply nets are identified for operator confirmation only.
Net names are never treated as verified voltages.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schematics.models import NetlistReport, SymbolFinding

_POWER_PIN_TYPES = {
    "power_in",
    "power_out",
    "power_inout",
    "power_input",
    "power_output",
}


@dataclass
class PinNet:
    reference: str
    pin: str
    net_name: str
    pintype: str | None = None
    pinfunction: str | None = None


@dataclass
class CircuitTopology:
    references: list[str]
    symbols_by_ref: dict[str, SymbolFinding]
    pin_nets: list[PinNet]
    nets_by_name: dict[str, list[PinNet]]
    candidate_supply_nets: list[tuple[str, str]]  # (net_name, reason)
    power_symbol_refs: list[str]
    netlist_available: bool
    limitations: list[str] = field(default_factory=list)


def _is_power_pin(pintype: str | None, pinfunction: str | None) -> bool:
    pt = (pintype or "").strip().lower().replace(" ", "_")
    pf = (pinfunction or "").strip().lower()
    if pt in _POWER_PIN_TYPES or pt.startswith("power"):
        return True
    if any(token in pf for token in ("vcc", "vdd", "vee", "vss", "gnd", "v+", "v-", "avdd", "dvdd")):
        return True
    return False


def _looks_like_supply_net_name(name: str) -> bool:
    """Heuristic for *candidate* listing only — never a voltage claim."""
    leaf = (name or "").strip().rsplit("/", 1)[-1].lower()
    if not leaf or leaf.startswith("net-(") or leaf.startswith("unconnected-("):
        return False
    tokens = ("vcc", "vdd", "vee", "vss", "gnd", "v+", "v-", "+5", "+3", "+12", "3v3", "5v", "12v", "avdd", "dvdd")
    return any(t in leaf for t in tokens)


def build_topology(
    *,
    symbols: list[SymbolFinding],
    netlist: NetlistReport | None,
) -> CircuitTopology:
    symbols_by_ref: dict[str, SymbolFinding] = {}
    for sym in symbols:
        if sym.reference:
            symbols_by_ref[sym.reference] = sym

    power_symbol_refs = [
        ref
        for ref, sym in symbols_by_ref.items()
        if (sym.lib_id or "").lower().startswith("power:")
    ]

    pin_nets: list[PinNet] = []
    limitations: list[str] = []
    netlist_available = bool(netlist and netlist.ran and netlist.nets)

    if not netlist_available:
        limitations.append(
            "KiCad netlist connectivity is unavailable; supply-pin to rail mapping "
            "and pin-level checks cannot run until netlist export succeeds."
        )
        # Still suggest label-like candidates from global labels on symbols? Skip —
        # without nets we only list empty candidates.
        refs = sorted(symbols_by_ref.keys())
        return CircuitTopology(
            references=refs,
            symbols_by_ref=symbols_by_ref,
            pin_nets=[],
            nets_by_name={},
            candidate_supply_nets=[],
            power_symbol_refs=power_symbol_refs,
            netlist_available=False,
            limitations=limitations,
        )

    assert netlist is not None
    for net in netlist.nets or []:
        for node in net.nodes or []:
            pin_nets.append(
                PinNet(
                    reference=node.reference,
                    pin=node.pin,
                    net_name=net.name,
                    pintype=node.pintype,
                    pinfunction=node.pinfunction,
                )
            )

    nets_by_name: dict[str, list[PinNet]] = {}
    for pn in pin_nets:
        nets_by_name.setdefault(pn.net_name, []).append(pn)

    candidates: dict[str, str] = {}
    for pn in pin_nets:
        if _is_power_pin(pn.pintype, pn.pinfunction):
            candidates.setdefault(
                pn.net_name,
                "Connected to a power-typed pin in the KiCad netlist (candidate only).",
            )
        if _looks_like_supply_net_name(pn.net_name):
            candidates.setdefault(
                pn.net_name,
                "Net name resembles a supply label (candidate only — not a verified voltage).",
            )

    for ref in power_symbol_refs:
        # Power symbols may not appear in netlist components; still note related nets
        # that share the symbol value as a net name (e.g. GND).
        sym = symbols_by_ref.get(ref)
        value = (sym.value or "").strip() if sym else ""
        if value and value in nets_by_name:
            candidates.setdefault(
                value,
                f"Matches power symbol {ref} value (candidate only — not a verified voltage).",
            )

    limitations.append(
        "Candidate supply nets are suggestions for operator confirmation. "
        "Net names and power symbols are never treated as measured voltages."
    )

    refs = sorted(set(symbols_by_ref.keys()) | {pn.reference for pn in pin_nets})
    return CircuitTopology(
        references=refs,
        symbols_by_ref=symbols_by_ref,
        pin_nets=pin_nets,
        nets_by_name=nets_by_name,
        candidate_supply_nets=sorted(candidates.items(), key=lambda x: x[0]),
        power_symbol_refs=power_symbol_refs,
        netlist_available=True,
        limitations=limitations,
    )


def nets_for_reference(topology: CircuitTopology, reference: str) -> list[str]:
    return sorted({pn.net_name for pn in topology.pin_nets if pn.reference == reference})


def power_nets_for_reference(topology: CircuitTopology, reference: str) -> list[str]:
    return sorted(
        {
            pn.net_name
            for pn in topology.pin_nets
            if pn.reference == reference and _is_power_pin(pn.pintype, pn.pinfunction)
        }
    )
