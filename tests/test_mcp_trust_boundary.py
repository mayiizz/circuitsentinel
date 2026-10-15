"""MCP and dashboard trust-boundary regression tests.

Unit / in-process tests (this file):
- Unauthorized direct MCP access is rejected.
- Authorized bearer may call read-only tools.
- Privileged mutating tools are refused at the MCP gate without mutation.
- Dashboard action routes go through ``invoke_governed_tool`` only
  (fail-closed stub; may be mocked in tests).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app as dashboard_app
from app.policy_runtime import GovernedActionResult, invoke_governed_tool
from app.tools import circuit_mcp
from app.tools.circuit_mcp import (
    FIXED_TEST_COMPONENT,
    MCP_TOKEN_ENV,
    PRIVILEGED_TOOL_REFUSED,
    PRIVILEGED_TOOLS,
    app as mcp_app,
    current_placement,
    reset_sandbox,
)

TEST_TOKEN = "test-mcp-token-not-a-secret"


@pytest.fixture(autouse=True)
def _clean_sandbox(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv(MCP_TOKEN_ENV, TEST_TOKEN)
    reset_sandbox()
    yield
    reset_sandbox()


mcp_client = TestClient(mcp_app)
dashboard_client = TestClient(dashboard_app)


def _mcp_headers(token: str | None = TEST_TOKEN) -> dict[str, str]:
    headers = {"content-type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _tools_call(name: str, arguments: dict[str, Any], *, token: str | None = TEST_TOKEN):
    return mcp_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        headers=_mcp_headers(token),
    )


# ---------------------------------------------------------------------------
# Unauthorized direct MCP access
# ---------------------------------------------------------------------------


def test_unauthorized_missing_bearer_cannot_call_privileged_tool() -> None:
    before = current_placement()
    response = _tools_call(
        "simulate_unverified_placement",
        {"reference": "R1", "x_mm": 1.0, "y_mm": 2.0},
        token=None,
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}
    assert current_placement() == before


def test_unauthorized_wrong_bearer_cannot_call_privileged_tool() -> None:
    before = current_placement()
    response = _tools_call(
        "simulate_unverified_placement",
        {"reference": "R1", "x_mm": 1.0, "y_mm": 2.0},
        token="wrong-token",
    )
    assert response.status_code == 401
    assert current_placement() == before


def test_unauthorized_cannot_call_allowed_tool_either() -> None:
    before = current_placement()
    response = mcp_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "get_component_status", "arguments": {}},
        },
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 401
    assert current_placement() == before


# ---------------------------------------------------------------------------
# Authorized read path
# ---------------------------------------------------------------------------


def test_authorized_bearer_can_call_get_component_status() -> None:
    """Valid bearer + allowed read tool."""
    before = current_placement()
    response = _tools_call("get_component_status", {})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: message" in response.text
    assert FIXED_TEST_COMPONENT["label"] in response.text
    assert current_placement() == before


def test_authorized_bearer_privileged_tool_refused_sandbox_unchanged() -> None:
    import json

    before = current_placement()
    response = _tools_call(
        "simulate_unverified_placement",
        {"reference": "EVIL", "x_mm": 99.0, "y_mm": 99.0},
    )
    assert response.status_code == 200
    assert response.text.startswith("event: message\n")
    data_line = response.text.split("\n")[1]
    assert data_line.startswith("data: ")
    body = json.loads(data_line.removeprefix("data: "))
    assert body["error"]["code"] == PRIVILEGED_TOOL_REFUSED
    assert body["error"]["data"]["authorization_decision"] is None
    assert body["error"]["data"]["trust_boundary"] == "mcp_privileged_tool_gate"
    assert current_placement() == before
    assert "simulate_unverified_placement" in PRIVILEGED_TOOLS


# ---------------------------------------------------------------------------
# Dashboard public API — must not bypass governed invoke
# ---------------------------------------------------------------------------


def test_dashboard_actions_are_fail_closed_without_mock() -> None:
    """Real invoke_governed_tool always blocks; never mutates MCP sandbox."""
    before = current_placement()
    for path in (
        "/api/actions/get_component_status",
        "/api/actions/simulate_unverified_placement",
    ):
        response = dashboard_client.post(path)
        assert response.status_code == 200
        body = response.json()
        assert body["decision"] == "blocked"
        assert body["result"] is None
        msg = body["message"].lower()
        assert "authorization unavailable" in msg or "fail-closed" in msg
    assert current_placement() == before
    stub = invoke_governed_tool("get_component_status", {}, "x")
    assert stub.decision == "blocked"


def test_dashboard_get_component_status_uses_governed_invoke_only() -> None:
    calls: list[tuple[str, dict[str, Any], str]] = []

    def fake_invoke(action: str, params: dict[str, Any], prompt: str) -> GovernedActionResult:
        calls.append((action, params, prompt))
        return GovernedActionResult(
            decision="blocked",
            action=action,
            message="Authorization unavailable: fail-closed stub.",
            result=None,
        )

    with patch("app.main.invoke_governed_tool", side_effect=fake_invoke):
        response = dashboard_client.post("/api/actions/get_component_status")

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "blocked"
    assert body["action"] == "get_component_status"
    assert len(calls) == 1
    assert calls[0][0] == "get_component_status"


def test_dashboard_simulate_uses_governed_invoke_and_reports_blocked() -> None:
    """Dashboard reports blocked from invoke; does not invent a local allow."""
    before = current_placement()
    calls: list[str] = []

    def fake_invoke(action: str, params: dict[str, Any], prompt: str) -> GovernedActionResult:
        calls.append(action)
        return GovernedActionResult(
            decision="blocked",
            action=action,
            message="Authorization unavailable: fail-closed stub.",
            result=None,
        )

    with patch("app.main.invoke_governed_tool", side_effect=fake_invoke):
        response = dashboard_client.post(
            "/api/actions/simulate_unverified_placement",
            json={"reference": "R9", "x_mm": 1.0, "y_mm": 2.0},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "blocked"
    assert body["result"] is None
    assert "authorization" in body["message"].lower()
    assert calls == ["simulate_unverified_placement"]
    assert current_placement() == before


def test_dashboard_does_not_call_mcp_handlers_directly_on_simulate() -> None:
    before = current_placement()
    handler_calls: list[dict[str, Any]] = []

    real_handler = circuit_mcp._simulate_unverified_placement

    def spying_handler(arguments: dict[str, Any]) -> dict[str, Any]:
        handler_calls.append(arguments)
        return real_handler(arguments)

    with (
        patch(
            "app.main.invoke_governed_tool",
            return_value=GovernedActionResult(
                decision="blocked",
                action="simulate_unverified_placement",
                message="Authorization unavailable: fail-closed stub.",
            ),
        ),
        patch.dict(
            circuit_mcp._TOOL_HANDLERS,
            {"simulate_unverified_placement": spying_handler},
        ),
    ):
        response = dashboard_client.post("/api/actions/simulate_unverified_placement")

    assert response.status_code == 200
    assert response.json()["decision"] == "blocked"
    assert handler_calls == []
    assert current_placement() == before
