"""Least-privilege hardware agent crew.

Roles, deny-by-default permissions, task/result models, orchestrator,
deterministic evidence-grounded workflow, and Prompt-Injection Gauntlet.
Executor tool calls go through ``invoke_governed_tool`` only; the workflow
never executes proposals.
"""

from app.agents.gauntlet import (
    GAUNTLET_LIMITATIONS,
    MALICIOUS_INSTRUCTION,
    SCENARIO_ID,
    UNTRUSTED_EVIDENCE_MARKER,
    GauntletEscalationAttempt,
    GauntletReport,
    build_gauntlet_analysis,
    build_gauntlet_datasheet_evidence,
    run_prompt_injection_gauntlet,
)
from app.agents.models import (
    AgentResult,
    AgentTask,
    CrewReport,
    ProposedChange,
    RequestedAction,
)
from app.agents.orchestrator import (
    describe_roles,
    propose_only,
    request_governed_sandbox_action,
    run_agent_task,
)
from app.agents.permissions import (
    ACTION_INSPECT_ANALYSIS,
    ACTION_INSPECT_DATASHEET_EVIDENCE,
    ACTION_INSPECT_ERC,
    ACTION_PROPOSE_CHANGE,
    ACTION_REQUEST_GOVERNED_ACTION,
    PERMITTED_SANDBOX_ACTIONS,
    ROLE_PERMISSIONS,
    allowed_actions_for,
    is_action_allowed,
    is_sandbox_action_permitted,
)
from app.agents.roles import ROLE_DESCRIPTIONS, ROLES, AgentRole, is_known_role
from app.agents.workflow import WORKFLOW_LIMITATIONS, run_crew_workflow

__all__ = [
    "ACTION_INSPECT_ANALYSIS",
    "ACTION_INSPECT_DATASHEET_EVIDENCE",
    "ACTION_INSPECT_ERC",
    "ACTION_PROPOSE_CHANGE",
    "ACTION_REQUEST_GOVERNED_ACTION",
    "AgentResult",
    "AgentRole",
    "AgentTask",
    "CrewReport",
    "GAUNTLET_LIMITATIONS",
    "GauntletEscalationAttempt",
    "GauntletReport",
    "MALICIOUS_INSTRUCTION",
    "PERMITTED_SANDBOX_ACTIONS",
    "ProposedChange",
    "ROLE_DESCRIPTIONS",
    "ROLE_PERMISSIONS",
    "ROLES",
    "RequestedAction",
    "SCENARIO_ID",
    "UNTRUSTED_EVIDENCE_MARKER",
    "WORKFLOW_LIMITATIONS",
    "allowed_actions_for",
    "build_gauntlet_analysis",
    "build_gauntlet_datasheet_evidence",
    "describe_roles",
    "is_action_allowed",
    "is_known_role",
    "is_sandbox_action_permitted",
    "propose_only",
    "request_governed_sandbox_action",
    "run_agent_task",
    "run_crew_workflow",
    "run_prompt_injection_gauntlet",
]
