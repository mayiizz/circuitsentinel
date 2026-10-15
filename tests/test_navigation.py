"""Coordinate mapping and finding-navigation helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.schematics.erc import parse_erc_json
from app.schematics.svg_coords import mm_to_view_percent, parse_svg_coordinate_mapping

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "schematics"

# Matches KiCad A4 SVG extents used by OPamp exports / test_render fixture.
OPAMP_LIKE_SVG = """<?xml version="1.0" standalone="no"?>
<svg xmlns="http://www.w3.org/2000/svg" version="1.1"
  width="297.0022mm" height="210.0072mm" viewBox="0.0000 0.0000 297.0022 210.0072">
</svg>
"""


def test_all_four_opamp_erc_findings_map_when_reliable():
    mapping = parse_svg_coordinate_mapping(OPAMP_LIKE_SVG)
    assert mapping.reliable is True

    findings, _ = parse_erc_json((FIXTURES / "erc_opamp.json").read_text())
    assert len(findings) == 4

    expected = [
        ("#PWR01", "1", 135.89, 186.69),
        ("U1", "3", 147.32, 96.52),
        ("U1", "4", 147.32, 111.76),
        ("U1", None, 149.86, 104.14),
    ]
    for finding, (ref, pin, x, y) in zip(findings, expected, strict=True):
        assert finding.reference == ref
        assert finding.pin == pin
        assert finding.x_mm == pytest.approx(x)
        assert finding.y_mm == pytest.approx(y)
        percent = mm_to_view_percent(finding.x_mm, finding.y_mm, mapping)
        assert percent is not None
        left, top = percent
        assert 0.0 <= left <= 100.0
        assert 0.0 <= top <= 100.0
        # Spot-check formula against viewBox origin at (0,0).
        assert left == pytest.approx(x / 297.0022 * 100.0, abs=0.05)
        assert top == pytest.approx(y / 210.0072 * 100.0, abs=0.05)


def test_unreliable_mapping_refuses_highlight():
    svg = '<svg viewBox="0 0 100 80" width="100px" height="80px"></svg>'
    mapping = parse_svg_coordinate_mapping(svg)
    assert mapping.reliable is False
    assert mm_to_view_percent(10.0, 10.0, mapping) is None


def test_mm_to_view_percent_respects_view_min_offset():
    svg = (
        '<svg width="100mm" height="50mm" '
        'viewBox="10 20 100 50"></svg>'
    )
    mapping = parse_svg_coordinate_mapping(svg)
    assert mapping.reliable is True
    percent = mm_to_view_percent(60.0, 45.0, mapping)
    assert percent is not None
    assert percent[0] == pytest.approx(50.0)
    assert percent[1] == pytest.approx(50.0)
