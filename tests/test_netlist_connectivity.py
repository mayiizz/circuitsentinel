"""Phase-2 verified connectivity: KiCad netlist parse + Evidence Graph nets."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schematics.evidence.build import PHASE2_LIMITATIONS, build_evidence_graph
from app.schematics.models import (
    ConfirmedFindings,
    ErcReport,
    NetlistReport,
    SymbolFinding,
)
from app.schematics.netlist import classify_net_name, parse_kicadxml_netlist

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "schematics"


def test_classify_net_name_distinguishes_explicit_generated_unconnected():
    assert classify_net_name("GND") == "explicit"
    assert classify_net_name("/Vmin") == "explicit"
    assert classify_net_name("V+") == "explicit"
    assert classify_net_name("Out") == "explicit"
    assert classify_net_name("/Audio/Left") == "explicit"
    assert classify_net_name("Network") == "explicit"
    assert classify_net_name("NetA") == "explicit"
    assert classify_net_name("Net-Foo") == "explicit"  # no KiCad paren form
    assert classify_net_name("unconnected") == "explicit"  # not unconnected-(…)
    assert classify_net_name("Net-(U1-Pad5)") == "generated"
    assert classify_net_name("unconnected-(U1-Pad2)") == "unconnected"
    # Hierarchical sheet path must not flip exporter-generated names to explicit.
    assert classify_net_name("/Net-(U1-Pad5)") == "generated"
    assert classify_net_name("/Child/unconnected-(R1-Pad1)") == "unconnected"
    assert classify_net_name("") == "generated"


def test_classify_preserves_original_name_on_parsed_nets():
    raw = """<?xml version="1.0" encoding="UTF-8"?>
<export version="E">
  <components/>
  <nets>
    <net code="1" name="/Child/Net-(R1-Pad1)" class="Default">
      <node ref="R1" pin="1"/>
    </net>
    <net code="2" name="/Audio/Left" class="Default">
      <node ref="R2" pin="1"/>
    </net>
  </nets>
