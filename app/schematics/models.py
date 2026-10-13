"""Structured analysis response models. Honesty buckets are explicit fields."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schematics.evidence.models import EvidenceGraph


class UploadInfo(BaseModel):
    original_filename: str
    stored_as: str
    format: Literal["kicad_sch", "pdf", "image"]
    size_bytes: int


class SymbolFinding(BaseModel):
    reference: str | None = None
    value: str | None = None
    lib_id: str | None = None
    unit: int | None = None
    uuid: str | None = None
    properties: dict[str, str] = Field(default_factory=dict)
    at_x: float | None = None
    at_y: float | None = None
    at_angle: float | None = None


class CoordinateMapping(BaseModel):
    """Describes whether schematic mm coordinates can map onto the preview."""

    reliable: bool = False
    units: str | None = None
    view_min_x: float | None = None
    view_min_y: float | None = None
    view_width: float | None = None
    view_height: float | None = None
    note: str = (
        "Coordinate mapping unavailable; findings show references/coords without a fake highlight."
    )


class ViewerInfo(BaseModel):
    file_id: str
    format: Literal["kicad_sch", "pdf", "image"]
    source_url: str
    preview_url: str | None = None
    render_status: Literal["ready", "unavailable", "error"]
    render_message: str
    page_count: int | None = None
    content_type: str
    coordinate_mapping: CoordinateMapping = Field(default_factory=CoordinateMapping)


class LabelFinding(BaseModel):
    kind: str
    text: str


class ConnectivityHint(BaseModel):
    kind: str
    detail: str


class HierarchyNode(BaseModel):
    name: str
    file: str | None = None
    detail: str | None = None


class ConfirmedFindings(BaseModel):
    symbols: list[SymbolFinding] = Field(default_factory=list)
    labels: list[LabelFinding] = Field(default_factory=list)
    connectivity: list[ConnectivityHint] = Field(default_factory=list)
    hierarchy: list[HierarchyNode] = Field(default_factory=list)
    pdf_text: str | None = None
    pages: int | None = None


class ErcFinding(BaseModel):
    """One KiCad-reported ERC violation. Facts only — not an AI suggestion."""

    rule_id: str
    severity: str
    description: str
    reference: str | None = None
    pin: str | None = None
    x_mm: float | None = None
    y_mm: float | None = None
    item_description: str | None = None
    source: Literal["kicad"] = "kicad"


class ErcReport(BaseModel):
    ran: bool = False
    available: bool = False
    findings: list[ErcFinding] = Field(default_factory=list)
    error_count: int = 0
    warning_count: int = 0
    message_count: int = 0
    failure_reason: str | None = None
    kicad_version: str | None = None
    units: str | None = None
    how_to_enable: str = (
        "Install KiCad and ensure `kicad-cli` is on PATH "
        "(e.g. `kicad-cli sch erc --help`), or set CIRCUITSENTINEL_KICAD_CLI. "
        "CircuitSentinel will not invent ERC faults."
    )


class NetlistPin(BaseModel):
    """Pin declared under a netlist component unit. Not a connectivity claim by itself."""

    number: str
    unit: str | None = None


class NetlistComponent(BaseModel):
    """One component entry from KiCad kicadxml netlist export."""

    reference: str
    value: str | None = None
    lib_id: str | None = None
    footprint: str | None = None
    tstamps: str | None = None
    sheetpath: str | None = None
    pins: list[NetlistPin] = Field(default_factory=list)


class NetlistNode(BaseModel):
    """One component-pin attachment on a net, as exported by KiCad."""

    reference: str
    pin: str
    pintype: str | None = None
    pinfunction: str | None = None


class NetlistNet(BaseModel):
    """One net from KiCad netlist export with explicit vs generated naming."""

    code: str
    name: str
    name_kind: Literal["explicit", "generated", "unconnected"] = "explicit"
    net_class: str | None = None
    nodes: list[NetlistNode] = Field(default_factory=list)


class NetlistReport(BaseModel):
    """Verified schematic connectivity from KiCad netlist export (or honest failure)."""

    ran: bool = False
    available: bool = False
    format: Literal["kicadxml"] | None = None
    components: list[NetlistComponent] = Field(default_factory=list)
    nets: list[NetlistNet] = Field(default_factory=list)
    component_count: int = 0
    net_count: int = 0
    failure_reason: str | None = None
    kicad_tool: str | None = None
    how_to_enable: str = (
        "Install KiCad and ensure `kicad-cli` is on PATH "
        "(e.g. `kicad-cli sch export netlist --help`), or set CIRCUITSENTINEL_KICAD_CLI. "
        "CircuitSentinel will not invent schematic connectivity."
    )
    limitations: list[str] = Field(default_factory=list)


class VisualReport(BaseModel):
    observations: list[str] = Field(default_factory=list)
    disclaimer: str = (
        "Visual metadata only; does not establish electrical connectivity."
    )


class StageResult(BaseModel):
    """Per-pipeline stage outcome. Independent of overall AnalysisResponse.status."""

    status: Literal["complete", "partial", "failed", "unavailable", "skipped"]
    detail: str


class AnalysisStages(BaseModel):
    """Honest stage breakdown so 'partial' overall is explainable."""

    parsing: StageResult = Field(
        default_factory=lambda: StageResult(status="skipped", detail="Not run.")
    )
    rendering: StageResult = Field(
        default_factory=lambda: StageResult(status="skipped", detail="Not run.")
    )
    erc: StageResult = Field(
        default_factory=lambda: StageResult(status="skipped", detail="Not run.")
    )


class FindingInterpretation(BaseModel):
    """Heuristic note tied to a KiCad ERC finding. Never a verified root cause."""

    rule_id: str
    severity: str
    reference: str | None = None
    pin: str | None = None
    kicad_description: str
    explanation: str
    inspection_steps: list[str] = Field(default_factory=list)
    disclaimer: str = (
        "Heuristic guidance only — not a verified root cause. "
        "CircuitSentinel does not modify the schematic or certify electrical safety."
    )


class AnalysisResponse(BaseModel):
    status: Literal["ok", "partial", "error"]
    upload: UploadInfo | None = None
    viewer: ViewerInfo | None = None
    confirmed: ConfirmedFindings = Field(default_factory=ConfirmedFindings)
    erc: ErcReport = Field(default_factory=ErcReport)
    visual: VisualReport = Field(default_factory=VisualReport)
    stages: AnalysisStages = Field(default_factory=AnalysisStages)
    finding_interpretations: list[FindingInterpretation] = Field(default_factory=list)
    netlist: NetlistReport = Field(default_factory=NetlistReport)
    evidence_graph: EvidenceGraph | None = None
    unverified_suggestions: list[str] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
