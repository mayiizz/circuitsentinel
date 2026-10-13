"""FastAPI entrypoint: health check, governed action API, and schematic analysis."""

from dotenv import load_dotenv
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from app.circuit.analyze import run_circuit_analysis
from app.circuit.identity import build_component_inventory
from app.circuit.models import (
    CircuitAnalysisReport,
    CircuitAnalyzeRequest,
    ComponentInventoryItem,
    RailMap,
    RailMapUpdate,
)
from app.circuit.rails import load_rail_map, merge_suggested_rails, store_rail_map
from app.circuit.topology import build_topology
from app.datasheets.checks import (
    EngineeringCheckRequest,
    EngineeringCheckResponse,
    run_recommended_supply_check,
)
from app.datasheets.ingest import ingest_datasheet_pdf
from app.datasheets.link import create_datasheet_component_link
from app.datasheets.models import (
    DatasheetComponentLinkRequest,
    DatasheetComponentLinkResponse,
    DatasheetIngestReport,
)
from app.datasheets.store import store_ingest_report
from app.datasheets.validate import (
    DatasheetUploadValidationError,
    validate_datasheet_upload,
)
from app.agents.assistant_models import AssistantChatRequest, AssistantChatResponse
from app.agents.gauntlet import GauntletReport, run_prompt_injection_gauntlet
from app.agents.langgraph_assistant import run_assistant
from app.hitl.access import NonLoopbackAccessError, require_loopback
from app.hitl.api_models import (
    CreateProposalRequest,
    DecisionRequest,
    DemoProposeRequest,
    ProposalListResponse,
    ReconcileRequest,
)
from app.hitl.audit import resolve_actor
from app.hitl.demo_propose import create_demo_proposal
from app.hitl.executor import (
    ExecutionError,
    approve_and_execute,
    reconcile_interrupted_approval,
    reject_proposal,
)
from app.hitl.models import ActionProposal, ProposalStatus
from app.hitl.service import ProposalTransitionError, ProposalValidationError, create_proposal
from app.hitl.store import (
    ProposalExistsError,
    ProposalIntegrityError,
    ProposalLockUnsupportedError,
    ProposalNotFoundError,
    create_proposal_file,
    list_proposals,
    load_proposal,
    normalize_proposal_id,
)
from app.policy_runtime import GovernedActionResult, invoke_governed_tool
from app.schematics.analyze import analyze_schematic_bytes
from app.schematics.kicad_parser import KiCadParseError, parse_kicad_sch
from app.schematics.models import AnalysisResponse
from app.schematics.netlist import build_netlist_report
from app.schematics.storage import (
    FILE_ID_RE,
    content_type_for_path,
    resolve_preview_path,
    resolve_upload_id,
)
from app.schematics.validate import UploadValidationError

load_dotenv()

