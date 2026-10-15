"""Least-privilege agent roles for the hardware agent crew.

Roles describe capability boundaries only. They do not perform schematic
analysis, datasheet research, or policy authorization by themselves.
"""

from __future__ import annotations

from typing import Literal

AgentRole = Literal["analyst", "researcher", "proposer", "executor"]

ROLES: frozenset[str] = frozenset({"analyst", "researcher", "proposer", "executor"})

ROLE_DESCRIPTIONS: dict[str, str] = {
    "analyst": (
        "May inspect schematic analysis results and ERC findings. "
        "Does not invent findings when no analysis evidence is supplied."
    ),
    "researcher": (
        "May work with component datasheet evidence already present in the system. "
        "Does not invent web-search or datasheet tools that do not exist."
    ),
    "proposer": (
        "May create suggested changes. "
        "Cannot execute tools, modify uploaded files, or produce fabrication output."
    ),
    "executor": (
        "May request only explicitly permitted sandbox actions through the "
        "existing governed invocation flow (invoke_governed_tool)."
    ),
}


def is_known_role(role: str) -> bool:
    """Return True when *role* is one of the four defined crew roles."""
    return role in ROLES
