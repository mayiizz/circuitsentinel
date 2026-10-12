"""Server-side ArmorIQ invoke helpers for the dashboard API.

Runs the real capture_plan → get_intent_token → invoke flow. Does not invent
allow or block decisions. Credentials stay on the server.
"""

from __future__ import annotations

import json
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from armoriq_sdk import ArmorIQClient, MCPInvocationException, PolicyBlockedException
from armoriq_sdk.config import load_armoriq_config, resolve_env_reference
from dotenv import load_dotenv

# #region agent log
_DEBUG_LOG_PATH = Path("/Users/btchinmayi/Projects/circuitsentinel/.cursor/debug-a16a8f.log")


def _agent_log(hypothesis_id: str, location: str, message: str, data: dict[str, Any]) -> None:
    payload = {
        "sessionId": "a16a8f",
        "runId": "post-fix",
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    try:
        with _DEBUG_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, default=str) + "\n")
    except Exception:
        pass


# #endregion


@dataclass
class GovernedActionResult:
    decision: str  # allowed | blocked | error
    action: str
    message: str
    result: Any = None
    status_code: int = 200


def _sanitize_invoke_error(exc: Exception) -> tuple[str, int]:
    """Build a safe client message and HTTP status. Never includes tokens or env values."""
    if isinstance(exc, MCPInvocationException):
        upstream = getattr(exc, "status_code", None)
        status = upstream if isinstance(upstream, int) and 400 <= upstream < 600 else 502
        raw = str(exc)
        if status == 502 or "Bad gateway" in raw or "origin_bad_gateway" in raw:
            return (
                "Governed invoke failed: MCP origin unreachable (Bad Gateway). "
                "Start the sandbox MCP on port 8001 and keep the Cloudflare tunnel pointed at it.",
                502,
            )
        if status == 503:
            return (
                "Governed invoke failed: MCP temporarily unavailable.",
                503,
            )
        return (
            f"Governed invoke failed: MCPInvocationException (HTTP {status}).",
            status,
        )
    return (f"Governed invoke failed: {type(exc).__name__}", 500)


def _build_client() -> ArmorIQClient:
    load_dotenv(".env", override=True)
    config = load_armoriq_config("armoriq.yaml")

    mcp_credentials: dict[str, dict[str, str]] = {}
    for server in config.mcp_servers:
        if server.auth.type == "bearer":
            mcp_credentials[server.id] = {
                "authType": "bearer",
                "token": resolve_env_reference(server.auth.token or ""),
            }
        elif server.auth.type == "api_key":
            mcp_credentials[server.id] = {
                "authType": "api_key",
                "apiKey": resolve_env_reference(server.auth.api_key or ""),
            }

    # #region agent log
    _agent_log(
        "B",
        "policy_runtime.py:_build_client",
        "client config summary",
        {
            "cwd": str(Path.cwd()),
            "mcp_server_ids": [s.id for s in config.mcp_servers],
            "mcp_urls": [s.url for s in config.mcp_servers],
            "bearer_cred_ids": [
                sid for sid, cred in mcp_credentials.items() if cred.get("authType") == "bearer"
            ],
            "bearer_token_nonempty": {
                sid: bool((cred.get("token") or "").strip())
                for sid, cred in mcp_credentials.items()
                if cred.get("authType") == "bearer"
            },
            "proxy_url": config.proxy.url,
            "api_key_nonempty": bool(config.identity.resolved_api_key()),
        },
    )
    # #endregion

    return ArmorIQClient(
        api_key=config.identity.resolved_api_key(),
        user_id=config.identity.user_id,
        agent_id=config.identity.agent_id,
        proxy_endpoint=config.proxy.url,
        timeout=float(config.proxy.timeout),
        max_retries=int(config.proxy.max_retries),
        use_production=True,
        mcp_credentials=mcp_credentials or None,
    )


def invoke_governed_tool(
    action: str,
    params: dict[str, Any],
    prompt: str,
) -> GovernedActionResult:
    """Invoke one MCP tool through ArmorIQ. Policy is enforced by the platform."""
    # #region agent log
    _agent_log(
        "D",
        "policy_runtime.py:invoke_governed_tool:entry",
        "invoke start",
        {"action": action, "param_keys": sorted(params.keys()), "prompt_len": len(prompt)},
    )
    # #endregion
    client = _build_client()
    stage = "build_client"
    try:
        stage = "capture_plan"
        plan = client.capture_plan(
            llm="circuitsentinel-dashboard",
            prompt=prompt,
            plan={
                "goal": prompt,
                "steps": [
                    {
                        "action": action,
                        "mcp": "circuit",
                        "params": params,
                    }
                ],
            },
        )
        stage = "get_intent_token"
        token = client.get_intent_token(plan, validity_seconds=300)
        # #region agent log
        _agent_log(
            "E",
            "policy_runtime.py:invoke_governed_tool:token",
            "intent token minted",
            {
                "action": action,
                "has_step_proofs": bool(getattr(token, "step_proofs", None)),
                "step_proofs_len": len(getattr(token, "step_proofs", None) or []),
            },
        )
        # #endregion
        stage = "invoke"
        invocation = client.invoke(
            mcp="circuit",
            action=action,
            intent_token=token,
            params=params,
        )
        payload = invocation.result if hasattr(invocation, "result") else invocation
        # #region agent log
        _agent_log(
            "C",
            "policy_runtime.py:invoke_governed_tool:success",
            "invoke succeeded",
            {"action": action, "result_type": type(payload).__name__},
        )
        # #endregion
        return GovernedActionResult(
            decision="allowed",
            action=action,
            message="ArmorIQ allowed this action and the sandbox tool completed.",
            result=payload,
            status_code=200,
        )
    except PolicyBlockedException as exc:
        # #region agent log
        _agent_log(
            "A",
            "policy_runtime.py:invoke_governed_tool:blocked",
            "policy blocked",
            {"action": action, "stage": stage, "exc_type": type(exc).__name__},
        )
        # #endregion
        return GovernedActionResult(
            decision="blocked",
            action=action,
            message=str(exc) or "ArmorIQ blocked this action by policy.",
            result=None,
            status_code=200,
        )
    except Exception as exc:
        safe_message, http_status = _sanitize_invoke_error(exc)
        # #region agent log
        _agent_log(
            "A",
            "policy_runtime.py:invoke_governed_tool:error",
            "governed invoke failed",
            {
                "action": action,
                "stage": stage,
                "exc_type": type(exc).__name__,
                "exc_message": str(exc)[:500],
                "exc_mcp": getattr(exc, "mcp", None),
                "exc_action": getattr(exc, "action", None),
                "exc_status_code": getattr(exc, "status_code", None),
                "http_status": http_status,
                "traceback_tail": traceback.format_exc()[-1200:],
            },
        )
        # #endregion
        return GovernedActionResult(
            decision="error",
            action=action,
            message=safe_message,
            result=None,
            status_code=http_status,
        )
    finally:
        client.close()
