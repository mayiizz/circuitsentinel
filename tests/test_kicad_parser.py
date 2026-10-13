"""Regression tests for KiCad placed-instance vs lib_symbols parsing."""

from __future__ import annotations

from pathlib import Path

from app.schematics.kicad_parser import parse_kicad_sch

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "schematics"

OPAMP_EXPECTED_REFS = {
    "#PWR01",
    "#PWR02",
    "#PWR03",
    "R1",
    "R2",
    "R3",
    "R4",
    "Rpot1",
    "U1",
    "V1",
    "V2",
}

LIBRARY_TEMPLATE_REFS = {"R", "U", "V", "#PWR"}


def test_sample_kicad_still_finds_r1():
    parsed = parse_kicad_sch((FIXTURES / "sample.kicad_sch").read_bytes())
    refs = {s.reference for s in parsed["symbols"]}
    assert refs == {"R1"}
    assert all(s.lib_id for s in parsed["symbols"])


def test_opamp_comparator_placed_instances_only():
    data = (FIXTURES / "OPamp-comparator.kicad_sch").read_bytes()
    parsed = parse_kicad_sch(data)
    symbols = parsed["symbols"]
    refs = {s.reference for s in symbols}

    assert len(symbols) == 11
    assert refs == OPAMP_EXPECTED_REFS
    assert refs.isdisjoint(LIBRARY_TEMPLATE_REFS)
    assert all(s.lib_id for s in symbols)
    assert all(s.uuid for s in symbols)

    by_ref = {s.reference: s for s in symbols}
    assert by_ref["U1"].value == "${SIM.PARAMS}"
    assert by_ref["U1"].lib_id == "Simulation_SPICE:OPAMP"
    assert by_ref["U1"].properties.get("Value") == "${SIM.PARAMS}"
    assert by_ref["R4"].lib_id == "Device:R"
    assert by_ref["R4"].value == "10k"

    # Legitimate repeated power symbols kept with distinct refs.
    assert {"#PWR01", "#PWR02", "#PWR03"}.issubset(refs)
    assert all(by_ref[r].lib_id == "power:GND" for r in ("#PWR01", "#PWR02", "#PWR03"))

    # Connectivity remains structural metadata, not ERC proof.
    assert parsed["connectivity"]
    assert all("not an ERC result" in c.detail for c in parsed["connectivity"])
