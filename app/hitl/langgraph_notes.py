"""LangGraph integration status.

Implemented in ``app.agents.langgraph_assistant``:

- Deterministic demo mode (default): ``CIRCUITSENTINEL_AGENT_MODE=demo``
- Optional live Groq mode: ``CIRCUITSENTINEL_AGENT_MODE=llm`` + ``GROQ_API_KEY``
  (``CIRCUITSENTINEL_MODEL_PROVIDER=groq``, default model ``qwen/qwen3.8-27b``)
- HTTP entry: ``POST /api/assistant/chat``
- Read-only allowlist via ``app.agents.read_tools``
- Proposal creation via HITL ``create_proposal`` only (never approve/execute)

Residual limits:

- Live mode uses Groq's OpenAI-compatible Chat Completions API only (not OpenAI).
- The assistant cannot and must not call approve/reject/reconcile/execute.
- Demo answers are templates, not model reasoning — UI labels this clearly.
"""

LANGGRAPH_STATUS = "implemented"
LANGGRAPH_ENTRY = "app.agents.langgraph_assistant:run_assistant"
