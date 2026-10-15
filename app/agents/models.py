"""Pydantic models for agent tasks and structured results."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

AgentResultStatus = Literal[
    "completed",
    "rejected",
    "needs_input",
    "error",
]


class ProposedChange(BaseModel):
    """A suggested design change. Never applied automatically to uploaded files."""

    summary: str = Field(min_length=1, description="Short description of the suggestion.")
    details: str | None = Field(
        default=None,
        description="Optional elaboration. Not an instruction to mutate schematics.",
    )
    target_reference: str | None = Field(
        default=None,
        description="Optional component reference this suggestion concerns.",
    )
    supporting_evidence_ids: list[str] = Field(
        default_factory=list,
        description="Ids of evidence items that ground this suggestion.",
    )
    suggestion_only: bool = Field(
        default=True,
        description="True when this is a suggestion only and must not be auto-executed.",
    )


class RequestedAction(BaseModel):
    """A sandbox tool request to be sent through governed invocation."""

    action: str = Field(min_length=1, description="MCP tool name, e.g. get_component_status.")
    params: dict[str, Any] = Field(default_factory=dict)
    prompt: str = Field(
        default="",
        description="Human-readable intent for governed invocation (HITL later).",
    )


class AgentTask(BaseModel):
    """One unit of work for a single crew role."""

    role: str = Field(description="Crew role name: analyst, researcher, proposer, or executor.")
    action: str = Field(description="Crew action the role is asked to perform.")
    goal: str | None = Field(default=None, description="Optional operator goal text.")
    # Analyst inputs — pass-through evidence only; never invented by the orchestrator.
    analysis: dict[str, Any] | None = Field(
        default=None,
        description="Existing schematic analysis payload (e.g. AnalysisResponse.model_dump()).",
    )
    erc: dict[str, Any] | None = Field(
        default=None,
        description="Existing ERC report payload when inspecting ERC findings.",
    )
    # Researcher input — existing datasheet evidence only.
    datasheet_evidence: dict[str, Any] | list[Any] | None = Field(
        default=None,
        description="Already-ingested datasheet evidence; no web search is performed.",
    )
    # Proposer input.
    proposal: ProposedChange | None = Field(
        default=None,
        description="Suggested change to record; not executed.",
    )
    proposals: list[ProposedChange] | None = Field(
        default=None,
        description="Optional batch of suggested changes; not executed.",
    )
    # Executor input.
    requested_action: RequestedAction | None = Field(
        default=None,
        description="Sandbox tool request for governed invocation.",
    )


class AgentResult(BaseModel):
    """Structured outcome of an agent task. Honest about missing evidence."""

    role: str
    status: AgentResultStatus
    summary: str
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    proposed_changes: list[ProposedChange] = Field(default_factory=list)
    requested_actions: list[RequestedAction] = Field(default_factory=list)
    governed_decision: str | None = Field(
        default=None,
        description=(
            "Decision from invoke_governed_tool (allowed|blocked|error). "
            "Currently always blocked (fail-closed) until HITL authorization."
        ),
    )
    governed_message: str | None = Field(
        default=None,
        description="Message returned by governed invocation, when applicable.",
    )
    governed_result: Any = Field(
        default=None,
        description="Sandbox tool payload from governed invocation, when applicable.",
    )
    error: str | None = None


class CrewReport(BaseModel):
    """Structured multi-role report from a deterministic crew workflow."""

    status: Literal["ok", "partial", "needs_input", "error"]
    analyst: AgentResult
    researcher: AgentResult
    proposer: AgentResult
    findings: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    proposed_changes: list[ProposedChange] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    error: str | None = None
