"""Orchestrate validation, storage, and honest format-specific analysis."""

from __future__ import annotations

from pathlib import Path

from app.schematics.erc import build_erc_report
from app.schematics.evidence.build import build_evidence_graph
from app.schematics.image_pipeline import ImageInspectError, inspect_image
from app.schematics.interpret import interpret_erc_findings
from app.schematics.kicad_parser import KiCadParseError, parse_kicad_sch
from app.schematics.models import (
    AnalysisResponse,
    AnalysisStages,
    ConfirmedFindings,
    ErcReport,
    NetlistReport,
    StageResult,
    UploadInfo,
    ViewerInfo,
    VisualReport,
)
from app.schematics.netlist import build_netlist_report
from app.schematics.pdf_inspect import PdfInspectError, inspect_pdf
from app.schematics.render import build_viewer_info
from app.schematics.storage import store_upload
from app.schematics.validate import validate_upload


def analyze_schematic_bytes(
    *,
    data: bytes,
    filename: str | None,
    content_type: str | None,
) -> AnalysisResponse:
    """Validate, store, and analyze an uploaded schematic. Never mutates the file."""
    validated = validate_upload(
        filename=filename,
        content_type=content_type,
        size_bytes=len(data),
    )

    stored_path = store_upload(data, validated.extension)
    upload = UploadInfo(
        original_filename=validated.original_basename,
        stored_as=stored_path.name,
        format=validated.format,  # type: ignore[arg-type]
        size_bytes=len(data),
    )

    if validated.format == "kicad_sch":
        erc = build_erc_report(schematic_path=stored_path)
        netlist = build_netlist_report(schematic_path=stored_path)
        return _analyze_kicad(
            data, upload=upload, stored_path=stored_path, erc=erc, netlist=netlist
        )

    # ERC / netlist are KiCad-only; do not imply a pass for PDF/image uploads.
    erc = ErcReport(
        ran=False,
        available=False,
        findings=[],
        failure_reason="ERC applies only to KiCad schematic (.kicad_sch) files.",
    )
    netlist = NetlistReport(
        ran=False,
        available=False,
        failure_reason="Netlist export applies only to KiCad schematic (.kicad_sch) files.",
    )
    if validated.format == "pdf":
        return _analyze_pdf(
            data, upload=upload, stored_path=stored_path, erc=erc, netlist=netlist
        )
    return _analyze_image(
        data, upload=upload, stored_path=stored_path, erc=erc, netlist=netlist
    )


def _rendering_stage(viewer: ViewerInfo) -> StageResult:
    if viewer.render_status == "ready":
        mapping = viewer.coordinate_mapping
        detail = viewer.render_message
        if viewer.format == "kicad_sch":
            detail += (
                " Coordinate mapping reliable."
                if mapping.reliable
                else f" Coordinate mapping unavailable ({mapping.note})"
            )
        return StageResult(status="complete", detail=detail)
    if viewer.render_status == "error":
        return StageResult(status="failed", detail=viewer.render_message)
    return StageResult(status="unavailable", detail=viewer.render_message)


def _erc_stage(erc: ErcReport, *, applicable: bool) -> StageResult:
    if not applicable:
        return StageResult(
            status="skipped",
            detail=erc.failure_reason or "ERC is not applicable for this upload format.",
        )
    if erc.ran:
        return StageResult(
            status="complete",
            detail=(
                f"KiCad ERC finished with {erc.error_count} error(s), "
                f"{erc.warning_count} warning(s), {len(erc.findings)} finding(s)."
            ),
        )
    if erc.available is False:
        return StageResult(
            status="unavailable",
            detail=erc.failure_reason or "kicad-cli ERC is not available.",
        )
    return StageResult(
        status="failed",
        detail=erc.failure_reason or "ERC did not complete.",
    )