app = FastAPI(
    title="CircuitSentinel",
    version="0.1.0",
    description="Hackathon prototype for Flow State 2026. Sandbox only.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8080",
        "http://localhost:8080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ActionResponse(BaseModel):
    decision: str
    action: str
    message: str
    result: object | None = None


class PlacementRequest(BaseModel):
    reference: str = Field(default="TEST-COMPONENT", min_length=1, max_length=32)
    x_mm: float = Field(default=10.0, ge=-10000, le=10000)
    y_mm: float = Field(default=20.0, ge=-10000, le=10000)


@app.get("/health")
def health() -> dict[str, str]:
    """Report that the API process is up."""
    return {"status": "ok", "service": "circuitsentinel"}


@app.get("/")
def root() -> dict[str, str]:
    """API root. The operator UI lives in the Vite frontend (`frontend/`)."""
    return {
        "service": "circuitsentinel",
        "ui": "Run the frontend with: cd frontend && bun install && bun run dev (or npm)",
        "health": "/health",
    }


def _action_response(outcome: GovernedActionResult) -> ActionResponse | JSONResponse:
    """Map governed outcomes to HTTP status. Errors are never reported as 200."""
    body = ActionResponse(
        decision=outcome.decision,
        action=outcome.action,
        message=outcome.message,
        result=outcome.result,
    )
    if outcome.decision == "error":
        return JSONResponse(
            status_code=outcome.status_code or 500,
            content=body.model_dump(),
        )
    return body


@app.post("/api/actions/get_component_status", response_model=None)
def api_get_component_status() -> ActionResponse | JSONResponse:
    """Legacy governed path — permanently fail-closed.

    Privileged/sandbox execution uses ``/api/proposals`` HITL approval instead.
    """
    outcome = invoke_governed_tool(
        action="get_component_status",
        params={},
        prompt="Read the CircuitSentinel sandbox component status.",
    )
    return _action_response(outcome)


@app.post("/api/actions/simulate_unverified_placement", response_model=None)
def api_simulate_unverified_placement(
    body: PlacementRequest = PlacementRequest(),
) -> ActionResponse | JSONResponse:
    """Legacy governed path — permanently fail-closed.

    Use ``POST /api/proposals`` then approve; this route never executes tools.
    """
    outcome = invoke_governed_tool(
        action="simulate_unverified_placement",
        params={
            "reference": body.reference,
            "x_mm": body.x_mm,
            "y_mm": body.y_mm,
        },
        prompt="Attempt an unverified sandbox placement.",
    )
    return _action_response(outcome)


def _proposal_error(
    status_code: int,
    detail: str,
    *,
    code: str | None = None,
    proposal_id: str | None = None,
    status: ProposalStatus | None = None,
) -> JSONResponse:
    body: dict[str, object] = {"detail": detail}
    if code is not None:
        body["code"] = code
    if proposal_id is not None:
        body["proposal_id"] = proposal_id
    if status is not None:
        body["status"] = status
    return JSONResponse(status_code=status_code, content=body)


@app.post("/api/proposals", response_model=None)
def api_create_proposal(
    body: CreateProposalRequest,
) -> ActionProposal | JSONResponse:
    """Create a pending proposal. Never executes a tool."""
    try:
        proposal = create_proposal(
            action=body.action,
            params=body.params,
            prompt=body.prompt,
        )
        create_proposal_file(proposal)
    except ProposalValidationError as exc:
        return _proposal_error(400, str(exc), code="validation_error")
    except ProposalExistsError as exc:
        return _proposal_error(409, str(exc), code="proposal_exists")
    except ProposalIntegrityError as exc:
        return _proposal_error(400, str(exc), code="integrity_error")
    return proposal


@app.get("/api/proposals", response_model=None)
def api_list_proposals(
    status: ProposalStatus | None = None,
) -> ProposalListResponse | JSONResponse:
    """List proposals, optionally filtered by status."""
    items = list_proposals(status=status)
    return ProposalListResponse(proposals=items, count=len(items))


@app.get("/api/proposals/{proposal_id}", response_model=None)
def api_get_proposal(proposal_id: str) -> ActionProposal | JSONResponse:
    """Retrieve one proposal by id."""
    if normalize_proposal_id(proposal_id) is None:
        return _proposal_error(400, "invalid proposal id", code="invalid_id")
    proposal = load_proposal(proposal_id)
    if proposal is None:
        return _proposal_error(404, "proposal not found", code="not_found")
    return proposal


@app.post("/api/proposals/demo", response_model=None)
def api_demo_proposal(
    body: DemoProposeRequest = DemoProposeRequest(),
) -> ActionProposal | JSONResponse:
    """Deterministic demo proposal (labelled; not an LLM agent). No execution."""
    try:
        return create_demo_proposal(body.kind)
    except (ProposalValidationError, ValueError) as exc:
        return _proposal_error(400, str(exc), code="validation_error")
    except ProposalExistsError as exc:
        return _proposal_error(409, str(exc), code="proposal_exists")


@app.post("/api/proposals/{proposal_id}/approve", response_model=None)
def api_approve_proposal(
    proposal_id: str,
    request: Request,
    body: DecisionRequest = DecisionRequest(),
) -> ActionProposal | JSONResponse:
    """Approve by id only, then execute the stored sandbox action under lock.

    Request body must not carry replacement action parameters. Restricted to
    loopback peers until real authentication exists. ``local-operator`` is an
    audit label only — not authentication.
    """
    try:
        require_loopback(request)
    except NonLoopbackAccessError as exc:
        return _proposal_error(403, str(exc), code="loopback_required")
    if normalize_proposal_id(proposal_id) is None:
        return _proposal_error(400, "invalid proposal id", code="invalid_id")
    actor = resolve_actor()
    try:
        return approve_and_execute(
            proposal_id,
            decision_note=body.decision_note,
            actor=actor,
        )
    except ProposalNotFoundError:
        return _proposal_error(404, "proposal not found", code="not_found")
    except ProposalIntegrityError as exc:
        return _proposal_error(409, str(exc), code="integrity_error")
    except ProposalTransitionError as exc:
        code = "expired" if "expired" in str(exc).lower() else "conflict"
        return _proposal_error(409, str(exc), code=code, proposal_id=proposal_id)
    except ProposalLockUnsupportedError as exc:
        return _proposal_error(501, str(exc), code="lock_unsupported")
    except ExecutionError as exc:
        return _proposal_error(
            500,
            str(exc),
            code="execution_failed",
            proposal_id=exc.proposal.id,
            status=exc.proposal.status,
        )
    except ProposalValidationError as exc:
        return _proposal_error(400, str(exc), code="validation_error")


@app.post("/api/proposals/{proposal_id}/reject", response_model=None)
def api_reject_proposal(
    proposal_id: str,
    request: Request,
    body: DecisionRequest = DecisionRequest(),
) -> ActionProposal | JSONResponse:
    """Reject a pending proposal. Never executes. Loopback-restricted."""
    try:
        require_loopback(request)
    except NonLoopbackAccessError as exc:
        return _proposal_error(403, str(exc), code="loopback_required")
    if normalize_proposal_id(proposal_id) is None:
        return _proposal_error(400, "invalid proposal id", code="invalid_id")
    try:
        return reject_proposal(
            proposal_id,
            decision_note=body.decision_note,
            actor=resolve_actor(),
        )
    except ProposalNotFoundError:
        return _proposal_error(404, "proposal not found", code="not_found")
    except ProposalIntegrityError as exc:
        return _proposal_error(409, str(exc), code="integrity_error")
    except ProposalTransitionError as exc:
        return _proposal_error(409, str(exc), code="conflict", proposal_id=proposal_id)
    except ProposalLockUnsupportedError as exc:
        return _proposal_error(501, str(exc), code="lock_unsupported")
    except ProposalValidationError as exc:
        return _proposal_error(400, str(exc), code="validation_error")


@app.post("/api/proposals/{proposal_id}/reconcile", response_model=None)
def api_reconcile_proposal(
    proposal_id: str,
    request: Request,
    body: ReconcileRequest = ReconcileRequest(),
) -> ActionProposal | JSONResponse:
    """Mark interrupted ``approved`` proposals as ``uncertain``. Never re-executes."""
    try:
        require_loopback(request)
    except NonLoopbackAccessError as exc:
        return _proposal_error(403, str(exc), code="loopback_required")
    if normalize_proposal_id(proposal_id) is None:
        return _proposal_error(400, "invalid proposal id", code="invalid_id")
    try:
        return reconcile_interrupted_approval(
            proposal_id,
            reason=body.reason,
            actor=resolve_actor(),
        )
    except ProposalNotFoundError:
        return _proposal_error(404, "proposal not found", code="not_found")
    except ProposalIntegrityError as exc:
        return _proposal_error(409, str(exc), code="integrity_error")
    except ProposalTransitionError as exc:
        return _proposal_error(409, str(exc), code="conflict", proposal_id=proposal_id)
    except ProposalLockUnsupportedError as exc:
        return _proposal_error(501, str(exc), code="lock_unsupported")
    except ProposalValidationError as exc:
        return _proposal_error(400, str(exc), code="validation_error")


@app.post("/api/schematics/analyze", response_model=None)
async def api_analyze_schematic(
    file: UploadFile = File(...),
) -> AnalysisResponse | JSONResponse:
    """Upload and inspect a schematic. Read-only; does not call MCP or governed actions.

    Design-changing actions remain behind the governed `/api/actions/*` routes.
    """
    data = await file.read()
    try:
        result = analyze_schematic_bytes(
            data=data,
            filename=file.filename,
            content_type=file.content_type,
        )
    except UploadValidationError as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content=AnalysisResponse(
                status="error",
                validation_errors=[str(exc)],
                limitations=["Upload rejected before analysis."],
            ).model_dump(),
        )
    return result


