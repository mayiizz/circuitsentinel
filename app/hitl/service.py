"""HITL proposal creation, hashing, expiry, and transition rules (no tool execution)."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.hitl.models import SUPPORTED_ACTIONS, ActionProposal, ProposalStatus

DEFAULT_TTL = timedelta(hours=24)

# Pure status machine. Tool execution lives in app.hitl.executor (not here).
# ``uncertain`` is terminal and non-retryable (ambiguous post-claim outcome).
ALLOWED_TRANSITIONS: frozenset[tuple[ProposalStatus, ProposalStatus]] = frozenset(
    {
        ("pending", "approved"),
        ("pending", "rejected"),
        ("approved", "executed"),
        ("approved", "failed"),
        ("approved", "uncertain"),
    }
)


class ProposalValidationError(ValueError):
    """Raised when action/params/prompt cannot form a valid proposal."""


class ProposalTransitionError(ValueError):
    """Raised when a status transition is not allowed, expired, or integrity-failed."""


def require_aware_utc(value: datetime, *, field: str) -> datetime:
    """Require a timezone-aware datetime and normalize to UTC."""
    if not isinstance(value, datetime):
        raise ProposalValidationError(f"{field} must be a datetime")
    if value.tzinfo is None:
        raise ProposalValidationError(f"{field} must be timezone-aware UTC")
    return value.astimezone(timezone.utc)


def is_expired(proposal: ActionProposal, *, now: datetime | None = None) -> bool:
    """True when ``now >= expires_at`` (UTC). Exact equality is expired."""
    current = require_aware_utc(now or datetime.now(timezone.utc), field="now")
    expires = require_aware_utc(proposal.expires_at, field="expires_at")
    return current >= expires


def validate_proposal_timestamps(proposal: ActionProposal) -> ActionProposal:
    """Normalize UTC timestamps; reject naive or inconsistent expiry metadata."""
    created = require_aware_utc(proposal.created_at, field="created_at")
    expires = require_aware_utc(proposal.expires_at, field="expires_at")
    if expires < created:
        raise ProposalValidationError("expires_at must be >= created_at")

    decided = proposal.decided_at
    if decided is not None:
        decided = require_aware_utc(decided, field="decided_at")

    executed = proposal.executed_at
    if executed is not None:
        executed = require_aware_utc(executed, field="executed_at")

    return proposal.model_copy(
        update={
            "created_at": created,
            "expires_at": expires,
            "decided_at": decided,
            "executed_at": executed,
        }
    )


def _assert_json_compatible(value: Any, *, path: str = "params") -> None:
    """Reject non-JSON-compatible values (no silent coercion of sets, bytes, etc.)."""
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, int) and not isinstance(value, bool):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ProposalValidationError(f"{path}: floats must be finite")
        return
    if isinstance(value, str):
        return
    if isinstance(value, list):
        for i, item in enumerate(value):
            _assert_json_compatible(item, path=f"{path}[{i}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ProposalValidationError(f"{path}: object keys must be strings")
            _assert_json_compatible(item, path=f"{path}.{key}")
        return
    raise ProposalValidationError(
        f"{path}: unsupported type {type(value).__name__} (JSON-compatible values only)"
    )


def canonical_action_payload(action: str, params: dict[str, Any]) -> str:
    """Deterministic JSON string of exactly ``action`` and ``params`` (sorted keys)."""
    if not isinstance(action, str) or not action.strip():
        raise ProposalValidationError("action must be a non-empty string")
    if not isinstance(params, dict):
        raise ProposalValidationError("params must be an object")
    _assert_json_compatible(params)
    payload = {"action": action.strip(), "params": params}
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def compute_content_hash(action: str, params: dict[str, Any]) -> str:
    """SHA-256 hex digest over the canonical action+params JSON."""
    body = canonical_action_payload(action, params)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def verify_content_hash(proposal: ActionProposal) -> bool:
    """Return True when stored ``content_hash`` matches recomputed action+params."""
    expected = compute_content_hash(proposal.action, proposal.params)
    return hmac.compare_digest(proposal.content_hash, expected)


def validate_action_params(action: str, params: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize params for a supported sandbox tool. No execution."""
    name = (action or "").strip()
    if name not in SUPPORTED_ACTIONS:
        raise ProposalValidationError(
            f"unsupported action {name!r}; allowed: {sorted(SUPPORTED_ACTIONS)}"
        )
    if not isinstance(params, dict):
        raise ProposalValidationError("params must be an object")
    _assert_json_compatible(params)

    if name == "get_component_status":
        if params:
            raise ProposalValidationError(
                "get_component_status accepts no parameters (empty object only)"
            )
        return {}

    allowed = {"reference", "x_mm", "y_mm"}
    extra = set(params) - allowed
    if extra:
        raise ProposalValidationError(
            f"simulate_unverified_placement unknown params: {sorted(extra)}"
        )
    missing = allowed - set(params)
    if missing:
        raise ProposalValidationError(
            f"simulate_unverified_placement missing params: {sorted(missing)}"
        )

    reference = params["reference"]
    if not isinstance(reference, str) or not reference.strip():
        raise ProposalValidationError("reference must be a non-empty string")
    if len(reference) > 32 or any(ord(ch) < 32 for ch in reference):
        raise ProposalValidationError("reference must be a short printable string")

    def _coord(key: str) -> float:
        raw = params[key]
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ProposalValidationError(f"{key} must be a finite number")
        number = float(raw)
        if not math.isfinite(number):
            raise ProposalValidationError(f"{key} must be a finite number")
        if number < -10_000 or number > 10_000:
            raise ProposalValidationError(f"{key} must be between -10000 and 10000")
        return number

    return {
        "reference": reference.strip(),
        "x_mm": _coord("x_mm"),
        "y_mm": _coord("y_mm"),
    }


