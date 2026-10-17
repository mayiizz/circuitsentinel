"""LangGraph assistant: demo mode, allowlists, proposal-only (no execute/approve)."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.agents.langgraph_assistant import run_assistant
from app.agents.assistant_models import AssistantChatRequest
from app.agents.read_tools import ReadToolError, call_read_tool
from app.hitl.store import load_proposal
from app.main import app
from app.tools.circuit_mcp import current_placement, reset_sandbox


@pytest.fixture()
def hitl_env(tmp_path, monkeypatch):
    import app.schematics.config as config

    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setenv("CIRCUITSENTINEL_AGENT_MODE", "demo")
    reset_sandbox()
    return tmp_path


@pytest.fixture()
def client(hitl_env):
    return TestClient(app)


def test_read_tool_allowlist_rejects_privileged():
    with pytest.raises(ReadToolError):
        call_read_tool("simulate_unverified_placement", {"reference": "X", "x_mm": 1, "y_mm": 2})


def test_demo_assistant_reads_without_mutating(hitl_env):
    before = current_placement()
    result = run_assistant(
        AssistantChatRequest(message="What is the sandbox component status?")
    )
    assert result.mode == "demo"
    assert result.demo_label
    assert "get_component_status" in result.tools_used
    assert result.proposal_created is False
    assert current_placement() == before
    assert "deterministic-demo" in result.answer.lower() or "[deterministic-demo]" in result.answer


def test_assistant_creates_pending_proposal_only(hitl_env):
    before = current_placement()
    result = run_assistant(
        AssistantChatRequest(
            message="Please propose a sandbox placement",
            create_proposal=True,
            proposed_action="simulate_unverified_placement",
            proposed_params={"reference": "AG-R1", "x_mm": 3.0, "y_mm": 4.0},
        )
    )
    assert result.proposal_created is True
    assert result.proposal_id
    assert result.proposal_status == "pending"
    loaded = load_proposal(result.proposal_id)
    assert loaded is not None
    assert loaded.status == "pending"
    assert loaded.params["reference"] == "AG-R1"
    assert current_placement() == before
    assert current_placement()["reference"] != "AG-R1"
    assert "do not require a circuit summary" in result.answer.lower()


def test_assistant_placement_proposal_without_circuit_or_params(hitl_env):
    """Sandbox placement HITL must not depend on circuit_summary."""
    before = current_placement()
    result = run_assistant(
        AssistantChatRequest(
            message="Please propose a sandbox placement",
            schematic_file_id=None,
            create_proposal=True,
            proposed_action="simulate_unverified_placement",
            proposed_params={},
        )
    )
    assert result.proposal_created is True
    assert result.proposal_id
    loaded = load_proposal(result.proposal_id)
    assert loaded is not None
    assert loaded.action == "simulate_unverified_placement"
    assert loaded.params["reference"] == "ASSIST-R1"
    assert loaded.params["x_mm"] == 10.0
    assert loaded.params["y_mm"] == 20.0
    assert current_placement() == before
    assert "Created pending HITL proposal" in result.answer


def test_assistant_cannot_import_privileged_helpers():
    import app.agents.langgraph_assistant as mod

    with pytest.raises(AttributeError):
        _ = mod.execute_sandbox_tool  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        _ = mod.approve_and_execute  # type: ignore[attr-defined]


def test_llm_mode_fails_clearly_without_credentials(hitl_env, monkeypatch):
    monkeypatch.setenv("CIRCUITSENTINEL_AGENT_MODE", "llm")
    monkeypatch.setenv("CIRCUITSENTINEL_MODEL_PROVIDER", "groq")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    result = run_assistant(AssistantChatRequest(message="hello"))
    assert result.mode == "llm"
    assert "GROQ_API_KEY" in result.answer or "missing" in result.answer.lower()


def test_llm_payload_allows_null_circuit_for_placement_proposal(hitl_env, monkeypatch):
    """LLM user payload must tell the model null circuit_summary is OK for sandbox HITL."""
    import json

    import app.agents.langgraph_assistant as mod

    monkeypatch.setenv("CIRCUITSENTINEL_AGENT_MODE", "llm")
    monkeypatch.setenv("CIRCUITSENTINEL_MODEL_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")

    captured: dict = {}

    class _Resp:
        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": "Will create pending HITL proposal."}}]}
            ).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(req, timeout=45):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _Resp()

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    # Reset compiled graph so mode is re-read through invoke path.
    monkeypatch.setattr(mod, "_GRAPH", None)

    result = run_assistant(
        AssistantChatRequest(
            message="Please propose a sandbox placement",
            create_proposal=True,
            proposed_action="simulate_unverified_placement",
            proposed_params={"reference": "LLM-R1", "x_mm": 1.0, "y_mm": 2.0},
        )
    )
    assert result.mode == "llm"
    assert result.proposal_created is True
    system = captured["body"]["messages"][0]["content"]
    user = json.loads(captured["body"]["messages"][1]["content"])
    assert "do not require circuit_summary" in system.lower()
    assert user["create_proposal"] is True
    assert user["proposed_action"] == "simulate_unverified_placement"
    assert user["circuit_summary"] is None
    assert "null circuit_summary is ok" in user["note"].lower()


def test_assistant_http_endpoint(client):
    response = client.post(
        "/api/assistant/chat",
        json={"message": "sandbox status please", "create_proposal": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "demo"
    assert "get_component_status" in body["tools_used"]


def test_assistant_http_proposal_then_legacy_still_blocked(client):
    created = client.post(
        "/api/assistant/chat",
        json={
            "message": "create read proposal",
            "create_proposal": True,
            "proposed_action": "get_component_status",
        },
    )
    assert created.status_code == 200
    assert created.json()["proposal_created"] is True
    legacy = client.post("/api/actions/get_component_status")
    assert legacy.json()["decision"] == "blocked"
