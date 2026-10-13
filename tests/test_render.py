"""Tests for KiCad SVG export, temp cleanup, and coordinate mapping."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schematics.render import export_kicad_svg_preview
from app.schematics.svg_coords import mm_to_view_percent, parse_svg_coordinate_mapping

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "schematics"

KICAD_LIKE_SVG = """<?xml version="1.0" standalone="no"?>
<svg xmlns="http://www.w3.org/2000/svg" version="1.1"
  width="297.0022mm" height="210.0072mm" viewBox="0.0000 0.0000 297.0022 210.0072">
  <rect x="0" y="0" width="297.0022" height="210.0072" />
</svg>
"""


@pytest.fixture()
def upload_root(tmp_path, monkeypatch):
    import app.schematics.config as config

    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    return tmp_path / "uploads"


def test_parse_kicad_svg_mapping_reliable():
    mapping = parse_svg_coordinate_mapping(KICAD_LIKE_SVG)
    assert mapping.reliable is True
    assert mapping.units == "mm"
    assert mapping.view_width == pytest.approx(297.0022)
    assert mapping.view_height == pytest.approx(210.0072)
    percent = mm_to_view_percent(148.5011, 105.0036, mapping)
    assert percent is not None
    assert percent[0] == pytest.approx(50.0, abs=0.01)
    assert percent[1] == pytest.approx(50.0, abs=0.01)


def test_parse_svg_without_mm_attrs_not_reliable():
    svg = '<svg viewBox="0 0 100 100" width="100" height="100"></svg>'
    mapping = parse_svg_coordinate_mapping(svg)
    assert mapping.reliable is False
    assert mm_to_view_percent(10, 10, mapping) is None


def test_export_missing_cli():
    with (
        patch("app.schematics.render.find_kicad_cli", return_value=None),
        patch("app.schematics.render.probe_kicad_cli_export_svg", return_value=False),
    ):
        path, mapping, error = export_kicad_svg_preview(
            FIXTURES / "sample.kicad_sch",
            "a" * 32,
        )
    assert path is None
    assert mapping.reliable is False
    assert error
    assert "KiCad CLI" in error


def test_export_failure_cleans_temp(tmp_path, upload_root, monkeypatch):
    seen_work: list[Path] = []

    def fake_mkdtemp(prefix=""):
        work = tmp_path / f"{prefix}work"
        work.mkdir()
        seen_work.append(work)
        return str(work)

    with (
        patch("app.schematics.render.find_kicad_cli", return_value="/fake/kicad-cli"),
        patch("app.schematics.render.probe_kicad_cli_export_svg", return_value=True),
        patch("app.schematics.render.tempfile.mkdtemp", side_effect=fake_mkdtemp),
        patch(
            "app.schematics.render.subprocess.run",
            return_value=MagicMock(returncode=1, stdout="", stderr="export failed"),
        ),
    ):
        path, _mapping, error = export_kicad_svg_preview(
            FIXTURES / "sample.kicad_sch",
            "b" * 32,
        )

    assert path is None
    assert error
    assert seen_work
    assert not seen_work[0].exists()


def test_export_success_copies_preview_and_cleans_temp(tmp_path, upload_root, monkeypatch):
    seen_work: list[Path] = []

    def fake_mkdtemp(prefix=""):
        work = tmp_path / f"{prefix}work"
        work.mkdir()
        seen_work.append(work)
        return str(work)

    def fake_run(args, **kwargs):
        out_dir = Path(args[args.index("--output") + 1])
        (out_dir / "sheet.svg").write_text(KICAD_LIKE_SVG, encoding="utf-8")
        return MagicMock(returncode=0, stdout="Done.", stderr="")

    file_id = "c" * 32
    with (
        patch("app.schematics.render.find_kicad_cli", return_value="/fake/kicad-cli"),
        patch("app.schematics.render.probe_kicad_cli_export_svg", return_value=True),
        patch("app.schematics.render.tempfile.mkdtemp", side_effect=fake_mkdtemp),
        patch("app.schematics.render.subprocess.run", side_effect=fake_run),
    ):
        path, mapping, error = export_kicad_svg_preview(
            FIXTURES / "sample.kicad_sch",
            file_id,
        )

    assert error is None
    assert path is not None
    assert path.is_file()
    assert path.name == f"{file_id}.svg"
    assert mapping.reliable is True
    assert seen_work
    assert not seen_work[0].exists()
    # Original fixture untouched.
    assert (FIXTURES / "sample.kicad_sch").is_file()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CIRCUITSENTINEL_MAX_UPLOAD_MB", "5")
    import app.schematics.config as config

    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr("app.schematics.erc.find_kicad_cli", lambda: None)
    monkeypatch.setattr("app.schematics.erc.probe_kicad_cli_erc", lambda: False)
    monkeypatch.setattr("app.schematics.netlist.find_kicad_cli", lambda: None)
    monkeypatch.setattr(
        "app.schematics.netlist.probe_kicad_cli_export_netlist", lambda: False
    )
    return TestClient(app)


def test_analyze_includes_reliable_coordinate_mapping(client):
    def fake_run(args, **kwargs):
        out_dir = Path(args[args.index("--output") + 1])
        (out_dir / "out.svg").write_text(KICAD_LIKE_SVG, encoding="utf-8")
        return MagicMock(returncode=0, stdout="", stderr="")

    with (
        patch("app.schematics.render.find_kicad_cli", return_value="/fake/kicad-cli"),
        patch("app.schematics.render.probe_kicad_cli_export_svg", return_value=True),
        patch("app.schematics.render.subprocess.run", side_effect=fake_run),
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
    viewer = body["viewer"]
    assert viewer["render_status"] == "ready"
    assert viewer["preview_url"]
    assert viewer["coordinate_mapping"]["reliable"] is True
    assert viewer["coordinate_mapping"]["units"] == "mm"
    preview = client.get(viewer["preview_url"])
    assert preview.status_code == 200
    assert "svg" in preview.headers["content-type"]
    # ERC did not run on this client fixture (mocked missing for ERC).
    assert body["erc"]["ran"] is False
