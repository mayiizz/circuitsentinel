"""Phase 4A: explicit user-confirmed datasheet↔component linking."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.datasheets.ingest import ingest_datasheet_pdf
from app.datasheets.link import PHASE4A_LIMITATIONS, create_datasheet_component_link
from app.datasheets.models import DatasheetComponentLinkRequest
from app.datasheets.store import store_ingest_report
from app.main import app
from app.schematics.storage import store_upload

FIXTURES_DS = Path(__file__).resolve().parent / "fixtures" / "datasheets"
FIXTURES_SCH = Path(__file__).resolve().parent / "fixtures" / "schematics"


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


def _store_schematic_with_r1() -> str:
    path = store_upload((FIXTURES_SCH / "sample.kicad_sch").read_bytes(), ".kicad_sch")
    return path.stem


def _ingest_and_store(*, document_id: str = "dsdoc") -> tuple[str, str, object]:
    data = (FIXTURES_DS / "text_single.pdf").read_bytes()
    report = ingest_datasheet_pdf(
        data, filename="text_single.pdf", document_id=document_id
    )
    assert report.status == "ok"
    assert report.source is not None
    store_ingest_report(report)
    return report.source.document_id, report.source.content_sha256, report


def test_successful_explicit_link_exposes_facts_and_graph_edge(upload_env):
    file_id = _store_schematic_with_r1()
    document_id, sha, report = _ingest_and_store(document_id="linkdoc")

    result = create_datasheet_component_link(
        DatasheetComponentLinkRequest(
            schematic_file_id=file_id,
            component_reference="R1",
            document_id=document_id,
            content_sha256=sha,
        )
    )
    assert result.status == "ok"
    assert result.link is not None
    assert result.link.provenance == "user_confirmed"
    assert result.link.component_reference == "R1"
    assert result.link.content_sha256 == sha
    assert result.link.schematic_file_id == file_id

    # Facts unchanged in content; still point at raw evidence pages.
    assert result.facts
    for fact in result.facts:
        assert fact.source_content_sha256 == sha
        assert fact.supporting_evidence_id
        assert any(e.id == fact.supporting_evidence_id for e in result.raw_evidence)
        assert fact.page_number >= 1
        raw = next(e for e in result.raw_evidence if e.id == fact.supporting_evidence_id)
        assert fact.supporting_excerpt in raw.text
        # Raw evidence objects from ingest are not mutated by linking.
        original = next(e for e in report.raw_evidence if e.id == raw.id)
        assert original.text == raw.text

    graph = result.evidence_graph_additions
    assert graph is not None
    docs = [n for n in graph.nodes if n.kind == "datasheet_document"]
    assert len(docs) == 1
    assert docs[0].attrs["content_sha256"] == sha
    assert docs[0].provenance == "user_confirmed"
    edges = [e for e in graph.edges if e.kind == "user_confirmed_datasheet"]
    assert len(edges) == 1
    assert edges[0].provenance == "user_confirmed"
    assert edges[0].source_id.startswith(f"{file_id}:component:")
    assert edges[0].target_id == docs[0].id
    # Facts are not silently attached as graph edges to the component.
    assert not any(e.kind == "applies_fact" for e in graph.edges)
    for item in PHASE4A_LIMITATIONS:
        assert item in result.limitations


def test_nonexistent_component_rejected(upload_env):
    file_id = _store_schematic_with_r1()
    document_id, sha, _ = _ingest_and_store()
    result = create_datasheet_component_link(
        DatasheetComponentLinkRequest(
            schematic_file_id=file_id,
            component_reference="U99",
            document_id=document_id,
            content_sha256=sha,
        )
    )
    assert result.status == "error"
    assert "does not exist" in (result.failure_reason or "")
    assert result.link is None
    assert result.facts == []


def test_incorrect_document_id_rejected(upload_env):
    file_id = _store_schematic_with_r1()
    _, sha, _ = _ingest_and_store(document_id="real-doc")
    result = create_datasheet_component_link(
        DatasheetComponentLinkRequest(
            schematic_file_id=file_id,
            component_reference="R1",
            document_id="wrong-doc",
            content_sha256=sha,
        )
    )
    assert result.status == "error"
    assert "document_id mismatch" in (result.failure_reason or "")


def test_unknown_content_hash_rejected(upload_env):
    file_id = _store_schematic_with_r1()
    result = create_datasheet_component_link(
        DatasheetComponentLinkRequest(
            schematic_file_id=file_id,
            component_reference="R1",
            document_id="doc",
            content_sha256="ab" * 32,
        )
    )
    assert result.status == "error"
    assert "No stored datasheet ingest report" in (result.failure_reason or "")


def test_duplicate_link_returns_duplicate_status(upload_env):
    file_id = _store_schematic_with_r1()
    document_id, sha, _ = _ingest_and_store(document_id="dup")
    req = DatasheetComponentLinkRequest(
        schematic_file_id=file_id,
        component_reference="R1",
        document_id=document_id,
        content_sha256=sha,
    )
    first = create_datasheet_component_link(req)
    second = create_datasheet_component_link(req)
    assert first.status == "ok"
    assert second.status == "duplicate"
    assert second.link is not None
    assert second.link.id == first.link.id
    assert second.facts  # still exposes facts


def test_stale_analysis_scope_missing_upload(upload_env):
    document_id, sha, _ = _ingest_and_store()
    result = create_datasheet_component_link(
        DatasheetComponentLinkRequest(
            schematic_file_id="a" * 32,
            component_reference="R1",
            document_id=document_id,
            content_sha256=sha,
        )
    )
    assert result.status == "error"
    assert "not found" in (result.failure_reason or "").lower()


def test_deleted_schematic_upload_rejected(upload_env):
    file_id = _store_schematic_with_r1()
    document_id, sha, _ = _ingest_and_store()
    # Delete the schematic file to simulate replaced/deleted upload.
    from app.schematics.storage import resolve_upload_id

    path = resolve_upload_id(file_id)
    assert path is not None
    path.unlink()
    result = create_datasheet_component_link(
        DatasheetComponentLinkRequest(
            schematic_file_id=file_id,
            component_reference="R1",
            document_id=document_id,
            content_sha256=sha,
        )
    )
    assert result.status == "error"
    assert "not found" in (result.failure_reason or "").lower()


@pytest.fixture()
def client(upload_env):
    return TestClient(app)


def test_api_link_success_and_traceability(client):
    # Analyze schematic
    sch = (FIXTURES_SCH / "sample.kicad_sch").read_bytes()
    analyze = client.post(
        "/api/schematics/analyze",
        files={"file": ("sample.kicad_sch", sch, "application/octet-stream")},
    )
    assert analyze.status_code == 200
    file_id = analyze.json()["viewer"]["file_id"]
    refs = {
        s["reference"]
        for s in analyze.json()["confirmed"]["symbols"]
        if s.get("reference")
    }
    assert "R1" in refs

    ingest = client.post(
        "/api/datasheets/ingest",
        files={
            "file": (
                "text_single.pdf",
                (FIXTURES_DS / "text_single.pdf").read_bytes(),
                "application/pdf",
            )
        },
    )
    assert ingest.status_code == 200
    body = ingest.json()
    document_id = body["source"]["document_id"]
    sha = body["source"]["content_sha256"]

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
    payload = link.json()
    assert payload["status"] == "ok"
    assert payload["link"]["provenance"] == "user_confirmed"
    assert payload["facts"]
    assert payload["evidence_graph_additions"]["edges"][0]["kind"] == (
        "user_confirmed_datasheet"
    )

    dup = client.post(
        "/api/datasheets/links",
        json={
            "schematic_file_id": file_id,
            "component_reference": "R1",
            "document_id": document_id,
            "content_sha256": sha,
        },
    )
    assert dup.status_code == 409
    assert dup.json()["status"] == "duplicate"
