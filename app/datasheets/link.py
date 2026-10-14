"""Explicit, auditable datasheet-to-component linking (Phase 4A).

Requires a user-confirmed request. Never infers matches from filename, fuzzy
text, voltage similarity, or unverified part numbers. Does not issue pass/fail.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.datasheets.models import (
    DatasheetComponentLink,
    DatasheetComponentLinkRequest,
    DatasheetComponentLinkResponse,
    NormalizedDatasheetFact,
    RawDatasheetEvidence,
)
from app.datasheets.store import (
    load_ingest_report,
    load_link,
    make_link_id,
    store_link,
)
from app.schematics.evidence.build import resolve_component_node_id
from app.schematics.evidence.models import EvidenceEdge, EvidenceGraph, EvidenceNode
from app.schematics.kicad_parser import KiCadParseError, parse_kicad_sch
from app.schematics.storage import FILE_ID_RE, resolve_upload_id

PHASE4A_LIMITATIONS = [
    "Phase 4A links require explicit user confirmation; nothing is auto-matched.",
    "Filename, fuzzy text, voltage similarity, and unverified part numbers are never used to invent a link.",
    "Normalized facts are exposed for the linked component without altering raw evidence.",
    "No electrical pass/fail judgments or automatic approval of component identity.",
    "Evidence Graph additions use only user_confirmed_datasheet edges — facts are not silently attached to other components.",
]


def _datasheet_document_node_id(scope: str, content_sha256: str) -> str:
    return f"{scope}:datasheet:{content_sha256}"


def _link_edge_id(scope: str, link_id: str) -> str:
    return f"{scope}:edge:user_confirmed_datasheet:{link_id}"


def _build_graph_additions(
    *,
    scope_id: str,
    component_node_id: str,
    link: DatasheetComponentLink,
    document_id: str,
    filename: str | None,
) -> EvidenceGraph:
    doc_node_id = _datasheet_document_node_id(scope_id, link.content_sha256)
    node = EvidenceNode(
        id=doc_node_id,
        kind="datasheet_document",
        label=filename or document_id,
        attrs={
            "document_id": document_id,
            "content_sha256": link.content_sha256,
            "component_reference": link.component_reference,
            "link_id": link.id,
        },
        provenance="user_confirmed",
    )
    edge = EvidenceEdge(
        id=_link_edge_id(scope_id, link.id),
        source_id=component_node_id,
        target_id=doc_node_id,
        kind="user_confirmed_datasheet",
        provenance="user_confirmed",
    )
    return EvidenceGraph(
        nodes=[node],
        edges=[edge],
        citations=[],
        limitations=list(PHASE4A_LIMITATIONS),
    )


def _facts_for_link(
    facts: list[NormalizedDatasheetFact],
    raw_evidence: list[RawDatasheetEvidence],
    *,
    content_sha256: str,
) -> tuple[list[NormalizedDatasheetFact], list[RawDatasheetEvidence]]:
    """Return facts whose source hash matches, plus only their supporting raw pages."""
    matched = [f for f in facts if f.source_content_sha256 == content_sha256]
    needed_ids = {f.supporting_evidence_id for f in matched}
    raw = [e for e in raw_evidence if e.id in needed_ids]
    return matched, raw


def create_datasheet_component_link(
    request: DatasheetComponentLinkRequest,
) -> DatasheetComponentLinkResponse:
    """Validate and record an explicit datasheet↔component link."""
    limitations = list(PHASE4A_LIMITATIONS)
    sha = request.content_sha256.strip().lower()
    file_id = request.schematic_file_id.strip().lower()
    reference = request.component_reference.strip()
    document_id = request.document_id.strip()

    if not FILE_ID_RE.fullmatch(file_id):
        return DatasheetComponentLinkResponse(
            status="error",
            failure_reason="schematic_file_id must be a 32-hex upload id.",
            limitations=limitations,
        )
    if not reference:
        return DatasheetComponentLinkResponse(
            status="error",
            failure_reason="component_reference is required.",
            limitations=limitations,
        )
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        return DatasheetComponentLinkResponse(
            status="error",
            failure_reason="content_sha256 must be a 64-character lowercase hex digest.",
            limitations=limitations,
        )

    schematic_path = resolve_upload_id(file_id)
    if schematic_path is None:
        return DatasheetComponentLinkResponse(
            status="error",
            failure_reason=(
                "Schematic upload not found for schematic_file_id "
                "(stale analysis scope, deleted, or replaced upload)."
            ),
            limitations=limitations,
        )
    if schematic_path.suffix.lower() != ".kicad_sch":
        return DatasheetComponentLinkResponse(
            status="error",
            failure_reason="Datasheet links require a KiCad schematic (.kicad_sch) upload.",
            limitations=limitations,
        )

    try:
        parsed = parse_kicad_sch(schematic_path.read_bytes())
    except KiCadParseError as exc:
        return DatasheetComponentLinkResponse(
            status="error",
            failure_reason=f"Unable to parse schematic for link validation: {exc}",
            limitations=limitations,
        )

    symbols = parsed["symbols"]
    refs = {s.reference for s in symbols if s.reference}
    if reference not in refs:
        return DatasheetComponentLinkResponse(
            status="error",
            failure_reason=(
                f"Component reference {reference!r} does not exist in the selected schematic."
            ),
            limitations=limitations,
        )

    report = load_ingest_report(sha)
    if report is None or report.source is None:
        return DatasheetComponentLinkResponse(
            status="error",
            failure_reason=(
                "No stored datasheet ingest report for content_sha256. "
                "Ingest the PDF first via /api/datasheets/ingest."
            ),
            limitations=limitations,
        )
    if report.source.content_sha256.lower() != sha:
        return DatasheetComponentLinkResponse(
            status="error",
            failure_reason="Stored datasheet hash does not match content_sha256.",
            limitations=limitations,
        )
    if report.source.document_id != document_id:
        return DatasheetComponentLinkResponse(
            status="error",
            failure_reason=(
                f"document_id mismatch: request has {document_id!r}, "
                f"stored ingest has {report.source.document_id!r}."
            ),
            limitations=limitations,
        )

    link_id = make_link_id(
        schematic_file_id=file_id,
        component_reference=reference,
        content_sha256=sha,
    )
    existing = load_link(link_id)
    component_node_id = resolve_component_node_id(
        symbols, reference, scope_id=file_id
    )
    if component_node_id is None:
        return DatasheetComponentLinkResponse(
            status="error",
            failure_reason=f"Could not resolve Evidence Graph node for {reference!r}.",
            limitations=limitations,
        )

    facts, raw = _facts_for_link(
        report.facts, report.raw_evidence, content_sha256=sha
    )

    if existing is not None:
        graph = _build_graph_additions(
            scope_id=file_id,
            component_node_id=component_node_id,
            link=existing,
            document_id=document_id,
            filename=report.source.filename,
        )
        return DatasheetComponentLinkResponse(
            status="duplicate",
            link=existing,
            facts=facts,
            raw_evidence=raw,
            evidence_graph_additions=graph,
            failure_reason=(
                "An identical user-confirmed link already exists for this "
                "schematic, component, and datasheet hash."
            ),
            limitations=limitations,
        )

    link = DatasheetComponentLink(
        id=link_id,
        schematic_file_id=file_id,
        component_reference=reference,
        document_id=document_id,
        content_sha256=sha,
        provenance="user_confirmed",
        created_at=datetime.now(timezone.utc).isoformat(),
        status="active",
    )
    store_link(link)
    graph = _build_graph_additions(
        scope_id=file_id,
        component_node_id=component_node_id,
        link=link,
        document_id=document_id,
        filename=report.source.filename,
    )
    return DatasheetComponentLinkResponse(
        status="ok",
        link=link,
        facts=facts,
        raw_evidence=raw,
        evidence_graph_additions=graph,
        failure_reason=None,
        limitations=limitations,
    )
