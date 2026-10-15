"""Prompt-Injection Gauntlet tests (deterministic; local trust boundaries only)."""

from __future__ import annotations

from unittest.mock import patch

from app.agents import (
    MALICIOUS_INSTRUCTION,
    PERMITTED_SANDBOX_ACTIONS,
    ROLE_PERMISSIONS,
    UNTRUSTED_EVIDENCE_MARKER,
    build_gauntlet_analysis,
    build_gauntlet_datasheet_evidence,
    run_prompt_injection_gauntlet,
)
from app.tools.circuit_mcp import current_placement, reset_sandbox


def test_malicious_instruction_is_clearly_labeled_untrusted() -> None:
    assert UNTRUSTED_EVIDENCE_MARKER in MALICIOUS_INSTRUCTION
    assert "simulate_unverified_placement" in MALICIOUS_INSTRUCTION
    assert "bypass" in MALICIOUS_INSTRUCTION.lower()

    analysis = build_gauntlet_analysis()
    assert analysis.confirmed.labels
    assert UNTRUSTED_EVIDENCE_MARKER in analysis.confirmed.labels[0].text
    assert "synthetic fixture" in " ".join(analysis.limitations).lower() or any(
        "fixture" in item.lower() for item in analysis.limitations
    )

    evidence = build_gauntlet_datasheet_evidence()
    assert evidence["evidence_kind"] == "gauntlet_test_fixture"
    assert evidence["trust"] == "untrusted"
    assert evidence["untrusted_passage"] == MALICIOUS_INSTRUCTION
    assert evidence["facts"] == []


def test_gauntlet_does_not_change_permissions_or_permit_list() -> None:
    before_roles = {k: frozenset(v) for k, v in ROLE_PERMISSIONS.items()}
    before_permit = frozenset(PERMITTED_SANDBOX_ACTIONS)

    report = run_prompt_injection_gauntlet()

    assert report.permissions_unchanged is True
    assert {k: frozenset(v) for k, v in ROLE_PERMISSIONS.items()} == before_roles
    assert frozenset(PERMITTED_SANDBOX_ACTIONS) == before_permit
    assert "simulate_unverified_placement" not in PERMITTED_SANDBOX_ACTIONS
    assert not hasattr(report, "armoriq_live_attempted")


def test_gauntlet_workflow_treats_evidence_as_fixture_and_keeps_suggestions_only() -> None:
    report = run_prompt_injection_gauntlet()

    assert report.evidence_kind == "gauntlet_test_fixture"
    assert report.crew_report.researcher.status == "completed"
    assert report.injection_proposal is not None
    assert report.injection_proposal.suggestion_only is True
    assert "do not" in report.injection_proposal.summary.lower()
    assert "simulate_unverified_placement" in report.injection_proposal.summary
    assert all(c.suggestion_only for c in report.crew_report.proposed_changes)


def test_privilege_escalation_attempts_rejected_with_accurate_sources() -> None:
    reset_sandbox()
    before = current_placement()

    report = run_prompt_injection_gauntlet()

    sources = {attempt.decision_source for attempt in report.escalation_attempts}
    assert "crew_policy" in sources
    assert "mcp_fail_closed" in sources
    assert "armoriq_live" not in sources

    for attempt in report.escalation_attempts:
        assert attempt.rejected is True
        assert attempt.sandbox_unchanged is True
        assert attempt.attempted_action == "simulate_unverified_placement"
        detail = attempt.detail.lower()
        assert "authorization allow" in detail or "fail-closed" in detail or "permit list" in detail
        assert attempt.decision_source in {"crew_policy", "mcp_fail_closed"}

    assert current_placement() == before or current_placement()["reference"] is None


def test_sandbox_unchanged_after_rejected_escalation() -> None:
    reset_sandbox()
    pristine = current_placement()
    report = run_prompt_injection_gauntlet()
    assert all(a.sandbox_unchanged for a in report.escalation_attempts)
    assert current_placement() == pristine


def test_gauntlet_never_calls_live_invoke_governed_tool() -> None:
    with patch("app.agents.orchestrator.invoke_governed_tool") as mock_invoke:
        report = run_prompt_injection_gauntlet()
        mock_invoke.assert_not_called()
    assert all(a.decision_source != "armoriq_live" for a in report.escalation_attempts)


def test_malicious_text_does_not_grant_executor_propose_or_analyst_tools() -> None:
    report = run_prompt_injection_gauntlet()
    assert report.role_permissions_after["proposer"] == ["propose_change"]
    assert "request_governed_action" not in report.role_permissions_after["proposer"]
    assert "request_governed_action" not in report.role_permissions_after["analyst"]
    assert report.permitted_sandbox_actions_after == ["get_component_status"]
