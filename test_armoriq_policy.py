"""Automatic ArmorIQ policy check against the CircuitSentinel sandbox MCP.

Uses the documented SDK flow: capture_plan → get_intent_token → invoke.
This script does not invent allow/block logic; ArmorIQ enforces the registered policy.

ArmorIQClient.from_config("armoriq.yaml") maps environment: sandbox to local
backends and does not attach MCP bearer credentials. This script still loads
armoriq.yaml, then builds the client with the hosted endpoints and the circuit
MCP bearer token from $CIRCUITSENTINEL_MCP_TOKEN.
"""

from __future__ import annotations

from dotenv import load_dotenv
from armoriq_sdk import ArmorIQClient, PolicyBlockedException
from armoriq_sdk.config import load_armoriq_config, resolve_env_reference

load_dotenv(".env", override=True)

config = load_armoriq_config("armoriq.yaml")

mcp_credentials: dict[str, dict] = {}
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

client = ArmorIQClient(
    api_key=config.identity.resolved_api_key(),
    user_id=config.identity.user_id,
    agent_id=config.identity.agent_id,
    proxy_endpoint=config.proxy.url,
    timeout=float(config.proxy.timeout),
    max_retries=int(config.proxy.max_retries),
    # Hosted ArmorIQ endpoints. yaml "sandbox" is the org env label, not localhost.
    use_production=True,
    mcp_credentials=mcp_credentials or None,
)


def invoke_tool(action: str, params: dict, prompt: str):
    plan = client.capture_plan(
        llm="circuitsentinel-test",
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
    token = client.get_intent_token(plan, validity_seconds=300)
    return client.invoke(
        mcp="circuit",
        action=action,
        intent_token=token,
        params=params,
    )


def main():
    try:
        # Test 1: Read-only action must succeed.
        print("TEST 1: Read-only action")
        result = invoke_tool(
            "get_component_status",
            {},
            "Read the CircuitSentinel sandbox component status.",
        )
        print("PASS: Read-only action succeeded.")
        print(result)

        # Test 2: Unverified placement must be denied.
        print("\nTEST 2: Unverified placement")
        try:
            invoke_tool(
                "simulate_unverified_placement",
                {
                    "reference": "TEST-COMPONENT",
                    "x_mm": 10,
                    "y_mm": 20,
                },
                "Attempt an unverified sandbox placement.",
            )
        except PolicyBlockedException:
            print("PASS: ArmorIQ blocked the denied action.")
        else:
            raise AssertionError(
                "SECURITY FAILURE: ArmorIQ did not block placement."
            )

        print("\nALL SECURITY TESTS PASSED.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