def _analyze_kicad(
    data: bytes,
    *,
    upload: UploadInfo,
    stored_path: Path,
    erc,
    netlist: NetlistReport,
) -> AnalysisResponse:
    limitations = [
        "Parser connectivity entries are structural hints, not verified electrical nets.",
        "Uploaded schematics are never modified.",
    ]
    if netlist.ran:
        limitations.append(
            f"KiCad netlist export produced {netlist.net_count} net(s) and "
            f"{netlist.component_count} component(s) (kicadxml)."
        )
        limitations.extend(netlist.limitations)
    else:
        limitations.append(
            netlist.failure_reason
            or "Netlist export did not run; absence of nets is not an open-circuit claim."
        )
    viewer = build_viewer_info(stored_path=stored_path, format_name="kicad_sch")
    if viewer.render_status != "ready":
        limitations.append(viewer.render_message)

    rendering = _rendering_stage(viewer)
    erc_stage = _erc_stage(erc, applicable=True)

    try:
        parsed = parse_kicad_sch(data)
    except KiCadParseError as exc:
        return AnalysisResponse(
            status="error",
            upload=upload,
            viewer=viewer,
            erc=erc,
            stages=AnalysisStages(
                parsing=StageResult(status="failed", detail=str(exc)),
                rendering=rendering,
                erc=erc_stage,
            ),
            netlist=netlist,
            validation_errors=[str(exc)],
            limitations=limitations,
        )

    confirmed = ConfirmedFindings(
        symbols=parsed["symbols"],
        labels=parsed["labels"],
        connectivity=parsed["connectivity"],
        hierarchy=parsed["hierarchy"],
    )
    symbol_count = len(confirmed.symbols)
    label_count = len(confirmed.labels)
    if symbol_count or label_count:
        parsing = StageResult(
            status="complete",
            detail=f"Parsed {symbol_count} placed symbol(s) and {label_count} label(s).",
        )
    else:
        parsing = StageResult(
            status="partial",
            detail="Schematic parsed but no placed symbols or labels were found.",
        )

    # Overall status: ok only when parse found content AND ERC is clean or did not run.
    # ERC findings intentionally keep the overall status "partial" — stages still report
    # ERC as complete when the CLI finished successfully.
    status = "ok" if symbol_count or label_count else "partial"
    interpretations = []
    if erc.ran:
        limitations.append(
            "ERC findings below are KiCad-reported facts, not AI suggestions. "
            "CircuitSentinel does not auto-fix the schematic or claim it is safe."
        )
        interpretations = interpret_erc_findings(erc)
        if erc.error_count or erc.warning_count:
            status = "partial"
            limitations.append(
                "Overall status is partial because KiCad ERC reported errors and/or warnings; "
                "parsing and ERC stages themselves completed."
            )
    else:
        limitations.append(
            erc.failure_reason
            or "Electrical-rule checks did not run; absence of findings is not a pass."
        )

    evidence_graph = build_evidence_graph(
        confirmed,
        erc,
        scope_id=upload.stored_as.rsplit(".", 1)[0],
        netlist=netlist,
    )

    return AnalysisResponse(
        status=status,
        upload=upload,
        viewer=viewer,
        confirmed=confirmed,
        erc=erc,
        stages=AnalysisStages(parsing=parsing, rendering=rendering, erc=erc_stage),
        finding_interpretations=interpretations,
        netlist=netlist,
        evidence_graph=evidence_graph,
        unverified_suggestions=[],
        limitations=limitations,
    )


