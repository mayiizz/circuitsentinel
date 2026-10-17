"""Isolated second sandbox MCP endpoint (v2) — JSON-RPC 2.0 over SSE.

Standalone copy of ``circuit_mcp`` for independent testing. Does not replace
the original server on port 8001.

Trust boundary (local):
- ``CIRCUITSENTINEL_MCP_V2_TOKEN`` bearer auth identifies the caller.
- Bearer auth is not an authorization allow for privileged mutations.
- Privileged mutating tools remain listed for discovery but are not executed
  on this endpoint (fail closed). Allowed read tools still run.
"""

from __future__ import annotations

import hmac
import json
import logging
import math
import os
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

load_dotenv()

logger = logging.getLogger("circuitsentinel.mcp.v2")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "circuitsentinel-sandbox-v2"
SERVER_VERSION = "1.0.0"
MCP_TOKEN_ENV = "CIRCUITSENTINEL_MCP_V2_TOKEN"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
# Application-range code: privileged tool blocked at MCP trust boundary.
PRIVILEGED_TOOL_REFUSED = -32010

# Mutating sandbox tools. Advertised in tools/list for discovery, but not
# executed here: bearer auth is not an authorization allow.
PRIVILEGED_TOOLS: frozenset[str] = frozenset({"simulate_unverified_placement"})

PRIVILEGED_TOOL_REFUSAL_MESSAGE = (
    "Privileged sandbox tool cannot be executed on this MCP endpoint. "
    "Bearer authentication identifies the caller but is not an authorization "
    "allow. This server fails closed for privileged mutations."
)

FIXED_TEST_COMPONENT: dict[str, Any] = {
    "label": "test-component",
    "reference": "TP1",
    "value": "sandbox-only",
    "status": "fixed-test-record",
    "sandbox": True,
}

_INITIAL_PLACEMENT: dict[str, Any] = {
    "label": "in-memory-test-record",
    "reference": None,
    "x_mm": None,
    "y_mm": None,
    "verified": False,
    "sandbox": True,
}

_placement: dict[str, Any] = dict(_INITIAL_PLACEMENT)


def reset_sandbox() -> None:
    """Restore the in-memory placement record. Does not touch disk or hardware."""
    _placement.clear()
    _placement.update(_INITIAL_PLACEMENT)


def current_placement() -> dict[str, Any]:
    """Return a copy of the in-memory placement record."""
    return dict(_placement)


def _log_token(value: str, limit: int = 64) -> str:
    cleaned = "".join(ch if ch.isprintable() else "?" for ch in value)
    return cleaned[:limit]


def _finite_number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("must be a finite number")
    if not math.isfinite(value):
        raise ValueError("must be a finite number")
    return float(value)


class EmptyArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlacementArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference: str
    x_mm: float
    y_mm: float

    @field_validator("reference", mode="before")
    @classmethod
    def reference_is_label(cls, value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must be a non-empty string")
        if len(value) > 32 or any(ord(char) < 32 for char in value):
            raise ValueError("must be a short printable reference")
        return value

    @field_validator("x_mm", "y_mm", mode="before")
    @classmethod
    def coordinates_are_finite(cls, value: object) -> float:
        number = _finite_number(value)
        if number < -10_000 or number > 10_000:
            raise ValueError("must be between -10000 and 10000")
        return number


TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_component_status",
        "description": (
            "Return the fixed, labeled test component record. "
            "This sandbox read does not access hardware or files."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "simulate_unverified_placement",
        "description": (
            "Update the in-memory unverified placement record and return its new state. "
            "This does not write files, access hardware, or create fabrication output."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "Test component reference designator, such as R1.",
                },
                "x_mm": {
                    "type": "number",
                    "description": "Sandbox X position in millimeters.",
                },
                "y_mm": {
                    "type": "number",
                    "description": "Sandbox Y position in millimeters.",
                },
            },
            "required": ["reference", "x_mm", "y_mm"],
        },
    },
]


def _validation_messages(exc: ValidationError) -> list[str]:
    messages: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "arguments"
        messages.append(f"{location}: {error['msg']}")
    return messages


