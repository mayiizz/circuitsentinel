"""Deterministic, evidence-grounded crew workflow (milestone 2).

Accepts an existing ``AnalysisResponse`` and optional datasheet evidence.
Runs analyst → researcher → proposer through the role-permission registry.
Never executes proposals, never modifies uploaded schematics, never invents
datasheet lookups, and never calls MCP or governed invoke (executor is not
part of this workflow).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.agents.models import AgentResult, AgentTask, CrewReport, ProposedChange
from app.agents.orchestrator import run_agent_task
from app.agents.permissions import (
    ACTION_INSPECT_ANALYSIS,
    ACTION_INSPECT_DATASHEET_EVIDENCE,
    ACTION_INSPECT_ERC,
    ACTION_PROPOSE_CHANGE,
)
from app.datasheets.models import (
    DatasheetComponentLinkResponse,
    DatasheetIngestReport,
    NormalizedDatasheetFact,
    RawDatasheetEvidence,
)
from app.schematics.models import AnalysisResponse, ErcFinding, NetlistReport

WORKFLOW_LIMITATIONS = [
    "Crew workflow is deterministic and evidence-grounded; it does not use an LLM.",
    "Proposed changes are suggestions only and are never applied to uploaded schematics.",
    "The proposer never invokes tools or governed sandbox actions.",
    "Missing datasheet evidence yields needs_input — no fabricated lookups or part specs.",
    "Unsupported claims (fabricated voltages, invented connectivity) are never emitted.",
]


def run_crew_workflow(
    analysis: AnalysisResponse,
    *,
    datasheet_evidence: (
        DatasheetIngestReport
        | DatasheetComponentLinkResponse
        | dict[str, Any]
        | list[Any]
        | None
    ) = None,
) -> CrewReport:
    """Run analyst → researcher → proposer on existing analysis evidence.

    Parameters
    ----------
    analysis:
        Existing schematic analysis from ``analyze_schematic_bytes`` / the API.
    datasheet_evidence:
        Optional already-ingested datasheet report, link response, dict, or list.
        When absent or empty, the researcher returns ``needs_input``.
    """
    if not isinstance(analysis, AnalysisResponse):
        return _failure_report(
            error="invalid_analysis",
            summary="Workflow requires an AnalysisResponse instance.",
        )

    try:
        analysis_payload = analysis.model_dump()
        analyst = _run_analyst(analysis, analysis_payload)
        researcher = _run_researcher(datasheet_evidence)
        proposals, unresolved = _build_proposals_and_questions(
            analysis=analysis,
            analyst=analyst,
            researcher=researcher,
        )
        proposer = _run_proposer(proposals)
        return _assemble_report(
            analysis=analysis,
            analyst=analyst,
            researcher=researcher,
            proposer=proposer,
            unresolved=unresolved,
        )
    except Exception as exc:  # noqa: BLE001 — surface as structured workflow error
        return _failure_report(
            error=f"workflow_exception:{type(exc).__name__}",
            summary=f"Crew workflow failed: {type(exc).__name__}.",
        )


def _run_analyst(analysis: AnalysisResponse, analysis_payload: dict[str, Any]) -> AgentResult:
    """Inspect parsed schematic data, ERC, and netlist from the analysis response."""
    analysis_result = run_agent_task(
        AgentTask(
            role="analyst",
            action=ACTION_INSPECT_ANALYSIS,
            analysis=analysis_payload,
        )
    )
    erc_result = run_agent_task(
        AgentTask(
            role="analyst",
            action=ACTION_INSPECT_ERC,
            analysis=analysis_payload,
            erc=analysis_payload.get("erc"),
        )
    )

    evidence: list[dict[str, Any]] = []
    evidence.extend(analysis_result.evidence)
    evidence.extend(erc_result.evidence)

    # Structured, id'd evidence derived only from existing analysis fields.
    for item in _schematic_evidence_items(analysis):
        evidence.append(item)

    findings = _analyst_findings(analysis)
    statuses = {analysis_result.status, erc_result.status}
    if "rejected" in statuses or "error" in statuses:
        status = "error"
    elif "needs_input" in statuses and "completed" not in statuses:
        status = "needs_input"
    elif "needs_input" in statuses:
        status = "completed"  # analysis present; erc may still complete from payload
    else:
        status = "completed"

    # Prefer completed when analysis payload was present (always for AnalysisResponse).
    if analysis_result.status == "completed":
        status = "completed"

    symbol_count = len(analysis.confirmed.symbols)
    erc_count = len(analysis.erc.findings) if analysis.erc.ran else 0
    netlist_note = _netlist_summary(analysis.netlist)
    summary = (
        f"Analyst inspected parsed schematic data ({symbol_count} symbol(s)), "
        f"ERC ({'ran' if analysis.erc.ran else 'did not run'}; {erc_count} finding(s)), "
        f"and netlist ({netlist_note})."
    )
    error = analysis_result.error or erc_result.error
    evidence.append({"kind": "analyst_findings", "payload": findings})
    return AgentResult(
        role="analyst",
        status=status,  # type: ignore[arg-type]
        summary=summary,
        evidence=evidence,
        error=error if status in {"error", "needs_input", "rejected"} else None,
    )


def _schematic_evidence_items(analysis: AnalysisResponse) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    items.append(
        {
            "id": "analysis:confirmed",
            "kind": "confirmed_findings",
            "symbol_count": len(analysis.confirmed.symbols),
            "label_count": len(analysis.confirmed.labels),
            "references": [
                s.reference for s in analysis.confirmed.symbols if s.reference
            ],
        }
    )
    for index, finding in enumerate(analysis.erc.findings):
        items.append(_erc_evidence_item(index, finding))
    netlist = analysis.netlist
    items.append(
        {
            "id": "analysis:netlist",
            "kind": "netlist_report",
            "ran": netlist.ran,
            "available": netlist.available,
            "component_count": netlist.component_count,
            "net_count": netlist.net_count,
            "failure_reason": netlist.failure_reason,
        }
    )
    if analysis.evidence_graph is not None:
        items.append(
            {
                "id": "analysis:evidence_graph",
                "kind": "evidence_graph_summary",
                "node_count": len(analysis.evidence_graph.nodes),
                "edge_count": len(analysis.evidence_graph.edges),
            }
        )
    return items


def _erc_evidence_item(index: int, finding: ErcFinding) -> dict[str, Any]:
    return {
        "id": f"erc:{index}",
        "kind": "erc_finding",
        "rule_id": finding.rule_id,
        "severity": finding.severity,
        "description": finding.description,
        "reference": finding.reference,
        "pin": finding.pin,
        "source": finding.source,
    }


def _analyst_findings(analysis: AnalysisResponse) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for index, finding in enumerate(analysis.erc.findings):
        findings.append(
            {
                "id": f"finding:erc:{index}",
                "kind": "erc",
                "evidence_id": f"erc:{index}",
                "rule_id": finding.rule_id,
                "severity": finding.severity,
                "description": finding.description,
                "reference": finding.reference,
            }
        )
    if analysis.netlist.ran:
        findings.append(
            {
                "id": "finding:netlist",
                "kind": "netlist",
                "evidence_id": "analysis:netlist",
                "component_count": analysis.netlist.component_count,
                "net_count": analysis.netlist.net_count,
            }
        )
    elif analysis.netlist.failure_reason:
        findings.append(
            {
                "id": "finding:netlist_unavailable",
                "kind": "netlist",
                "evidence_id": "analysis:netlist",
                "failure_reason": analysis.netlist.failure_reason,
            }
        )
    return findings


def _netlist_summary(netlist: NetlistReport) -> str:
    if netlist.ran:
        return f"{netlist.net_count} net(s), {netlist.component_count} component(s)"
    if netlist.failure_reason:
        return f"unavailable: {netlist.failure_reason}"
    return "not run"


def _run_researcher(
    datasheet_evidence: (
        DatasheetIngestReport
        | DatasheetComponentLinkResponse
        | dict[str, Any]
        | list[Any]
        | None
    ),
) -> AgentResult:
    """Inspect supplied datasheet evidence only — no fabricated lookups."""
    if datasheet_evidence is None:
        return run_agent_task(
            AgentTask(role="researcher", action=ACTION_INSPECT_DATASHEET_EVIDENCE)
        )

    if isinstance(datasheet_evidence, list) and len(datasheet_evidence) == 0:
        return AgentResult(
            role="researcher",
            status="needs_input",
            summary=(
                "Datasheet evidence list was empty. "
                "The researcher does not invent datasheet facts or perform web search."
            ),
            error="empty_datasheet_evidence",
        )

    payload = _normalize_datasheet_payload(datasheet_evidence)
    if payload is None:
        return AgentResult(
            role="researcher",
            status="needs_input",
            summary=(
                "No usable datasheet evidence was supplied. "
                "The researcher does not invent datasheet facts or perform web search."
            ),
            error="unusable_datasheet_evidence",
        )

    result = run_agent_task(
        AgentTask(
            role="researcher",
            action=ACTION_INSPECT_DATASHEET_EVIDENCE,
            datasheet_evidence=payload,
        )
    )
    # Attach id'd evidence items from known datasheet modules when possible.
    extra = _datasheet_evidence_items(datasheet_evidence)
    if extra:
        result = result.model_copy(update={"evidence": list(result.evidence) + extra})
    return result


def _normalize_datasheet_payload(
    datasheet_evidence: (
        DatasheetIngestReport
        | DatasheetComponentLinkResponse
        | dict[str, Any]
        | list[Any]
    ),
) -> dict[str, Any] | list[Any] | None:
    if isinstance(datasheet_evidence, BaseModel):
        dumped = datasheet_evidence.model_dump()
        if isinstance(datasheet_evidence, DatasheetIngestReport):
            if (
                not datasheet_evidence.facts
                and not datasheet_evidence.raw_evidence
                and datasheet_evidence.status in {"empty", "error"}
            ):
                return None
        if isinstance(datasheet_evidence, DatasheetComponentLinkResponse):
            if datasheet_evidence.status == "error" and not datasheet_evidence.facts:
                return None
        return dumped
    if isinstance(datasheet_evidence, dict):
        return datasheet_evidence
    if isinstance(datasheet_evidence, list):
        return datasheet_evidence
    return None


def _datasheet_evidence_items(
    datasheet_evidence: (
        DatasheetIngestReport
        | DatasheetComponentLinkResponse
        | dict[str, Any]
        | list[Any]
    ),
) -> list[dict[str, Any]]:
    facts: list[NormalizedDatasheetFact] = []
    raw: list[RawDatasheetEvidence] = []
    if isinstance(datasheet_evidence, DatasheetIngestReport):
        facts = list(datasheet_evidence.facts)
        raw = list(datasheet_evidence.raw_evidence)
    elif isinstance(datasheet_evidence, DatasheetComponentLinkResponse):
        facts = list(datasheet_evidence.facts)
        raw = list(datasheet_evidence.raw_evidence)
    elif isinstance(datasheet_evidence, dict):
        # Only surface structured fields already present — do not invent facts.
        return [
            {
                "id": "datasheet:supplied",
                "kind": "datasheet_evidence",
                "keys": sorted(datasheet_evidence.keys()),
            }
        ]
    else:
        return [
            {
                "id": "datasheet:supplied_list",
                "kind": "datasheet_evidence",
                "item_count": len(datasheet_evidence),
            }
        ]

    items: list[dict[str, Any]] = []
    for index, fact in enumerate(facts):
        items.append(
            {
                "id": f"datasheet:fact:{index}",
                "kind": "normalized_datasheet_fact",
                "fact_id": fact.id,
                "fact_type": fact.fact_type,
                "value": fact.value,
                "unit": fact.unit,
                "page_number": fact.page_number,
                "supporting_evidence_id": fact.supporting_evidence_id,
            }
        )
    for index, evidence in enumerate(raw):
        items.append(
            {
                "id": f"datasheet:raw:{index}",
                "kind": "raw_datasheet_evidence",
                "evidence_id": evidence.id,
                "page_number": evidence.page_number,
                "char_count": len(evidence.text),
            }
        )
    return items


def _build_proposals_and_questions(
    *,
    analysis: AnalysisResponse,
    analyst: AgentResult,
    researcher: AgentResult,
) -> tuple[list[ProposedChange], list[str]]:
    """Build suggestion-only proposals grounded in analyst/researcher evidence."""
    proposals: list[ProposedChange] = []
    unresolved: list[str] = []

    for index, finding in enumerate(analysis.erc.findings):
        evidence_id = f"erc:{index}"
        ref = finding.reference or "unknown"
        proposals.append(
            ProposedChange(
                summary=(
                    f"Suggestion only: review ERC finding '{finding.rule_id}' "
                    f"on {ref} (severity={finding.severity})."
                ),
                details=(
                    f"{finding.description} "
                    "This is a suggestion only — CircuitSentinel will not modify "
                    "the schematic or certify a fix."
                ),
                target_reference=finding.reference,
                supporting_evidence_ids=[evidence_id, "analysis:confirmed"],
                suggestion_only=True,
            )
        )

    if researcher.status == "needs_input":
        unresolved.append(
            "Datasheet evidence is missing or unusable. "
            "Ingest and explicitly link a datasheet before drawing part-spec conclusions."
        )
        # Do not invent component specifications or fabricated lookups.
    elif researcher.status == "completed":
        fact_ids = [
            item["id"]
            for item in researcher.evidence
            if isinstance(item, dict) and item.get("kind") == "normalized_datasheet_fact"
        ]
        if fact_ids:
            proposals.append(
                ProposedChange(
                    summary=(
                        "Suggestion only: cross-check linked datasheet recommended "
                        "operating facts against the user-stated supply (not performed here)."
                    ),
                    details=(
                        "Researcher inspected supplied datasheet evidence only. "
                        "No automatic recommended-supply check was executed by this workflow, "
                        "and no schematic changes were applied."
                    ),
                    supporting_evidence_ids=fact_ids,
                    suggestion_only=True,
                )
            )
        else:
            unresolved.append(
                "Datasheet evidence was supplied but contained no normalized facts "
                "to ground a supply or part-spec suggestion."
            )

    if analyst.status == "error":
        unresolved.append("Analyst reported an error; proposals may be incomplete.")

    if not analysis.erc.ran and analysis.erc.failure_reason:
        unresolved.append(
            f"ERC did not run ({analysis.erc.failure_reason}). "
            "Install/configure kicad-cli to obtain ERC findings."
        )

    if not proposals and researcher.status != "needs_input":
        # Still allow empty proposal list — proposer will get needs_input if empty.
        pass

    return proposals, unresolved


def _run_proposer(proposals: list[ProposedChange]) -> AgentResult:
    """Record proposals through the permission registry. Never invokes tools."""
    if not proposals:
        return run_agent_task(
            AgentTask(role="proposer", action=ACTION_PROPOSE_CHANGE)
        )
    return run_agent_task(
        AgentTask(
            role="proposer",
            action=ACTION_PROPOSE_CHANGE,
            proposals=proposals,
        )
    )


def _assemble_report(
    *,
    analysis: AnalysisResponse,
    analyst: AgentResult,
    researcher: AgentResult,
    proposer: AgentResult,
    unresolved: list[str],
) -> CrewReport:
    findings = _analyst_findings(analysis)
    evidence: list[dict[str, Any]] = []
    # Prefer id'd schematic/datasheet items; skip bulky raw analysis dumps in the rollup.
    for item in analyst.evidence:
        if isinstance(item, dict) and item.get("id"):
            evidence.append(item)
    for item in researcher.evidence:
        if isinstance(item, dict) and (
            item.get("id") or item.get("kind") == "datasheet_evidence"
        ):
            evidence.append(item)

    proposed = list(proposer.proposed_changes)

    statuses = [analyst.status, researcher.status, proposer.status]
    if "error" in statuses or "rejected" in statuses:
        status: str = "error"
    elif "needs_input" in statuses:
        status = "needs_input"
    elif analysis.status == "error":
        status = "partial"
    elif analysis.status == "partial" or not analysis.erc.ran:
        status = "partial"
    else:
        status = "ok"

    limitations = list(WORKFLOW_LIMITATIONS)
    limitations.extend(analysis.limitations)
    if analysis.evidence_graph is not None:
        limitations.extend(analysis.evidence_graph.limitations)

    # De-duplicate limitations while preserving order.
    seen: set[str] = set()
    unique_limitations: list[str] = []
    for item in limitations:
        if item not in seen:
            seen.add(item)
            unique_limitations.append(item)

    return CrewReport(
        status=status,  # type: ignore[arg-type]
        analyst=analyst,
        researcher=researcher,
        proposer=proposer,
        findings=findings,
        evidence=evidence,
        proposed_changes=proposed,
        unresolved_questions=unresolved,
        limitations=unique_limitations,
    )


def _failure_report(*, error: str, summary: str) -> CrewReport:
    empty = AgentResult(
        role="workflow",
        status="error",
        summary=summary,
        error=error,
    )
    # Role-shaped placeholders so the report schema stays consistent.
    analyst = empty.model_copy(update={"role": "analyst"})
    researcher = empty.model_copy(update={"role": "researcher"})
    proposer = empty.model_copy(update={"role": "proposer"})
    return CrewReport(
        status="error",
        analyst=analyst,
        researcher=researcher,
        proposer=proposer,
        unresolved_questions=[summary],
        limitations=list(WORKFLOW_LIMITATIONS),
        error=error,
    )
