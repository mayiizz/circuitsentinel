"""Unit tests for the least-privilege hardware agent crew (milestone 1)."""

from __future__ import annotations

from typing import Any

import pytest

from app.agents import (
    ACTION_INSPECT_ANALYSIS,
    ACTION_INSPECT_DATASHEET_EVIDENCE,
    ACTION_INSPECT_ERC,
    ACTION_PROPOSE_CHANGE,
    ACTION_REQUEST_GOVERNED_ACTION,
    PERMITTED_SANDBOX_ACTIONS,
    ROLE_DESCRIPTIONS,
    ROLE_PERMISSIONS,
    ROLES,
    AgentTask,
    ProposedChange,
    RequestedAction,
    allowed_actions_for,
    describe_roles,
    is_action_allowed,
    is_known_role,
    is_sandbox_action_permitted,
    propose_only,
    request_governed_sandbox_action,
    run_agent_task,
)
from app.agents.roles import AgentRole
from app.policy_runtime import GovernedActionResult
from app.schematics.analyze import analyze_schematic_bytes
from app.schematics.validate import UploadValidationError


# ---------------------------------------------------------------------------
# Role definitions
# ---------------------------------------------------------------------------


def test_all_four_roles_are_defined() -> None:
    expected: set[AgentRole] = {"analyst", "researcher", "proposer", "executor"}
    assert ROLES == frozenset(expected)
    assert set(ROLE_DESCRIPTIONS) == expected
    assert set(ROLE_PERMISSIONS) == expected
    assert set(describe_roles()) == expected
    for role in expected:
        assert is_known_role(role)
        assert ROLE_DESCRIPTIONS[role].strip()
        assert allowed_actions_for(role)


def test_analyst_may_inspect_analysis_and_erc() -> None:
    assert is_action_allowed("analyst", ACTION_INSPECT_ANALYSIS)
    assert is_action_allowed("analyst", ACTION_INSPECT_ERC)
    assert not is_action_allowed("analyst", ACTION_PROPOSE_CHANGE)
    assert not is_action_allowed("analyst", ACTION_REQUEST_GOVERNED_ACTION)


def test_researcher_may_inspect_datasheet_evidence_only() -> None:
    assert is_action_allowed("researcher", ACTION_INSPECT_DATASHEET_EVIDENCE)
    assert not is_action_allowed("researcher", ACTION_INSPECT_ANALYSIS)
    assert not is_action_allowed("researcher", ACTION_REQUEST_GOVERNED_ACTION)


def test_proposer_may_propose_but_not_execute() -> None:
    assert is_action_allowed("proposer", ACTION_PROPOSE_CHANGE)
    assert not is_action_allowed("proposer", ACTION_REQUEST_GOVERNED_ACTION)
    assert not is_action_allowed("proposer", ACTION_INSPECT_ANALYSIS)


def test_executor_may_request_governed_action_only() -> None:
    assert is_action_allowed("executor", ACTION_REQUEST_GOVERNED_ACTION)
    assert not is_action_allowed("executor", ACTION_PROPOSE_CHANGE)
    assert not is_action_allowed("executor", ACTION_INSPECT_ANALYSIS)
    assert PERMITTED_SANDBOX_ACTIONS == frozenset({"get_component_status"})
    assert is_sandbox_action_permitted("get_component_status")
    assert not is_sandbox_action_permitted("simulate_unverified_placement")


# ---------------------------------------------------------------------------
# Deny-by-default
# ---------------------------------------------------------------------------


def test_unknown_role_is_rejected() -> None:
    result = run_agent_task(
        AgentTask(role="hacker", action=ACTION_INSPECT_ANALYSIS, analysis={"confirmed": {}})
    )
    assert result.status == "rejected"
    assert result.error == "unknown_role:hacker"
    assert "denied" in result.summary.lower() or "unknown" in result.summary.lower()
    assert result.governed_decision is None


def test_unauthorized_action_is_rejected() -> None:
    result = run_agent_task(
        AgentTask(role="analyst", action=ACTION_REQUEST_GOVERNED_ACTION)
    )
    assert result.status == "rejected"
    assert result.error == "unauthorized_action:analyst:request_governed_action"
    assert result.governed_decision is None


