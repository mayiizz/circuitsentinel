"""Protocol tests for the isolated CircuitSentinel MCP sandbox v2."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.tools import circuit_mcp_v2
from app.tools.circuit_mcp_v2 import (
    MCP_TOKEN_ENV,
    PRIVILEGED_TOOL_REFUSED,
    SERVER_NAME,
    app,
    current_placement,
    reset_sandbox,
)

TEST_TOKEN = "test-mcp-v2-token-not-a-secret"


@pytest.fixture(autouse=True)
def _clean_sandbox(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv(MCP_TOKEN_ENV, TEST_TOKEN)
    # Ensure v1 token env does not accidentally authorize v2.
    monkeypatch.delenv("CIRCUITSENTINEL_MCP_TOKEN", raising=False)
    reset_sandbox()
    yield
    reset_sandbox()


client = TestClient(app)


def auth_headers(token: str = TEST_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def parse_sse(body: str) -> dict:
    assert body.startswith("event: message\n")
    assert body.endswith("\n\n")
    lines = body.split("\n")
    assert lines[0] == "event: message"
    assert lines[1].startswith("data: ")
    assert lines[2:] == ["", ""]
    return json.loads(lines[1].removeprefix("data: "))


def post_rpc(
    payload: dict | str,
    *,
    headers: dict[str, str] | None = None,
) -> tuple[int, str | None, dict | None]:
    request_headers = {"content-type": "application/json"}
    if headers is None:
        request_headers.update(auth_headers())
    else:
        request_headers.update(headers)

    if isinstance(payload, str):
        response = client.post("/mcp", content=payload, headers=request_headers)
    else:
        response = client.post("/mcp", json=payload, headers=request_headers)

    content_type = response.headers.get("content-type")
    if response.status_code != 200:
        return response.status_code, content_type, response.json()

    assert content_type is not None
    assert content_type.startswith("text/event-stream")
    return response.status_code, content_type, parse_sse(response.text)


def test_v2_uses_distinct_server_name_and_token_env() -> None:
    assert SERVER_NAME == "circuitsentinel-sandbox-v2"
    assert MCP_TOKEN_ENV == "CIRCUITSENTINEL_MCP_V2_TOKEN"
    assert circuit_mcp_v2.expected_mcp_token() == TEST_TOKEN


def test_v2_root_identifies_sandbox_v2() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "sandbox v2" in response.text
    assert "POST /mcp" in response.text


def test_v2_missing_bearer_returns_401() -> None:
    status, _, body = post_rpc(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers={},
    )
    assert status == 401
    assert body == {"detail": "Unauthorized"}


def test_v2_v1_token_does_not_authorize() -> None:
    status, _, body = post_rpc(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers=auth_headers("v1-token-should-not-work"),
    )
    assert status == 401
    assert body == {"detail": "Unauthorized"}


def test_v2_missing_env_token_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(MCP_TOKEN_ENV, raising=False)
    status, _, body = post_rpc(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers=auth_headers("anything"),
    )
    assert status == 503
    assert body == {"detail": "MCP authentication is not configured"}
    assert circuit_mcp_v2.expected_mcp_token() is None


def test_v2_initialize_handshake() -> None:
    status, content_type, body = post_rpc(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "circuitsentinel-test", "version": "1.0.0"},
            },
        }
    )
    assert status == 200
    assert content_type is not None
    assert content_type.startswith("text/event-stream")
    assert body == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {
                "name": "circuitsentinel-sandbox-v2",
                "version": "1.0.0",
            },
        },
    }


def test_v2_notifications_initialized_returns_202() -> None:
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers={"content-type": "application/json", **auth_headers()},
    )
    assert response.status_code == 202
    assert response.content == b""


def test_v2_tools_list_matches_original_tool_names() -> None:
    status, _, body = post_rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert status == 200
    assert body is not None
    names = [tool["name"] for tool in body["result"]["tools"]]
    assert names == ["get_component_status", "simulate_unverified_placement"]


def test_v2_get_component_status_succeeds() -> None:
    status, _, body = post_rpc(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "get_component_status", "arguments": {}},
        }
    )
    assert status == 200
    assert body is not None
    payload = json.loads(body["result"]["content"][0]["text"])
    assert payload["reference"] == "TP1"
    assert payload["sandbox"] is True


def test_v2_privileged_placement_is_fail_closed() -> None:
    before = current_placement()
    status, _, body = post_rpc(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "simulate_unverified_placement",
                "arguments": {"reference": "R1", "x_mm": 1.5, "y_mm": 2.0},
            },
        }
    )
    assert status == 200
    assert body is not None
    assert body["error"]["code"] == PRIVILEGED_TOOL_REFUSED
    assert body["error"]["data"]["trust_boundary"] == "mcp_privileged_tool_gate"
    assert body["error"]["data"]["authorization_decision"] is None
    assert current_placement() == before


def test_v2_auth_failure_does_not_log_authorization_header(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "super-secret-v2-bearer-value"
    with caplog.at_level("WARNING", logger="circuitsentinel.mcp.v2"):
        post_rpc(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            headers=auth_headers(secret),
        )
    joined = " ".join(record.getMessage() for record in caplog.records)
    assert secret not in joined
    assert "Authorization" not in joined
    assert "Bearer " not in joined
