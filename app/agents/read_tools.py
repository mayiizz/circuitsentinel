"""Allowlisted read-only helpers for the assistant graph.

Never imports MCP ``_TOOL_HANDLERS`` or HITL ``execute_registered_tool``.
State-changing sandbox tools are intentionally absent.
"""

from __future__ import annotations

from typing import Any

from app.tools.circuit_mcp import current_placement

# Tools the assistant graph may invoke directly (read-only only).
ASSISTANT_READ_TOOLS: frozenset[str] = frozenset({"get_component_status"})


class ReadToolError(ValueError):
    """Unknown or disallowed read tool."""


def call_read_tool(name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run a single allowlisted read-only tool. Rejects everything else."""
    tool = (name or "").strip()
    if tool not in ASSISTANT_READ_TOOLS:
        raise ReadToolError(
            f"tool {tool!r} is not an allowlisted read-only assistant tool"
        )
    if params:
        raise ReadToolError(f"{tool} accepts no parameters")
    if tool == "get_component_status":
        # Fixed labeled sandbox record — same source as MCP read path, without
        # privileged handlers or HITL execution.
        from app.tools.circuit_mcp import FIXED_TEST_COMPONENT

        return dict(FIXED_TEST_COMPONENT)
    raise ReadToolError(f"unhandled read tool {tool!r}")


def sandbox_snapshot() -> dict[str, Any]:
    """Non-mutating copy of the in-memory placement record for explanations."""
    return current_placement()