@app.post("/api/datasheets/ingest", response_model=None)
async def api_ingest_datasheet(
    file: UploadFile = File(...),
) -> DatasheetIngestReport | JSONResponse:
    """Ingest a PDF datasheet into raw page-text evidence. Read-only.

    Does not match components, run OCR, or alter schematics.
    Successful reports are stored under uploads/datasheets/ keyed by content SHA-256
    so Phase 4A can form explicit user-confirmed component links.
    """
    data = await file.read()
    try:
        basename = validate_datasheet_upload(
            filename=file.filename,
            content_type=file.content_type,
            size_bytes=len(data),
        )
    except DatasheetUploadValidationError as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content=DatasheetIngestReport(
                status="error",
                failure_reason=str(exc),
                limitations=[
                    "Phase 3A extracts raw PDF text only; no OCR for scanned pages.",
                    "No component matching or electrical validation is performed.",
                ],
                claims=[],
            ).model_dump(),
        )
    # Malformed PDFs return status=error in the report body (HTTP 200), not 500.
    report = ingest_datasheet_pdf(data, filename=basename)
    if report.status in {"ok", "partial"}:
        store_ingest_report(report)
    return report


@app.post("/api/datasheets/links", response_model=None)
def api_create_datasheet_link(
    body: DatasheetComponentLinkRequest,
) -> DatasheetComponentLinkResponse | JSONResponse:
    """Create an explicit user-confirmed datasheet↔component link.

    Does not infer matches or issue electrical pass/fail judgments.
    """
    result = create_datasheet_component_link(body)
    if result.status == "error":
        return JSONResponse(status_code=400, content=result.model_dump())
    if result.status == "duplicate":
        return JSONResponse(status_code=409, content=result.model_dump())
    return result


