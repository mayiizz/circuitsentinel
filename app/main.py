"""FastAPI entrypoint: health check, governed action API, and schematic analysis."""

from dotenv import load_dotenv
from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from app.policy_runtime import GovernedActionResult, invoke_governed_tool
from app.schematics.analyze import analyze_schematic_bytes
from app.schematics.models import AnalysisResponse
from app.schematics.storage import (
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
    """Report that the API process is up. This does not check ArmorIQ."""
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
    """Allowed read-only action via ArmorIQ → circuit MCP."""
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
    """Denied action. ArmorIQ must block this; the UI does not fake the outcome."""
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


@app.post("/api/schematics/analyze", response_model=None)
async def api_analyze_schematic(
    file: UploadFile = File(...),
) -> AnalysisResponse | JSONResponse:
    """Upload and inspect a schematic. Read-only; does not call ArmorIQ or MCP.

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
