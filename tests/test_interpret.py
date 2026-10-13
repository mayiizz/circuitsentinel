"""Tests for heuristic ERC interpretations (separate from KiCad facts)."""

from __future__ import annotations

import json
from pathlib import Path

from app.schematics.erc import parse_erc_json
from app.schematics.interpret import interpret_erc_findings
from app.schematics.models import ErcFinding, ErcReport

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "schematics"


def test_interpret_opamp_fixture_findings():
    raw = (FIXTURES / "erc_opamp.json").read_text()
    findings, _meta = parse_erc_json(raw)
    assert len(findings) == 4
    erc = ErcReport(
        ran=True,
        available=True,
        findings=findings,
        error_count=3,
        warning_count=1,
        message_count=4,
    )
    notes = interpret_erc_findings(erc)
    assert len(notes) == 4
    assert all(n.kicad_description for n in notes)
    assert all("not a verified" in n.disclaimer.lower() for n in notes)
    assert all("does not modify" in n.disclaimer.lower() for n in notes)
    power = [n for n in notes if n.rule_id == "power_pin_not_driven"]
    assert len(power) == 3
    mismatch = [n for n in notes if n.rule_id == "lib_symbol_mismatch"]
    assert len(mismatch) == 1
    assert "library" in mismatch[0].explanation.lower()


def test_interpret_empty_when_erc_did_not_run():
    assert interpret_erc_findings(ErcReport(ran=False)) == []


def test_generic_rule_still_has_disclaimer():
    finding = ErcFinding(
        rule_id="custom_rule",
        severity="error",
        description="Something unusual",
        reference="R1",
    )
    notes = interpret_erc_findings(
        ErcReport(ran=True, available=True, findings=[finding], error_count=1)
    )
    assert len(notes) == 1
    assert notes[0].rule_id == "custom_rule"
    assert "speculative" in notes[0].explanation.lower() or "factual" in notes[0].explanation.lower()
