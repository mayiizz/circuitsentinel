"""Deterministic demo proposal creation (not an LLM / LangGraph agent).

LangGraph orchestration is deferred until langgraph and a configured model are
available. Agents must not call privileged handlers directly; they may only
create proposals that still require human approval via ``/api/proposals``.
"""

from __future__ import annotations

from typing import Literal

from app.hitl.models import ActionProposal
from app.hitl.service import create_proposal
from app.hitl.store import create_proposal_file

DemoKind = Literal["read_status", "sandbox_placement"]

DEMO_PROMPT_PREFIX = "[deterministic-demo] Not an autonomous LLM agent. "


def create_demo_proposal(kind: DemoKind = "read_status") -> ActionProposal:
    """Create and persist a labelled demo proposal. Does not execute tools."""
    if kind == "read_status":
        proposal = create_proposal(
            action="get_component_status",
            params={},
            prompt=DEMO_PROMPT_PREFIX + "Request sandbox component status.",
        )
    elif kind == "sandbox_placement":
        proposal = create_proposal(
            action="simulate_unverified_placement",
            params={"reference": "DEMO-R1", "x_mm": 12.0, "y_mm": 24.0},
            prompt=(
                DEMO_PROMPT_PREFIX
                + "Request in-memory sandbox placement (not a KiCad edit)."
            ),
        )
    else:
        raise ValueError(f"unknown demo kind {kind!r}")
    create_proposal_file(proposal)
    return proposal
