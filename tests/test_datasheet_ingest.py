"""Phase 3A datasheet PDF ingestion: raw evidence, provenance, honesty."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.datasheets.ingest import PHASE3A_LIMITATIONS, ingest_datasheet_pdf
from app.main import app

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "datasheets"


def test_text_pdf_produces_raw_evidence_with_exact_text():
    data = (FIXTURES / "text_single.pdf").read_bytes()
    report = ingest_datasheet_pdf(data, filename="text_single.pdf", document_id="docA")
    assert report.status == "ok"
    assert report.claims == []
    assert report.likely_scanned is False
    assert report.source is not None
    assert report.source.document_id == "docA"
    assert report.source.filename == "text_single.pdf"
    assert report.source.page_count == 1
    assert len(report.raw_evidence) == 1
    ev = report.raw_evidence[0]
    assert ev.id == "docA:raw:page:1:pypdf_extract_text"
    assert ev.provenance == "datasheet_pdf"
    assert ev.extraction_method == "pypdf_extract_text"
    assert ev.page_number == 1
    assert "LM358 Dual Operational Amplifier" in ev.text
    assert "Supply voltage 32 V" in ev.text
    assert report.pages[0].text == ev.text
    for item in PHASE3A_LIMITATIONS:
        assert item in report.limitations


def test_multipage_preserves_page_numbers_and_stable_ids():
    data = (FIXTURES / "text_multipage.pdf").read_bytes()
    report = ingest_datasheet_pdf(
        data, filename="text_multipage.pdf", document_id="multi"
    )
    assert report.status == "ok"
    assert report.source is not None
    assert report.source.page_count == 3
    assert len(report.pages) == 3
    assert len(report.raw_evidence) == 3
    assert [p.page_number for p in report.pages] == [1, 2, 3]
    assert [e.page_number for e in report.raw_evidence] == [1, 2, 3]
    assert [e.id for e in report.raw_evidence] == [
        "multi:raw:page:1:pypdf_extract_text",
        "multi:raw:page:2:pypdf_extract_text",
        "multi:raw:page:3:pypdf_extract_text",
    ]
    assert "Datasheet Page One" in report.raw_evidence[0].text
    assert "Datasheet Page Two" in report.raw_evidence[1].text
    assert "Datasheet Page Three" in report.raw_evidence[2].text
    assert all(e.document_id == "multi" for e in report.raw_evidence)
    assert report.claims == []


def test_stable_ids_are_deterministic_for_same_document_id():
    data = (FIXTURES / "text_single.pdf").read_bytes()
    a = ingest_datasheet_pdf(data, document_id="stable")
    b = ingest_datasheet_pdf(data, document_id="stable")
    assert [e.id for e in a.raw_evidence] == [e.id for e in b.raw_evidence]
    assert a.source is not None and b.source is not None
    assert a.source.content_sha256 == b.source.content_sha256
    # Different scope => different evidence ids (no cross-document collision).
    c = ingest_datasheet_pdf(data, document_id="other")
    assert [e.id for e in c.raw_evidence] != [e.id for e in a.raw_evidence]


def test_content_derived_document_id_without_explicit_scope():
    data = (FIXTURES / "text_single.pdf").read_bytes()
    report = ingest_datasheet_pdf(data, filename="part.pdf")
    assert report.source is not None
    assert report.source.document_id.startswith("part-")
    assert len(report.source.content_sha256) == 64
    assert report.raw_evidence[0].document_id == report.source.document_id


def test_scanned_like_pdf_is_explicit_empty_not_success():
    data = (FIXTURES / "scanned_like.pdf").read_bytes()
    report = ingest_datasheet_pdf(
        data, filename="scanned_like.pdf", document_id="scan"
    )
    assert report.status == "empty"
    assert report.likely_scanned is True
    assert report.raw_evidence == []
    assert report.claims == []
    assert report.failure_reason is not None
    assert "OCR" in " ".join(report.limitations) or "scanned" in (
        report.failure_reason or ""
    ).lower()
    assert report.source is not None
    assert report.source.page_count == 1
    assert report.pages[0].has_text is False


def test_malformed_pdf_returns_error_without_invented_text():
    data = (FIXTURES / "malformed.pdf").read_bytes()
    report = ingest_datasheet_pdf(data, filename="malformed.pdf", document_id="bad")
    assert report.status == "error"
    assert report.raw_evidence == []
    assert report.claims == []
    assert report.failure_reason is not None
    assert "Unable to read" in report.failure_reason or "PDF" in report.failure_reason


def test_empty_bytes_error():
    report = ingest_datasheet_pdf(b"", filename="empty.pdf")
    assert report.status == "error"
    assert report.raw_evidence == []
    assert report.claims == []


def test_no_component_matching_or_claims_from_filename():
    data = (FIXTURES / "text_single.pdf").read_bytes()
    report = ingest_datasheet_pdf(
        data, filename="LM358_definitely_the_part.pdf", document_id="fn"
    )
    # Filename is recorded as source identity only — not a verified part link.
    assert report.source is not None
    assert report.source.filename == "LM358_definitely_the_part.pdf"
    assert report.claims == []
    assert not hasattr(report, "matched_components")
    assert any("not treated as verified component" in item for item in report.limitations)


def test_provenance_fields_present_on_every_evidence_record():
    data = (FIXTURES / "text_multipage.pdf").read_bytes()
    report = ingest_datasheet_pdf(data, document_id="prov")
    assert report.raw_evidence
    for ev in report.raw_evidence:
        assert ev.provenance == "datasheet_pdf"
        assert ev.extraction_method == "pypdf_extract_text"
        assert ev.document_id == "prov"
        assert ev.text == report.pages[ev.page_number - 1].text


@pytest.fixture()
def client():
    return TestClient(app)


def test_api_ingest_datasheet_endpoint(client):
    response = client.post(
        "/api/datasheets/ingest",
        files={
            "file": (
                "text_multipage.pdf",
                (FIXTURES / "text_multipage.pdf").read_bytes(),
                "application/pdf",
            )
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["claims"] == []
    assert len(body["raw_evidence"]) == 3
    assert body["raw_evidence"][0]["provenance"] == "datasheet_pdf"
    assert body["source"]["page_count"] == 3


def test_api_rejects_non_pdf_extension(client):
    response = client.post(
        "/api/datasheets/ingest",
        files={"file": ("notes.txt", b"not a pdf", "text/plain")},
    )
    assert response.status_code == 400
    body = response.json()
    assert body["status"] == "error"
    assert body["raw_evidence"] == []


def test_api_malformed_pdf_returns_error_report_not_500(client):
    response = client.post(
        "/api/datasheets/ingest",
        files={
            "file": (
                "malformed.pdf",
                (FIXTURES / "malformed.pdf").read_bytes(),
                "application/pdf",
            )
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert body["raw_evidence"] == []
    assert body["claims"] == []
    assert body["failure_reason"]


def test_api_rejects_oversized_upload(client, monkeypatch):
    monkeypatch.setenv("CIRCUITSENTINEL_MAX_UPLOAD_MB", "0.000001")  # ~1 byte
    # Re-read limit after env change (config reads env each call).
    from app.schematics.config import max_upload_bytes

    assert max_upload_bytes() < 100
    response = client.post(
        "/api/datasheets/ingest",
        files={
            "file": (
                "big.pdf",
                (FIXTURES / "text_single.pdf").read_bytes(),
                "application/pdf",
            )
        },
    )
    assert response.status_code == 413
    body = response.json()
    assert body["status"] == "error"
    assert "maximum upload size" in body["failure_reason"].lower()
    assert body["raw_evidence"] == []


def test_api_ingest_stores_report_under_datasheets_not_schematic_uploads(
    client, tmp_path, monkeypatch
):
    """Phase 4A persists ingest reports by hash; schematic upload files stay separate."""
    import app.schematics.config as config

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr(config, "UPLOAD_DIR", upload_dir)
    response = client.post(
        "/api/datasheets/ingest",
        files={
            "file": (
                "text_single.pdf",
                (FIXTURES / "text_single.pdf").read_bytes(),
                "application/pdf",
            )
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    sha = body["source"]["content_sha256"]
    # Only the datasheets/ store subtree — not a schematic UUID upload.
    assert not any(p.suffix == ".kicad_sch" for p in upload_dir.rglob("*"))
    stored = upload_dir / "datasheets" / f"{sha}.json"
    assert stored.is_file()


def test_content_sha256_is_deterministic_hash_of_original_bytes():
    import hashlib

    data = (FIXTURES / "text_multipage.pdf").read_bytes()
    expected = hashlib.sha256(data).hexdigest()
    a = ingest_datasheet_pdf(data, document_id="hash")
    b = ingest_datasheet_pdf(data, document_id="hash")
    assert a.source is not None and b.source is not None
    assert a.source.content_sha256 == expected
    assert b.source.content_sha256 == expected
    assert a.source.byte_length == len(data)


def test_page_numbers_are_one_based():
    data = (FIXTURES / "text_multipage.pdf").read_bytes()
    report = ingest_datasheet_pdf(data, document_id="pages")
    assert [p.page_number for p in report.pages] == [1, 2, 3]
    assert all(p.page_number >= 1 for p in report.pages)
    assert [e.page_number for e in report.raw_evidence] == [1, 2, 3]


def test_schematic_analyze_api_unchanged_by_datasheet_module(client, tmp_path, monkeypatch):
    """Phase 3A must not alter schematic analyze behavior."""
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

    sch = (
        Path(__file__).resolve().parent / "fixtures" / "schematics" / "sample.kicad_sch"
    )
    response = client.post(
        "/api/schematics/analyze",
        files={
            "file": ("sample.kicad_sch", sch.read_bytes(), "application/octet-stream")
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "confirmed" in body
    assert "erc" in body
    assert "netlist" in body
    assert "evidence_graph" in body
    assert "datasheet" not in body  # not auto-attached to schematic analysis
