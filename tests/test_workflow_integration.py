"""End-to-end workflow: analyze → ingest → link → recommended-supply check."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

FIXTURES_SCH = Path(__file__).resolve().parent / "fixtures" / "schematics"
FIXTURES_DS = Path(__file__).resolve().parent / "fixtures" / "datasheets"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import app.schematics.config as config
    import app.schematics.storage as storage

    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(storage, "ensure_upload_dir", config.ensure_upload_dir)
    # Keep ERC/netlist/render stubbed for determinism (workflow still exercises APIs).
    monkeypatch.setattr("app.schematics.erc.find_kicad_cli", lambda: None)
    monkeypatch.setattr("app.schematics.erc.probe_kicad_cli_erc", lambda: False)
    monkeypatch.setattr("app.schematics.netlist.find_kicad_cli", lambda: None)
    monkeypatch.setattr(
        "app.schematics.netlist.probe_kicad_cli_export_netlist", lambda: False
    )
    monkeypatch.setattr("app.schematics.render.find_kicad_cli", lambda: None)
    return TestClient(app)


def test_full_workflow_reaches_no_violation_and_potential_violation(client):
    analyze = client.post(
        "/api/schematics/analyze",
        files={
            "file": (
                "sample.kicad_sch",
                (FIXTURES_SCH / "sample.kicad_sch").read_bytes(),
                "application/octet-stream",
            )
        },
    )
    assert analyze.status_code == 200
    analysis = analyze.json()
    assert "evidence_graph" in analysis
    assert "netlist" in analysis
    file_id = analysis["viewer"]["file_id"]

    ingest = client.post(
        "/api/datasheets/ingest",
        files={
            "file": (
                "recommended_supply.pdf",
                (FIXTURES_DS / "recommended_supply.pdf").read_bytes(),
                "application/pdf",
            )
        },
    )
    assert ingest.status_code == 200
    ds = ingest.json()
    assert ds["status"] == "ok"
    assert any(
        "recommended_operating" in f.get("qualifiers", []) for f in ds["facts"]
    )
    document_id = ds["source"]["document_id"]
    sha = ds["source"]["content_sha256"]

    link = client.post(
        "/api/datasheets/links",
        json={
            "schematic_file_id": file_id,
            "component_reference": "R1",
            "document_id": document_id,
            "content_sha256": sha,
        },
    )
    assert link.status_code == 200
    assert link.json()["status"] == "ok"
    assert link.json()["evidence_graph_additions"]["edges"][0]["kind"] == (
        "user_confirmed_datasheet"
    )

    ok = client.post(
        "/api/checks/recommended_supply",
        json={
            "schematic_file_id": file_id,
            "component_reference": "R1",
            "document_id": document_id,
            "content_sha256": sha,
            "stated_supply": {"value_v": 3.3},
        },
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "no_violation_detected"

    bad = client.post(
        "/api/checks/recommended_supply",
        json={
            "schematic_file_id": file_id,
            "component_reference": "R1",
            "document_id": document_id,
            "content_sha256": sha,
            "stated_supply": {"value_v": 12.0},
        },
    )
    assert bad.status_code == 200
    assert bad.json()["status"] == "potential_violation"


def test_workflow_abs_max_only_stays_inconclusive(client):
    analyze = client.post(
        "/api/schematics/analyze",
        files={
            "file": (
                "sample.kicad_sch",
                (FIXTURES_SCH / "sample.kicad_sch").read_bytes(),
                "application/octet-stream",
            )
        },
    )
    file_id = analyze.json()["viewer"]["file_id"]
    ingest = client.post(
        "/api/datasheets/ingest",
        files={
            "file": (
                "absolute_maximum_only.pdf",
                (FIXTURES_DS / "absolute_maximum_only.pdf").read_bytes(),
                "application/pdf",
            )
        },
    )
    ds = ingest.json()
    link = client.post(
        "/api/datasheets/links",
        json={
            "schematic_file_id": file_id,
            "component_reference": "R1",
            "document_id": ds["source"]["document_id"],
            "content_sha256": ds["source"]["content_sha256"],
        },
    )
    assert link.status_code == 200
    check = client.post(
        "/api/checks/recommended_supply",
        json={
            "schematic_file_id": file_id,
            "component_reference": "R1",
            "document_id": ds["source"]["document_id"],
            "content_sha256": ds["source"]["content_sha256"],
            "stated_supply": {"value_v": 5.0},
        },
    )
    assert check.status_code == 200
    body = check.json()
    assert body["status"] == "inconclusive"
    assert "absolute-maximum" in body["finding"]["explanation"].lower()
