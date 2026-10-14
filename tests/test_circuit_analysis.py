"""Circuit-level electrical analysis: rails, supply, pin checks, aggregation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.circuit.models import (
    CircuitCheckFinding,
    ComponentInventoryItem,
    RailEntry,
)
from app.circuit.rules.engine import aggregate_assessment
from app.circuit.rules.pin_voltage import run_pin_voltage_checks
from app.circuit.rules.supply import run_supply_checks
from app.circuit.rules.unsupported import run_unsupported_stubs
from app.circuit.topology import CircuitTopology, PinNet, build_topology
from app.datasheets.models import (
    DatasheetComponentLink,
    DatasheetIngestReport,
    DatasheetSource,
    NormalizedDatasheetFact,
)
from app.datasheets.store import store_ingest_report, store_link
from app.main import app
from app.schematics.models import (
    NetlistComponent,
    NetlistNet,
    NetlistNode,
    NetlistReport,
    SymbolFinding,
)
from app.schematics.storage import store_upload

FIXTURES_SCH = Path(__file__).resolve().parent / "fixtures" / "schematics"
client = TestClient(app)


@pytest.fixture()
def upload_env(tmp_path, monkeypatch):
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
    return tmp_path


def _fact(
    *,
    fact_type: str,
    value: float,
    qualifiers: list[str],
    sha: str,
    page: int = 1,
) -> NormalizedDatasheetFact:
    return NormalizedDatasheetFact(
        id=f"fact-{fact_type}-{value}-{'-'.join(qualifiers)}",
        fact_type=fact_type,  # type: ignore[arg-type]
        value=value,
        unit="V",
        qualifiers=qualifiers,
        source_content_sha256=sha,
        page_number=page,
        supporting_evidence_id="ev-1",
        supporting_excerpt=f"{fact_type} {value} V",
    )


def _store_linked(
    *,
    file_id: str,
    reference: str,
    sha: str,
    facts: list[NormalizedDatasheetFact],
    document_id: str = "doc-1",
) -> None:
    report = DatasheetIngestReport(
        status="ok",
        source=DatasheetSource(
            document_id=document_id,
            filename="part.pdf",
            content_sha256=sha,
            page_count=1,
            byte_length=10,
        ),
        facts=facts,
        raw_evidence=[],
        unresolved=[],
        limitations=[],
    )
    store_ingest_report(report)
    store_link(
        DatasheetComponentLink(
            id=f"{file_id}:{reference}:{sha[:16]}",
            schematic_file_id=file_id,
            component_reference=reference,
            document_id=document_id,
            content_sha256=sha,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
    )


def _topo_single_rail(*, refs: list[str] = ("U1",), net: str = "VCC") -> CircuitTopology:
    pin_nets = [
        PinNet(reference=ref, pin="8", net_name=net, pintype="power_in", pinfunction="VCC")
        for ref in refs
    ]
    symbols = {
        ref: SymbolFinding(reference=ref, value="IC", lib_id="Device:IC") for ref in refs
    }
    return CircuitTopology(
        references=list(refs),
        symbols_by_ref=symbols,
        pin_nets=pin_nets,
        nets_by_name={net: list(pin_nets)},
        candidate_supply_nets=[(net, "power pin")],
        power_symbol_refs=[],
        netlist_available=True,
    )


def _inv(ref: str, *, sha: str | None = None) -> ComponentInventoryItem:
    return ComponentInventoryItem(
        reference=ref,
        value="IC",
        lib_id="Device:IC",
        datasheet_linked=sha is not None,
        content_sha256=sha,
        identity_status="linked" if sha else "unresolved",
        connected_nets=["VCC"],
    )


# --- Unit: stubs & aggregation -------------------------------------------------


def test_unsupported_stubs_always_not_performed():
    findings = run_unsupported_stubs()
    assert {f.check_id for f in findings} == {
        "current_limit_compatibility",
        "power_dissipation",
    }
    assert all(f.status == "not_performed" for f in findings)


def test_aggregate_violation_over_inconclusive_over_pass():
    findings = [
        CircuitCheckFinding(
            check_id="a", status="passed", explanation="ok", component_refs=["U1"]
        ),
        CircuitCheckFinding(
            check_id="b", status="inconclusive", explanation="?", component_refs=["U2"]
        ),
        CircuitCheckFinding(
            check_id="c", status="violation", explanation="bad", component_refs=["U3"]
        ),
    ]
    assessment, counts, _ = aggregate_assessment(findings)
    assert assessment == "violations_detected"
    assert counts.checks_violations == 1

    findings2 = [
        CircuitCheckFinding(check_id="a", status="passed", explanation="ok"),
        CircuitCheckFinding(check_id="b", status="inconclusive", explanation="?"),
        CircuitCheckFinding(check_id="c", status="not_performed", explanation="np"),
    ]
    assessment2, _, not_perf = aggregate_assessment(findings2)
    assert assessment2 == "inconclusive"
    assert "c" in not_perf

    findings3 = [
        CircuitCheckFinding(check_id="a", status="passed", explanation="ok"),
        CircuitCheckFinding(check_id="b", status="not_performed", explanation="np"),
    ]
    assessment3, _, _ = aggregate_assessment(findings3)
    assert assessment3 == "no_violations_found_within_scope"


def test_topology_candidates_do_not_invent_volts():
    symbols = [
        SymbolFinding(reference="U1", value="OPAMP", lib_id="Simulation_SPICE:OPAMP"),
        SymbolFinding(reference="#PWR01", value="GND", lib_id="power:GND"),
    ]
    netlist = NetlistReport(
        ran=True,
        available=True,
        format="kicadxml",
        components=[NetlistComponent(reference="U1", value="OPAMP", lib_id="X:Y")],
        nets=[
            NetlistNet(
                code="1",
                name="V+",
                name_kind="explicit",
                nodes=[
                    NetlistNode(
                        reference="U1", pin="8", pintype="power_in", pinfunction="V+"
                    ),
                ],
            ),
            NetlistNet(
                code="2",
                name="GND",
                name_kind="explicit",
                nodes=[
                    NetlistNode(
                        reference="U1", pin="4", pintype="power_in", pinfunction="V-"
                    ),
                ],
            ),
        ],
        component_count=1,
        net_count=2,
    )
    topo = build_topology(symbols=symbols, netlist=netlist)
    names = {n for n, _ in topo.candidate_supply_nets}
    assert "V+" in names
    assert "GND" in names
    assert all(isinstance(reason, str) and reason for _, reason in topo.candidate_supply_nets)


# --- Unit: supply rule matrix ---------------------------------------------------


def test_supply_missing_rail_inconclusive(upload_env):
    sha = "a" * 64
    _store_linked(
        file_id="0" * 32,
        reference="U1",
        sha=sha,
        facts=[
            _fact(
                fact_type="supply_voltage_min",
                value=3.0,
                qualifiers=["recommended_operating"],
                sha=sha,
            ),
            _fact(
                fact_type="supply_voltage_max",
                value=32.0,
                qualifiers=["recommended_operating"],
                sha=sha,
            ),
        ],
    )
    topo = _topo_single_rail()
    rails = [RailEntry(net_name="VCC", status="unconfirmed", source="operator")]
    findings = run_supply_checks(
        topology=topo,
        inventory=[_inv("U1", sha=sha)],
        rails=rails,
        device_variants={},
    )
    supply = [f for f in findings if f.check_id == "supply_rail_vs_recommended"]
    assert supply
    assert all(f.status == "inconclusive" for f in supply)


def test_supply_same_rail_multi_component_pass_and_violation(upload_env):
    sha1 = "b" * 64
    sha2 = "c" * 64
    _store_linked(
        file_id="0" * 32,
        reference="U1",
        sha=sha1,
        facts=[
            _fact(
                fact_type="supply_voltage_min",
                value=3.0,
                qualifiers=["recommended_operating"],
                sha=sha1,
            ),
            _fact(
                fact_type="supply_voltage_max",
                value=5.5,
                qualifiers=["recommended_operating"],
                sha=sha1,
            ),
        ],
    )
    _store_linked(
        file_id="0" * 32,
        reference="U2",
        sha=sha2,
        document_id="doc-2",
        facts=[
            _fact(
                fact_type="supply_voltage_min",
                value=3.0,
                qualifiers=["recommended_operating"],
                sha=sha2,
            ),
            _fact(
                fact_type="supply_voltage_max",
                value=3.6,
                qualifiers=["recommended_operating"],
                sha=sha2,
            ),
        ],
    )
    topo = _topo_single_rail(refs=["U1", "U2"], net="VCC")
    rails = [
        RailEntry(net_name="VCC", value_v=5.0, status="confirmed", source="operator")
    ]
    findings = run_supply_checks(
        topology=topo,
        inventory=[_inv("U1", sha=sha1), _inv("U2", sha=sha2)],
        rails=rails,
        device_variants={},
    )
    by_ref = {
        f.component_refs[0]: f
        for f in findings
        if f.check_id == "supply_rail_vs_recommended"
    }
    assert by_ref["U1"].status == "passed"
    assert by_ref["U2"].status == "violation"


def test_dual_supply_partial_inconclusive(upload_env):
    sha = "d" * 64
    _store_linked(
        file_id="0" * 32,
        reference="U1",
        sha=sha,
        facts=[
            _fact(
                fact_type="supply_voltage_min",
                value=3.0,
                qualifiers=["recommended_operating"],
                sha=sha,
            ),
            _fact(
                fact_type="supply_voltage_max",
                value=32.0,
                qualifiers=["recommended_operating"],
                sha=sha,
            ),
        ],
    )
    pin_nets = [
        PinNet(
            reference="U1", pin="8", net_name="V+", pintype="power_in", pinfunction="V+"
        ),
        PinNet(
            reference="U1", pin="4", net_name="V-", pintype="power_in", pinfunction="V-"
        ),
    ]
    topo = CircuitTopology(
        references=["U1"],
        symbols_by_ref={"U1": SymbolFinding(reference="U1", lib_id="Device:IC")},
        pin_nets=pin_nets,
        nets_by_name={"V+": [pin_nets[0]], "V-": [pin_nets[1]]},
        candidate_supply_nets=[("V+", "power"), ("V-", "power")],
        power_symbol_refs=[],
        netlist_available=True,
    )
    rails = [
        RailEntry(net_name="V+", value_v=15.0, status="confirmed", source="operator"),
        RailEntry(net_name="V-", status="unconfirmed", source="operator"),
    ]
    findings = run_supply_checks(
        topology=topo,
        inventory=[_inv("U1", sha=sha)],
        rails=rails,
        device_variants={},
    )
    supply = [f for f in findings if f.check_id == "supply_rail_vs_recommended"]
    assert any(f.status == "inconclusive" for f in supply)
    assert any("Dual-supply" in f.explanation or "unknown" in f.explanation.lower() for f in supply)


def test_abs_max_warning_separate_from_recommended(upload_env):
    sha = "e" * 64
    _store_linked(
        file_id="0" * 32,
        reference="U1",
        sha=sha,
        facts=[
            _fact(
                fact_type="supply_voltage_min",
                value=3.0,
                qualifiers=["recommended_operating"],
                sha=sha,
            ),
            _fact(
                fact_type="supply_voltage_max",
                value=30.0,
                qualifiers=["recommended_operating"],
                sha=sha,
            ),
            _fact(
                fact_type="supply_voltage_max",
                value=32.0,
                qualifiers=["absolute_maximum"],
                sha=sha,
            ),
        ],
    )
    topo = _topo_single_rail()
    # Within recommended, within abs-max
    rails_ok = [
        RailEntry(net_name="VCC", value_v=5.0, status="confirmed", source="operator")
    ]
    findings_ok = run_supply_checks(
        topology=topo,
        inventory=[_inv("U1", sha=sha)],
        rails=rails_ok,
        device_variants={},
    )
    supply = [f for f in findings_ok if f.check_id == "supply_rail_vs_recommended"]
    absmax = [f for f in findings_ok if f.check_id == "absolute_maximum_supply_warning"]
    assert supply and supply[0].status == "passed"
    assert absmax and absmax[0].status == "passed"

    # Above recommended but below abs-max → recommended violation, abs-max still passed
    rails_hi = [
        RailEntry(net_name="VCC", value_v=31.0, status="confirmed", source="operator")
    ]
    findings_hi = run_supply_checks(
        topology=topo,
        inventory=[_inv("U1", sha=sha)],
        rails=rails_hi,
        device_variants={},
    )
    supply_hi = [f for f in findings_hi if f.check_id == "supply_rail_vs_recommended"]
    abs_hi = [f for f in findings_hi if f.check_id == "absolute_maximum_supply_warning"]
    assert supply_hi[0].status == "violation"
    assert abs_hi[0].status == "passed"

    # Above abs-max → warning (not used as recommended pass)
    rails_over = [
        RailEntry(net_name="VCC", value_v=40.0, status="confirmed", source="operator")
    ]
    findings_over = run_supply_checks(
        topology=topo,
        inventory=[_inv("U1", sha=sha)],
        rails=rails_over,
        device_variants={},
    )
    abs_over = [
        f for f in findings_over if f.check_id == "absolute_maximum_supply_warning"
    ]
    assert abs_over[0].status == "warning"


def test_unlinked_component_inconclusive(upload_env):
    topo = _topo_single_rail()
    rails = [
        RailEntry(net_name="VCC", value_v=5.0, status="confirmed", source="operator")
    ]
    findings = run_supply_checks(
        topology=topo,
        inventory=[_inv("U1", sha=None)],
        rails=rails,
        device_variants={},
    )
    assert findings[0].status == "inconclusive"
    assert "datasheet link" in findings[0].explanation.lower()


# --- Unit: pin voltage ----------------------------------------------------------


def test_pin_voltage_hard_tie_violation(upload_env):
    sha = "f" * 64
    _store_linked(
        file_id="0" * 32,
        reference="U2",
        sha=sha,
        facts=[
            _fact(
                fact_type="input_voltage_max",
                value=3.6,
                qualifiers=["recommended_operating"],
                sha=sha,
            ),
            _fact(
                fact_type="input_voltage_min",
                value=-0.3,
                qualifiers=["recommended_operating"],
                sha=sha,
            ),
        ],
    )
    # Driver U1 output hard-tied to confirmed 5 V rail; receiver U2 input on same net.
    pin_nets = [
        PinNet(reference="U1", pin="1", net_name="SIG", pintype="output"),
        PinNet(reference="U2", pin="2", net_name="SIG", pintype="input"),
    ]
    topo = CircuitTopology(
        references=["U1", "U2"],
        symbols_by_ref={
            "U1": SymbolFinding(reference="U1", lib_id="Device:IC"),
            "U2": SymbolFinding(reference="U2", lib_id="Device:IC"),
        },
        pin_nets=pin_nets,
        nets_by_name={"SIG": pin_nets},
        candidate_supply_nets=[],
        power_symbol_refs=[],
        netlist_available=True,
    )
    rails = [
        RailEntry(net_name="SIG", value_v=5.0, status="confirmed", source="operator")
    ]
    findings = run_pin_voltage_checks(
        topology=topo,
        inventory=[
            _inv("U1", sha=None),
            ComponentInventoryItem(
                reference="U2",
                datasheet_linked=True,
                content_sha256=sha,
                identity_status="linked",
                connected_nets=["SIG"],
            ),
        ],
        rails=rails,
        device_variants={},
    )
    pin = [f for f in findings if f.check_id == "pin_voltage_compatibility"]
    assert any(f.status == "violation" for f in pin)


def test_pin_voltage_without_signal_voltage_inconclusive(upload_env):
    sha = "11" * 32
    _store_linked(
        file_id="0" * 32,
        reference="U2",
        sha=sha,
        facts=[
            _fact(
                fact_type="input_voltage_max",
                value=5.5,
                qualifiers=["recommended_operating"],
                sha=sha,
            ),
        ],
    )
    pin_nets = [
        PinNet(reference="U1", pin="1", net_name="SIG", pintype="output"),
        PinNet(reference="U2", pin="2", net_name="SIG", pintype="input"),
    ]
    topo = CircuitTopology(
        references=["U1", "U2"],
        symbols_by_ref={
            "U1": SymbolFinding(reference="U1", lib_id="Device:IC"),
            "U2": SymbolFinding(reference="U2", lib_id="Device:IC"),
        },
        pin_nets=pin_nets,
        nets_by_name={"SIG": pin_nets},
        candidate_supply_nets=[],
        power_symbol_refs=[],
        netlist_available=True,
    )
    findings = run_pin_voltage_checks(
        topology=topo,
        inventory=[
            _inv("U1"),
            ComponentInventoryItem(
                reference="U2",
                datasheet_linked=True,
                content_sha256=sha,
                identity_status="linked",
                connected_nets=["SIG"],
            ),
        ],
        rails=[],
        device_variants={},
    )
    pin = [f for f in findings if f.check_id == "pin_voltage_compatibility"]
    assert pin and all(f.status == "inconclusive" for f in pin)


# --- API integration ------------------------------------------------------------


def test_rails_get_put_and_analyze_api(upload_env):
    file_id = store_upload(
        (FIXTURES_SCH / "sample.kicad_sch").read_bytes(), ".kicad_sch"
    ).stem
    sha = "aa" * 32
    _store_linked(
        file_id=file_id,
        reference="U1",
        sha=sha,
        facts=[
            _fact(
                fact_type="supply_voltage_min",
                value=3.0,
                qualifiers=["recommended_operating"],
                sha=sha,
            ),
            _fact(
                fact_type="supply_voltage_max",
                value=32.0,
                qualifiers=["recommended_operating"],
                sha=sha,
            ),
        ],
    )

    rails_resp = client.get(f"/api/circuit/{file_id}/rails")
    assert rails_resp.status_code == 200
    body = rails_resp.json()
    assert body["schematic_file_id"] == file_id
    for rail in body["rails"]:
        # Suggestions never invent volts
        if rail["status"] != "confirmed":
            assert rail["value_v"] is None

    put = client.put(
        f"/api/circuit/{file_id}/rails",
        json={
            "rails": [
                {
                    "net_name": "VCC",
                    "value_v": 5.0,
                    "reference_net": "GND",
                    "status": "confirmed",
                    "source": "operator",
                }
            ]
        },
    )
    assert put.status_code == 200

    comps = client.get(f"/api/circuit/{file_id}/components")
    assert comps.status_code == 200
    assert isinstance(comps.json(), list)

    analysis = client.post(f"/api/circuit/{file_id}/analyze", json={})
    assert analysis.status_code == 200
    report = analysis.json()
    assert report["assessment"] in {
        "violations_detected",
        "no_violations_found_within_scope",
        "inconclusive",
    }
    assert any(
        f["check_id"] == "current_limit_compatibility"
        and f["status"] == "not_performed"
        for f in report["findings"]
    )
    assert any(
        f["check_id"] == "power_dissipation" and f["status"] == "not_performed"
        for f in report["findings"]
    )
    assert "not" in report["scope"].lower()
    assert "safe" in report["scope"].lower() or "safety" in " ".join(
        report.get("limitations", [])
    ).lower() or "not" in report["scope"].lower()
