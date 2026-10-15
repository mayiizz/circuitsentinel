"""Simple least-privilege orchestrator for the hardware agent crew.

Validates role permissions, builds honest task results, and routes executor
tool requests exclusively through ``invoke_governed_tool``. Does not invent
analysis or research outcomes when no evidence is supplied.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.agents.models import AgentResult, AgentTask, ProposedChange, RequestedAction
from app.agents.permissions import (
    ACTION_INSPECT_ANALYSIS,
    ACTION_INSPECT_DATASHEET_EVIDENCE,
    ACTION_INSPECT_ERC,
    ACTION_PROPOSE_CHANGE,
    ACTION_REQUEST_GOVERNED_ACTION,
    is_action_allowed,
    is_sandbox_action_permitted,
)
from app.agents.roles import ROLE_DESCRIPTIONS, is_known_role
from app.policy_runtime import GovernedActionResult, invoke_governed_tool

GovernedInvokeFn = Callable[[str, dict[str, Any], str], GovernedActionResult]


def run_agent_task(
    task: AgentTask,
    *,
    invoke_fn: GovernedInvokeFn | None = None,
) -> AgentResult:
    """Validate permissions and run one crew task.

    *invoke_fn* defaults to ``invoke_governed_tool`` (fail-closed until HITL).
    Tests may inject a stub to assert the governed boundary.
    """
    if not is_known_role(task.role):
        return AgentResult(
            role=task.role,
            status="rejected",
            summary=f"Unknown role '{task.role}' is denied by default.",
            error=f"unknown_role:{task.role}",
        )

    if not is_action_allowed(task.role, task.action):
        return AgentResult(
            role=task.role,
            status="rejected",
            summary=(
                f"Role '{task.role}' is not permitted to perform action "
                f"'{task.action}' (deny-by-default)."
            ),
            error=f"unauthorized_action:{task.role}:{task.action}",
        )

    if task.action == ACTION_INSPECT_ANALYSIS:
        return _run_inspect_analysis(task)
    if task.action == ACTION_INSPECT_ERC:
        return _run_inspect_erc(task)
    if task.action == ACTION_INSPECT_DATASHEET_EVIDENCE:
        return _run_inspect_datasheet(task)
    if task.action == ACTION_PROPOSE_CHANGE:
        return _run_propose_change(task)
    if task.action == ACTION_REQUEST_GOVERNED_ACTION:
        return _run_request_governed_action(task, invoke_fn=invoke_fn or invoke_governed_tool)

    # Listed in permissions but not implemented — should not happen if registry stays in sync.
    return AgentResult(
        role=task.role,
        status="error",
        summary=f"Action '{task.action}' has no handler.",
        error=f"unhandled_action:{task.action}",
    )


def _run_inspect_analysis(task: AgentTask) -> AgentResult:
    if task.analysis is None:
        return AgentResult(
            role=task.role,
            status="needs_input",
            summary=(
                "No schematic analysis evidence was supplied. "
                "The analyst did not invent findings."
            ),
            error="missing_analysis",
        )
    evidence = [{"kind": "schematic_analysis", "payload": task.analysis}]
    confirmed = task.analysis.get("confirmed") if isinstance(task.analysis, dict) else None
    symbol_count = None
    if isinstance(confirmed, dict) and isinstance(confirmed.get("symbols"), list):
        symbol_count = len(confirmed["symbols"])
    summary = (
        f"Inspected supplied schematic analysis evidence"
        f"{f' ({symbol_count} symbol finding(s))' if symbol_count is not None else ''}."
    )
    return AgentResult(
        role=task.role,
        status="completed",
        summary=summary,
        evidence=evidence,
    )


def _run_inspect_erc(task: AgentTask) -> AgentResult:
    erc = task.erc
    if erc is None and isinstance(task.analysis, dict):
        erc = task.analysis.get("erc")
    if erc is None:
        return AgentResult(
            role=task.role,
            status="needs_input",
            summary=(
                "No ERC findings were supplied. "
                "The analyst did not invent ERC results."
            ),
            error="missing_erc",
        )
    evidence = [{"kind": "erc_report", "payload": erc}]
    ran = erc.get("ran") if isinstance(erc, dict) else None
    findings = erc.get("findings") if isinstance(erc, dict) else None
    finding_count = len(findings) if isinstance(findings, list) else None
    if ran is False:
        summary = "Inspected supplied ERC report (ERC did not run)."
    elif finding_count is not None:
        summary = f"Inspected supplied ERC report ({finding_count} finding(s))."
    else:
        summary = "Inspected supplied ERC report."
    return AgentResult(
        role=task.role,
        status="completed",
        summary=summary,
        evidence=evidence,
    )


def _run_inspect_datasheet(task: AgentTask) -> AgentResult:
    if task.datasheet_evidence is None:
        return AgentResult(
            role=task.role,
            status="needs_input",
            summary=(
                "No datasheet evidence was supplied. "
                "The researcher does not invent datasheet facts or perform web search."
            ),
            error="missing_datasheet_evidence",
        )
    if isinstance(task.datasheet_evidence, list):
        payload: Any = task.datasheet_evidence
        item_count = len(task.datasheet_evidence)
    else:
        payload = task.datasheet_evidence
        item_count = None
    evidence = [{"kind": "datasheet_evidence", "payload": payload}]
    summary = (
        f"Inspected supplied datasheet evidence"
        f"{f' ({item_count} item(s))' if item_count is not None else ''}."
    )
    return AgentResult(
        role=task.role,
        status="completed",
        summary=summary,
        evidence=evidence,
    )


def _run_propose_change(task: AgentTask) -> AgentResult:
    items: list[ProposedChange] = []
    if task.proposal is not None:
        items.append(task.proposal)
    if task.proposals:
        items.extend(task.proposals)
    if not items:
        return AgentResult(
            role=task.role,
            status="needs_input",
            summary=(
                "No proposal was supplied. "
                "The proposer creates suggestions only when given an explicit proposal."
            ),
            error="missing_proposal",
        )
    # Proposer never executes tools or mutates files. Force suggestion_only.
    recorded = [
        item.model_copy(update={"suggestion_only": True})
        if not item.suggestion_only
        else item
        for item in items
    ]
    count = len(recorded)
    return AgentResult(
        role=task.role,
        status="completed",
        summary=(
            f"Recorded {count} suggested change(s). "
            "None were executed and no uploaded schematic was modified."
        ),
        proposed_changes=recorded,
    )


def _run_request_governed_action(
    task: AgentTask,
    *,
    invoke_fn: GovernedInvokeFn,
) -> AgentResult:
    if task.requested_action is None:
        return AgentResult(
            role=task.role,
            status="needs_input",
            summary="No sandbox action was requested.",
            error="missing_requested_action",
        )

    requested = task.requested_action
    if not is_sandbox_action_permitted(requested.action):
        return AgentResult(
            role=task.role,
            status="rejected",
            summary=(
                f"Sandbox action '{requested.action}' is not on the executor "
                f"permit list. Denied without bypassing fail-closed authorization."
            ),
            requested_actions=[requested],
            error=f"sandbox_action_not_permitted:{requested.action}",
        )

    prompt = requested.prompt.strip() or (
        f"Executor requests permitted sandbox action '{requested.action}'."
    )
    outcome = invoke_fn(requested.action, dict(requested.params), prompt)

    return AgentResult(
        role=task.role,
        status="completed" if outcome.decision in {"allowed", "blocked"} else "error",
        summary=(
            f"Requested '{requested.action}' through governed invocation "
            f"(decision={outcome.decision})."
        ),
        requested_actions=[requested],
        governed_decision=outcome.decision,
        governed_message=outcome.message,
        governed_result=outcome.result,
        error=None if outcome.decision != "error" else outcome.message,
    )


def describe_roles() -> dict[str, str]:
    """Return role → description for documentation and tests."""
    return dict(ROLE_DESCRIPTIONS)


def propose_only(proposal: ProposedChange, *, role: str = "proposer") -> AgentResult:
    """Convenience helper: record a proposal without executing anything."""
    return run_agent_task(
        AgentTask(role=role, action=ACTION_PROPOSE_CHANGE, proposal=proposal)
    )


def request_governed_sandbox_action(
    action: str,
    params: dict[str, Any] | None = None,
    *,
    prompt: str = "",
    invoke_fn: GovernedInvokeFn | None = None,
) -> AgentResult:
    """Convenience helper: executor requests a permitted sandbox tool via governed invoke."""
    return run_agent_task(
        AgentTask(
            role="executor",
            action=ACTION_REQUEST_GOVERNED_ACTION,
            requested_action=RequestedAction(
                action=action,
                params=params or {},
                prompt=prompt,
            ),
        ),
        invoke_fn=invoke_fn,
    )
