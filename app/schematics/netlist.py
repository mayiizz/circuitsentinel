"""Export and parse KiCad schematic connectivity via kicad-cli netlist.

Uses documented ``sch export netlist --format kicadxml`` output only.
Never reconstructs nets from wires, junctions, or coordinates.
Never modifies the original uploaded schematic.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from app.schematics.kicad_cli import find_kicad_cli, probe_kicad_cli_export_netlist
from app.schematics.models import (
    NetlistComponent,
    NetlistNet,
    NetlistNode,
    NetlistPin,
    NetlistReport,
)

HOW_TO_ENABLE = (
    "Install KiCad and ensure `kicad-cli` is on PATH "
    "(verify with `kicad-cli sch export netlist --help`), or set CIRCUITSENTINEL_KICAD_CLI "
    "to the executable. CircuitSentinel will not invent schematic connectivity."
)

# KiCad auto-generated net name patterns (documented exporter conventions).
_GENERATED_NET_RE = re.compile(r"^Net-\(", re.IGNORECASE)
_UNCONNECTED_NET_RE = re.compile(r"^unconnected-\(", re.IGNORECASE)


def classify_net_name(name: str) -> str:
    """Return ``explicit``, ``generated``, or ``unconnected`` for a KiCad net name.

    The original net name string is never rewritten — only classified. KiCad may
    prefix hierarchical names with sheet paths (``/Sheet/Net-(…)``); classification
    uses the leaf segment after the final ``/`` so path prefixes do not turn
    exporter-generated names into ``explicit``.
    """
    cleaned = (name or "").strip()
    if not cleaned:
        return "generated"
    # Preserve full name elsewhere; classify the leaf after optional sheet path.
    leaf = cleaned.rsplit("/", 1)[-1]
    if _UNCONNECTED_NET_RE.match(leaf):
        return "unconnected"
    if _GENERATED_NET_RE.match(leaf):
        return "generated"
    return "explicit"


def build_netlist_report(*, schematic_path: str | Path | None = None) -> NetlistReport:
    """Export connectivity when possible; never invent nets on failure."""
    cli = find_kicad_cli()
    available = bool(cli) and probe_kicad_cli_export_netlist()

    if schematic_path is None:
        return NetlistReport(
            ran=False,
            available=available,
            how_to_enable=HOW_TO_ENABLE,
            failure_reason=(
                None
                if available
                else "KiCad CLI is not available; netlist export was not executed."
            ),
        )

    path = Path(schematic_path)
    if path.suffix.lower() != ".kicad_sch":
        return NetlistReport(
            ran=False,
            available=False,
            how_to_enable=HOW_TO_ENABLE,
            failure_reason="Netlist export applies only to KiCad schematic (.kicad_sch) files.",
        )

    if not available or cli is None:
        return NetlistReport(
            ran=False,
            available=False,
            how_to_enable=HOW_TO_ENABLE,
            failure_reason="KiCad CLI is not available; netlist export was not executed.",
        )

    if not path.is_file():
        return NetlistReport(
            ran=False,
            available=True,
            how_to_enable=HOW_TO_ENABLE,
            failure_reason=f"Schematic file not found for netlist export: {path.name}",
        )

    try:
        return _export_netlist_on_copy(cli=cli, schematic_path=path)
    except Exception as exc:  # noqa: BLE001 — surface as honest failure
        return NetlistReport(
            ran=False,
            available=True,
            how_to_enable=HOW_TO_ENABLE,
            failure_reason=f"Netlist export failed: {type(exc).__name__}: {exc}",
        )


def _export_netlist_on_copy(*, cli: str, schematic_path: Path) -> NetlistReport:
    """Copy the schematic to a temp dir, export kicadxml, parse, delete temps."""
    work = Path(tempfile.mkdtemp(prefix="circuitsentinel-netlist-"))
    try:
        copy_name = f"{uuid.uuid4().hex}.kicad_sch"
        copy_path = work / copy_name
        out_path = work / f"{uuid.uuid4().hex}-netlist.xml"
        shutil.copy2(schematic_path, copy_path)

        completed = subprocess.run(
            [
                cli,
                "sch",
                "export",
                "netlist",
                "--format",
                "kicadxml",
                "--output",
                str(out_path),
                str(copy_path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

        if completed.returncode != 0 and not out_path.is_file():
            detail = (completed.stderr or completed.stdout or "").strip()
            return NetlistReport(
                ran=False,
                available=True,
                how_to_enable=HOW_TO_ENABLE,
                failure_reason=(
                    "KiCad CLI netlist export failed"
                    + (f": {detail[:400]}" if detail else ".")
                ),
            )

        if not out_path.is_file():
            detail = (completed.stderr or completed.stdout or "").strip()
            return NetlistReport(
                ran=False,
                available=True,
                how_to_enable=HOW_TO_ENABLE,
                failure_reason=(
                    "KiCad CLI did not write a netlist file"
                    + (f": {detail[:400]}" if detail else ".")
                ),
            )

        raw = out_path.read_text(encoding="utf-8")
        return parse_kicadxml_netlist(raw)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def parse_kicadxml_netlist(raw: str) -> NetlistReport:
    """Parse KiCad ``kicadxml`` netlist export into typed connectivity facts."""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        return NetlistReport(
            ran=False,
            available=True,
            how_to_enable=HOW_TO_ENABLE,
            failure_reason=f"Netlist XML parse failed: {exc}",
        )

    if root.tag != "export":
        return NetlistReport(
            ran=False,
            available=True,
            how_to_enable=HOW_TO_ENABLE,
            failure_reason=f"Unexpected netlist root element: {root.tag!r}",
        )

    tool = None
    design = root.find("design")
    if design is not None:
        tool = (design.findtext("tool") or "").strip() or None

    components: list[NetlistComponent] = []
    comps_el = root.find("components")
    if comps_el is not None:
        for comp in comps_el.findall("comp"):
            parsed = _parse_component(comp)
            if parsed is not None:
                components.append(parsed)

    nets: list[NetlistNet] = []
    nets_el = root.find("nets")
    if nets_el is not None:
        for net_el in nets_el.findall("net"):
            parsed_net = _parse_net(net_el)
            if parsed_net is not None:
                nets.append(parsed_net)

    limitations = [
        "Connectivity comes only from KiCad kicadxml netlist export — not from wire counts or coordinates.",
        "Pins absent from exported nets are not asserted as unconnected; missing export data is not an open.",
        "Power symbols may appear only as named nets (e.g. GND) without a separate component entry.",
        "Hierarchical sheet resolution depends on KiCad finding child sheet files beside the root schematic.",
        "Multi-unit symbols share one reference; pin identity is reference + pin number from the exporter.",
        "No datasheet facts or electrical-rule conclusions are derived from this netlist.",
    ]
    if not components and not nets:
        limitations.append(
            "Netlist export produced no components or nets; hierarchical or incomplete "
            "schematics may yield empty connectivity without implying an open circuit."
        )

    return NetlistReport(
        ran=True,
        available=True,
        format="kicadxml",
        components=components,
        nets=nets,
        component_count=len(components),
        net_count=len(nets),
        how_to_enable=HOW_TO_ENABLE,
        failure_reason=None,
        kicad_tool=tool,
        limitations=limitations,
    )


def _parse_component(comp: ET.Element) -> NetlistComponent | None:
    ref = (comp.get("ref") or "").strip()
    if not ref:
        return None
    value = (comp.findtext("value") or "").strip() or None
    footprint = (comp.findtext("footprint") or "").strip() or None
    tstamps = (comp.findtext("tstamps") or "").strip() or None
    lib_id = None
    libsource = comp.find("libsource")
    if libsource is not None:
        lib = (libsource.get("lib") or "").strip()
        part = (libsource.get("part") or "").strip()
        if lib or part:
            lib_id = f"{lib}:{part}" if lib else part

    sheetpath = None
    sheet_el = comp.find("sheetpath")
    if sheet_el is not None:
        sheetpath = (sheet_el.get("names") or "").strip() or None

    pins: list[NetlistPin] = []
    units = comp.find("units")
    if units is not None:
        for unit in units.findall("unit"):
            unit_name = (unit.get("name") or "").strip() or None
            pins_el = unit.find("pins")
            if pins_el is None:
                continue
            for pin in pins_el.findall("pin"):
                num = (pin.get("num") or "").strip()
                if not num:
                    continue
                pins.append(NetlistPin(number=num, unit=unit_name))

    return NetlistComponent(
        reference=ref,
        value=value,
        lib_id=lib_id,
        footprint=footprint,
        tstamps=tstamps,
        sheetpath=sheetpath,
        pins=pins,
    )


def _parse_net(net_el: ET.Element) -> NetlistNet | None:
    code = (net_el.get("code") or "").strip()
    name = net_el.get("name")
    if name is None:
        name = ""
    else:
        name = str(name)
    if not code and not name:
        return None
    net_class = (net_el.get("class") or "").strip() or None
    nodes: list[NetlistNode] = []
    for node in net_el.findall("node"):
        ref = (node.get("ref") or "").strip()
        pin = (node.get("pin") or "").strip()
        if not ref or not pin:
            continue
        nodes.append(
            NetlistNode(
                reference=ref,
                pin=pin,
                pintype=(node.get("pintype") or "").strip() or None,
                pinfunction=(node.get("pinfunction") or "").strip() or None,
            )
        )
    return NetlistNet(
        code=code or name,
        name=name,
        name_kind=classify_net_name(name),  # type: ignore[arg-type]
        net_class=net_class,
        nodes=nodes,
    )


def netlist_status_dict() -> dict[str, Any]:
    report = build_netlist_report()
    return report.model_dump()
