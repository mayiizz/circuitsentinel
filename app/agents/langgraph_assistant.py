"""LangGraph-backed circuit assistant with hard permission boundaries.

Demo mode is deterministic and requires no model credentials.
Live LLM mode is optional and fails clearly when credentials are missing.

The graph may:
- call allowlisted read-only tools via ``app.agents.read_tools``
- load circuit analysis summaries when a file id is provided
- create HITL proposals via ``create_proposal`` / ``create_proposal_file``

The graph must not:
- approve, reject, reconcile, or execute proposals
- import ``_TOOL_HANDLERS`` or ``execute_sandbox_tool`` / ``execute_registered_tool``
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents.assistant_models import AssistantChatRequest, AssistantChatResponse
from app.agents.read_tools import ASSISTANT_READ_TOOLS, ReadToolError, call_read_tool
from app.circuit.analyze import run_circuit_analysis
from app.circuit.models import CircuitAnalyzeRequest
from app.hitl.service import ProposalValidationError, create_proposal
from app.hitl.store import create_proposal_file

AgentMode = Literal["demo", "llm"]

_FILE_ID_RE = re.compile(r"^[a-f0-9]{32}$", re.I)


class AssistantState(TypedDict, total=False):
    message: str
    schematic_file_id: str | None
    create_proposal: bool
    proposed_action: str
    proposed_params: dict[str, Any]
    mode: AgentMode
    intent: str
    circuit_summary: str | None
    read_evidence: list[dict[str, Any]]
    tools_used: list[str]
    answer: str
    uncertainty: list[str]
    limitations: list[str]
    proposal_id: str | None
    proposal_status: str | None
    proposal_created: bool
    graph_path: list[str]
    error: str | None


def agent_mode() -> AgentMode:
    raw = os.environ.get("CIRCUITSENTINEL_AGENT_MODE", "demo").strip().lower()
    return "llm" if raw == "llm" else "demo"


def _append_path(state: AssistantState, name: str) -> list[str]:
    path = list(state.get("graph_path") or [])
    path.append(name)
    return path


def classify_request(state: AssistantState) -> AssistantState:
    message = (state.get("message") or "").lower()
    intent = "explain"
    if state.get("create_proposal") or state.get("proposed_action", "none") != "none":
        intent = "propose"
    elif any(w in message for w in ("status", "component", "sandbox", "placement")):
        intent = "read_status"
    elif any(w in message for w in ("rail", "voltage", "supply", "analyze", "erc")):
        intent = "analyze"
    return {
        **state,
        "intent": intent,
        "graph_path": _append_path(state, "classify_request"),
        "tools_used": list(state.get("tools_used") or []),
        "read_evidence": list(state.get("read_evidence") or []),
        "uncertainty": list(state.get("uncertainty") or []),
        "limitations": list(state.get("limitations") or []),
    }


def load_circuit_context(state: AssistantState) -> AssistantState:
    fid = (state.get("schematic_file_id") or "").strip().lower() or None
    summary = None
    uncertainty = list(state.get("uncertainty") or [])
    limitations = list(state.get("limitations") or [])
    if fid:
        if not _FILE_ID_RE.fullmatch(fid):
            uncertainty.append("schematic_file_id is not a valid 32-hex upload id.")
        else:
            report = run_circuit_analysis(fid, CircuitAnalyzeRequest())
            summary = (
                f"assessment={report.assessment}; findings={len(report.findings)}; "
                f"components={len(report.components)}; "
                f"failure_reason={report.failure_reason or 'none'}"
            )
            if report.assessment in {"error", "inconclusive"}:
                uncertainty.append(
                    report.failure_reason or "circuit analysis incomplete or errored"
                )
            limitations.extend(list(report.limitations or [])[:5])
    else:
        limitations.append("No schematic_file_id provided; circuit analysis skipped.")
    return {
        **state,
        "schematic_file_id": fid,
        "circuit_summary": summary,
        "uncertainty": uncertainty,
        "limitations": limitations,
        "graph_path": _append_path(state, "load_circuit_context"),
    }


def collect_read_evidence(state: AssistantState) -> AssistantState:
    tools = list(state.get("tools_used") or [])
    evidence = list(state.get("read_evidence") or [])
    uncertainty = list(state.get("uncertainty") or [])
    intent = state.get("intent") or "explain"
    if intent in {"read_status", "propose", "explain", "analyze"}:
        try:
            result = call_read_tool("get_component_status", {})
            tools.append("get_component_status")
            evidence.append({"tool": "get_component_status", "result": result})
        except ReadToolError as exc:
            uncertainty.append(str(exc))
    return {
        **state,
        "tools_used": tools,
        "read_evidence": evidence,
        "uncertainty": uncertainty,
        "graph_path": _append_path(state, "collect_read_evidence"),
    }


def analyze_or_explain(state: AssistantState) -> AssistantState:
    mode = state.get("mode") or agent_mode()
    if mode == "llm":
        return _llm_explain(state)
    return _demo_explain(state)


def _default_placement_params() -> dict[str, Any]:
    return {"reference": "ASSIST-R1", "x_mm": 10.0, "y_mm": 20.0}


def _demo_explain(state: AssistantState) -> AssistantState:
    parts = [
        "[deterministic-demo] Not an autonomous LLM agent.",
        f"Intent classified as {state.get('intent')!r}.",
    ]
    if state.get("circuit_summary"):
        parts.append(f"Circuit context: {state['circuit_summary']}")
    else:
        parts.append(
            "No circuit analysis context was loaded "
            "(sandbox HITL proposals do not require a circuit summary)."
        )
    if state.get("read_evidence"):
        parts.append(
            "Read-only sandbox status: "
            + json.dumps(state["read_evidence"][-1].get("result"), sort_keys=True)
        )
    if state.get("create_proposal"):
        action = (state.get("proposed_action") or "none").strip()
        params = dict(state.get("proposed_params") or {})
        if action == "simulate_unverified_placement" and not params:
            params = _default_placement_params()
        if action == "none":
            action = "get_component_status"
        parts.append(
            f"Operator requested a pending HITL proposal for {action!r} "
            f"with params {json.dumps(params, sort_keys=True)}. "
            "This does not execute the action."
        )
    parts.append(
        "State-changing tools are never executed here. "
        "Eligible actions require a pending HITL proposal and human approval."
    )
    return {
        **state,
        "answer": " ".join(parts),
        "graph_path": _append_path(state, "analyze_or_explain"),
        "limitations": list(state.get("limitations") or [])
        + ["Demo mode uses deterministic templates, not live model reasoning."],
    }


def _llm_explain(state: AssistantState) -> AssistantState:
    """Call Groq Chat Completions (OpenAI-compatible HTTP API). No OpenAI provider."""
    provider = os.environ.get("CIRCUITSENTINEL_MODEL_PROVIDER", "groq").strip().lower()
    model = os.environ.get(
        "CIRCUITSENTINEL_MODEL",
        "qwen/qwen3.8-27b",
    ).strip()
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if provider != "groq":
        return {
            **state,
            "error": f"Unsupported model provider {provider!r}. Supported: groq.",
            "answer": "Live model mode is misconfigured. Set CIRCUITSENTINEL_MODEL_PROVIDER=groq.",
            "graph_path": _append_path(state, "analyze_or_explain"),
        }
    if not api_key:
        return {
            **state,
            "error": "CIRCUITSENTINEL_AGENT_MODE=llm requires GROQ_API_KEY.",
            "answer": (
                "Live model mode is selected but GROQ_API_KEY is missing. "
                "Set credentials or switch CIRCUITSENTINEL_AGENT_MODE=demo."
            ),
            "graph_path": _append_path(state, "analyze_or_explain"),
        }

    system = (
        "You are CircuitSentinel's assistant. Explain using only provided evidence. "
        "Do not invent voltages, datasheet limits, or tool results. "
        "Never claim you approved or executed an action. "
        "Sandbox HITL proposals (get_component_status, simulate_unverified_placement) "
        "do not require circuit_summary or schematic topology. "
        "A null circuit_summary only means no schematic was loaded; it is not a reason "
        "to refuse acknowledging a pending proposal when create_proposal is true. "
        "When create_proposal is true, acknowledge that a pending HITL proposal will be "
        "created with the operator-supplied proposed_action and proposed_params. "
        "Do not invent placement coordinates; use proposed_params when present. "
        "Human approval is still required before any execution."
    )
    proposed_action = (state.get("proposed_action") or "none").strip()
    proposed_params = dict(state.get("proposed_params") or {})
    if (
        state.get("create_proposal")
        and proposed_action == "simulate_unverified_placement"
        and not proposed_params
    ):
        proposed_params = _default_placement_params()
    user = json.dumps(
        {
            "message": state.get("message"),
            "intent": state.get("intent"),
            "create_proposal": bool(state.get("create_proposal")),
            "proposed_action": proposed_action,
            "proposed_params": proposed_params,
            "circuit_summary": state.get("circuit_summary"),
            "read_evidence": state.get("read_evidence"),
            "uncertainty": state.get("uncertainty"),
            "note": (
                "Null circuit_summary is OK for sandbox-only HITL proposals. "
                "Do not refuse propose intent solely because circuit_summary is null."
            ),
        },
        ensure_ascii=True,
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
    }
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # Groq/CDN rejects urllib's default User-Agent (HTTP 403 / CF 1010).
            "User-Agent": "CircuitSentinel/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        answer = body["choices"][0]["message"]["content"]
    except (urllib.error.URLError, urllib.error.HTTPError, KeyError, IndexError, TypeError) as exc:
        return {
            **state,
            "error": f"LLM request failed: {type(exc).__name__}",
            "answer": "The live Groq model request failed. No fabricated answer was substituted.",
            "graph_path": _append_path(state, "analyze_or_explain"),
        }
    return {
        **state,
        "answer": str(answer).strip(),
        "graph_path": _append_path(state, "analyze_or_explain"),
    }


def create_proposal_if_requested(state: AssistantState) -> AssistantState:
    if state.get("error"):
        return {**state, "graph_path": _append_path(state, "create_proposal_if_requested")}
    if not state.get("create_proposal"):
        return {
            **state,
            "proposal_created": False,
            "graph_path": _append_path(state, "create_proposal_if_requested"),
        }

    action = (state.get("proposed_action") or "none").strip()
    if action == "none":
        # Infer a safe read-only proposal only.
        action = "get_component_status"
        params: dict[str, Any] = {}
    else:
        params = dict(state.get("proposed_params") or {})
        if action == "simulate_unverified_placement" and not params:
            # Sandbox placement is operator-intent, not derived from circuit topology.
            params = _default_placement_params()

    # Never allow the graph to "approve" via fake actions.
    if action not in {"get_component_status", "simulate_unverified_placement"}:
        return {
            **state,
            "proposal_created": False,
            "uncertainty": list(state.get("uncertainty") or [])
            + [f"Refused unregistered proposal action {action!r}."],
            "graph_path": _append_path(state, "create_proposal_if_requested"),
        }

    try:
        proposal = create_proposal(
            action=action,
            params=params,
            prompt=(
                f"[assistant:{state.get('mode')}] "
                f"{(state.get('message') or '')[:500]}"
            ),
        )
        create_proposal_file(proposal)
    except (ProposalValidationError, OSError, ValueError) as exc:
        return {
            **state,
            "proposal_created": False,
            "uncertainty": list(state.get("uncertainty") or []) + [str(exc)],
            "graph_path": _append_path(state, "create_proposal_if_requested"),
        }

    return {
        **state,
        "proposal_id": proposal.id,
        "proposal_status": proposal.status,
        "proposal_created": True,
        "answer": (
            (state.get("answer") or "")
            + f" Created pending HITL proposal {proposal.id} for action {action!r}. "
            "Human approval is required before any execution."
        ).strip(),
        "graph_path": _append_path(state, "create_proposal_if_requested"),
    }


def format_response(state: AssistantState) -> AssistantState:
    return {**state, "graph_path": _append_path(state, "format_response")}


def build_assistant_graph():
    graph: StateGraph = StateGraph(AssistantState)
    graph.add_node("classify_request", classify_request)
    graph.add_node("load_circuit_context", load_circuit_context)
    graph.add_node("collect_read_evidence", collect_read_evidence)
    graph.add_node("analyze_or_explain", analyze_or_explain)
    graph.add_node("create_proposal_if_requested", create_proposal_if_requested)
    graph.add_node("format_response", format_response)

    graph.add_edge(START, "classify_request")
    graph.add_edge("classify_request", "load_circuit_context")
    graph.add_edge("load_circuit_context", "collect_read_evidence")
    graph.add_edge("collect_read_evidence", "analyze_or_explain")
    graph.add_edge("analyze_or_explain", "create_proposal_if_requested")
    graph.add_edge("create_proposal_if_requested", "format_response")
    graph.add_edge("format_response", END)
    return graph.compile()


_GRAPH = None


def get_assistant_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_assistant_graph()
    return _GRAPH


def run_assistant(request: AssistantChatRequest) -> AssistantChatResponse:
    """Execute the assistant graph. Never approves or executes privileged tools."""
    mode = agent_mode()
    initial: AssistantState = {
        "message": request.message.strip(),
        "schematic_file_id": request.schematic_file_id,
        "create_proposal": request.create_proposal,
        "proposed_action": request.proposed_action,
        "proposed_params": dict(request.proposed_params or {}),
        "mode": mode,
        "tools_used": [],
        "read_evidence": [],
        "uncertainty": [],
        "limitations": [
            f"Assistant read allowlist: {sorted(ASSISTANT_READ_TOOLS)}",
            "Assistant cannot approve, reject, reconcile, or execute HITL proposals.",
        ],
        "proposal_created": False,
        "graph_path": [],
    }
    final = get_assistant_graph().invoke(initial)
    return AssistantChatResponse(
        mode=mode,
        demo_label="[deterministic-demo]" if mode == "demo" else None,
        answer=final.get("answer") or final.get("error") or "No answer produced.",
        uncertainty=list(final.get("uncertainty") or []),
        evidence=list(final.get("read_evidence") or []),
        tools_used=list(final.get("tools_used") or []),
        proposal_id=final.get("proposal_id"),
        proposal_status=final.get("proposal_status"),
        proposal_created=bool(final.get("proposal_created")),
        graph_path=list(final.get("graph_path") or []),
        limitations=list(final.get("limitations") or []),
    )


# Guardrail: refuse accidental imports of privileged execution from this module.
def __getattr__(name: str) -> Any:  # pragma: no cover - defensive
    if name in {
        "execute_sandbox_tool",
        "execute_registered_tool",
        "approve_and_execute",
        "_TOOL_HANDLERS",
    }:
        raise AttributeError(
            f"{name} is not available on the assistant module (permission boundary)"
        )
    raise AttributeError(name)
