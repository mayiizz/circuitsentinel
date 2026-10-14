"""Phase 3B: text-grounded normalized datasheet facts."""

from __future__ import annotations

from pathlib import Path

from app.datasheets.ingest import ingest_datasheet_pdf
from app.datasheets.models import RawDatasheetEvidence
from app.datasheets.normalize import (
    PHASE3B_LIMITATIONS,
    SUPPORTED_FACT_TYPES,
    normalize_raw_evidence,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "datasheets"
DOC_HASH = "a" * 64


def _evidence(text: str, *, page: int = 1, doc: str = "doc") -> RawDatasheetEvidence:
    return RawDatasheetEvidence(
        id=f"{doc}:raw:page:{page}:pypdf_extract_text",
        document_id=doc,
        page_number=page,
        text=text,
    )


def test_supported_fact_types_are_explicit_and_small():
    assert SUPPORTED_FACT_TYPES == (
        "supply_voltage_max",
        "supply_voltage_min",
        "input_voltage_max",
        "input_voltage_min",
    )


def test_valid_supply_voltage_with_unit():
    ev = _evidence("Absolute Maximum Ratings\nSupply voltage 32 V\n")
    facts, unresolved = normalize_raw_evidence(
        [ev], source_content_sha256=DOC_HASH, document_id="doc"
    )
    assert unresolved == []
    assert len(facts) == 1
    fact = facts[0]
    assert fact.fact_type == "supply_voltage_max"
    assert fact.value == 32.0
    assert fact.unit == "V"
    assert "absolute_maximum" in fact.qualifiers
    assert fact.page_number == 1
    assert fact.supporting_evidence_id == ev.id
    assert fact.source_content_sha256 == DOC_HASH
    assert "Supply voltage 32 V" in fact.supporting_excerpt
    assert fact.supporting_excerpt in ev.text
    assert fact.provenance == "datasheet_normalized"


def test_negative_and_dual_rail_supply():
    ev = _evidence("Operating supply voltage ±15 V\n")
    facts, unresolved = normalize_raw_evidence(
        [ev], source_content_sha256=DOC_HASH, document_id="doc"
    )
    assert unresolved == []
    by_type = {f.fact_type: f for f in facts}
    assert by_type["supply_voltage_max"].value == 15.0
    assert by_type["supply_voltage_min"].value == -15.0
    assert by_type["supply_voltage_min"].unit == "V"
    assert "dual_rail_symmetric" in by_type["supply_voltage_max"].qualifiers


def test_explicit_supply_min_max():
    ev = _evidence("Supply voltage min -0.3 V\nSupply voltage max 5.5 V\n")
    facts, _ = normalize_raw_evidence(
        [ev], source_content_sha256=DOC_HASH, document_id="doc"
    )
    by_type = {f.fact_type: f for f in facts}
    assert by_type["supply_voltage_min"].value == -0.3
    assert by_type["supply_voltage_max"].value == 5.5


def test_input_voltage_range():
    ev = _evidence("Input voltage range -0.3 V to 5.5 V\n")
    facts, unresolved = normalize_raw_evidence(
        [ev], source_content_sha256=DOC_HASH, document_id="doc"
    )
    assert unresolved == []
    by_type = {f.fact_type: f for f in facts}
    assert by_type["input_voltage_min"].value == -0.3
    assert by_type["input_voltage_max"].value == 5.5
    assert by_type["input_voltage_max"].unit == "V"


def test_input_voltage_max_explicit():
    ev = _evidence("Input voltage max 5 V\n")
    facts, unresolved = normalize_raw_evidence(
        [ev], source_content_sha256=DOC_HASH, document_id="doc"
    )
    assert unresolved == []
    assert len(facts) == 1
    assert facts[0].fact_type == "input_voltage_max"
    assert facts[0].value == 5.0


def test_recommended_operating_qualifier():
    ev = _evidence("Recommended Operating Conditions\nSupply voltage 3.3 V\n")
    facts, _ = normalize_raw_evidence(
        [ev], source_content_sha256=DOC_HASH, document_id="doc"
    )
    assert facts[0].qualifiers == ["recommended_operating"]


def test_unitless_value_is_unresolved_not_guessed():
    ev = _evidence("Supply voltage 32\n")  # no unit
    facts, unresolved = normalize_raw_evidence(
        [ev], source_content_sha256=DOC_HASH, document_id="doc"
    )
    assert facts == []
    assert len(unresolved) >= 1
    assert any("no explicit volt unit" in u.reason for u in unresolved)
    assert unresolved[0].supporting_evidence_id == ev.id
    assert unresolved[0].page_number == 1


def test_ambiguous_conflict_is_unresolved():
    ev = _evidence("Supply voltage 5 V\nSupply voltage 12 V\n")
    facts, unresolved = normalize_raw_evidence(
        [ev], source_content_sha256=DOC_HASH, document_id="doc"
    )
    assert facts == []
    assert any("Conflicting values" in u.reason for u in unresolved)


def test_inverted_input_range_unresolved():
    ev = _evidence("Input voltage range 5.5 V to -0.3 V\n")
    facts, unresolved = normalize_raw_evidence(
        [ev], source_content_sha256=DOC_HASH, document_id="doc"
    )
    assert facts == []
    assert any("low > high" in u.reason for u in unresolved)


def test_missing_evidence_yields_no_facts():
    facts, unresolved = normalize_raw_evidence(
        [], source_content_sha256=DOC_HASH, document_id="doc"
    )
    assert facts == []
    assert unresolved == []


def test_empty_page_text_yields_no_facts():
    ev = _evidence("   \n")
    facts, unresolved = normalize_raw_evidence(
        [ev], source_content_sha256=DOC_HASH, document_id="doc"
    )
    assert facts == []
    assert unresolved == []


def test_stable_fact_ids_for_same_document_and_excerpt():
    ev = _evidence("Supply voltage 32 V\n")
    a, _ = normalize_raw_evidence(
        [ev], source_content_sha256=DOC_HASH, document_id="doc"
    )
    b, _ = normalize_raw_evidence(
        [ev], source_content_sha256=DOC_HASH, document_id="doc"
    )
    assert [f.id for f in a] == [f.id for f in b]
    assert a[0].id.startswith("doc:fact:supply_voltage_max:page:1:")
    other_ev = _evidence("Supply voltage 32 V\n", doc="other")
    c, _ = normalize_raw_evidence(
        [other_ev], source_content_sha256=DOC_HASH, document_id="other"
    )
    assert c[0].id != a[0].id


def test_raw_evidence_not_mutated():
    ev = _evidence("Supply voltage 32 V\n")
    original = ev.model_dump()
    normalize_raw_evidence(
        [ev], source_content_sha256=DOC_HASH, document_id="doc"
    )
    assert ev.model_dump() == original


def test_page_traceability_across_pages():
    pages = [
        _evidence("Supply voltage 5 V\n", page=1),
        _evidence("Input voltage max 3.6 V\n", page=2),
    ]
    facts, _ = normalize_raw_evidence(
        pages, source_content_sha256=DOC_HASH, document_id="doc"
    )
    by_type = {f.fact_type: f for f in facts}
    assert by_type["supply_voltage_max"].page_number == 1
    assert by_type["supply_voltage_max"].supporting_evidence_id.endswith(":page:1:pypdf_extract_text")
    assert by_type["input_voltage_max"].page_number == 2
    assert by_type["input_voltage_max"].supporting_evidence_id.endswith(":page:2:pypdf_extract_text")


def test_ingest_wires_facts_from_fixture_without_claims_or_component_match():
    data = (FIXTURES / "text_single.pdf").read_bytes()
    report = ingest_datasheet_pdf(data, filename="text_single.pdf", document_id="docA")
    assert report.status == "ok"
    assert report.claims == []
    assert report.raw_evidence  # immutable raw still present
    # Fixture text includes "Supply voltage 32 V"
    supply = [f for f in report.facts if f.fact_type == "supply_voltage_max"]
    assert len(supply) == 1
    assert supply[0].value == 32.0
    assert supply[0].unit == "V"
    assert supply[0].source_content_sha256 == report.source.content_sha256
    assert supply[0].supporting_evidence_id == report.raw_evidence[0].id
    assert supply[0].supporting_excerpt in report.raw_evidence[0].text
    for item in PHASE3B_LIMITATIONS:
        assert item in report.limitations
    assert not hasattr(report, "matched_components")


def test_scanned_ingest_has_no_fabricated_facts():
    data = (FIXTURES / "scanned_like.pdf").read_bytes()
    report = ingest_datasheet_pdf(data, filename="scanned_like.pdf", document_id="scan")
    assert report.status == "empty"
    assert report.facts == []
    assert report.unresolved == []
    assert report.claims == []