def test_unlisted_action_string_is_rejected_for_known_role() -> None:
    result = run_agent_task(AgentTask(role="researcher", action="web_search"))
    assert result.status == "rejected"
    assert "unauthorized_action" in (result.error or "")


# ---------------------------------------------------------------------------
# Honest stubs — no invented analysis/research
# ---------------------------------------------------------------------------


def test_analyst_without_analysis_does_not_invent_findings() -> None:
    result = run_agent_task(
        AgentTask(role="analyst", action=ACTION_INSPECT_ANALYSIS)
    )
    assert result.status == "needs_input"
    assert result.error == "missing_analysis"
    assert result.evidence == []
    assert "did not invent" in result.summary.lower()


def test_analyst_inspects_supplied_analysis() -> None:
    analysis = {
        "confirmed": {"symbols": [{"reference": "U1"}], "labels": [], "connectivity": [], "hierarchy": []},
    }
    result = run_agent_task(
        AgentTask(role="analyst", action=ACTION_INSPECT_ANALYSIS, analysis=analysis)
    )
    assert result.status == "completed"
    assert len(result.evidence) == 1
    assert result.evidence[0]["kind"] == "schematic_analysis"
    assert "1 symbol" in result.summary


def test_analyst_inspects_supplied_erc() -> None:
    erc = {"ran": True, "findings": [{"severity": "unconnected_pin"}], "available": True}
    result = run_agent_task(
        AgentTask(role="analyst", action=ACTION_INSPECT_ERC, erc=erc)
    )
    assert result.status == "completed"
    assert result.evidence[0]["kind"] == "erc_report"
    assert "1 finding" in result.summary


def test_researcher_without_evidence_does_not_invent_datasheet() -> None:
    result = run_agent_task(
        AgentTask(role="researcher", action=ACTION_INSPECT_DATASHEET_EVIDENCE)
    )
    assert result.status == "needs_input"
    assert result.error == "missing_datasheet_evidence"
    assert "web search" in result.summary.lower() or "does not invent" in result.summary.lower()


# ---------------------------------------------------------------------------
# Proposer cannot execute tools
# ---------------------------------------------------------------------------


def test_proposer_records_proposal_without_executing() -> None:
    proposal = ProposedChange(
        summary="Add decoupling capacitor near U1",
        details="Suggestion only.",
        target_reference="U1",
    )
    calls: list[tuple[Any, ...]] = []

    def fake_invoke(action: str, params: dict[str, Any], prompt: str) -> GovernedActionResult:
        calls.append((action, params, prompt))
        return GovernedActionResult(decision="allowed", action=action, message="should not run")

    # Direct propose path
    result = propose_only(proposal)
    assert result.status == "completed"
    assert result.proposed_changes == [proposal]
    assert result.requested_actions == []
    assert result.governed_decision is None

    # Even if someone tries to smuggle a tool request on a propose task, proposer
    # action does not call invoke_fn (handler ignores requested_action).
    result2 = run_agent_task(
        AgentTask(
            role="proposer",
            action=ACTION_PROPOSE_CHANGE,
            proposal=proposal,
            requested_action=RequestedAction(action="get_component_status"),
        ),
        invoke_fn=fake_invoke,
    )
    assert result2.status == "completed"
    assert calls == []
    assert result2.governed_decision is None


def test_proposer_cannot_use_request_governed_action() -> None:
    result = run_agent_task(
        AgentTask(
            role="proposer",
            action=ACTION_REQUEST_GOVERNED_ACTION,
            requested_action=RequestedAction(action="get_component_status"),
        )
    )
    assert result.status == "rejected"
    assert "unauthorized_action" in (result.error or "")


# ---------------------------------------------------------------------------
# Executor → governed invocation boundary
# ---------------------------------------------------------------------------