</export>
"""
    report = parse_kicadxml_netlist(raw)
    assert report.ran is True
    by_code = {n.code: n for n in report.nets}
    assert by_code["1"].name == "/Child/Net-(R1-Pad1)"
    assert by_code["1"].name_kind == "generated"
    assert by_code["2"].name == "/Audio/Left"
    assert by_code["2"].name_kind == "explicit"


def test_parse_real_opamp_netlist_export():
    raw = (FIXTURES / "opamp_netlist.xml").read_text(encoding="utf-8")
    report = parse_kicadxml_netlist(raw)
    assert report.ran is True
    assert report.format == "kicadxml"
    assert report.component_count == 8
    assert report.net_count == 6

    by_name = {n.name: n for n in report.nets}
    assert by_name["GND"].name_kind == "explicit"
    assert by_name["/Vmin"].name_kind == "explicit"
    assert by_name["/Vplus"].name_kind == "explicit"
    assert by_name["V+"].name_kind == "explicit"
    assert by_name["V-"].name_kind == "explicit"
    assert by_name["Out"].name_kind == "explicit"

    # Label-backed local nets connect expected pins.
    vmin_refs = {(n.reference, n.pin) for n in by_name["/Vmin"].nodes}
    assert ("U1", "2") in vmin_refs
    assert ("R2", "2") in vmin_refs

    # Power net from power symbol / global naming.
    gnd_refs = {(n.reference, n.pin) for n in by_name["GND"].nodes}
    assert ("V1", "2") in gnd_refs
    assert ("R4", "2") in gnd_refs


def test_parse_synthetic_covers_labels_power_generated_unconnected_multiunit():
    raw = (FIXTURES / "netlist_connectivity.xml").read_text(encoding="utf-8")
    report = parse_kicadxml_netlist(raw)
    assert report.ran is True
    assert report.net_count == 6
    by_name = {n.name: n for n in report.nets}

    assert by_name["/NET_A"].name_kind == "explicit"
    assert {(n.reference, n.pin) for n in by_name["/NET_A"].nodes} == {
        ("R1", "1"),
        ("U1", "1"),
    }

    assert by_name["GND"].name_kind == "explicit"
    assert by_name["V+"].name_kind == "explicit"
    assert by_name["Net-(U1-Pad5)"].name_kind == "generated"
    assert by_name["unconnected-(U1-Pad2)"].name_kind == "unconnected"
    assert len(by_name["unconnected-(U1-Pad2)"].nodes) == 1
    assert by_name["unconnected-(U1-Pad2)"].nodes[0].reference == "U1"
    assert by_name["unconnected-(U1-Pad2)"].nodes[0].pin == "2"

    # Multi-unit reference U2 appears on distinct nets without inventing a second component.
    unit_b = {(n.reference, n.pin) for n in by_name["/UNIT_B"].nodes}
    assert unit_b == {("U2", "5"), ("U2", "6")}
    u2 = next(c for c in report.components if c.reference == "U2")
    assert {p.unit for p in u2.pins} == {"A", "B"}


def test_evidence_graph_nets_from_fixture_connected_and_unconnected():
    raw = (FIXTURES / "netlist_connectivity.xml").read_text(encoding="utf-8")
    netlist = parse_kicadxml_netlist(raw)
    confirmed = ConfirmedFindings(
        symbols=[
            SymbolFinding(reference="R1", value="10k", lib_id="Device:R", uuid="r1"),
            SymbolFinding(reference="U1", value="OPAMP", lib_id="X:OPAMP", uuid="u1"),
            # U2 intentionally absent — netlist pins must not invent a component.
        ]
    )
    graph = build_evidence_graph(
        confirmed, ErcReport(), scope_id="conn", netlist=netlist
    )

    nets = [n for n in graph.nodes if n.kind == "net"]
    assert len(nets) == 6
    assert {n.provenance for n in nets} == {"kicad_netlist"}
    kinds = {n.attrs["name"]: n.attrs["name_kind"] for n in nets}
    assert kinds["/NET_A"] == "explicit"
    assert kinds["GND"] == "explicit"
    assert kinds["Net-(U1-Pad5)"] == "generated"
    assert kinds["unconnected-(U1-Pad2)"] == "unconnected"

    connected = [e for e in graph.edges if e.kind == "connected_to"]
    assert len(connected) == sum(len(n.nodes) for n in netlist.nets)
    assert all(e.provenance == "kicad_netlist" for e in connected)

    # Confirmed components get has_pin; unmatched U2 pins exist but have no has_pin.
    has_pin = [e for e in graph.edges if e.kind == "has_pin"]
    has_pin_targets = {e.target_id for e in has_pin}
    assert "conn:pin:R1:1" in has_pin_targets
    assert "conn:pin:U1:2" in has_pin_targets
    assert not any(tid.startswith("conn:pin:U2:") for tid in has_pin_targets)

    pin_u2 = [n for n in graph.nodes if n.kind == "pin" and n.attrs.get("reference") == "U2"]
    assert pin_u2  # pins from netlist nodes still recorded
    assert all(n.id.startswith("conn:pin:U2:") for n in pin_u2)

    assert graph.citations == []
    for item in PHASE2_LIMITATIONS:
        assert item in graph.limitations


def test_pin_in_units_but_absent_from_nets_is_not_marked_unconnected():
    """Absence from <node> lists is not proof of an open — do not fabricate it."""
    raw = (FIXTURES / "netlist_connectivity.xml").read_text(encoding="utf-8")
    netlist = parse_kicadxml_netlist(raw)
    r1 = next(c for c in netlist.components if c.reference == "R1")
    assert {p.number for p in r1.pins} == {"1", "2"}
    connected = {(n.reference, n.pin) for net in netlist.nets for n in net.nodes}
    assert ("R1", "1") in connected
    assert ("R1", "2") not in connected

    graph = build_evidence_graph(
        ConfirmedFindings(
            symbols=[SymbolFinding(reference="R1", value="10k", uuid="r1")]
        ),
        ErcReport(),
        scope_id="absent",
        netlist=netlist,
    )
    assert "absent:pin:R1:1" in {n.id for n in graph.nodes}
    assert "absent:pin:R1:2" not in {n.id for n in graph.nodes}
    assert not any(
        e.kind == "connected_to" and e.source_id == "absent:pin:R1:2" for e in graph.edges
    )
    # No synthetic unconnected-* net invented for the missing pin.
    assert not any(
        n.kind == "net" and "R1" in n.attrs.get("name", "") and "unconnected" in n.attrs.get("name", "")
        for n in graph.nodes
    )


def test_has_pin_only_for_confirmed_components_and_connected_to_uses_pin_ids():
    raw = (FIXTURES / "netlist_connectivity.xml").read_text(encoding="utf-8")
    netlist = parse_kicadxml_netlist(raw)
    confirmed = ConfirmedFindings(
        symbols=[SymbolFinding(reference="R1", uuid="r1")]
    )
    graph = build_evidence_graph(
        confirmed, ErcReport(), scope_id="ids", netlist=netlist
    )
    component_ids = {n.id for n in graph.nodes if n.kind == "component"}
    for edge in graph.edges:
        if edge.kind == "has_pin":
            assert edge.source_id in component_ids
            assert edge.target_id.startswith("ids:pin:")
            # Unconfirmed U2 must never receive has_pin.
            assert ":U2:" not in edge.target_id
        if edge.kind == "connected_to":
            assert edge.source_id.startswith("ids:pin:")
            assert edge.target_id.startswith("ids:net:")
            pin = next(n for n in graph.nodes if n.id == edge.source_id)
            assert edge.source_id == (
                f"ids:pin:{pin.attrs['reference']}:{pin.attrs['pin']}"
            )


def test_export_uses_temp_copy_and_leaves_source_unchanged(tmp_path, monkeypatch):
    """CLI must receive the temp copy path; uploaded bytes/mtime stay untouched."""
    import hashlib
    import shutil
    from unittest.mock import MagicMock

    from app.schematics import netlist as netlist_mod

    src = tmp_path / "upload.kicad_sch"
    shutil.copy2(FIXTURES / "sample.kicad_sch", src)
    before_hash = hashlib.sha256(src.read_bytes()).hexdigest()
    before_mtime = src.stat().st_mtime_ns

    fixture_xml = (FIXTURES / "opamp_netlist.xml").read_text(encoding="utf-8")
    seen_args: list[list[str]] = []

    def fake_run(args, **kwargs):
        seen_args.append(list(args))
        out = Path(args[args.index("--output") + 1])
        out.write_text(fixture_xml, encoding="utf-8")
        # Confirm CLI input is the temp copy, not the original upload path.
        input_path = Path(args[-1])
        assert input_path.resolve() != src.resolve()
        assert "circuitsentinel-netlist-" in input_path.parent.name
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(netlist_mod, "find_kicad_cli", lambda: "/fake/kicad-cli")
    monkeypatch.setattr(netlist_mod, "probe_kicad_cli_export_netlist", lambda: True)
    monkeypatch.setattr(netlist_mod.subprocess, "run", fake_run)

    report = netlist_mod.build_netlist_report(schematic_path=src)
    assert report.ran is True
    assert report.net_count == 6
    assert seen_args, "kicad-cli should have been invoked"
    assert "--format" in seen_args[0] and "kicadxml" in seen_args[0]
    assert hashlib.sha256(src.read_bytes()).hexdigest() == before_hash
    assert src.stat().st_mtime_ns == before_mtime


def test_empty_netlist_export_produces_no_net_nodes():
    empty = NetlistReport(
        ran=True,
        available=True,
        format="kicadxml",
        components=[],
        nets=[],
        component_count=0,
        net_count=0,
        limitations=["empty export"],
    )
    confirmed = ConfirmedFindings(
        symbols=[SymbolFinding(reference="R1", uuid="r1")]
    )
    graph = build_evidence_graph(confirmed, ErcReport(), scope_id="empty", netlist=empty)
    assert [n for n in graph.nodes if n.kind == "net"] == []
    assert [e for e in graph.edges if e.kind == "connected_to"] == []
    assert len([n for n in graph.nodes if n.kind == "component"]) == 1


def test_failed_netlist_export_adds_no_nets_and_records_limitation():
    failed = NetlistReport(
        ran=False,
        available=True,
        failure_reason="KiCad CLI netlist export failed: boom",
    )
    confirmed = ConfirmedFindings(
        symbols=[SymbolFinding(reference="R1", uuid="r1")]
    )
    graph = build_evidence_graph(confirmed, ErcReport(), scope_id="fail", netlist=failed)
    assert [n for n in graph.nodes if n.kind == "net"] == []
    assert "KiCad CLI netlist export failed: boom" in graph.limitations
    assert graph.citations == []


def test_malformed_netlist_xml_is_honest_failure():
    report = parse_kicadxml_netlist("<not-valid")
    assert report.ran is False
    assert report.nets == []
    assert report.failure_reason and "parse failed" in report.failure_reason.lower()


def test_phase1_erc_nodes_preserved_alongside_nets():
    from app.schematics.models import ErcFinding

    netlist = parse_kicadxml_netlist(
        (FIXTURES / "netlist_connectivity.xml").read_text(encoding="utf-8")
    )
    confirmed = ConfirmedFindings(
        symbols=[SymbolFinding(reference="U1", uuid="u1")]
    )
    erc = ErcReport(
        ran=True,
        findings=[
            ErcFinding(
                rule_id="power_pin_not_driven",
                severity="error",
                description="undriven",
                reference="U1",
                pin="3",
            )
        ],
    )
    graph = build_evidence_graph(confirmed, erc, scope_id="both", netlist=netlist)
    assert len([n for n in graph.nodes if n.kind == "finding"]) == 1
    assert len([n for n in graph.nodes if n.kind == "net"]) == 6
    assert any(e.kind == "mentions_component" for e in graph.edges)
    assert any(e.kind == "connected_to" for e in graph.edges)
    # Shared pin identity for U1 pin 3 (ERC + netlist V+)
    pins_u1_3 = [
        n for n in graph.nodes if n.id == "both:pin:U1:3"
    ]
    assert len(pins_u1_3) == 1


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import app.schematics.config as config
    import app.schematics.storage as storage

    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(storage, "ensure_upload_dir", config.ensure_upload_dir)
    monkeypatch.setattr("app.schematics.erc.find_kicad_cli", lambda: None)
    monkeypatch.setattr("app.schematics.erc.probe_kicad_cli_erc", lambda: False)
    monkeypatch.setattr("app.schematics.netlist.find_kicad_cli", lambda: None)
    monkeypatch.setattr(
        "app.schematics.netlist.probe_kicad_cli_export_netlist", lambda: False
    )
    monkeypatch.setattr("app.schematics.render.find_kicad_cli", lambda: None)
    return TestClient(app)


def test_analyze_api_includes_netlist_and_graph_when_export_stubbed(client):
    netlist = parse_kicadxml_netlist(
        (FIXTURES / "opamp_netlist.xml").read_text(encoding="utf-8")
    )
    from app.schematics.models import CoordinateMapping, ViewerInfo

    fake_viewer = ViewerInfo(
        file_id="c" * 32,
        format="kicad_sch",
        source_url="/api/schematics/files/" + "c" * 32,
        preview_url=None,
        render_status="unavailable",
        render_message="stubbed",
        content_type="application/x-kicad-schematic",
        coordinate_mapping=CoordinateMapping(reliable=False),
    )
    with (
        patch("app.schematics.analyze.build_erc_report", return_value=ErcReport()),
        patch("app.schematics.analyze.build_netlist_report", return_value=netlist),
        patch("app.schematics.analyze.build_viewer_info", return_value=fake_viewer),
    ):
        response = client.post(
            "/api/schematics/analyze",
            files={
                "file": (
                    "OPamp-comparator.kicad_sch",
                    (FIXTURES / "OPamp-comparator.kicad_sch").read_bytes(),
                    "application/octet-stream",
                )
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["netlist"]["ran"] is True
    assert body["netlist"]["net_count"] == 6
    graph = body["evidence_graph"]
    assert graph["citations"] == []
    nets = [n for n in graph["nodes"] if n["kind"] == "net"]
    assert len(nets) == 6
    assert any(n["attrs"]["name"] == "GND" for n in nets)
    assert any(n["attrs"]["name"] == "/Vmin" for n in nets)
    assert any(e["kind"] == "connected_to" for e in graph["edges"])
    assert any("Phase 2" in item for item in graph["limitations"])


def test_analyze_api_export_failure_leaves_graph_without_nets(client):
    failed = NetlistReport(
        ran=False,
        available=True,
        failure_reason="KiCad CLI netlist export failed: stub",
    )
    from app.schematics.models import CoordinateMapping, ViewerInfo

    fake_viewer = ViewerInfo(
        file_id="d" * 32,
        format="kicad_sch",
        source_url="/api/schematics/files/" + "d" * 32,
        preview_url=None,
        render_status="unavailable",
        render_message="stubbed",
        content_type="application/x-kicad-schematic",
        coordinate_mapping=CoordinateMapping(reliable=False),
    )
    with (
        patch("app.schematics.analyze.build_erc_report", return_value=ErcReport()),
        patch("app.schematics.analyze.build_netlist_report", return_value=failed),
        patch("app.schematics.analyze.build_viewer_info", return_value=fake_viewer),
    ):
        response = client.post(
            "/api/schematics/analyze",
            files={
                "file": (
                    "sample.kicad_sch",
                    (FIXTURES / "sample.kicad_sch").read_bytes(),
                    "application/octet-stream",
                )
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["netlist"]["ran"] is False
    graph = body["evidence_graph"]
    assert [n for n in graph["nodes"] if n["kind"] == "net"] == []
    assert "KiCad CLI netlist export failed: stub" in graph["limitations"]
