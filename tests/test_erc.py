"""Tests for KiCad ERC execution and report parsing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schematics.erc import (
    build_erc_report,
    parse_erc_json,
    parse_erc_report_text,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "schematics"


def test_parse_opamp_json_report():
    raw = (FIXTURES / "erc_opamp.json").read_text(encoding="utf-8")
    findings, meta = parse_erc_json(raw)
    assert meta["kicad_version"] == "10.0.7"
    assert len(findings) == 4
    assert sum(1 for f in findings if f.severity == "error") == 3
    assert sum(1 for f in findings if f.severity == "warning") == 1

    by_key = {(f.rule_id, f.reference, f.pin): f for f in findings}
    pwr = by_key[("power_pin_not_driven", "#PWR01", "1")]
    assert pwr.x_mm == 135.89
    assert pwr.y_mm == 186.69
    assert pwr.source == "kicad"

    u1_vplus = by_key[("power_pin_not_driven", "U1", "3")]
    assert u1_vplus.x_mm == 147.32
    assert u1_vplus.y_mm == 96.52

    mismatch = by_key[("lib_symbol_mismatch", "U1", None)]
    assert mismatch.severity == "warning"
    assert mismatch.x_mm == 149.86


def test_parse_opamp_text_report():
    raw = (FIXTURES / "erc_opamp_report.txt").read_text(encoding="utf-8")
    findings, counts = parse_erc_report_text(raw)
    assert counts == {"messages": 4, "errors": 3, "warnings": 1}
    assert len(findings) == 4
    refs = {f.reference for f in findings}
    assert "#PWR01" in refs and "U1" in refs


def test_parse_clean_json_zero_violations():
    raw = (FIXTURES / "erc_clean.json").read_text(encoding="utf-8")
    findings, _meta = parse_erc_json(raw)
    assert findings == []


def test_missing_cli_does_not_claim_pass():
    with (
        patch("app.schematics.erc.find_kicad_cli", return_value=None),
        patch("app.schematics.erc.probe_kicad_cli_erc", return_value=False),
    ):
        report = build_erc_report(
            schematic_path=FIXTURES / "OPamp-comparator.kicad_sch"
        )
    assert report.available is False
    assert report.ran is False
    assert report.findings == []
    assert report.failure_reason
    assert "not available" in report.failure_reason.lower()


def test_cli_failure_without_report():
    with (
        patch("app.schematics.erc.find_kicad_cli", return_value="/fake/kicad-cli"),
        patch("app.schematics.erc.probe_kicad_cli_erc", return_value=True),
        patch(
            "app.schematics.erc.subprocess.run",
            return_value=MagicMock(returncode=1, stdout="", stderr="boom"),
        ),
    ):
        report = build_erc_report(
            schematic_path=FIXTURES / "sample.kicad_sch"
        )
    assert report.available is True
    assert report.ran is False
    assert report.findings == []
    assert report.failure_reason
    assert "did not write" in report.failure_reason.lower() or "failed" in report.failure_reason.lower()


def test_cli_success_parses_json_via_temp_copy(tmp_path):
    json_payload = (FIXTURES / "erc_opamp.json").read_text(encoding="utf-8")

    def fake_run(args, **kwargs):
        # args: [cli, sch, erc, ..., --output, report_path, copy_path]
        output = Path(args[args.index("--output") + 1])
        output.write_text(json_payload, encoding="utf-8")
        return MagicMock(returncode=0, stdout="Found 4 violations", stderr="")

    with (
        patch("app.schematics.erc.find_kicad_cli", return_value="/fake/kicad-cli"),
        patch("app.schematics.erc.probe_kicad_cli_erc", return_value=True),
        patch("app.schematics.erc.subprocess.run", side_effect=fake_run),
    ):
        report = build_erc_report(
            schematic_path=FIXTURES / "OPamp-comparator.kicad_sch"
        )

    assert report.ran is True
    assert report.available is True
    assert report.error_count == 3
    assert report.warning_count == 1
    assert report.message_count == 4
    assert report.failure_reason is None
    assert report.kicad_version == "10.0.7"
    # Original fixture must remain untouched (read-only guarantee).
    assert (FIXTURES / "OPamp-comparator.kicad_sch").is_file()


def test_zero_violation_report_is_explicit_pass_not_skipped():
    json_payload = (FIXTURES / "erc_clean.json").read_text(encoding="utf-8")

    def fake_run(args, **kwargs):
        output = Path(args[args.index("--output") + 1])
        output.write_text(json_payload, encoding="utf-8")
        return MagicMock(returncode=0, stdout="Found 0 violations", stderr="")

    with (
        patch("app.schematics.erc.find_kicad_cli", return_value="/fake/kicad-cli"),
        patch("app.schematics.erc.probe_kicad_cli_erc", return_value=True),
        patch("app.schematics.erc.subprocess.run", side_effect=fake_run),
    ):
        report = build_erc_report(schematic_path=FIXTURES / "sample.kicad_sch")

    assert report.ran is True
    assert report.findings == []
    assert report.error_count == 0
    assert report.warning_count == 0
    assert report.message_count == 0
    assert report.failure_reason is None


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CIRCUITSENTINEL_MAX_UPLOAD_MB", "5")
    import app.schematics.config as config

    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    return TestClient(app)


def test_analyze_kicad_includes_structured_erc(client):
    json_payload = (FIXTURES / "erc_opamp.json").read_text(encoding="utf-8")

    def fake_run(args, **kwargs):
        output = Path(args[args.index("--output") + 1])
        output.write_text(json_payload, encoding="utf-8")
        return MagicMock(returncode=0, stdout="", stderr="")

    with (
        patch("app.schematics.erc.find_kicad_cli", return_value="/fake/kicad-cli"),
        patch("app.schematics.erc.probe_kicad_cli_erc", return_value=True),
        patch("app.schematics.render.find_kicad_cli", return_value=None),
        patch("app.schematics.render.probe_kicad_cli_export_svg", return_value=False),
        patch("app.schematics.netlist.find_kicad_cli", return_value=None),
        patch("app.schematics.netlist.probe_kicad_cli_export_netlist", return_value=False),
        patch("app.schematics.erc.subprocess.run", side_effect=fake_run),
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
    assert body["erc"]["ran"] is True
    assert body["erc"]["error_count"] == 3
    assert body["erc"]["warning_count"] == 1
    assert len(body["erc"]["findings"]) == 4
    assert all(f["source"] == "kicad" for f in body["erc"]["findings"])