def _error(
    message_id: Any,
    code: int,
    message: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": message_id, "error": error}


def _valid_id(value: object) -> bool:
    if isinstance(value, bool) or isinstance(value, str):
        return isinstance(value, str)
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    return False


def _tool_result(message_id: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(payload),
                }
            ]
        },
    }


def _get_component_status(arguments: dict[str, Any]) -> dict[str, Any]:
    EmptyArguments.model_validate(arguments)
    return dict(FIXED_TEST_COMPONENT)


def _simulate_unverified_placement(arguments: dict[str, Any]) -> dict[str, Any]:
    parsed = PlacementArguments.model_validate(arguments)
    _placement["reference"] = parsed.reference
    _placement["x_mm"] = parsed.x_mm
    _placement["y_mm"] = parsed.y_mm
    _placement["verified"] = False
    logger.info("sandbox placement updated reference=%s", _log_token(parsed.reference))
    return current_placement()


_TOOL_HANDLERS = {
    "get_component_status": _get_component_status,
    "simulate_unverified_placement": _simulate_unverified_placement,
}


def is_privileged_tool(name: str) -> bool:
    """True when *name* is a mutating sandbox tool that must not run via MCP HTTP."""
    return name in PRIVILEGED_TOOLS


def _refuse_privileged_tool(message_id: Any, name: str) -> dict[str, Any]:
    """Reject execution without mutating state or claiming an authorization allow."""
    logger.warning(
        "refused privileged tool at mcp trust boundary tool=%s",
        _log_token(name),
    )
    return _error(
        message_id,
        PRIVILEGED_TOOL_REFUSED,
        PRIVILEGED_TOOL_REFUSAL_MESSAGE,
        {
            "tool": name,
            "trust_boundary": "mcp_privileged_tool_gate",
            "authorization_decision": None,
            "note": (
                "This refusal is a local MCP fail-closed gate. "
                "It is not an authorization allow decision."
            ),
        },
    )


def _call_tool(message_id: Any, params: object) -> dict[str, Any]:
    if not isinstance(params, dict):
        return _error(message_id, INVALID_PARAMS, "Invalid params")
    name = params.get("name")
    if not isinstance(name, str) or not name:
        return _error(message_id, INVALID_PARAMS, "Invalid params")
    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict):
        return _error(message_id, INVALID_PARAMS, "Invalid params")
    if is_privileged_tool(name):
        # Fail closed before argument handling so direct bearer callers cannot mutate.
        return _refuse_privileged_tool(message_id, name)
    handler = _TOOL_HANDLERS.get(name)
    if handler is None:
        logger.warning("unknown tool name=%s", _log_token(name))
        return _error(message_id, INVALID_PARAMS, "Unknown tool")
    try:
        result = handler(arguments)
    except ValidationError as exc:
        logger.warning("invalid arguments tool=%s", _log_token(name))
        return _error(
            message_id,
            INVALID_PARAMS,
            "Invalid params",
            {"errors": _validation_messages(exc)},
        )
    except Exception:
        logger.exception("tool failed tool=%s", _log_token(name))
        return _error(message_id, INTERNAL_ERROR, "Internal error")
    logger.info("tool completed tool=%s", _log_token(name))
    return _tool_result(message_id, result)


def is_initialized_notification(request_data: dict[str, Any]) -> bool:
    """True for MCP ``notifications/initialized`` (JSON-RPC notification: no id)."""
    return (
        request_data.get("jsonrpc") == "2.0"
        and request_data.get("method") == "notifications/initialized"
        and "id" not in request_data
    )