def create_proposal(
    *,
    action: str,
    params: dict[str, Any] | None = None,
    prompt: str | None = None,
    ttl: timedelta = DEFAULT_TTL,
    now: datetime | None = None,
) -> ActionProposal:
    """Build a pending proposal with content hash. Does not persist or execute."""
    if ttl <= timedelta(0):
        raise ProposalValidationError("ttl must be positive")
    created = require_aware_utc(now or datetime.now(timezone.utc), field="now")

    normalized = validate_action_params(action, dict(params or {}))
    content_hash = compute_content_hash(action.strip(), normalized)
    if prompt is not None and not isinstance(prompt, str):
        raise ProposalValidationError("prompt must be a string or null")
    prompt_value = prompt.strip() if isinstance(prompt, str) and prompt.strip() else None

    return ActionProposal(
        id=uuid.uuid4().hex,
        action=action.strip(),
        params=normalized,
        prompt=prompt_value,
        status="pending",
        content_hash=content_hash,
        created_at=created,
        expires_at=created + ttl,
        decided_at=None,
        executed_at=None,
        decision_note=None,
        execution_result=None,
        failure_reason=None,
    )


def apply_status_transition(
    proposal: ActionProposal,
    *,
    to_status: ProposalStatus,
    decision_note: str | None = None,
    execution_result: Any = None,
    failure_reason: str | None = None,
    now: datetime | None = None,
) -> ActionProposal:
    """Return an updated proposal for an allowed transition. Does not persist or run tools.

    Expiry: ``pending → approved`` and ``approved → executed`` are refused when expired.
    ``pending → rejected`` remains allowed so stale proposals can be closed.
    """
    proposal = validate_proposal_timestamps(proposal)
    if not verify_content_hash(proposal):
        raise ProposalTransitionError("content_hash does not match action/params")

    current = require_aware_utc(now or datetime.now(timezone.utc), field="now")
    edge = (proposal.status, to_status)
    if edge not in ALLOWED_TRANSITIONS:
        raise ProposalTransitionError(
            f"invalid transition {proposal.status!r} → {to_status!r}"
        )

    expired = is_expired(proposal, now=current)
    if expired and edge in {("pending", "approved"), ("approved", "executed")}:
        raise ProposalTransitionError("proposal is expired")

    updates: dict[str, Any] = {"status": to_status}

    if to_status in {"approved", "rejected"}:
        updates["decided_at"] = current
        if decision_note is not None:
            if not isinstance(decision_note, str):
                raise ProposalTransitionError("decision_note must be a string or null")
            updates["decision_note"] = decision_note.strip() or None
        if to_status == "rejected":
            updates["execution_result"] = None
            updates["executed_at"] = None
            updates["failure_reason"] = None

    if to_status == "executed":
        updates["executed_at"] = current
        updates["execution_result"] = execution_result
        updates["failure_reason"] = None

    if to_status == "failed":
        updates["executed_at"] = current
        if failure_reason is not None and not isinstance(failure_reason, str):
            raise ProposalTransitionError("failure_reason must be a string or null")
        updates["failure_reason"] = (
            failure_reason.strip() if isinstance(failure_reason, str) else failure_reason
        ) or "failed"
        if execution_result is not None:
            updates["execution_result"] = execution_result

    if to_status == "uncertain":
        # Terminal non-retryable recovery: execution may have started; do not re-run.
        updates["executed_at"] = current
        if failure_reason is not None and not isinstance(failure_reason, str):
            raise ProposalTransitionError("failure_reason must be a string or null")
        updates["failure_reason"] = (
            (failure_reason.strip() if isinstance(failure_reason, str) else failure_reason)
            or "execution outcome uncertain; do not retry"
        )
        if execution_result is not None:
            updates["execution_result"] = execution_result

    return proposal.model_copy(update=updates)
