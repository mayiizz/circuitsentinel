"""HITL action-proposal models. Proposals are records only — never auto-executed."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ProposalStatus = Literal[
    "pending",
    "approved",
    "rejected",
    "executed",
    "failed",
    "uncertain",
]

# Tool names that may appear on a proposal. Execution is Stage 2+.
SUPPORTED_ACTIONS = frozenset(
    {
        "get_component_status",
        "simulate_unverified_placement",
    }
)


class ActionProposal(BaseModel):
    """Persisted request for a governed sandbox tool, pending human review.

    Creating or loading a proposal never runs an MCP tool. Status starts as
    ``pending``; later stages advance it through approve/reject/execute.
    """

    id: str = Field(
        min_length=32,
        max_length=32,
        pattern=r"^[a-f0-9]{32}$",
        description="32-hex proposal id (filesystem-safe).",
    )
    action: str = Field(
        min_length=1,
        max_length=128,
        description="Sandbox tool name, e.g. get_component_status.",
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Exact JSON-compatible tool arguments (canonicalized for hashing).",
    )
    prompt: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional human-readable intent or explanation.",
    )
    status: ProposalStatus = Field(
        default="pending",
        description="Lifecycle status. New proposals are always pending.",
    )
    content_hash: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
        description="SHA-256 of canonical {action, params}.",
    )
    created_at: datetime = Field(description="Timezone-aware UTC creation time.")
    expires_at: datetime = Field(description="Timezone-aware UTC expiry; past = stale.")
    decided_at: datetime | None = Field(
        default=None,
        description="When approved or rejected (Stage 2+).",
    )
    executed_at: datetime | None = Field(
        default=None,
        description="When execution finished (Stage 2+).",
    )
    decision_note: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional operator note on approve/reject.",
    )
    execution_result: Any | None = Field(
        default=None,
        description="Tool payload after successful execution (Stage 2+).",
    )
    failure_reason: str | None = Field(
        default=None,
        max_length=2000,
        description="Error detail when status is failed (Stage 2+).",
    )
