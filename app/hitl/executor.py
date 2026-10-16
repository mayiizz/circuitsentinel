"""Locked approve-and-execute boundary for HITL proposals.

Approval requests identify a proposal by ID only. Execution always uses the
server-stored, hash-verified action and parameters. Never executes from
request-body parameters. Does not call MCP HTTP.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.hitl.audit import append_audit_event
from app.hitl.models import ActionProposal
from app.hitl.registry import RegistryError, execute_registered_tool, get_registered_tool
from app.hitl.service import (
    ProposalTransitionError,
    ProposalValidationError,
    apply_status_transition,
    verify_content_hash,
)
from app.hitl.store import (
    ProposalIntegrityError,
    ProposalNotFoundError,
    _atomic_replace,
    _parse_stored_proposal,
    _proposal_lock,
    normalize_proposal_id,
    proposal_path,
)


class ExecutionError(RuntimeError):
    """Raised when sandbox execution fails after a successful approval claim."""

    def __init__(self, message: str, *, proposal: ActionProposal):
        super().__init__(message)
        self.proposal = proposal


def approve_and_execute(
    proposal_id: str,
    *,
    decision_note: str | None = None,
    actor: str | None = None,
    now: datetime | None = None,
    correlation_id: str | None = None,
) -> ActionProposal:
    """Approve a pending proposal and execute its stored sandbox action under lock.

    Sequence under flock:
    1. Reload, verify id/hash/status/expiry.
    2. Transition pending → approved (persisted).
    3. Run registry using stored action/params only.
    4. Transition approved → executed | failed.
       If the outcome is ambiguous after claim, mark ``uncertain`` (non-retryable).

    Repeated approval of a non-pending proposal raises ``ProposalTransitionError``
    without re-executing.
    """
    pid = normalize_proposal_id(proposal_id)
    if pid is None:
        raise ProposalValidationError("proposal id must be a 32-hex string")
    path = proposal_path(pid)
    assert path is not None
    current_time = now or datetime.now(timezone.utc)

    with _proposal_lock(pid):
        if not path.is_file():
            raise ProposalNotFoundError(f"proposal {pid} not found")
        try:
            current = _parse_stored_proposal(
                path.read_text(encoding="utf-8"), expected_id=pid
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ProposalIntegrityError("stored proposal is corrupt or invalid") from exc

        if not verify_content_hash(current):
            append_audit_event(
                proposal_id=pid,
                action=current.action,
                content_hash=current.content_hash,
                transition="approve_blocked",
                actor=actor,
                validation_outcome="hash_mismatch",
                correlation_id=correlation_id,
            )
            raise ProposalIntegrityError("content_hash does not match action/params")

        # Refuse silent retry of terminal / already-decided states.
        if current.status in {"executed", "uncertain", "failed", "rejected", "approved"}:
            append_audit_event(
                proposal_id=pid,
                action=current.action,
                content_hash=current.content_hash,
                transition="approve_conflict",
                actor=actor,
                validation_outcome=f"status_{current.status}",
                correlation_id=correlation_id,
            )
            raise ProposalTransitionError(
                f"invalid transition {current.status!r} → 'approved'"
            )

        approved = apply_status_transition(
            current,
            to_status="approved",
            decision_note=decision_note,
            now=current_time,
        )
        _atomic_replace(path, approved.model_dump_json(indent=2))

        append_audit_event(
            proposal_id=pid,
            action=approved.action,
            content_hash=approved.content_hash,
            transition="pending->approved",
            actor=actor,
            validation_outcome="ok",
            correlation_id=correlation_id,
        )

        # Claimed: run tool using ONLY stored fields.
        tool = get_registered_tool(approved.action)
        try:
            result = execute_registered_tool(approved.action, approved.params)
        except RegistryError as exc:
            failed = apply_status_transition(
                approved,
                to_status="failed",
                failure_reason=str(exc),
                now=datetime.now(timezone.utc),
            )
            _atomic_replace(path, failed.model_dump_json(indent=2))
            append_audit_event(
                proposal_id=pid,
                action=failed.action,
                content_hash=failed.content_hash,
                transition="approved->failed",
                actor=actor,
                validation_outcome="registry_error",
                failure_reason=str(exc),
                correlation_id=correlation_id,
                extra={"classification": tool.classification, "effects": tool.effects},
            )
            raise ExecutionError(str(exc), proposal=failed) from exc
        except Exception as exc:
            # Known failure after claim — mark failed, do not leave approved hanging.
            # Ambiguous outcomes (e.g. killed mid-handler) may leave approved on disk;
            # operators must not auto-retry — use uncertain via mark_uncertain_locked.
            failed = apply_status_transition(
                approved,
                to_status="failed",
                failure_reason=f"{type(exc).__name__}: {exc}",
                now=datetime.now(timezone.utc),
            )
            _atomic_replace(path, failed.model_dump_json(indent=2))
            append_audit_event(
                proposal_id=pid,
                action=failed.action,
                content_hash=failed.content_hash,
                transition="approved->failed",
                actor=actor,
                validation_outcome="execution_error",
                failure_reason=failed.failure_reason,
                correlation_id=correlation_id,
                extra={"classification": tool.classification, "effects": tool.effects},
            )
            raise ExecutionError(str(exc), proposal=failed) from exc

        executed = apply_status_transition(
            approved,
            to_status="executed",
            execution_result={
                "sandbox": True,
                "kicad_schematic_modified": False,
                "classification": tool.classification,
                "effects": tool.effects,
                "tool_result": result,
            },
            now=datetime.now(timezone.utc),
        )
        _atomic_replace(path, executed.model_dump_json(indent=2))
        append_audit_event(
            proposal_id=pid,
            action=executed.action,
            content_hash=executed.content_hash,
            transition="approved->executed",
            actor=actor,
            validation_outcome="ok",
            execution_result=executed.execution_result,
            correlation_id=correlation_id,
        )
        return executed


def mark_uncertain(
    proposal_id: str,
    *,
    reason: str,
    actor: str | None = None,
    correlation_id: str | None = None,
) -> ActionProposal:
    """Mark an approved proposal as uncertain (non-retryable). No tool execution."""
    from app.hitl.store import transition_proposal

    updated = transition_proposal(
        proposal_id,
        to_status="uncertain",
        failure_reason=reason,
    )
    append_audit_event(
        proposal_id=updated.id,
        action=updated.action,
        content_hash=updated.content_hash,
        transition="approved->uncertain",
        actor=actor,
        validation_outcome="ok",
        failure_reason=reason,
        correlation_id=correlation_id,
    )
    return updated


def reconcile_interrupted_approval(
    proposal_id: str,
    *,
    reason: str | None = None,
    actor: str | None = None,
    correlation_id: str | None = None,
) -> ActionProposal:
    """Recover a proposal left in ``approved`` after interrupted execution.

    Marks ``approved → uncertain`` under lock. Never re-executes the tool.
    Refuses any other status (including ``pending`` / ``executed``).
    """
    from app.hitl.store import (
        ProposalIntegrityError,
        ProposalNotFoundError,
        _atomic_replace,
        _parse_stored_proposal,
        _proposal_lock,
        normalize_proposal_id,
        proposal_path,
    )

    pid = normalize_proposal_id(proposal_id)
    if pid is None:
        raise ProposalValidationError("proposal id must be a 32-hex string")
    path = proposal_path(pid)
    assert path is not None
    note = (reason or "").strip() or (
        "execution interrupted after approval claim; outcome uncertain — do not retry"
    )

    with _proposal_lock(pid):
        if not path.is_file():
            raise ProposalNotFoundError(f"proposal {pid} not found")
        try:
            current = _parse_stored_proposal(
                path.read_text(encoding="utf-8"), expected_id=pid
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ProposalIntegrityError("stored proposal is corrupt or invalid") from exc

        if not verify_content_hash(current):
            raise ProposalIntegrityError("content_hash does not match action/params")
        if current.status != "approved":
            raise ProposalTransitionError(
                f"reconcile requires status 'approved', found {current.status!r}"
            )

        updated = apply_status_transition(
            current,
            to_status="uncertain",
            failure_reason=note,
            now=datetime.now(timezone.utc),
        )
        _atomic_replace(path, updated.model_dump_json(indent=2))
        append_audit_event(
            proposal_id=updated.id,
            action=updated.action,
            content_hash=updated.content_hash,
            transition="approved->uncertain",
            actor=actor,
            validation_outcome="reconciled_interrupted",
            failure_reason=note,
            correlation_id=correlation_id,
        )
        return updated


def reject_proposal(
    proposal_id: str,
    *,
    decision_note: str | None = None,
    actor: str | None = None,
    now: datetime | None = None,
    correlation_id: str | None = None,
) -> ActionProposal:
    """Reject a pending proposal. Never executes a tool."""
    from app.hitl.store import transition_proposal

    updated = transition_proposal(
        proposal_id,
        to_status="rejected",
        decision_note=decision_note,
        now=now,
    )
    append_audit_event(
        proposal_id=updated.id,
        action=updated.action,
        content_hash=updated.content_hash,
        transition="pending->rejected",
        actor=actor,
        validation_outcome="ok",
        correlation_id=correlation_id,
    )
    return updated
