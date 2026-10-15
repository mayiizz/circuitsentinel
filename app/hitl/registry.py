"""Fixed server-side allowlist for HITL-executable sandbox tools.

Handlers run in-process via ``execute_sandbox_tool``. This is not KiCad editing
and is not reachable through the MCP HTTP privileged gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.hitl.service import ProposalValidationError, validate_action_params
from app.tools.circuit_mcp import execute_sandbox_tool

ToolClass = Literal["read_only", "state_changing_sandbox"]


@dataclass(frozen=True)
class RegisteredTool:
    name: str
    classification: ToolClass
    description: str
    effects: str


REGISTRY: dict[str, RegisteredTool] = {
    "get_component_status": RegisteredTool(
        name="get_component_status",
        classification="read_only",
        description="Return the fixed labeled sandbox component record.",
        effects="No mutation. In-memory sandbox read only.",
    ),
    "simulate_unverified_placement": RegisteredTool(
        name="simulate_unverified_placement",
        classification="state_changing_sandbox",
        description="Update the in-memory unverified placement record.",
        effects=(
            "Mutates process-local sandbox placement only. "
            "Does not modify KiCad schematic files or hardware."
        ),
    ),
}


class RegistryError(ValueError):
    """Unknown tool or validation failure against the fixed registry."""


def get_registered_tool(name: str) -> RegisteredTool:
    tool = REGISTRY.get((name or "").strip())
    if tool is None:
        raise RegistryError(f"unsupported tool {name!r}")
    return tool


def execute_registered_tool(name: str, params: dict[str, Any]) -> dict[str, Any]:
    """Validate params against HITL rules, then run the sandbox handler."""
    tool = get_registered_tool(name)
    try:
        normalized = validate_action_params(tool.name, dict(params or {}))
    except ProposalValidationError as exc:
        raise RegistryError(str(exc)) from exc
    return execute_sandbox_tool(tool.name, normalized)
