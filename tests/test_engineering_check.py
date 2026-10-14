"""Phase 4B: recommended_supply_vs_stated_rail engineering check."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.datasheets.checks import (
    CHECK_ID,
    PHASE4B_LIMITATIONS,
    EngineeringCheckRequest,
    StatedSupplyVoltage,
    run_recommended_supply_check,
)
from app.datasheets.link import create_datasheet_component_link
from app.datasheets.models import (
    DatasheetComponentLinkRequest,
    DatasheetIngestReport,
    DatasheetSource,
    NormalizedDatasheetFact,
    RawDatasheetEvidence,
)
from app.datasheets.store import store_ingest_report
from app.main import app
from app.schematics.storage import store_upload

FIXTURES_SCH = Path(__file__).resolve().parent / "fixtures" / "schematics"
DOC_HASH = "b" * 64


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


def _store_schematic() -> str:
    return store_upload(
        (FIXTURES_SCH / "sample.kicad_sch").read_bytes(), ".kicad_sch"
    ).stem


def _fact(
    *,
    fact_type: str,
    value: float,
    qualifiers: list[str],
    page: int = 1,
    doc: str = "ds",
    sha: str = DOC_HASH,
    excerpt: str,
) -> NormalizedDatasheetFact:
    ev_id = f"{doc}:raw:page:{page}:pypdf_extract_text"
    return NormalizedDatasheetFact(
        id=f"{doc}:fact:{fact_type}:page:{page}:deadbeefcafe",
        fact_type=fact_type,  # type: ignore[arg-type]
        value=value,
        unit="V",
        qualifiers=qualifiers,
        source_content_sha256=sha,
        page_number=page,
        supporting_evidence_id=ev_id,
        supporting_excerpt=excerpt,
    )


def _store_report(
    *,
    document_id: str,
    sha: str,
    facts: list[NormalizedDatasheetFact],
    page_text: str = "Recommended Operating Conditions\nSupply voltage 3.3 V\n",
) -> DatasheetIngestReport:
    raw = [
        RawDatasheetEvidence(
            id=f"{document_id}:raw:page:1:pypdf_extract_text",
            document_id=document_id,
            page_number=1,
            text=page_text,
        )
    ]
    # Align evidence ids on facts
    aligned = []
    for f in facts:
        aligned.append(
            f.model_copy(
                update={
                    "supporting_evidence_id": raw[0].id,
                    "source_content_sha256": sha,
                }
            )
        )
    report = DatasheetIngestReport(
        status="ok",
        source=DatasheetSource(
            document_id=document_id,
            filename="part.pdf",
            content_sha256=sha,
            page_count=1,
            byte_length=100,
        ),
        pages=[],
        raw_evidence=raw,
        facts=aligned,
        unresolved=[],
        claims=[],
    )
    store_ingest_report(report)
    return report


def _link(file_id: str, document_id: str, sha: str):
    result = create_datasheet_component_link(
        DatasheetComponentLinkRequest(
            schematic_file_id=file_id,
            component_reference="R1",
            document_id=document_id,
            content_sha256=sha,
        )
    )
    assert result.status in {"ok", "duplicate"}, result.failure_reason
    return result


def test_no_violation_when_stated_within_recommended(upload_env):
    file_id = _store_schematic()
    sha = "c" * 64
    doc = "rec-ok"
    _store_report(
        document_id=doc,
        sha=sha,
        facts=[
            _fact(
                fact_type="supply_voltage_min",
                value=3.0,
                qualifiers=["recommended_operating"],
                excerpt="Supply voltage min 3.0 V",
                sha=sha,
                doc=doc,
            ),
            _fact(
                fact_type="supply_voltage_max",
                value=3.6,
                qualifiers=["recommended_operating"],
                excerpt="Supply voltage max 3.6 V",
                sha=sha,
                doc=doc,
            ),
        ],
    )
    _link(file_id, doc, sha)
    result = run_recommended_supply_check(
        EngineeringCheckRequest(
            schematic_file_id=file_id,
            component_reference="R1",
            document_id=doc,
            content_sha256=sha,
            stated_supply=StatedSupplyVoltage(value_v=3.3, note="bench measurement"),
        )
    )
    assert result.status == "no_violation_detected"
    assert result.finding is not None
    assert result.finding.check_id == CHECK_ID
    assert result.finding.stated_supply_v == 3.3
    assert result.finding.datasheet_supply_min_v == 3.0
    assert result.finding.datasheet_supply_max_v == 3.6
    assert result.finding.evidence_references
    assert all(r.page_number == 1 for r in result.finding.evidence_references)
    assert "not a claim that the entire circuit" in result.finding.explanation.lower()
    assert any("net names" in a.lower() for a in result.finding.assumptions)
    for item in PHASE4B_LIMITATIONS:
        assert item in result.limitations


def test_potential_violation_when_stated_above_recommended_max(upload_env):
    file_id = _store_schematic()
    sha = "d" * 64
    doc = "rec-hi"
    _store_report(
        document_id=doc,
        sha=sha,
        facts=[
            _fact(
                fact_type="supply_voltage_max",
                value=5.0,
                qualifiers=["recommended_operating"],
                excerpt="Supply voltage max 5.0 V",
                sha=sha,
                doc=doc,
            ),
            _fact(
                fact_type="supply_voltage_min",
                value=4.5,
                qualifiers=["recommended_operating"],
                excerpt="Supply voltage min 4.5 V",
                sha=sha,
                doc=doc,
            ),
        ],
    )
    _link(file_id, doc, sha)
    result = run_recommended_supply_check(
        EngineeringCheckRequest(
            schematic_file_id=file_id,
            component_reference="R1",
            document_id=doc,
            content_sha256=sha,
            stated_supply=StatedSupplyVoltage(value_v=12.0),
        )
    )
    assert result.status == "potential_violation"
    assert result.finding is not None
    assert "above recommended maximum" in result.finding.explanation
    assert result.finding.evidence_references


def test_inconclusive_without_stated_supply_even_if_nets_exist(upload_env):
    """Missing stated supply → inconclusive; nets are never consulted."""
    file_id = _store_schematic()
    sha = "e" * 64
    doc = "no-stated"
    _store_report(
        document_id=doc,
        sha=sha,
        facts=[
            _fact(
                fact_type="supply_voltage_max",
                value=5.0,
                qualifiers=["recommended_operating"],
                excerpt="Supply voltage max 5.0 V",
                sha=sha,
                doc=doc,
            ),
        ],
    )
    _link(file_id, doc, sha)
    result = run_recommended_supply_check(
        EngineeringCheckRequest(
            schematic_file_id=file_id,
            component_reference="R1",
            document_id=doc,
            content_sha256=sha,
            stated_supply=None,
        )
    )
    assert result.status == "inconclusive"
    assert result.finding is not None
    assert any(
        "stated_supply" in m for m in result.finding.missing_information
    )
    assert "does not infer rail voltage from net" in result.finding.explanation.lower()


def test_inconclusive_when_only_absolute_maximum_specs(upload_env):
    file_id = _store_schematic()
    sha = "f" * 64
    doc = "abs-only"
    _store_report(
        document_id=doc,
        sha=sha,
        facts=[
            _fact(
                fact_type="supply_voltage_max",
                value=32.0,
                qualifiers=["absolute_maximum"],
                excerpt="Supply voltage 32 V",
                sha=sha,
                doc=doc,
            ),
        ],
        page_text="Absolute Maximum Ratings\nSupply voltage 32 V\n",
    )
    _link(file_id, doc, sha)
    result = run_recommended_supply_check(
        EngineeringCheckRequest(
            schematic_file_id=file_id,
            component_reference="R1",
            document_id=doc,
            content_sha256=sha,
            stated_supply=StatedSupplyVoltage(value_v=5.0),
        )
    )
    assert result.status == "inconclusive"
    assert result.finding is not None
    assert "absolute-maximum" in result.finding.explanation.lower()
    assert result.finding.evidence_references
    assert result.finding.evidence_references[0].qualifiers == ["absolute_maximum"]


def test_mismatched_document_id_errors(upload_env):
    file_id = _store_schematic()
    sha = "1" * 64
    doc = "real"
    _store_report(
        document_id=doc,
        sha=sha,
        facts=[
            _fact(
                fact_type="supply_voltage_max",
                value=5.0,
                qualifiers=["recommended_operating"],
                excerpt="Supply voltage max 5.0 V",
                sha=sha,
                doc=doc,
            ),
        ],
    )
    _link(file_id, doc, sha)
    result = run_recommended_supply_check(
        EngineeringCheckRequest(
            schematic_file_id=file_id,
            component_reference="R1",
            document_id="wrong",
            content_sha256=sha,
            stated_supply=StatedSupplyVoltage(value_v=5.0),
        )
    )
    assert result.status == "error"
    assert "document_id mismatch" in (result.failure_reason or "")


def test_stale_link_missing_schematic(upload_env):
    file_id = _store_schematic()
    sha = "2" * 64
    doc = "stale"
    _store_report(
        document_id=doc,
        sha=sha,
        facts=[
            _fact(
                fact_type="supply_voltage_max",
                value=5.0,
                qualifiers=["recommended_operating"],
                excerpt="Supply voltage max 5.0 V",
                sha=sha,
                doc=doc,
            ),
        ],
    )
    _link(file_id, doc, sha)
    from app.schematics.storage import resolve_upload_id

    path = resolve_upload_id(file_id)
    assert path is not None
    path.unlink()
    result = run_recommended_supply_check(
        EngineeringCheckRequest(
            schematic_file_id=file_id,
            component_reference="R1",
            document_id=doc,
            content_sha256=sha,
            stated_supply=StatedSupplyVoltage(value_v=5.0),
        )
    )
    assert result.status == "error"
    assert "not found" in (result.failure_reason or "").lower()


def test_missing_link_errors(upload_env):
    file_id = _store_schematic()
    result = run_recommended_supply_check(
        EngineeringCheckRequest(
            schematic_file_id=file_id,
            component_reference="R1",
            document_id="none",
            content_sha256="3" * 64,
            stated_supply=StatedSupplyVoltage(value_v=5.0),
        )
    )
    assert result.status == "error"
    assert "No user-confirmed datasheet link" in (result.failure_reason or "")


def test_potential_violation_below_recommended_min(upload_env):
    file_id = _store_schematic()
    sha = "4" * 64
    doc = "lo"
    _store_report(
        document_id=doc,
        sha=sha,
        facts=[
            _fact(
                fact_type="supply_voltage_min",
                value=4.5,
                qualifiers=["recommended_operating"],
                excerpt="Supply voltage min 4.5 V",
                sha=sha,
                doc=doc,
            ),
            _fact(
                fact_type="supply_voltage_max",
                value=5.5,
                qualifiers=["recommended_operating"],
                excerpt="Supply voltage max 5.5 V",
                sha=sha,
                doc=doc,
            ),
        ],
    )
    _link(file_id, doc, sha)
    result = run_recommended_supply_check(
        EngineeringCheckRequest(
            schematic_file_id=file_id,
            component_reference="R1",
            document_id=doc,
            content_sha256=sha,
            stated_supply=StatedSupplyVoltage(value_v=3.0),
        )
    )
    assert result.status == "potential_violation"
    assert "below recommended minimum" in (result.finding.explanation if result.finding else "")


@pytest.fixture()
def client(upload_env):
    return TestClient(app)


def test_api_recommended_supply_check(client):
    sch = (FIXTURES_SCH / "sample.kicad_sch").read_bytes()
    analyze = client.post(
        "/api/schematics/analyze",
        files={"file": ("sample.kicad_sch", sch, "application/octet-stream")},
    )
    assert analyze.status_code == 200
    file_id = analyze.json()["viewer"]["file_id"]

    sha = "a1" * 32
    doc = "api-doc"
    _store_report(
        document_id=doc,
        sha=sha,
        facts=[
            _fact(
                fact_type="supply_voltage_min",
                value=3.0,
                qualifiers=["recommended_operating"],
                excerpt="Supply voltage min 3.0 V",
                sha=sha,
                doc=doc,
            ),
            _fact(
                fact_type="supply_voltage_max",
                value=3.6,
                qualifiers=["recommended_operating"],
                excerpt="Supply voltage max 3.6 V",
                sha=sha,
                doc=doc,
            ),
        ],
    )
    link = client.post(
        "/api/datasheets/links",
        json={
            "schematic_file_id": file_id,
            "component_reference": "R1",
            "document_id": doc,
            "content_sha256": sha,
        },
    )
    assert link.status_code == 200

    check = client.post(
        "/api/checks/recommended_supply",
        json={
            "schematic_file_id": file_id,
            "component_reference": "R1",
            "document_id": doc,
            "content_sha256": sha,
            "stated_supply": {"value_v": 3.3},
        },
    )
    assert check.status_code == 200
    body = check.json()
    assert body["status"] == "no_violation_detected"
    assert body["finding"]["check_id"] == CHECK_ID
