"""Append-only HITL audit trail (application-level; not cryptographically protected)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.schematics.config import ensure_upload_dir

DEFAULT_ACTOR = "local-operator"
ACTOR_ENV = "CIRCUITSENTINEL_HITL_ACTOR"


def audit_dir() -> Path:
    path = ensure_upload_dir() / "hitl_audit"
    path.mkdir(parents=True, exist_ok=True)
    return path


def audit_log_path() -> Path:
    return audit_dir() / "events.jsonl"


def resolve_actor(explicit: str | None = None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()[:128]
    env = os.environ.get(ACTOR_ENV, "").strip()
    if env:
        return env[:128]
    return DEFAULT_ACTOR


def append_audit_event(
    *,
    proposal_id: str,
    action: str,
    content_hash: str,
    transition: str,
    actor: str | None = None,
    validation_outcome: str,
    execution_result: Any = None,
    failure_reason: str | None = None,
    correlation_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Append one JSON line. Failures are logged by raising OSError to callers."""
    event: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "proposal_id": proposal_id,
        "action": action,
        "content_hash": content_hash,
        "transition": transition,
        "actor": resolve_actor(actor),
        "validation_outcome": validation_outcome,
        "execution_result": _sanitize_result(execution_result),
        "failure_reason": failure_reason,
        "correlation_id": correlation_id,
    }
    if extra:
        event["extra"] = extra
    line = json.dumps(event, ensure_ascii=True, default=str, separators=(",", ":"))
    path = audit_log_path()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _sanitize_result(value: Any) -> Any:
    """Drop oversized or obviously secret-looking keys from audit payloads."""
    if value is None:
        return None
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                continue
            lowered = key.lower()
            if any(part in lowered for part in ("token", "secret", "password", "api_key")):
                out[key] = "[redacted]"
            else:
                out[key] = item
        return out
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)[:500]
