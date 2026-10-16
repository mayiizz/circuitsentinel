"""HTTP tests for HITL proposal routes and fail-closed legacy actions."""

from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.tools.circuit_mcp import current_placement, reset_sandbox


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import app.schematics.config as config

    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    reset_sandbox()
    return TestClient(app)


def test_create_list_get_proposal(client):
    created = client.post(
        "/api/proposals",
        json={
            "action": "get_component_status",
            "params": {},
            "prompt": "status check",
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "pending"
    assert body["executed_at"] is None
    pid = body["id"]

    listed = client.get("/api/proposals")
    assert listed.status_code == 200
    assert listed.json()["count"] >= 1

    pending = client.get("/api/proposals", params={"status": "pending"})
    assert any(p["id"] == pid for p in pending.json()["proposals"])

    got = client.get(f"/api/proposals/{pid}")
    assert got.status_code == 200
    assert got.json()["id"] == pid


def test_create_does_not_mutate_sandbox(client):
    before = current_placement()
    response = client.post(
        "/api/proposals",
        json={
            "action": "simulate_unverified_placement",
            "params": {"reference": "NOPE", "x_mm": 1.0, "y_mm": 2.0},
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    assert current_placement() == before


def test_approve_executes_stored_params_not_body(client):
    created = client.post(
        "/api/proposals",
        json={
            "action": "simulate_unverified_placement",
            "params": {"reference": "HITL-R1", "x_mm": 3.0, "y_mm": 4.0},
        },
    )
    pid = created.json()["id"]
    # Replacement params on approve must be rejected (extra=forbid).
    poisoned = client.post(
        f"/api/proposals/{pid}/approve",
        json={
            "decision_note": "ok",
            "params": {"reference": "ATTACK", "x_mm": 99.0, "y_mm": 99.0},
        },
    )
    assert poisoned.status_code == 422
    assert current_placement()["reference"] != "ATTACK"

    approved = client.post(
        f"/api/proposals/{pid}/approve",
        json={"decision_note": "ok"},
    )
    assert approved.status_code == 200
    body = approved.json()
    assert body["status"] == "executed"
    assert body["execution_result"]["kicad_schematic_modified"] is False
    assert body["execution_result"]["sandbox"] is True
    assert current_placement()["reference"] == "HITL-R1"


def test_reject_never_executes(client):
    before = current_placement()
    created = client.post(
        "/api/proposals",
        json={
            "action": "simulate_unverified_placement",
            "params": {"reference": "REJ", "x_mm": 1.0, "y_mm": 1.0},
        },
    )
    pid = created.json()["id"]
    rejected = client.post(f"/api/proposals/{pid}/reject", json={"decision_note": "no"})
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert current_placement() == before


def test_repeated_approve_does_not_reexecute(client):
    created = client.post(
        "/api/proposals",
        json={"action": "get_component_status", "params": {}},
    )
    pid = created.json()["id"]
    first = client.post(f"/api/proposals/{pid}/approve", json={})
    assert first.status_code == 200
    assert first.json()["status"] == "executed"
    second = client.post(f"/api/proposals/{pid}/approve", json={})
    assert second.status_code == 409


def test_invalid_and_missing_ids(client):
    # Path-traversal style ids must not load a proposal (400 invalid or 404 missing).
    traversal = client.get("/api/proposals/not-a-valid-id")
    assert traversal.status_code == 400
    assert client.get(f"/api/proposals/{'0' * 32}").status_code == 404
    assert client.post(f"/api/proposals/{'0' * 32}/approve", json={}).status_code == 404


def test_invalid_create_params(client):
    bad = client.post(
        "/api/proposals",
        json={"action": "unknown_tool", "params": {}},
    )
    assert bad.status_code == 400


def test_demo_proposal(client):
    response = client.post("/api/proposals/demo", json={"kind": "read_status"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert "deterministic-demo" in (body.get("prompt") or "")


def test_legacy_actions_remain_fail_closed(client):
    read = client.post("/api/actions/get_component_status")
    assert read.status_code == 200
    assert read.json()["decision"] == "blocked"
    place = client.post(
        "/api/actions/simulate_unverified_placement",
        json={"reference": "X", "x_mm": 1, "y_mm": 2},
    )
    assert place.status_code == 200
    assert place.json()["decision"] == "blocked"
    assert current_placement()["reference"] != "X"


def test_concurrent_approve_only_one_executes(client):
    created = client.post(
        "/api/proposals",
        json={
            "action": "simulate_unverified_placement",
            "params": {"reference": "CONC", "x_mm": 5.0, "y_mm": 6.0},
        },
    )
    pid = created.json()["id"]
    outcomes: list[int] = []
    lock = threading.Lock()
    barrier = threading.Barrier(2)

    def worker() -> None:
        barrier.wait()
        response = client.post(f"/api/proposals/{pid}/approve", json={})
        with lock:
            outcomes.append(response.status_code)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert outcomes.count(200) == 1
    assert outcomes.count(409) == 1
    assert current_placement()["reference"] == "CONC"
    got = client.get(f"/api/proposals/{pid}").json()
    assert got["status"] == "executed"