def handle_jsonrpc(request_data: dict[str, Any]) -> dict[str, Any]:
    """Dispatch one JSON-RPC request. The caller wraps the result as SSE.

    Notifications (no ``id``) must not be passed here — they have no JSON-RPC reply.
    """
    raw_id = request_data.get("id")
    message_id = raw_id if "id" in request_data and _valid_id(raw_id) else None
    if (
        request_data.get("jsonrpc") != "2.0"
        or "id" not in request_data
        or not _valid_id(raw_id)
        or not isinstance(request_data.get("method"), str)
    ):
        logger.warning("rejected invalid JSON-RPC request")
        return _error(message_id, INVALID_REQUEST, "Invalid Request")

    method = request_data["method"]
    logger.info("jsonrpc method=%s id=%s", _log_token(method), message_id)

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": message_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": SERVER_NAME,
                    "version": SERVER_VERSION,
                },
            },
        }

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": message_id,
            "result": {"tools": TOOLS},
        }

    if method == "tools/call":
        return _call_tool(message_id, request_data.get("params"))

    logger.warning("method not found method=%s", _log_token(method))
    return _error(message_id, METHOD_NOT_FOUND, "Method not found")


def sse_frame(payload: dict[str, Any]) -> str:
    """Wrap one JSON-RPC object in the documented SSE event."""
    return f"event: message\ndata: {json.dumps(payload)}\n\n"


def _sse(payload: dict[str, Any]) -> StreamingResponse:
    frame = sse_frame(payload)

    async def stream() -> Any:
        yield frame

    return StreamingResponse(stream(), media_type="text/event-stream")


app = FastAPI(
    title="CircuitSentinel sandbox MCP v2",
    version=SERVER_VERSION,
    description=(
        "Isolated in-memory hardware-design sandbox (v2). "
        "POST /mcp speaks JSON-RPC 2.0 over Server-Sent Events. "
        "Bearer auth authenticates callers. Privileged mutating tools are listed "
        "but not executed on this endpoint (local fail-closed)."
    ),
)


@app.get("/", response_class=HTMLResponse)
def root() -> str:
    """Show that this process is the sandbox MCP v2 server, not a website root."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>CircuitSentinel sandbox v2</title>
</head>
<body>
  <h1>CircuitSentinel sandbox v2</h1>
  <p>This server is running.</p>
  <p>The MCP endpoint is <code>POST /mcp</code>.</p>
</body>
</html>
"""


def expected_mcp_token() -> str | None:
    """Return the configured bearer token, or None when auth cannot be enforced."""
    token = os.environ.get(MCP_TOKEN_ENV, "").strip()
    return token or None


def _extract_bearer_token(authorization: str | None) -> str | None:
    if authorization is None:
        return None
    scheme, _, credential = authorization.partition(" ")
    if scheme.lower() != "bearer" or not credential or " " in credential.strip():
        return None
    token = credential.strip()
    return token or None


def authorize_mcp_request(request: Request) -> JSONResponse | None:
    """Require a bearer token before any MCP dispatch.

    Does not grant privileged-tool authorization. Returns an HTTP error when
    the request must be rejected, otherwise None. Never logs the token.
    """
    expected = expected_mcp_token()
    if expected is None:
        logger.error("mcp auth unavailable: %s is missing or empty", MCP_TOKEN_ENV)
        return JSONResponse(
            status_code=503,
            content={"detail": "MCP authentication is not configured"},
        )

    provided = _extract_bearer_token(request.headers.get("authorization"))
    # compare_digest requires equal-length strings; mismatched length is invalid.
    if (
        provided is None
        or len(provided) != len(expected)
        or not hmac.compare_digest(provided, expected)
    ):
        logger.warning("rejected mcp request: missing or invalid bearer token")
        return JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return None


@app.post("/mcp", response_model=None)
async def mcp_endpoint(
    request: Request,
) -> StreamingResponse | JSONResponse | Response:
    auth_error = authorize_mcp_request(request)
    if auth_error is not None:
        return auth_error

    try:
        request_data = await request.json()
    except json.JSONDecodeError:
        logger.warning("rejected request: body is not JSON")
        return _sse(_error(None, PARSE_ERROR, "Parse error"))

    if not isinstance(request_data, dict):
        logger.warning("rejected request: JSON-RPC body must be an object")
        return _sse(_error(None, INVALID_REQUEST, "Invalid Request"))

    # JSON-RPC notifications omit ``id`` and must not receive a JSON-RPC reply.
    if is_initialized_notification(request_data):
        logger.info("jsonrpc notification method=notifications/initialized")
        return Response(status_code=202)

    return _sse(handle_jsonrpc(request_data))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8002)
