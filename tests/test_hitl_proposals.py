"""HITL Stages 1–2A: hashing, create-only store, expiry, locked transitions."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.hitl.service import (
    ProposalTransitionError,
    ProposalValidationError,
    apply_status_transition,
    compute_content_hash,
    create_proposal,
    is_expired,
    require_aware_utc,
    validate_action_params,
    validate_proposal_timestamps,
    verify_content_hash,
)
from app.hitl.store import (
    ProposalExistsError,
    ProposalIntegrityError,
    ProposalNotFoundError,
    create_proposal_file,
    list_proposals,
    load_proposal,
    normalize_proposal_id,
    proposal_path,
    save_proposal,
    transition_proposal,
)
from app.tools.circuit_mcp import current_placement, reset_sandbox


@pytest.fixture()
def hitl_env(tmp_path, monkeypatch):
    import app.schematics.config as config

    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    return tmp_path


def test_content_hash_stable_under_key_reordering():
    a = compute_content_hash(
        "simulate_unverified_placement",
        {"reference": "R1", "x_mm": 1.0, "y_mm": 2.0},
    )
    b = compute_content_hash(
        "simulate_unverified_placement",
        {"y_mm": 2.0, "reference": "R1", "x_mm": 1.0},
    )
    assert a == b
    assert len(a) == 64


def test_content_hash_changes_when_action_or_params_change():
    base = compute_content_hash(
        "simulate_unverified_placement",
        {"reference": "R1", "x_mm": 1.0, "y_mm": 2.0},
    )
    different_action = compute_content_hash("get_component_status", {})
    different_params = compute_content_hash(
        "simulate_unverified_placement",
        {"reference": "R1", "x_mm": 1.0, "y_mm": 3.0},
    )
    assert base != different_action
    assert base != different_params


def test_create_and_persist_round_trip(hitl_env):
    proposal = create_proposal(
        action="get_component_status",
        params={},
        prompt="Read sandbox status",
    )
    assert proposal.status == "pending"
    assert proposal.executed_at is None
    assert proposal.decided_at is None
    assert proposal.created_at.tzinfo is not None
    assert proposal.expires_at > proposal.created_at
    assert verify_content_hash(proposal)

    path = create_proposal_file(proposal)
    assert path.is_file()
    loaded = load_proposal(proposal.id)
    assert loaded is not None
    assert loaded == proposal
    assert verify_content_hash(loaded)


def test_list_proposals_and_status_filter(hitl_env):
    p1 = create_proposal(action="get_component_status", params={})
    p2 = create_proposal(
        action="simulate_unverified_placement",
        params={"reference": "U1", "x_mm": 0.0, "y_mm": 1.0},
    )
    create_proposal_file(p1)
    create_proposal_file(p2)
    transition_proposal(p2.id, to_status="rejected", decision_note="nope")

    all_items = list_proposals()
    assert {p.id for p in all_items} == {p1.id, p2.id}

    pending = list_proposals(status="pending")
    assert [p.id for p in pending] == [p1.id]

    rejected = list_proposals(status="rejected")
    assert [p.id for p in rejected] == [p2.id]


def test_unknown_proposal_id_returns_none(hitl_env):
    assert load_proposal("0" * 32) is None
    assert load_proposal("../etc/passwd") is None
    assert load_proposal("not-a-valid-id") is None
    assert normalize_proposal_id("../etc/passwd") is None
    assert proposal_path("..%2f..%2fetc") is None


def test_corrupt_stored_json_returns_none(hitl_env):
    proposal = create_proposal(action="get_component_status", params={})
    path = create_proposal_file(proposal)
    path.write_text("{not-json", encoding="utf-8")
    assert load_proposal(proposal.id) is None


def test_invalid_parameters_rejected():
    with pytest.raises(ProposalValidationError):
        validate_action_params("unknown_tool", {})
    with pytest.raises(ProposalValidationError):
        validate_action_params("get_component_status", {"extra": 1})
    with pytest.raises(ProposalValidationError):
        validate_action_params(
            "simulate_unverified_placement",
            {"reference": "R1", "x_mm": 1.0},
        )
    with pytest.raises(ProposalValidationError):
        create_proposal(
            action="simulate_unverified_placement",
            params={"reference": "R1", "x_mm": float("nan"), "y_mm": 0.0},
        )
    with pytest.raises(ProposalValidationError):
        compute_content_hash("get_component_status", {"nested": {1: "bad-key"}})  # type: ignore[dict-item]


def test_non_json_compatible_values_rejected_in_hash():
    with pytest.raises(ProposalValidationError):
        compute_content_hash("get_component_status", {"x": {1, 2, 3}})  # type: ignore[dict-item]
    with pytest.raises(ProposalValidationError):
        compute_content_hash("get_component_status", {"x": b"bytes"})  # type: ignore[dict-item]


def test_create_proposal_does_not_execute_tools_or_mutate_sandbox(hitl_env):
    reset_sandbox()
    before = current_placement()
    proposal = create_proposal(
        action="simulate_unverified_placement",
        params={"reference": "EVIL", "x_mm": 99.0, "y_mm": 99.0},
        prompt="should not run",
    )
    create_proposal_file(proposal)
    transition_proposal(proposal.id, to_status="approved")
    transition_proposal(
        proposal.id,
        to_status="executed",
        execution_result={"note": "record only"},
    )
    assert current_placement() == before
    assert current_placement()["reference"] != "EVIL"


def test_verify_content_hash_detects_tamper(hitl_env):
    proposal = create_proposal(action="get_component_status", params={})
    tampered = proposal.model_copy(
        update={"params": {"sneaky": True}, "content_hash": proposal.content_hash}
    )
    assert verify_content_hash(proposal) is True
    assert verify_content_hash(tampered) is False


def test_proposal_not_approved_or_executed_on_create():
    proposal = create_proposal(action="get_component_status", params={})
    assert proposal.status == "pending"
    assert proposal.decided_at is None
    assert proposal.executed_at is None
    assert proposal.execution_result is None


def test_naive_datetime_rejected():
    with pytest.raises(ProposalValidationError):
        create_proposal(
            action="get_component_status",
            params={},
            now=datetime(2026, 1, 1, 12, 0, 0),  # naive
        )


def test_custom_ttl(hitl_env):
    now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    proposal = create_proposal(
        action="get_component_status",
        params={},
        ttl=timedelta(minutes=30),
        now=now,
    )
    assert proposal.expires_at == now + timedelta(minutes=30)


# --- Stage 2A ---


def test_create_only_refuses_overwrite(hitl_env):
    proposal = create_proposal(action="get_component_status", params={})
    create_proposal_file(proposal)
    twin = proposal.model_copy(update={"prompt": "different"})
    with pytest.raises(ProposalExistsError):
        create_proposal_file(twin)
    with pytest.raises(ProposalExistsError):
        save_proposal(twin)
    loaded = load_proposal(proposal.id)
    assert loaded is not None
    assert loaded.prompt is None


def test_expiry_helper_timezone_and_boundary():
    created = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    proposal = create_proposal(
        action="get_component_status",
        params={},
        ttl=timedelta(hours=1),
        now=created,
    )
    assert is_expired(proposal, now=created) is False
    assert is_expired(proposal, now=proposal.expires_at - timedelta(microseconds=1)) is False
    assert is_expired(proposal, now=proposal.expires_at) is True
    assert is_expired(proposal, now=proposal.expires_at + timedelta(seconds=1)) is True

    # Non-UTC aware input is normalized for comparison.
    eastern = timezone(timedelta(hours=-5))
    at_expiry_eastern = proposal.expires_at.astimezone(eastern)
    assert is_expired(proposal, now=at_expiry_eastern) is True

    with pytest.raises(ProposalValidationError):
        require_aware_utc(datetime(2026, 1, 1), field="now")
    with pytest.raises(ProposalValidationError):
        is_expired(proposal, now=datetime(2026, 1, 1, 13, 0, 0))


def test_load_rejects_naive_or_inconsistent_expiry(hitl_env):
    proposal = create_proposal(action="get_component_status", params={})
    path = create_proposal_file(proposal)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["created_at"] = "2026-01-01T12:00:00"
    data["expires_at"] = "2026-01-02T12:00:00"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert load_proposal(proposal.id) is None

    path.write_text(proposal.model_dump_json(indent=2), encoding="utf-8")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["expires_at"] = "2025-01-01T00:00:00+00:00"  # before created
    path.write_text(json.dumps(data), encoding="utf-8")
    assert load_proposal(proposal.id) is None


def test_transition_rejects_expired_approval(hitl_env):
    created = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    proposal = create_proposal(
        action="get_component_status",
        params={},
        ttl=timedelta(minutes=5),
        now=created,
    )
    create_proposal_file(proposal)
    with pytest.raises(ProposalTransitionError, match="expired"):
        transition_proposal(
            proposal.id,
            to_status="approved",
            now=created + timedelta(minutes=5),
        )
    assert load_proposal(proposal.id).status == "pending"

    # Rejection of an expired pending proposal remains allowed.
    updated = transition_proposal(
        proposal.id,
        to_status="rejected",
        now=created + timedelta(minutes=6),
        decision_note="stale",
    )
    assert updated.status == "rejected"


def test_transition_rejects_tampered_action_params_hash(hitl_env):
    proposal = create_proposal(action="get_component_status", params={})
    path = create_proposal_file(proposal)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["params"] = {"sneaky": True}
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ProposalIntegrityError):
        transition_proposal(proposal.id, to_status="approved")


def test_transition_rejects_invalid_status_edges(hitl_env):
    proposal = create_proposal(action="get_component_status", params={})
    create_proposal_file(proposal)
    with pytest.raises(ProposalTransitionError, match="invalid transition"):
        transition_proposal(proposal.id, to_status="executed")
    transition_proposal(proposal.id, to_status="approved")
    with pytest.raises(ProposalTransitionError, match="invalid transition"):
        transition_proposal(proposal.id, to_status="pending")
    with pytest.raises(ProposalTransitionError, match="invalid transition"):
        transition_proposal(proposal.id, to_status="approved")


def test_transition_missing_proposal(hitl_env):
    with pytest.raises(ProposalNotFoundError):
        transition_proposal("a" * 32, to_status="approved")
    with pytest.raises(ProposalValidationError):
        transition_proposal("../etc/passwd", to_status="approved")


def test_concurrent_same_transition_only_one_succeeds(hitl_env):
    proposal = create_proposal(action="get_component_status", params={})
    create_proposal_file(proposal)

    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        barrier.wait()
        try:
            transition_proposal(proposal.id, to_status="approved")
            with lock:
                outcomes.append("ok")
        except ProposalTransitionError:
            with lock:
                outcomes.append("conflict")
        except Exception as exc:  # pragma: no cover - unexpected
            with lock:
                outcomes.append(f"error:{type(exc).__name__}")

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
        assert not t.is_alive()

    assert outcomes.count("ok") == 1
    assert outcomes.count("conflict") == 1
    assert load_proposal(proposal.id).status == "approved"


def test_atomic_replace_failure_leaves_prior_json_intact(hitl_env, monkeypatch):
    proposal = create_proposal(action="get_component_status", params={})
    path = create_proposal_file(proposal)
    original = path.read_text(encoding="utf-8")

    def boom(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="simulated replace failure"):
        transition_proposal(proposal.id, to_status="approved")

    assert path.read_text(encoding="utf-8") == original
    assert load_proposal(proposal.id).status == "pending"
    # Temp files from the failed write should not become the canonical JSON.
    leftovers = list(path.parent.glob(f"{path.name}.*.tmp"))
    assert leftovers == []


def test_apply_transition_without_persist_does_not_mutate_sandbox():
    reset_sandbox()
    before = current_placement()
    proposal = create_proposal(
        action="simulate_unverified_placement",
        params={"reference": "X9", "x_mm": 1.0, "y_mm": 2.0},
    )
    apply_status_transition(proposal, to_status="approved")
    assert current_placement() == before


def test_validate_timestamps_normalizes_offset():
    created = datetime(2026, 3, 1, 7, 0, 0, tzinfo=timezone(timedelta(hours=-5)))
    proposal = create_proposal(
        action="get_component_status",
        params={},
        now=created,
        ttl=timedelta(hours=2),
    )
    normalized = validate_proposal_timestamps(proposal)
    assert normalized.created_at.utcoffset() == timedelta(0)
    assert normalized.expires_at.utcoffset() == timedelta(0)
