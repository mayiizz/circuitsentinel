"""HTTP request/response models for HITL proposal routes."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.hitl.models import ActionProposal, ProposalStatus


class CreateProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(min_length=1, max_length=128)
    params: dict[str, Any] = Field(default_factory=dict)
    prompt: str | None = Field(default=None, max_length=2000)


class DecisionRequest(BaseModel):
    """Approve/reject body: decision note only — never replacement params."""

    model_config = ConfigDict(extra="forbid")

    decision_note: str | None = Field(default=None, max_length=2000)


class ReconcileRequest(BaseModel):
    """Mark an interrupted ``approved`` proposal as ``uncertain`` (never re-executes)."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=2000)


class DemoProposeRequest(BaseModel):
    """Deterministic demo proposal (not an LLM agent)."""

    kind: Literal["read_status", "sandbox_placement"] = "read_status"


class ProposalListResponse(BaseModel):
    proposals: list[ActionProposal]
    count: int


class ProposalErrorBody(BaseModel):
    detail: str
    code: str | None = None
    proposal_id: str | None = None
    status: ProposalStatus | None = None
