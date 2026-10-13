"""Tests for schematic upload validation and honest analysis responses."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schematics.kicad_parser import parse_kicad_sch

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "schematics"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CIRCUITSENTINEL_MAX_UPLOAD_MB", "1")
    # Keep uploads inside the temp directory for tests.
    import app.schematics.config as config
    import app.schematics.storage as storage

    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(storage, "ensure_upload_dir", config.ensure_upload_dir)
    # Isolate upload/parser tests from a real local KiCad install.
    monkeypatch.setattr("app.schematics.erc.find_kicad_cli", lambda: None)
    monkeypatch.setattr("app.schematics.erc.probe_kicad_cli_erc", lambda: False)
    monkeypatch.setattr("app.schematics.netlist.find_kicad_cli", lambda: None)
    monkeypatch.setattr(
        "app.schematics.netlist.probe_kicad_cli_export_netlist", lambda: False
    )
    monkeypatch.setattr("app.schematics.render.find_kicad_cli", lambda: None)
    return TestClient(app)


def _upload(client: TestClient, path: Path, *, content_type: str, filename: str | None = None):
    data = path.read_bytes()
    files = {
        "file": (filename or path.name, data, content_type),
    }
    return client.post("/api/schematics/analyze", files=files)


def test_kicad_schematic_extracts_symbols_and_labels(client):
    response = _upload(
        client,
        FIXTURES / "sample.kicad_sch",
        content_type="application/octet-stream",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "partial"}
    assert body["upload"]["format"] == "kicad_sch"
    refs = {item["reference"] for item in body["confirmed"]["symbols"]}
    assert "R1" in refs
    texts = {item["text"] for item in body["confirmed"]["labels"]}
    assert "NET_A" in texts
    assert body["erc"]["ran"] is False
    assert body["erc"]["failure_reason"]
    assert body["unverified_suggestions"] == []
    assert body["stages"]["parsing"]["status"] == "complete"
    assert body["stages"]["erc"]["status"] == "unavailable"
    assert body["finding_interpretations"] == []


def test_malformed_kicad_returns_structured_error(client):
    response = _upload(
        client,
        FIXTURES / "malformed.kicad_sch",
        content_type="text/plain",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert body["validation_errors"]
    assert body["erc"]["ran"] is False
    assert body["erc"]["failure_reason"]


def test_pdf_extracts_pages(client):
    response = _upload(
        client,
        FIXTURES / "sample.pdf",
        content_type="application/pdf",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["upload"]["format"] == "pdf"
    assert body["confirmed"]["pages"] == 1
    assert body["erc"]["ran"] is False


def test_scanned_pdf_is_visual_partial(client):
    response = _upload(
        client,
        FIXTURES / "scanned.pdf",
        content_type="application/pdf",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "partial"
    assert body["visual"]["observations"]
    assert "connectivity" in body["visual"]["disclaimer"].lower()


def test_png_image_pipeline(client):
    response = _upload(
        client,
        FIXTURES / "sample.png",
        content_type="image/png",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["upload"]["format"] == "image"
    assert body["status"] == "partial"
    assert any("Dimensions" in item for item in body["visual"]["observations"])
    assert "does not establish electrical connectivity" in body["visual"]["disclaimer"]
    assert body["erc"]["ran"] is False
    # Must not invent electrical faults
    assert body["unverified_suggestions"] == []
    assert body["confirmed"]["symbols"] == []


def test_invalid_extension_rejected(client):
    response = client.post(
        "/api/schematics/analyze",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400
    body = response.json()
    assert body["status"] == "error"
    assert any("extension" in err.lower() for err in body["validation_errors"])


def test_mime_mismatch_rejected(client):
    response = client.post(
        "/api/schematics/analyze",
        files={
            "file": (
                "sample.png",
                (FIXTURES / "sample.png").read_bytes(),
                "application/zip",
            )
        },
    )
    assert response.status_code == 400
    body = response.json()
    assert body["status"] == "error"
    assert any("mime" in err.lower() for err in body["validation_errors"])


def test_oversized_file_rejected(client, monkeypatch):
    monkeypatch.setenv("CIRCUITSENTINEL_MAX_UPLOAD_MB", "0.000001")
    # Re-import max via env: validate reads env each call
    huge = b"x" * 2048
    response = client.post(
        "/api/schematics/analyze",
        files={"file": ("sample.png", huge, "image/png")},
    )
    assert response.status_code == 413
    body = response.json()
    assert body["status"] == "error"
    assert any("maximum" in err.lower() for err in body["validation_errors"])


def test_path_traversal_filename_is_sanitized(client, tmp_path, monkeypatch):
    import app.schematics.config as config

    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    png = (FIXTURES / "sample.png").read_bytes()
    response = client.post(
        "/api/schematics/analyze",
        files={"file": ("../../evil.png", png, "image/png")},
    )
    assert response.status_code == 200
    stored = response.json()["upload"]["stored_as"]
    assert ".." not in stored
    assert stored.endswith(".png")
    assert (tmp_path / "uploads" / stored).is_file()


def test_parse_kicad_helper_directly():
    data = (FIXTURES / "sample.kicad_sch").read_bytes()
    parsed = parse_kicad_sch(data)
    assert any(s.reference == "R1" for s in parsed["symbols"])
    assert any(c.kind == "wire" for c in parsed["connectivity"])
