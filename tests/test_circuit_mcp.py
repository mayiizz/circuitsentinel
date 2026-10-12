"""Protocol tests for the in-memory CircuitSentinel MCP sandbox."""

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.tools import circuit_mcp
from app.tools.circuit_mcp import (
    FIXED_TEST_COMPONENT,
    MCP_TOKEN_ENV,
    app,
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


def test_root_get_shows_the_mcp_endpoint() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "POST /mcp" in response.text


def test_missing_bearer_token_returns_401() -> None:
    status, _, body = post_rpc(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers={},
    )

    assert status == 401
    assert body == {"detail": "Unauthorized"}


def test_invalid_bearer_token_returns_401() -> None:
    status, _, body = post_rpc(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers=auth_headers("wrong-token"),
    )

    assert status == 401
    assert body == {"detail": "Unauthorized"}


def test_valid_bearer_token_allows_initialize() -> None:
    status, content_type, body = post_rpc(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "armoriq-agent", "version": "1.0.0"},
            },
        },
        headers=auth_headers(TEST_TOKEN),
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
                "name": "circuitsentinel-sandbox",
                "version": "1.0.0",
            },
        },
    }


def test_missing_env_token_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(MCP_TOKEN_ENV, raising=False)

    status, _, body = post_rpc(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers=auth_headers("anything"),
    )

    assert status == 503
    assert body == {"detail": "MCP authentication is not configured"}
    assert circuit_mcp.expected_mcp_token() is None


def test_initialize_returns_documented_handshake() -> None:
    status, _, body = post_rpc(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "armoriq-agent", "version": "1.0.0"},
            },
        }
    )

    assert status == 200
    assert body == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {
                "name": "circuitsentinel-sandbox",
                "version": "1.0.0",
            },
        },
    }


def test_tools_list_advertises_two_sandbox_tools() -> None:
    _, _, body = post_rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})

    assert body is not None
    tools = body["result"]["tools"]
    assert [tool["name"] for tool in tools] == [
        "get_component_status",
        "simulate_unverified_placement",
    ]
    placement = tools[1]["inputSchema"]
    assert placement["required"] == ["reference", "x_mm", "y_mm"]
    assert set(placement["properties"]) == {"reference", "x_mm", "y_mm"}


def test_get_component_status_returns_fixed_test_record() -> None:
    before = current_placement()

    _, _, body = post_rpc(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "get_component_status", "arguments": {}},
        }
    )

    assert body is not None
    content = body["result"]["content"]
    assert content[0]["type"] == "text"
    assert isinstance(content[0]["text"], str)
    assert json.loads(content[0]["text"]) == FIXED_TEST_COMPONENT
    assert current_placement() == before


def test_simulate_unverified_placement_updates_memory_only() -> None:
    _, _, first = post_rpc(
        {
            "jsonrpc": "2.0",
            "id": "place-1",
            "method": "tools/call",
            "params": {
                "name": "simulate_unverified_placement",
                "arguments": {"reference": "R1", "x_mm": 1.5, "y_mm": 2},
            },
        }
    )
    assert first is not None
    first_state = json.loads(first["result"]["content"][0]["text"])

    assert first_state == {
        "label": "in-memory-test-record",
        "reference": "R1",
        "x_mm": 1.5,
        "y_mm": 2.0,
        "verified": False,
        "sandbox": True,
    }
    assert current_placement() == first_state

    _, _, second = post_rpc(
        {
            "jsonrpc": "2.0",
            "id": "place-2",
            "method": "tools/call",
            "params": {
                "name": "simulate_unverified_placement",
                "arguments": {"reference": "R1", "x_mm": 4, "y_mm": 5},
            },
        }
    )
    assert second is not None
    second_state = json.loads(second["result"]["content"][0]["text"])

    assert second_state["x_mm"] == 4.0
    assert second_state["y_mm"] == 5.0
    assert second_state["verified"] is False
    assert current_placement() == second_state
    _, _, status = post_rpc(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "get_component_status", "arguments": {}},
        }
    )
    assert status is not None
    assert json.loads(status["result"]["content"][0]["text"]) == FIXED_TEST_COMPONENT


def test_unknown_method_returns_jsonrpc_error() -> None:
    status, _, body = post_rpc(
        {"jsonrpc": "2.0", "id": 5, "method": "resources/list"}
    )

    assert status == 200
    assert body is not None
    assert body["error"]["code"] == -32601
    assert body["error"]["message"] == "Method not found"
    assert body["id"] == 5


def test_unknown_tool_returns_jsonrpc_error() -> None:
    _, _, body = post_rpc(
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {"name": "fabricate_board", "arguments": {}},
        }
    )

    assert body is not None
    assert body["error"]["code"] == -32602
    assert body["error"]["message"] == "Unknown tool"
    assert current_placement()["reference"] is None


def test_invalid_arguments_return_jsonrpc_error() -> None:
    _, _, missing = post_rpc(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "simulate_unverified_placement",
                "arguments": {"reference": "R1"},
            },
        }
    )
    _, _, wrong_type = post_rpc(
        {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {
                "name": "simulate_unverified_placement",
                "arguments": {"reference": "R1", "x_mm": "left", "y_mm": 1},
            },
        }
    )

    assert missing is not None
    assert wrong_type is not None
    assert missing["error"]["code"] == -32602
    assert missing["error"]["message"] == "Invalid params"
    assert wrong_type["error"]["code"] == -32602
    assert current_placement()["reference"] is None


def test_invalid_json_returns_parse_error_as_sse() -> None:
    status, _, body = post_rpc("{")

    assert status == 200
    assert body == {
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": -32700, "message": "Parse error"},
    }
