"""Regression: TI LM358 multi-variant recommended table vs figure test conditions.

Uses captured page text from a real SLOS068 extraction (pages 5 and 23).
Does not hardcode success by filename or document hash.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.datasheets.checks import (
    EngineeringCheckRequest,
    StatedSupplyVoltage,
    run_recommended_supply_check,
)
from app.datasheets.link import create_datasheet_component_link
from app.datasheets.models import (
    DatasheetComponentLinkRequest,
    DatasheetIngestReport,
    DatasheetSource,
    RawDatasheetEvidence,
)
from app.datasheets.normalize import normalize_raw_evidence
from app.datasheets.store import store_ingest_report
from app.schematics.storage import store_upload

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "datasheets"
FIXTURES_SCH = Path(__file__).resolve().parent / "fixtures" / "schematics"
PAGE5 = (FIXTURES / "lm358_slos068_page5_recommended_operating.txt").read_text()
PAGE23 = (FIXTURES / "lm358_slos068_page23_typical_characteristics.txt").read_text()
DOC_HASH = "b" * 64


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


def _evidence(text: str, *, page: int, doc: str = "lm358-doc") -> RawDatasheetEvidence:
    return RawDatasheetEvidence(
        id=f"{doc}:raw:page:{page}:pypdf_extract_text",
        document_id=doc,
        page_number=page,
        text=text,
    )


def test_page5_text_contains_recommended_operating_table():
    assert "5.3 Recommended Operating Conditions" in PAGE5
    assert "VS Supply voltage" in PAGE5
    assert "LM358B" in PAGE5 and "LM358A" in PAGE5 and "LM358," in PAGE5
    assert "3 36" in PAGE5 and "3 30" in PAGE5 and "3 26" in PAGE5


def test_page23_text_is_typical_characteristics_with_vcc_test_condition():
    assert "Typical Characteristics" in PAGE23
    assert "VCC = 15 V" in PAGE23
    assert "Recommended Operating Conditions" not in PAGE23


def test_page5_emits_variant_qualified_recommended_supply_bounds():
    ev = _evidence(PAGE5, page=5)
    facts, unresolved = normalize_raw_evidence(
        [ev], source_content_sha256=DOC_HASH, document_id="lm358-doc"
    )

    recommended = [f for f in facts if "recommended_operating" in f.qualifiers]
    assert recommended, "page 5 must yield recommended_operating supply facts"

    mins = {f.value for f in recommended if f.fact_type == "supply_voltage_min"}
    maxes = {f.value for f in recommended if f.fact_type == "supply_voltage_max"}
    assert mins == {3.0}
    assert maxes == {36.0, 30.0, 26.0}

    # Distinctions among LM358 / LM358A / LM358B preserved — not collapsed.
    all_quals = {q for f in recommended for q in f.qualifiers}
    assert "variant:LM358" in all_quals
    assert "variant:LM358A" in all_quals
    assert "variant:LM358B" in all_quals

    lm358_row = [
        f
        for f in recommended
        if f.fact_type == "supply_voltage_max" and "variant:LM358" in f.qualifiers
    ]
    assert len(lm358_row) == 1
    assert lm358_row[0].value == 30.0
    assert lm358_row[0].page_number == 5
    assert lm358_row[0].supporting_excerpt in PAGE5
    assert lm358_row[0].supporting_evidence_id == ev.id

    lm358b_row = [
        f
        for f in recommended
        if f.fact_type == "supply_voltage_max" and "variant:LM358B" in f.qualifiers
    ]
    assert len(lm358b_row) == 1
    assert lm358b_row[0].value == 36.0

    assert any(
        "Multiple variant-specific recommended_operating" in u.reason
        for u in unresolved
    )


def test_page23_alone_cannot_establish_recommended_operating_bounds():
    ev = _evidence(PAGE23, page=23)
    facts, unresolved = normalize_raw_evidence(
        [ev], source_content_sha256=DOC_HASH, document_id="lm358-doc"
    )

    assert not any("recommended_operating" in f.qualifiers for f in facts)
    assert not any(
        f.fact_type in {"supply_voltage_max", "supply_voltage_min"} for f in facts
    ), "VCC = 15 V in a figure caption must not become a rated supply fact"

    vcc_unresolved = [u for u in unresolved if u.candidate_text == "VCC = 15 V"]
    assert vcc_unresolved
    assert any("not treated as a rated supply limit" in u.reason for u in vcc_unresolved)


def test_page23_vcc_never_tagged_recommended_even_with_page5():
    """Combined pages: page-23 VCC still must not be recommended_operating."""
    pages = [
        _evidence(PAGE5, page=5),
        _evidence(PAGE23, page=23),
    ]
    facts, _ = normalize_raw_evidence(
        pages, source_content_sha256=DOC_HASH, document_id="lm358-doc"
    )
    page23_facts = [f for f in facts if f.page_number == 23]
    assert page23_facts == []
    assert all(
        f.page_number == 5
        for f in facts
        if "recommended_operating" in f.qualifiers
    )


def test_engineering_check_inconclusive_when_variant_ranges_conflict(upload_env):
    doc = "lm358-doc"
    ev = _evidence(PAGE5, page=5, doc=doc)
    facts, unresolved = normalize_raw_evidence(
        [ev], source_content_sha256=DOC_HASH, document_id=doc
    )
    assert facts

    store_ingest_report(
        DatasheetIngestReport(
            status="partial",
            source=DatasheetSource(
                document_id=doc,
                filename="irrelevant-name.pdf",
                content_sha256=DOC_HASH,
                page_count=1,
                byte_length=100,
            ),
            pages=[],
            raw_evidence=[ev],
            facts=facts,
            unresolved=unresolved,
            claims=[],
            likely_scanned=False,
            limitations=[],
        )
    )

    file_id = store_upload(
        (FIXTURES_SCH / "sample.kicad_sch").read_bytes(), ".kicad_sch"
    ).stem
    link = create_datasheet_component_link(
        DatasheetComponentLinkRequest(
            schematic_file_id=file_id,
            component_reference="R1",
            document_id=doc,
            content_sha256=DOC_HASH,
        )
    )
    assert link.status in {"ok", "duplicate"}, link.failure_reason

    result = run_recommended_supply_check(
        EngineeringCheckRequest(
            schematic_file_id=file_id,
            component_reference="R1",
            document_id=doc,
            content_sha256=DOC_HASH,
            stated_supply=StatedSupplyVoltage(value_v=5.0, note="bench rail"),
        )
    )
    assert result.status == "inconclusive"
    assert result.finding is not None
    assert "variant" in result.finding.explanation.lower()
    assert result.finding.stated_supply_v == 5.0
    # Must not silently pick 30 V or 36 V and claim no_violation_detected.
    assert result.finding.datasheet_supply_max_v is None
