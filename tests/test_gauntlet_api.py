"""API tests for the Prompt-Injection Gauntlet public entry point."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.agents.gauntlet import run_prompt_injection_gauntlet
from app.main import app

client = TestClient(app)


def test_gauntlet_api_returns_deterministic_local_report() -> None:
    response = client.post("/api/agents/gauntlet")
    assert response.status_code == 200
    body = response.json()
    assert body["scenario_id"] == "prompt_injection_gauntlet_v1"
    assert body["evidence_kind"] == "gauntlet_test_fixture"
    assert "UNTRUSTED_TEST_EVIDENCE" in body["untrusted_passage"]
    assert "armoriq_live_attempted" not in body
    assert body["schematic_modified"] is False
    assert body["sandbox_state_before"] == body["sandbox_state_after"] or all(
        a["sandbox_unchanged"] for a in body["escalation_attempts"]
    )
    sources = {a["decision_source"] for a in body["escalation_attempts"]}
    assert "crew_policy" in sources
    assert "mcp_fail_closed" in sources
    assert "armoriq_live" not in sources
    assert body["injection_proposal"]["suggestion_only"] is True


def test_gauntlet_api_does_not_expose_mcp_handlers_or_tokens() -> None:
    response = client.post("/api/agents/gauntlet")
    text = response.text
    assert "CIRCUITSENTINEL_MCP_TOKEN" not in text
    assert "gauntlet-mcp-token-not-a-secret" not in text
    assert "ak_live_" not in text.lower()
    assert "Authorization: Bearer" not in text


def test_gauntlet_api_surfaces_server_errors_safely() -> None:
    with patch(
        "app.main.run_prompt_injection_gauntlet",
        side_effect=RuntimeError("boom"),
    ):
        response = client.post("/api/agents/gauntlet")
    assert response.status_code == 500
    body = response.json()
    assert "armoriq_live_attempted" not in body
    assert "detail" in body
    assert "RuntimeError" in body["detail"] or body.get("error") == "RuntimeError"


def test_gauntlet_helper_matches_api_shape() -> None:
    report = run_prompt_injection_gauntlet()
    response = client.post("/api/agents/gauntlet")
    api = response.json()
    assert api["scenario_id"] == report.scenario_id
    assert api["schematic_modified"] == report.schematic_modified
