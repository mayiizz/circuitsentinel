"""JSON persistence for HITL action proposals under uploads/action_proposals/.

Stage 2A+: create-only inserts, atomic replace, and locked status transitions.
Does not execute MCP tools (see app.hitl.executor). Statuses ``executed`` and
``uncertain`` are terminal — never silently re-run those proposals.

Locking
-------
Per-proposal advisory locks use a stable ``{id}.lock`` sidecar so the lock
survives atomic ``os.replace`` of the JSON file. On POSIX platforms that
provide ``fcntl.flock``, transitions take an exclusive lock for the whole
reload → validate → write sequence.

Platform limitation: ``fcntl`` is not available on typical Windows CPython
builds. ``transition_proposal`` raises ``ProposalLockUnsupportedError`` there
rather than silently running unlocked. Same-process tests on macOS/Linux cover
the flock path; multi-node / NFS lock semantics are out of scope.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from app.hitl.models import ActionProposal, ProposalStatus
from app.hitl.service import (
    ProposalTransitionError,
    ProposalValidationError,
    apply_status_transition,
    validate_proposal_timestamps,
    verify_content_hash,
)
from app.schematics.config import ensure_upload_dir

_PROPOSAL_ID_RE = re.compile(r"^[a-f0-9]{32}$")

try:
    import fcntl
except ImportError:  # pragma: no cover - platform without fcntl
    fcntl = None  # type: ignore[assignment]


class ProposalExistsError(FileExistsError):
    """Raised when create-only persistence finds an existing proposal ID."""


class ProposalNotFoundError(LookupError):
    """Raised when a transition targets a missing proposal."""


class ProposalLockUnsupportedError(RuntimeError):
    """Raised when advisory locking is unavailable on this platform."""


class ProposalIntegrityError(ValueError):
    """Raised when on-disk identity/hash checks fail under lock."""


def proposals_dir() -> Path:
    path = ensure_upload_dir() / "action_proposals"
    path.mkdir(parents=True, exist_ok=True)
    return path


def normalize_proposal_id(proposal_id: str) -> str | None:
    """Return lowercased 32-hex id, or None if invalid / unsafe."""
    pid = (proposal_id or "").strip().lower()
    if not _PROPOSAL_ID_RE.fullmatch(pid):
        return None
    return pid


def proposal_path(proposal_id: str) -> Path | None:
    """Resolve a filesystem path only for a valid 32-hex id. Else None."""
    pid = normalize_proposal_id(proposal_id)
    if pid is None:
        return None
    return proposals_dir() / f"{pid}.json"


def proposal_lock_path(proposal_id: str) -> Path | None:
    """Stable lock sidecar path (survives JSON atomic replace)."""
    pid = normalize_proposal_id(proposal_id)
    if pid is None:
        return None
    return proposals_dir() / f"{pid}.lock"


def _parse_stored_proposal(raw: str, *, expected_id: str | None = None) -> ActionProposal:
    proposal = ActionProposal.model_validate_json(raw)
    proposal = validate_proposal_timestamps(proposal)
    if expected_id is not None and proposal.id != expected_id:
        raise ProposalIntegrityError("stored proposal id does not match file id")
    return proposal


def _atomic_replace(path: Path, payload: str) -> None:
    """Write via a unique temp file then ``os.replace`` into ``path``."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


def create_proposal_file(proposal: ActionProposal) -> Path:
    """Create-only persist. Refuses to overwrite an existing ID. No tool execution.

    Uses ``O_CREAT|O_EXCL`` to reserve the final path, then atomically replaces
    that reservation with the full JSON payload.
    """
    path = proposal_path(proposal.id)
    if path is None:
        raise ProposalValidationError("proposal id must be a 32-hex string")
    proposal = validate_proposal_timestamps(proposal)
    if not verify_content_hash(proposal):
        raise ProposalIntegrityError("content_hash does not match action/params")
    if proposal.id != path.stem.lower():
        raise ProposalIntegrityError("proposal id does not match storage path")

    payload = proposal.model_dump_json(indent=2)
    # Reserve the name exclusively so concurrent creates cannot both succeed.
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(str(path), flags, 0o644)
    except FileExistsError as exc:
        raise ProposalExistsError(
            f"proposal {proposal.id} already exists"
        ) from exc
    try:
        os.close(fd)
        _atomic_replace(path, payload)
    except BaseException:
        # Leave no empty/partial reservation if the write path fails after EXCL.
        if path.exists() and path.stat().st_size == 0:
            try:
                path.unlink()
            except OSError:
                pass
        raise
    return path


def save_proposal(proposal: ActionProposal) -> Path:
    """Create-only alias used by Stage 1 call sites. Does not overwrite."""
    return create_proposal_file(proposal)


def load_proposal(proposal_id: str) -> ActionProposal | None:
    """Load by id. Returns None for invalid id, missing file, or corrupt/invalid data."""
    path = proposal_path(proposal_id)
    if path is None or not path.is_file():
        return None
    pid = path.stem.lower()
    try:
        return _parse_stored_proposal(path.read_text(encoding="utf-8"), expected_id=pid)
    except (OSError, ValueError, json.JSONDecodeError, ProposalIntegrityError):
        return None


def list_proposals(
    *,
    status: ProposalStatus | None = None,
) -> list[ActionProposal]:
    """List stored proposals, optionally filtered by status. Skips corrupt files."""
    results: list[ActionProposal] = []
    for path in sorted(proposals_dir().glob("*.json")):
        stem = path.stem.lower()
        if not _PROPOSAL_ID_RE.fullmatch(stem):
            continue
        try:
            proposal = _parse_stored_proposal(
                path.read_text(encoding="utf-8"), expected_id=stem
            )
        except (OSError, ValueError, json.JSONDecodeError, ProposalIntegrityError):
            continue
        if status is not None and proposal.status != status:
            continue
        results.append(proposal)
    return results


@contextmanager
def _proposal_lock(proposal_id: str) -> Iterator[None]:
    """Exclusive advisory lock on the stable ``{id}.lock`` sidecar."""
    if fcntl is None:
        raise ProposalLockUnsupportedError(
            "proposal transitions require POSIX fcntl.flock; "
            "this platform does not provide it"
        )
    lock_path = proposal_lock_path(proposal_id)
    if lock_path is None:
        raise ProposalValidationError("proposal id must be a 32-hex string")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # Create/open the lock file without truncating; keep it around across JSON replaces.
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def transition_proposal(
    proposal_id: str,
    *,
    to_status: ProposalStatus,
    decision_note: str | None = None,
    execution_result: Any = None,
    failure_reason: str | None = None,
    now: datetime | None = None,
) -> ActionProposal:
    """Atomically apply an allowed status transition under an advisory lock.

    Reloads the current record under the lock, checks id / content hash / expiry /
    status, then writes via temp + ``os.replace``. Never executes MCP tools.
    Does not retry on ambiguous failure.
    """
    pid = normalize_proposal_id(proposal_id)
    if pid is None:
        raise ProposalValidationError("proposal id must be a 32-hex string")
    path = proposal_path(pid)
    assert path is not None

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

        updated = apply_status_transition(
            current,
            to_status=to_status,
            decision_note=decision_note,
            execution_result=execution_result,
            failure_reason=failure_reason,
            now=now,
        )
        _atomic_replace(path, updated.model_dump_json(indent=2))
        return updated
