"""Phase-1 Circuit Evidence Graph builder and analyze API integration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schematics.evidence.build import PHASE1_LIMITATIONS, build_evidence_graph
from app.schematics.models import (
    ConfirmedFindings,
    ErcFinding,
    ErcReport,
    NetlistReport,
    SymbolFinding,
)
from app.schematics.kicad_parser import parse_kicad_sch

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "schematics"


def _symbols_from_fixture(name: str) -> list[SymbolFinding]:
    data = (FIXTURES / name).read_bytes()
    return parse_kicad_sch(data)["symbols"]


def test_component_nodes_match_confirmed_symbols():
    symbols = _symbols_from_fixture("sample.kicad_sch")
    confirmed = ConfirmedFindings(symbols=symbols)
    graph = build_evidence_graph(confirmed, ErcReport(), scope_id="scopeA")
    components = [n for n in graph.nodes if n.kind == "component"]
    assert len(components) == len(symbols)
    assert {n.provenance for n in components} == {"parser"}
    assert all(n.id.startswith("scopeA:component:") for n in components)
    assert graph.citations == []
    for limitation in PHASE1_LIMITATIONS:
        assert limitation in graph.limitations


def test_empty_parser_results_produce_no_components():
    graph = build_evidence_graph(ConfirmedFindings(), ErcReport(), scope_id="empty")
    assert [n for n in graph.nodes if n.kind == "component"] == []
    assert graph.citations == []
    assert graph.limitations


def test_every_erc_finding_has_one_finding_node():
    findings = [
        ErcFinding(
            rule_id="power_pin_not_driven",
            severity="error",
            description="Input Power pin not driven",
            reference="U1",
            pin="3",
            x_mm=1.0,
            y_mm=2.0,
        ),
        ErcFinding(
            rule_id="lib_symbol_mismatch",
            severity="warning",
            description="Symbol mismatch",
            reference="U1",
            x_mm=3.0,
            y_mm=4.0,
        ),
    ]
    erc = ErcReport(ran=True, available=True, findings=findings, error_count=1, warning_count=1)
    confirmed = ConfirmedFindings(
        symbols=[
            SymbolFinding(reference="U1", value="OPAMP", lib_id="Simulation_SPICE:OPAMP", uuid="u1")
        ]
    )
    graph = build_evidence_graph(confirmed, erc, scope_id="op")
    finding_nodes = [n for n in graph.nodes if n.kind == "finding"]
    assert len(finding_nodes) == 2
    assert finding_nodes[0].attrs["rule_id"] == "power_pin_not_driven"
    assert finding_nodes[0].attrs["pin"] == "3"
    assert finding_nodes[0].attrs["x_mm"] == 1.0
    assert finding_nodes[1].attrs["severity"] == "warning"
    assert all(n.provenance == "kicad_erc" for n in finding_nodes)


def test_empty_erc_produces_no_finding_nodes():
    symbols = _symbols_from_fixture("sample.kicad_sch")
    graph = build_evidence_graph(
        ConfirmedFindings(symbols=symbols),
        ErcReport(ran=True, available=True, findings=[]),
        scope_id="noerc",
    )
    assert [n for n in graph.nodes if n.kind == "finding"] == []
    assert len([n for n in graph.nodes if n.kind == "component"]) == len(symbols)


def test_matching_reference_links_finding_to_component():
    confirmed = ConfirmedFindings(
        symbols=[SymbolFinding(reference="R1", value="1k", lib_id="Device:R", uuid="r1")]
    )
    erc = ErcReport(
        ran=True,
        findings=[
            ErcFinding(
                rule_id="power_pin_not_driven",
                severity="error",
                description="msg",
                reference="R1",
            )
        ],
    )
    graph = build_evidence_graph(confirmed, erc, scope_id="link")
    mention = [e for e in graph.edges if e.kind == "mentions_component"]
    assert len(mention) == 1
    assert mention[0].target_id.endswith("r1") or "component:r1" in mention[0].target_id
    assert mention[0].provenance == "kicad_erc"


def test_unmatched_reference_does_not_link_component():
    confirmed = ConfirmedFindings(
        symbols=[SymbolFinding(reference="R1", value="1k", lib_id="Device:R", uuid="r1")]
    )
    erc = ErcReport(
        ran=True,
        findings=[
            ErcFinding(
                rule_id="power_pin_not_driven",
                severity="error",
                description="msg",
                reference="U99",
                pin="1",
            )
        ],
    )
    graph = build_evidence_graph(confirmed, erc, scope_id="nolink")
    assert [e for e in graph.edges if e.kind == "mentions_component"] == []
    assert [e for e in graph.edges if e.kind == "has_pin"] == []
    # Pin may still exist from explicit ERC pin data, but is not attached via has_pin.
    pins = [n for n in graph.nodes if n.kind == "pin"]
    assert len(pins) == 1
    assert pins[0].attrs["reference"] == "U99"
    assert pins[0].attrs["pin"] == "1"


def test_pin_nodes_only_from_explicit_pin_data():
    confirmed = ConfirmedFindings(
        symbols=[SymbolFinding(reference="U1", lib_id="X:Y", uuid="u1")]
    )
    erc = ErcReport(
        ran=True,
        findings=[
            ErcFinding(
                rule_id="lib_symbol_mismatch",
                severity="warning",
                description="mismatch",
                reference="U1",
                # no pin
            ),
            ErcFinding(
                rule_id="power_pin_not_driven",
                severity="error",
                description="undriven",
                reference="U1",
                pin="4",
            ),
        ],
    )
    graph = build_evidence_graph(confirmed, erc, scope_id="pins")
    pins = [n for n in graph.nodes if n.kind == "pin"]
    assert len(pins) == 1
    assert pins[0].attrs["pin"] == "4"
    has_pin = [e for e in graph.edges if e.kind == "has_pin"]
    assert len(has_pin) == 1
    mentions_pin = [e for e in graph.edges if e.kind == "mentions_pin"]
    assert len(mentions_pin) == 1


def test_scope_ids_differ_across_analyses():
    sym = SymbolFinding(reference="R1", uuid="same-uuid")
    confirmed = ConfirmedFindings(symbols=[sym])
    g1 = build_evidence_graph(confirmed, ErcReport(), scope_id="uploadAAA")
    g2 = build_evidence_graph(confirmed, ErcReport(), scope_id="uploadBBB")
    assert g1.nodes[0].id != g2.nodes[0].id
    assert g1.nodes[0].id.startswith("uploadAAA:")
    assert g2.nodes[0].id.startswith("uploadBBB:")


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


def test_analyze_api_includes_evidence_graph(client):
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
    graph = body["evidence_graph"]
    assert graph is not None
    assert graph["citations"] == []
    assert any("Phase 1" in item for item in graph["limitations"])
    components = [n for n in graph["nodes"] if n["kind"] == "component"]
    assert len(components) == len(body["confirmed"]["symbols"])
    # ERC stubbed off → no finding nodes
    assert [n for n in graph["nodes"] if n["kind"] == "finding"] == []


def test_analyze_api_graph_with_stubbed_erc_findings(client, tmp_path, monkeypatch):
    from app.schematics.models import CoordinateMapping, ViewerInfo

    fake_erc = ErcReport(
        ran=True,
        available=True,
        findings=[
            ErcFinding(
                rule_id="power_pin_not_driven",
                severity="error",
                description="Input Power pin not driven",
                reference="R1",
                pin="1",
                x_mm=10.0,
                y_mm=20.0,
            )
        ],
        error_count=1,
    )
    fake_viewer = ViewerInfo(
        file_id="b" * 32,
        format="kicad_sch",
        source_url="/api/schematics/files/" + "b" * 32,
        preview_url=None,
        render_status="unavailable",
        render_message="stubbed",
        content_type="application/x-kicad-schematic",
        coordinate_mapping=CoordinateMapping(reliable=False),
    )

    with (
        patch("app.schematics.analyze.build_erc_report", return_value=fake_erc),
        patch(
            "app.schematics.analyze.build_netlist_report",
            return_value=NetlistReport(
                ran=False,
                available=False,
                failure_reason="stubbed netlist off",
            ),
        ),
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
    graph = response.json()["evidence_graph"]
    findings = [n for n in graph["nodes"] if n["kind"] == "finding"]
    assert len(findings) == 1
    assert findings[0]["attrs"]["rule_id"] == "power_pin_not_driven"
    assert any(e["kind"] == "mentions_component" for e in graph["edges"])
    assert any(n["kind"] == "pin" for n in graph["nodes"])
    assert graph["citations"] == []
