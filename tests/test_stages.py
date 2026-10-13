"""Overall status vs per-stage completion for KiCad analysis."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app.schematics.analyze import analyze_schematic_bytes
from app.schematics.models import (
    CoordinateMapping,
    ErcFinding,
    ErcReport,
    NetlistReport,
    ViewerInfo,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "schematics"


def test_erc_findings_keep_overall_partial_but_stages_complete(tmp_path, monkeypatch):
    import app.schematics.config as config
    import app.schematics.storage as storage

    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(storage, "ensure_upload_dir", config.ensure_upload_dir)

    data = (FIXTURES / "sample.kicad_sch").read_bytes()
    fake_erc = ErcReport(
        ran=True,
        available=True,
        findings=[
            ErcFinding(
                rule_id="power_pin_not_driven",
                severity="error",
                description="Input Power pin not driven",
                reference="U1",
                pin="3",
                x_mm=10.0,
                y_mm=20.0,
            )
        ],
        error_count=1,
        warning_count=0,
        message_count=1,
        kicad_version="10.0.7",
    )
    fake_viewer = ViewerInfo(
        file_id="a" * 32,
        format="kicad_sch",
        source_url=f"/api/schematics/files/{'a' * 32}",
        preview_url=f"/api/schematics/files/{'a' * 32}/preview",
        render_status="ready",
        render_message="SVG ready",
        content_type="image/svg+xml",
        coordinate_mapping=CoordinateMapping(
            reliable=True,
            units="mm",
            view_min_x=0,
            view_min_y=0,
            view_width=100,
            view_height=100,
            note="reliable",
        ),
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
        result = analyze_schematic_bytes(
            data=data,
            filename="sample.kicad_sch",
            content_type="application/octet-stream",
        )

    assert result.status == "partial"
    assert result.stages.parsing.status == "complete"
    assert result.stages.rendering.status == "complete"
    assert result.stages.erc.status == "complete"
    assert "error" in result.stages.erc.detail.lower()
    assert len(result.finding_interpretations) == 1
    assert result.finding_interpretations[0].rule_id == "power_pin_not_driven"
    assert any("partial because" in item.lower() for item in result.limitations)