@app.post("/api/checks/recommended_supply", response_model=None)
def api_recommended_supply_check(
    body: EngineeringCheckRequest,
) -> EngineeringCheckResponse | JSONResponse:
    """Compare a user-stated supply rail to recommended_operating datasheet limits.

    Does not infer voltages from nets, use absolute-maximum as operating limits,
    or claim whole-circuit safety.
    """
    result = run_recommended_supply_check(body)
    if result.status == "error":
        return JSONResponse(status_code=400, content=result.model_dump())
    return result


def _topology_for_file(file_id: str):
    path = resolve_upload_id(file_id)
    if path is None:
        return None, None, JSONResponse(
            status_code=404, content={"detail": "Schematic upload not found."}
        )
    try:
        parsed = parse_kicad_sch(path.read_bytes())
    except KiCadParseError as exc:
        return None, None, JSONResponse(
            status_code=400, content={"detail": f"Unable to parse schematic: {exc}"}
        )
    netlist = build_netlist_report(schematic_path=path)
    topology = build_topology(symbols=parsed["symbols"], netlist=netlist)
    return topology, path, None


@app.get("/api/circuit/{file_id}/rails", response_model=None)
def api_get_circuit_rails(file_id: str) -> RailMap | JSONResponse:
    """Return suggested candidate nets merged with operator-confirmed rail map.

    Suggested nets never carry invented voltages — only names and reasons.
    """
    fid = (file_id or "").strip().lower()
    if not FILE_ID_RE.fullmatch(fid):
        return JSONResponse(status_code=400, content={"detail": "Invalid file id."})
    topology, _path, err = _topology_for_file(fid)
    if err is not None:
        return err
    assert topology is not None
    stored = load_rail_map(fid)
    return merge_suggested_rails(topology, stored, fid)


