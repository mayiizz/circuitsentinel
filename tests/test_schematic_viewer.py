"""Tests for schematic file serving and viewer metadata."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schematics.kicad_parser import parse_kicad_sch

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "schematics"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CIRCUITSENTINEL_MAX_UPLOAD_MB", "5")
    import app.schematics.config as config
    import app.schematics.storage as storage

    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(storage, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr("app.schematics.erc.find_kicad_cli", lambda: None)
    monkeypatch.setattr("app.schematics.erc.probe_kicad_cli_erc", lambda: False)
    monkeypatch.setattr("app.schematics.netlist.find_kicad_cli", lambda: None)
    monkeypatch.setattr(
        "app.schematics.netlist.probe_kicad_cli_export_netlist", lambda: False
    )
    return TestClient(app)


def _upload(client: TestClient, path: Path, *, content_type: str):
    return client.post(
        "/api/schematics/analyze",
        files={"file": (path.name, path.read_bytes(), content_type)},
    )


def test_png_viewer_ready_and_file_served(client):
    response = _upload(client, FIXTURES / "sample.png", content_type="image/png")
    assert response.status_code == 200
    body = response.json()
    assert body["viewer"]["render_status"] == "ready"
    assert body["viewer"]["format"] == "image"
    file_id = body["viewer"]["file_id"]
    served = client.get(f"/api/schematics/files/{file_id}")
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("image/png")
    assert served.content[:8] == (FIXTURES / "sample.png").read_bytes()[:8]


def test_pdf_viewer_ready_and_file_served(client):
    response = _upload(client, FIXTURES / "sample.pdf", content_type="application/pdf")
    assert response.status_code == 200
    body = response.json()
    assert body["viewer"]["render_status"] == "ready"
    assert body["viewer"]["format"] == "pdf"
    file_id = body["viewer"]["file_id"]
    served = client.get(f"/api/schematics/files/{file_id}")
    assert served.status_code == 200
    assert "pdf" in served.headers["content-type"]


def test_invalid_file_id_returns_404(client):
    assert client.get("/api/schematics/files/not-a-valid-id").status_code == 404
    assert client.get("/api/schematics/files/../etc/passwd").status_code == 404
    assert (
        client.get("/api/schematics/files/0123456789abcdef0123456789abcdef").status_code
        == 404
    )


def test_path_like_file_id_rejected(client):
    response = client.get("/api/schematics/files/../../uploads/secret.png")
    assert response.status_code == 404


def test_kicad_missing_cli_unavailable_preview(client):
    with (
        patch("app.schematics.render.find_kicad_cli", return_value=None),
        patch("app.schematics.render.probe_kicad_cli_export_svg", return_value=False),
    ):
        response = _upload(
            client,
            FIXTURES / "OPamp-comparator.kicad_sch",
            content_type="application/octet-stream",
        )
    assert response.status_code == 200
    body = response.json()
    assert body["viewer"]["render_status"] == "unavailable"
    assert body["viewer"]["preview_url"] is None
    assert "KiCad CLI" in body["viewer"]["render_message"]
    assert body["erc"]["ran"] is False
    file_id = body["viewer"]["file_id"]
    assert client.get(f"/api/schematics/files/{file_id}").status_code == 200
    assert client.get(f"/api/schematics/files/{file_id}/preview").status_code == 404


def test_kicad_cli_export_success_serves_preview(client, tmp_path):
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="297mm" height="210mm" '
        'viewBox="0 0 297 210"></svg>'
    )

    def fake_run(args, **kwargs):
        from unittest.mock import MagicMock

        out_dir = Path(args[args.index("--output") + 1])
        (out_dir / "sheet.svg").write_text(svg, encoding="utf-8")
        return MagicMock(returncode=0, stdout="Done.", stderr="")

    with (
        patch("app.schematics.render.find_kicad_cli", return_value="/fake/kicad-cli"),
        patch("app.schematics.render.probe_kicad_cli_export_svg", return_value=True),
        patch("app.schematics.render.subprocess.run", side_effect=fake_run),
    ):
        response = _upload(
            client,
            FIXTURES / "sample.kicad_sch",
            content_type="application/octet-stream",
        )
    assert response.status_code == 200
    body = response.json()
    assert body["viewer"]["render_status"] == "ready"
    assert body["viewer"]["preview_url"]
    assert body["viewer"]["coordinate_mapping"]["reliable"] is True
    preview = client.get(body["viewer"]["preview_url"])
    assert preview.status_code == 200
    assert "svg" in preview.headers["content-type"]


def test_unsupported_extension_still_rejected(client):
    response = client.post(
        "/api/schematics/analyze",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400
    assert response.json()["viewer"] is None


def test_opamp_parser_still_eleven_placed_refs():
    parsed = parse_kicad_sch((FIXTURES / "OPamp-comparator.kicad_sch").read_bytes())
    refs = {s.reference for s in parsed["symbols"]}
    assert len(parsed["symbols"]) == 11
    assert "R" not in refs and "U" not in refs and "V" not in refs
    assert all(s.at_x is not None and s.at_y is not None for s in parsed["symbols"])
