"""Unit tests for HITL registry execution and uncertain recovery."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.hitl.executor import (
    ExecutionError,
    approve_and_execute,
    mark_uncertain,
    reconcile_interrupted_approval,
    reject_proposal,
)
from app.hitl.service import ProposalTransitionError, create_proposal
from app.hitl.store import create_proposal_file, load_proposal, transition_proposal
from app.tools.circuit_mcp import current_placement, reset_sandbox


@pytest.fixture()
def hitl_env(tmp_path, monkeypatch):
    import app.schematics.config as config

    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    reset_sandbox()
    return tmp_path


def test_approve_and_execute_read_only(hitl_env):
    proposal = create_proposal(action="get_component_status", params={})
    create_proposal_file(proposal)
    result = approve_and_execute(proposal.id, actor="tester")
    assert result.status == "executed"
    assert result.execution_result["sandbox"] is True
    assert result.execution_result["kicad_schematic_modified"] is False


def test_reject_no_mutation(hitl_env):
    before = current_placement()
    proposal = create_proposal(
        action="simulate_unverified_placement",
        params={"reference": "Z1", "x_mm": 1.0, "y_mm": 2.0},
    )
    create_proposal_file(proposal)
    reject_proposal(proposal.id, decision_note="no")
    assert current_placement() == before
    assert load_proposal(proposal.id).status == "rejected"


def test_uncertain_is_non_retryable(hitl_env):
    proposal = create_proposal(action="get_component_status", params={})
    create_proposal_file(proposal)
    transition_proposal(proposal.id, to_status="approved")
    marked = mark_uncertain(proposal.id, reason="simulated ambiguous outcome")
    assert marked.status == "uncertain"
    with pytest.raises(ProposalTransitionError):
        approve_and_execute(proposal.id)
    # Must not silently re-execute.
    assert load_proposal(proposal.id).status == "uncertain"


def test_reconcile_interrupted_approved_marks_uncertain_without_execute(hitl_env):
    before = current_placement()
    proposal = create_proposal(
        action="simulate_unverified_placement",
        params={"reference": "CRASH", "x_mm": 1.0, "y_mm": 2.0},
    )
    create_proposal_file(proposal)
    # Simulate crash after claim: status left at approved, tool never ran.
    transition_proposal(proposal.id, to_status="approved")
    assert load_proposal(proposal.id).status == "approved"

    reconciled = reconcile_interrupted_approval(
        proposal.id,
        reason="simulated process crash after claim",
    )
    assert reconciled.status == "uncertain"
    assert reconciled.failure_reason == "simulated process crash after claim"
    assert current_placement() == before

    with pytest.raises(ProposalTransitionError):
        approve_and_execute(proposal.id)
    with pytest.raises(ProposalTransitionError):
        reconcile_interrupted_approval(proposal.id)
    assert load_proposal(proposal.id).status == "uncertain"


def test_reconcile_rejects_pending_and_executed(hitl_env):
    pending = create_proposal(action="get_component_status", params={})
    create_proposal_file(pending)
    with pytest.raises(ProposalTransitionError):
        reconcile_interrupted_approval(pending.id)

    executed = create_proposal(action="get_component_status", params={})
    create_proposal_file(executed)
    approve_and_execute(executed.id)
    with pytest.raises(ProposalTransitionError):
        reconcile_interrupted_approval(executed.id)


def test_expired_cannot_approve(hitl_env):
    created = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    proposal = create_proposal(
        action="get_component_status",
        params={},
        ttl=timedelta(minutes=1),
        now=created,
    )
    create_proposal_file(proposal)
    with pytest.raises(ProposalTransitionError, match="expired"):
        approve_and_execute(
            proposal.id,
            now=created + timedelta(minutes=2),
        )


def test_execution_error_marks_failed(hitl_env, monkeypatch):
    proposal = create_proposal(action="get_component_status", params={})
    create_proposal_file(proposal)

    def boom(name, params):
        raise RuntimeError("sandbox blew up")

    monkeypatch.setattr("app.hitl.executor.execute_registered_tool", boom)
    with pytest.raises(ExecutionError):
        approve_and_execute(proposal.id)
    loaded = load_proposal(proposal.id)
    assert loaded.status == "failed"
    assert "sandbox blew up" in (loaded.failure_reason or "")
