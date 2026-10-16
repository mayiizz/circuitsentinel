"""Fail-closed governed invoke stub for legacy ``/api/actions/*``.

Dashboard and crew executor paths still call ``invoke_governed_tool`` for
sandbox actions. This legacy path always returns ``blocked`` and never calls
MCP or any external policy provider. Authorized sandbox execution uses HITL
``/api/proposals`` instead. ArmorIQ is not used.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_FAIL_CLOSED_MESSAGE = (
    "Legacy /api/actions/* path is permanently fail-closed. "
    "Use Human-in-the-Loop proposals (/api/proposals) for sandbox execution. "
    "This response is not an allow decision."
)


@dataclass
class GovernedActionResult:
    decision: str  # allowed | blocked | error
    action: str
    message: str
    result: Any = None
    status_code: int = 200


def invoke_governed_tool(
    action: str,
    params: dict[str, Any],
    prompt: str,
) -> GovernedActionResult:
    """Refuse all governed tool invokes (fail-closed).

    Does not call MCP, invent an allow decision, or bypass local MCP
    privileged-tool gates. ``params`` and ``prompt`` are accepted for API
    compatibility and ignored.
    """
    _ = params, prompt
    name = (action or "").strip() or "unknown"
    return GovernedActionResult(
        decision="blocked",
        action=name,
        message=_FAIL_CLOSED_MESSAGE,
        result=None,
        status_code=200,
    )
