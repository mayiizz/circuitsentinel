"""Loopback guardrails for unauthenticated HITL decision routes."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.hitl.access import (
    NonLoopbackAccessError,
    client_host,
    is_loopback_request,
    require_loopback,
)
from app.main import app
from app.tools.circuit_mcp import reset_sandbox


def _request(host: str | None):
    client = None if host is None else SimpleNamespace(host=host)
    return SimpleNamespace(client=client)


def test_loopback_hosts_allowed():
    for host in ("127.0.0.1", "::1", "localhost", "testclient", "TESTCLIENT"):
        req = _request(host)
        assert is_loopback_request(req) is True
        require_loopback(req)


def test_non_loopback_hosts_denied():
    for host in ("203.0.113.10", "10.0.0.5", "192.168.1.2"):
        req = _request(host)
        assert is_loopback_request(req) is False
        with pytest.raises(NonLoopbackAccessError):
            require_loopback(req)
    with pytest.raises(NonLoopbackAccessError):
        require_loopback(_request(None))


def test_forwarded_headers_are_not_consulted():
    """Peer host alone matters; spoofed X-Forwarded-For must not grant access."""
    req = _request("203.0.113.9")
    # Access helper never reads headers — only request.client.host.
    assert client_host(req) == "203.0.113.9"
    assert is_loopback_request(req) is False


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import app.schematics.config as config

    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    reset_sandbox()
    return TestClient(app)


def test_approve_allowed_for_testclient_loopback(client):
    created = client.post(
        "/api/proposals",
        json={"action": "get_component_status", "params": {}},
    )
    assert created.status_code == 200
    pid = created.json()["id"]
    approved = client.post(f"/api/proposals/{pid}/approve", json={})
    assert approved.status_code == 200
    assert approved.json()["status"] == "executed"


def test_approve_denied_for_non_loopback_peer(client, monkeypatch):
    created = client.post(
        "/api/proposals",
        json={"action": "get_component_status", "params": {}},
    )
    pid = created.json()["id"]

    def deny(_request):
        raise NonLoopbackAccessError("refused peer '203.0.113.10'")

    monkeypatch.setattr("app.main.require_loopback", deny)
    response = client.post(f"/api/proposals/{pid}/approve", json={})
    assert response.status_code == 403
    assert response.json()["code"] == "loopback_required"
    # Proposal must remain pending (no execute).
    got = client.get(f"/api/proposals/{pid}")
    assert got.json()["status"] == "pending"


def test_reject_and_reconcile_also_require_loopback(client, monkeypatch):
    created = client.post(
        "/api/proposals",
        json={"action": "get_component_status", "params": {}},
    )
    pid = created.json()["id"]

    def deny(_request):
        raise NonLoopbackAccessError("refused")

    monkeypatch.setattr("app.main.require_loopback", deny)
    assert client.post(f"/api/proposals/{pid}/reject", json={}).status_code == 403
    assert client.post(f"/api/proposals/{pid}/reconcile", json={}).status_code == 403
