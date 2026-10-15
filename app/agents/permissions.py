"""Central role-permission registry with deny-by-default behavior.

Unknown roles and unlisted actions are rejected. This registry only decides
which crew role may attempt which crew action. Governed sandbox invokes go
through ``invoke_governed_tool`` (currently fail-closed until HITL).
"""

from __future__ import annotations

from app.agents.roles import ROLES

# Crew-level actions. Not MCP tool names (except where noted for the executor).
ACTION_INSPECT_ANALYSIS = "inspect_analysis"
ACTION_INSPECT_ERC = "inspect_erc"
ACTION_INSPECT_DATASHEET_EVIDENCE = "inspect_datasheet_evidence"
ACTION_PROPOSE_CHANGE = "propose_change"
ACTION_REQUEST_GOVERNED_ACTION = "request_governed_action"

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "analyst": frozenset({ACTION_INSPECT_ANALYSIS, ACTION_INSPECT_ERC}),
    "researcher": frozenset({ACTION_INSPECT_DATASHEET_EVIDENCE}),
    "proposer": frozenset({ACTION_PROPOSE_CHANGE}),
    "executor": frozenset({ACTION_REQUEST_GOVERNED_ACTION}),
}

# Sandbox MCP tools the executor may *request* through governed invocation.
# Permit list is not an allow decision; invoke_governed_tool remains fail-closed.
PERMITTED_SANDBOX_ACTIONS: frozenset[str] = frozenset({"get_component_status"})


def allowed_actions_for(role: str) -> frozenset[str]:
    """Return the allowlisted crew actions for *role*, or empty if unknown."""
    return ROLE_PERMISSIONS.get(role, frozenset())


def is_action_allowed(role: str, action: str) -> bool:
    """Deny by default: unknown roles and unlisted actions are not allowed."""
    if role not in ROLES:
        return False
    return action in ROLE_PERMISSIONS.get(role, frozenset())


def is_sandbox_action_permitted(tool_name: str) -> bool:
    """Whether the executor may request *tool_name* via governed invocation."""
    return tool_name in PERMITTED_SANDBOX_ACTIONS
