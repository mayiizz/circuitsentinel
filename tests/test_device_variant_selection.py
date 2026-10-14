"""Explicit device_variant selection for recommended-supply checks.

Uses page-5 LM358 multi-variant recommended text. Does not hardcode success
by PDF filename or document hash. Does not infer variants from references.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.datasheets.checks import (
    EngineeringCheckRequest,
    StatedSupplyVoltage,
    _fact_matches_exact_variant,
    run_recommended_supply_check,
)
from app.datasheets.link import create_datasheet_component_link
from app.datasheets.models import (
    DatasheetComponentLinkRequest,
    DatasheetIngestReport,
    DatasheetSource,
    NormalizedDatasheetFact,
    RawDatasheetEvidence,
)
from app.datasheets.normalize import normalize_raw_evidence
from app.datasheets.store import store_ingest_report
from app.schematics.storage import store_upload

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "datasheets"
FIXTURES_SCH = Path(__file__).resolve().parent / "fixtures" / "schematics"
PAGE5 = (FIXTURES / "lm358_slos068_page5_recommended_operating.txt").read_text()
DOC_HASH = "d" * 64


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


def _evidence(text: str, *, page: int, doc: str) -> RawDatasheetEvidence:
    return RawDatasheetEvidence(
        id=f"{doc}:raw:page:{page}:pypdf_extract_text",
        document_id=doc,
        page_number=page,
        text=text,
    )


def _prepare_page5_link(doc: str = "variant-doc"):
    ev = _evidence(PAGE5, page=5, doc=doc)
    facts, unresolved = normalize_raw_evidence(
        [ev], source_content_sha256=DOC_HASH, document_id=doc
    )
    store_ingest_report(
        DatasheetIngestReport(
            status="partial",
            source=DatasheetSource(
                document_id=doc,
                filename="any-name.pdf",
                content_sha256=DOC_HASH,
                page_count=1,
                byte_length=len(PAGE5),
            ),
            pages=[],
            raw_evidence=[ev],
            facts=facts,
            unresolved=unresolved,
            claims=[],
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
    return file_id, doc, facts, ev


def _check(file_id: str, doc: str, *, volts: float, variant: str | None):
    return run_recommended_supply_check(
        EngineeringCheckRequest(
            schematic_file_id=file_id,
            component_reference="R1",
            document_id=doc,
            content_sha256=DOC_HASH,
            stated_supply=StatedSupplyVoltage(value_v=volts),
            device_variant=variant,
        )
    )


def test_exact_variant_match_does_not_substring():
    fact = NormalizedDatasheetFact(
        id="x",
        fact_type="supply_voltage_max",
        value=36.0,
        unit="V",
        qualifiers=["recommended_operating", "variant:LM358B"],
        source_content_sha256=DOC_HASH,
        page_number=5,
        supporting_evidence_id="e",
        supporting_excerpt="LM358B 3 36",
    )
    assert _fact_matches_exact_variant(fact, "LM358B") is True
    assert _fact_matches_exact_variant(fact, "LM358") is False
    assert _fact_matches_exact_variant(fact, "LM358BA") is False
    assert _fact_matches_exact_variant(fact, "lm358b") is True  # case-insensitive exact


def test_missing_variant_selection_is_inconclusive(upload_env):
    file_id, doc, _, _ = _prepare_page5_link()
    result = _check(file_id, doc, volts=5.0, variant=None)
    assert result.status == "inconclusive"
    assert result.finding is not None
    assert "device_variant" in " ".join(result.finding.missing_information)
    assert result.finding.datasheet_supply_max_v is None
    assert result.finding.selected_device_variant is None


def test_lm358_uses_3_to_30_range_not_lm358b(upload_env):
    file_id, doc, facts, ev = _prepare_page5_link()
    result = _check(file_id, doc, volts=5.0, variant="LM358")
    assert result.status == "no_violation_detected"
    assert result.finding is not None
    assert result.finding.selected_device_variant == "LM358"
    assert result.finding.datasheet_supply_min_v == 3.0
    assert result.finding.datasheet_supply_max_v == 30.0
    # Evidence is the LM358 row (30 V), not the LM358B 36 V row.
    assert result.finding.evidence_references
    for ref in result.finding.evidence_references:
        assert ref.page_number == 5
        assert ref.evidence_id == ev.id
        assert ref.excerpt is not None and ref.excerpt in PAGE5
        assert "recommended_operating" in (ref.qualifiers or [])
        assert "variant:LM358" in (ref.qualifiers or [])
        assert "variant:LM358B" not in (ref.qualifiers or [])
    # Above LM358 max but within LM358B max → violation for LM358 only.
    over = _check(file_id, doc, volts=32.0, variant="LM358")
    assert over.status == "potential_violation"
    assert over.finding is not None
    assert over.finding.datasheet_supply_max_v == 30.0


def test_lm358b_uses_3_to_36_range(upload_env):
    file_id, doc, _, ev = _prepare_page5_link(doc="variant-b")
    result = _check(file_id, doc, volts=32.0, variant="LM358B")
    assert result.status == "no_violation_detected"
    assert result.finding is not None
    assert result.finding.selected_device_variant == "LM358B"
    assert result.finding.datasheet_supply_min_v == 3.0
    assert result.finding.datasheet_supply_max_v == 36.0
    for ref in result.finding.evidence_references:
        assert ref.page_number == 5
        assert ref.evidence_id == ev.id
        assert "variant:LM358B" in (ref.qualifiers or [])
        # Exact qualifier present; bare LM358 must not be treated as selected.
        assert result.finding.selected_device_variant != "LM358"


def test_unknown_variant_is_inconclusive(upload_env):
    file_id, doc, _, _ = _prepare_page5_link(doc="variant-unknown")
    result = _check(file_id, doc, volts=5.0, variant="LM999")
    assert result.status == "inconclusive"
    assert result.finding is not None
    assert result.finding.selected_device_variant == "LM999"
    assert "exactly match" in result.finding.explanation.lower()
    assert result.finding.datasheet_supply_max_v is None


def test_selecting_lm358_does_not_use_lm358b_only_facts(upload_env):
    """If only LM358B facts exist, selecting LM358 must not substring-match."""
    doc = "b-only"
    facts = [
        NormalizedDatasheetFact(
            id=f"{doc}:fact:supply_voltage_min:page:5:aaaa",
            fact_type="supply_voltage_min",
            value=3.0,
            unit="V",
            qualifiers=["recommended_operating", "variant:LM358B"],
            source_content_sha256=DOC_HASH,
            page_number=5,
            supporting_evidence_id=f"{doc}:raw:page:5:pypdf_extract_text",
            supporting_excerpt="LM358B, LM358BA 3 36",
        ),
        NormalizedDatasheetFact(
            id=f"{doc}:fact:supply_voltage_max:page:5:bbbb",
            fact_type="supply_voltage_max",
            value=36.0,
            unit="V",
            qualifiers=["recommended_operating", "variant:LM358B"],
            source_content_sha256=DOC_HASH,
            page_number=5,
            supporting_evidence_id=f"{doc}:raw:page:5:pypdf_extract_text",
            supporting_excerpt="LM358B, LM358BA 3 36",
        ),
    ]
    page_text = "Recommended Operating Conditions\nLM358B, LM358BA 3 36\n"
    raw = [
        RawDatasheetEvidence(
            id=f"{doc}:raw:page:5:pypdf_extract_text",
            document_id=doc,
            page_number=5,
            text=page_text,
        )
    ]
    store_ingest_report(
        DatasheetIngestReport(
            status="ok",
            source=DatasheetSource(
                document_id=doc,
                filename="b-only.pdf",
                content_sha256=DOC_HASH,
                page_count=1,
                byte_length=10,
            ),
            pages=[],
            raw_evidence=raw,
            facts=facts,
            unresolved=[],
            claims=[],
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
    assert link.status in {"ok", "duplicate"}
    result = _check(file_id, doc, volts=5.0, variant="LM358")
    assert result.status == "inconclusive"
    assert "exactly match" in (result.finding.explanation or "").lower()


def test_incomplete_variant_range_is_inconclusive(upload_env):
    doc = "incomplete"
    facts = [
        NormalizedDatasheetFact(
            id=f"{doc}:fact:supply_voltage_max:page:5:cccc",
            fact_type="supply_voltage_max",
            value=30.0,
            unit="V",
            qualifiers=["recommended_operating", "variant:LM358"],
            source_content_sha256=DOC_HASH,
            page_number=5,
            supporting_evidence_id=f"{doc}:raw:page:5:pypdf_extract_text",
            supporting_excerpt="LM358 30",
        ),
    ]
    store_ingest_report(
        DatasheetIngestReport(
            status="partial",
            source=DatasheetSource(
                document_id=doc,
                filename="incomplete.pdf",
                content_sha256=DOC_HASH,
                page_count=1,
                byte_length=10,
            ),
            pages=[],
            raw_evidence=[
                RawDatasheetEvidence(
                    id=f"{doc}:raw:page:5:pypdf_extract_text",
                    document_id=doc,
                    page_number=5,
                    text="Recommended Operating Conditions\nLM358 30\n",
                )
            ],
            facts=facts,
            unresolved=[],
            claims=[],
        )
    )
    file_id = store_upload(
        (FIXTURES_SCH / "sample.kicad_sch").read_bytes(), ".kicad_sch"
    ).stem
    assert (
        create_datasheet_component_link(
            DatasheetComponentLinkRequest(
                schematic_file_id=file_id,
                component_reference="R1",
                document_id=doc,
                content_sha256=DOC_HASH,
            )
        ).status
        in {"ok", "duplicate"}
    )
    result = _check(file_id, doc, volts=5.0, variant="LM358")
    assert result.status == "inconclusive"
    assert result.finding is not None
    assert "complete" in result.finding.explanation.lower()
    assert any("supply_voltage_min" in m for m in result.finding.missing_information)