def _analyze_pdf(
    data: bytes,
    *,
    upload: UploadInfo,
    stored_path: Path,
    erc,
    netlist: NetlistReport,
) -> AnalysisResponse:
    limitations = [
        "PDF text extraction does not prove net connectivity.",
        "Uploaded schematics are never modified.",
        "Electrical-rule checks did not run (PDF is not a KiCad project).",
    ]
    erc_stage = _erc_stage(erc, applicable=False)
    try:
        inspected = inspect_pdf(data)
    except PdfInspectError as exc:
        viewer = build_viewer_info(stored_path=stored_path, format_name="pdf")
        return AnalysisResponse(
            status="error",
            upload=upload,
            viewer=viewer,
            erc=erc,
            stages=AnalysisStages(
                parsing=StageResult(status="failed", detail=str(exc)),
                rendering=_rendering_stage(viewer),
                erc=erc_stage,
            ),
            netlist=netlist,
            validation_errors=[str(exc)],
            limitations=limitations,
        )

    viewer = build_viewer_info(
        stored_path=stored_path,
        format_name="pdf",
        page_count=inspected["pages"],
    )
    confirmed = ConfirmedFindings(
        pdf_text=inspected["pdf_text"],
        pages=inspected["pages"],
    )
    visual = VisualReport(observations=[])
    status: str = "ok"

    if inspected["likely_scanned"]:
        status = "partial"
        parsing = StageResult(
            status="partial",
            detail="PDF has no extractable text (treated as scanned/image-like).",
        )
        visual.observations.extend(
            [
                f"PDF has {inspected['pages']} page(s) with no extractable text.",
                "Treated as a scanned/image-like PDF; image-analysis pipeline prepared.",
                "Visual inspection does not establish electrical connectivity.",
            ]
        )
        limitations.append(
            "Scanned PDFs need a future vision/OCR pass; none was claimed here."
        )
    elif not inspected["pdf_text"]:
        status = "partial"
        parsing = StageResult(
            status="partial",
            detail="Little or no extractable text on PDF pages.",
        )
        visual.observations.append("Little or no extractable text on PDF pages.")
    else:
        parsing = StageResult(
            status="complete",
            detail=(
                f"Extracted text from {inspected['nonempty_text_pages']} of "
                f"{inspected['pages']} page(s)."
            ),
        )
        visual.observations.append(
            f"Extracted text from {inspected['nonempty_text_pages']} of "
            f"{inspected['pages']} page(s)."
        )

    evidence_graph = build_evidence_graph(
        confirmed,
        erc,
        scope_id=upload.stored_as.rsplit(".", 1)[0],
        netlist=netlist,
    )

    return AnalysisResponse(
        status=status,  # type: ignore[arg-type]
        upload=upload,
        viewer=viewer,
        confirmed=confirmed,
        erc=erc,
        visual=visual,
        stages=AnalysisStages(
            parsing=parsing,
            rendering=_rendering_stage(viewer),
            erc=erc_stage,
        ),
        netlist=netlist,
        evidence_graph=evidence_graph,
        unverified_suggestions=[],
        limitations=limitations,
    )


def _analyze_image(
    data: bytes,
    *,
    upload: UploadInfo,
    stored_path: Path,
    erc,
    netlist: NetlistReport,
) -> AnalysisResponse:
    limitations = [
        "Image pixels are not used to infer nets, shorts, or opens.",
        "Uploaded schematics are never modified.",
        "Electrical-rule checks did not run (image is not a KiCad project).",
    ]
    viewer = build_viewer_info(stored_path=stored_path, format_name="image")
    erc_stage = _erc_stage(erc, applicable=False)
    try:
        inspected = inspect_image(data)
    except ImageInspectError as exc:
        return AnalysisResponse(
            status="error",
            upload=upload,
            viewer=viewer,
            erc=erc,
            stages=AnalysisStages(
                parsing=StageResult(status="failed", detail=str(exc)),
                rendering=_rendering_stage(viewer),
                erc=erc_stage,
            ),
            netlist=netlist,
            validation_errors=[str(exc)],
            limitations=limitations,
        )

    confirmed = ConfirmedFindings()
    evidence_graph = build_evidence_graph(
        confirmed,
        erc,
        scope_id=upload.stored_as.rsplit(".", 1)[0],
        netlist=netlist,
    )

    return AnalysisResponse(
        status="partial",
        upload=upload,
        viewer=viewer,
        confirmed=confirmed,
        erc=erc,
        visual=VisualReport(observations=inspected["observations"]),
        stages=AnalysisStages(
            parsing=StageResult(
                status="partial",
                detail="Image metadata inspected; no schematic symbols are parsed from pixels.",
            ),
            rendering=_rendering_stage(viewer),
            erc=erc_stage,
        ),
        netlist=netlist,
        evidence_graph=evidence_graph,
        unverified_suggestions=[],
        limitations=limitations,
    )


def analyze_stored_file(path: Path, *, original_filename: str, content_type: str) -> AnalysisResponse:
    """Helper for tests that already wrote a file."""
    data = path.read_bytes()
    return analyze_schematic_bytes(
        data=data,
        filename=original_filename,
        content_type=content_type,
    )