def test_executor_tool_request_goes_through_governed_invocation() -> None:
    calls: list[dict[str, Any]] = []

    def fake_invoke(action: str, params: dict[str, Any], prompt: str) -> GovernedActionResult:
        calls.append({"action": action, "params": params, "prompt": prompt})
        return GovernedActionResult(
            decision="allowed",
            action=action,
            message="Governed invoke allowed this action (test stub).",
            result={"label": "test-component", "sandbox": True},
            status_code=200,
        )

    result = request_governed_sandbox_action(
        "get_component_status",
        {},
        prompt="Read sandbox component status.",
        invoke_fn=fake_invoke,
    )
    assert len(calls) == 1
    assert calls[0]["action"] == "get_component_status"
    assert result.status == "completed"
    assert result.governed_decision == "allowed"
    assert result.governed_result == {"label": "test-component", "sandbox": True}
    assert result.requested_actions[0].action == "get_component_status"


def test_executor_does_not_invent_authorization_decision_locally() -> None:
    """Blocked outcome must come from invoke_fn, not a local fake policy label."""

    def fake_invoke(action: str, params: dict[str, Any], prompt: str) -> GovernedActionResult:
        return GovernedActionResult(
            decision="blocked",
            action=action,
            message="Authorization unavailable: fail-closed stub.",
            result=None,
        )

    # get_component_status is permitted at crew layer; decision still from invoke_fn.
    result = run_agent_task(
        AgentTask(
            role="executor",
            action=ACTION_REQUEST_GOVERNED_ACTION,
            requested_action=RequestedAction(action="get_component_status"),
        ),
        invoke_fn=fake_invoke,
    )
    assert result.governed_decision == "blocked"
    assert "authorization" in (result.governed_message or "").lower()


def test_executor_rejects_non_permitted_sandbox_action_without_invoke() -> None:
    calls: list[str] = []

    def fake_invoke(action: str, params: dict[str, Any], prompt: str) -> GovernedActionResult:
        calls.append(action)
        return GovernedActionResult(decision="allowed", action=action, message="no")

    result = run_agent_task(
        AgentTask(
            role="executor",
            action=ACTION_REQUEST_GOVERNED_ACTION,
            requested_action=RequestedAction(
                action="simulate_unverified_placement",
                params={"reference": "R1", "x_mm": 1.0, "y_mm": 2.0},
            ),
        ),
        invoke_fn=fake_invoke,
    )
    assert result.status == "rejected"
    assert "sandbox_action_not_permitted" in (result.error or "")
    assert calls == []
    assert result.governed_decision is None


def test_executor_default_invoke_fn_is_policy_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without an injected stub, orchestrator must call invoke_governed_tool."""
    seen: list[str] = []

    def stub(action: str, params: dict[str, Any], prompt: str) -> GovernedActionResult:
        seen.append(action)
        return GovernedActionResult(
            decision="allowed",
            action=action,
            message="ok",
            result={"ok": True},
        )

    monkeypatch.setattr("app.agents.orchestrator.invoke_governed_tool", stub)
    result = run_agent_task(
        AgentTask(
            role="executor",
            action=ACTION_REQUEST_GOVERNED_ACTION,
            requested_action=RequestedAction(action="get_component_status"),
        )
    )
    assert seen == ["get_component_status"]
    assert result.governed_decision == "allowed"


# ---------------------------------------------------------------------------
# Existing analysis / policy behavior unchanged
# ---------------------------------------------------------------------------


def test_existing_schematic_analysis_still_rejects_bad_upload() -> None:
    with pytest.raises(UploadValidationError):
        analyze_schematic_bytes(
            data=b"not-a-schematic",
            filename="evil.exe",
            content_type="application/octet-stream",
        )


def test_policy_runtime_invoke_governed_tool_still_exported() -> None:
    from app.policy_runtime import GovernedActionResult as GAR
    from app.policy_runtime import invoke_governed_tool

    assert callable(invoke_governed_tool)
    sample = GAR(decision="allowed", action="get_component_status", message="x")
    assert sample.decision == "allowed"
    # Real stub is fail-closed.
    outcome = invoke_governed_tool("get_component_status", {}, "test")
    assert outcome.decision == "blocked"


def test_deny_by_default_helper() -> None:
    assert not is_action_allowed("unknown", ACTION_INSPECT_ANALYSIS)
    assert not is_action_allowed("analyst", "delete_board")
    assert allowed_actions_for("ghost") == frozenset()