@app.put("/api/circuit/{file_id}/rails", response_model=None)
def api_put_circuit_rails(file_id: str, body: RailMapUpdate) -> RailMap | JSONResponse:
    """Persist operator-confirmed rail voltages (never inferred from net names)."""
    fid = (file_id or "").strip().lower()
    if not FILE_ID_RE.fullmatch(fid):
        return JSONResponse(status_code=400, content={"detail": "Invalid file id."})
    if resolve_upload_id(fid) is None:
        return JSONResponse(status_code=404, content={"detail": "Schematic upload not found."})
    for rail in body.rails:
        if rail.status == "confirmed" and rail.value_v is None:
            return JSONResponse(
                status_code=400,
                content={
                    "detail": (
                        f"Rail {rail.net_name!r} is marked confirmed but has no value_v."
                    )
                },
            )
    rail_map = RailMap(schematic_file_id=fid, rails=body.rails)
    store_rail_map(rail_map)
    topology, _path, err = _topology_for_file(fid)
    if err is not None:
        return rail_map
    assert topology is not None
    return merge_suggested_rails(topology, rail_map, fid)


@app.get("/api/circuit/{file_id}/components", response_model=None)
def api_get_circuit_components(
    file_id: str,
) -> list[ComponentInventoryItem] | JSONResponse:
    """Component inventory with datasheet link status (no auto-matching)."""
    fid = (file_id or "").strip().lower()
    if not FILE_ID_RE.fullmatch(fid):
        return JSONResponse(status_code=400, content={"detail": "Invalid file id."})
    topology, _path, err = _topology_for_file(fid)
    if err is not None:
        return err
    assert topology is not None
    return build_component_inventory(topology, schematic_file_id=fid)


@app.post("/api/circuit/{file_id}/analyze", response_model=None)
def api_circuit_analyze(
    file_id: str,
    body: CircuitAnalyzeRequest | None = None,
) -> CircuitAnalysisReport | JSONResponse:
    """Run whole-circuit electrical compatibility analysis within declared scope.

    Does not invent voltages from net names or claim the circuit is certified safe.
    """
    fid = (file_id or "").strip().lower()
    if not FILE_ID_RE.fullmatch(fid):
        return JSONResponse(status_code=400, content={"detail": "Invalid file id."})
    result = run_circuit_analysis(fid, body)
    if result.assessment == "error":
        return JSONResponse(status_code=400, content=result.model_dump())
    return result


@app.post("/api/assistant/chat", response_model=None)
def api_assistant_chat(
    body: AssistantChatRequest,
) -> AssistantChatResponse | JSONResponse:
    """LangGraph circuit assistant (demo by default). Never approves or executes."""
    try:
        return run_assistant(body)
    except Exception as exc:  # noqa: BLE001 — structured API error
        return JSONResponse(
            status_code=500,
            content={
                "detail": f"Assistant failed: {type(exc).__name__}.",
                "error": type(exc).__name__,
            },
        )


@app.post("/api/agents/gauntlet", response_model=None)
def api_run_prompt_injection_gauntlet() -> GauntletReport | JSONResponse:
    """Run the deterministic Prompt-Injection Gauntlet (local crew + MCP fail-closed).

    Safe public entry point: reuses ``run_prompt_injection_gauntlet`` only.
    Does not expose privileged MCP handlers, invent authorization allows, or
    modify uploaded schematics. Uses local crew_policy and mcp_fail_closed only.
    """
    try:
        return run_prompt_injection_gauntlet()
    except Exception as exc:  # noqa: BLE001 — surface as structured API error
        return JSONResponse(
            status_code=500,
            content={
                "detail": f"Gauntlet failed: {type(exc).__name__}.",
                "error": type(exc).__name__,
            },
        )


@app.get("/api/schematics/files/{file_id}", response_model=None)
def api_get_schematic_file(file_id: str) -> FileResponse | JSONResponse:
    """Serve an uploaded schematic by UUID only. Never accepts filesystem paths."""
    path = resolve_upload_id(file_id)
    if path is None:
        return JSONResponse(status_code=404, content={"detail": "File not found."})
    return FileResponse(
        path,
        media_type=content_type_for_path(path),
        filename=path.name,
    )


@app.get("/api/schematics/files/{file_id}/preview", response_model=None)
def api_get_schematic_preview(file_id: str) -> FileResponse | JSONResponse:
    """Serve a generated SVG preview when one exists for the file id."""
    path = resolve_preview_path(file_id)
    if path is None:
        return JSONResponse(status_code=404, content={"detail": "Preview not found."})
    return FileResponse(
        path,
        media_type="image/svg+xml",
        filename=path.name,
    )
