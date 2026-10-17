"""Request/response models for the circuit assistant API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AssistantChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4000)
    schematic_file_id: str | None = Field(
        default=None,
        description="Optional 32-hex upload id for circuit context.",
    )
    create_proposal: bool = Field(
        default=False,
        description="When true and a supported action is inferred, create a pending HITL proposal.",
    )
    proposed_action: Literal[
        "none",
        "get_component_status",
        "simulate_unverified_placement",
    ] = "none"
    proposed_params: dict[str, Any] = Field(default_factory=dict)


class AssistantChatResponse(BaseModel):
    mode: Literal["demo", "llm"]
    demo_label: str | None = None
    answer: str
    uncertainty: list[str] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    proposal_id: str | None = None
    proposal_status: str | None = None
    proposal_created: bool = False
    graph_path: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
