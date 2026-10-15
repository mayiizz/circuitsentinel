"""Deterministic crew workflow tests (evidence-grounded milestone)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from app.agents import (
    ACTION_REQUEST_GOVERNED_ACTION,
    ROLE_PERMISSIONS,
    AgentTask,
    ProposedChange,
    run_agent_task,
    run_crew_workflow,
)
from app.agents.workflow import WORKFLOW_LIMITATIONS
from app.datasheets.models import (
    DatasheetIngestReport,
    DatasheetSource,
    NormalizedDatasheetFact,
    RawDatasheetEvidence,
)
from app.schematics.models import (
    AnalysisResponse,
    ConfirmedFindings,
    ErcFinding,
    ErcReport,
    NetlistComponent,
    NetlistNet,
    NetlistNode,
    NetlistReport,
    SymbolFinding,
    UploadInfo,
)


def _analysis_with_erc(*, with_netlist: bool = True) -> AnalysisResponse:
    erc = ErcReport(
        ran=True,
        available=True,
        findings=[
            ErcFinding(
                rule_id="power_pin_not_driven",
                severity="error",
                description="Input Power pin not driven by any Output Power pins",
                reference="U1",
                pin="3",
            ),
            ErcFinding(
                rule_id="lib_symbol_mismatch",
                severity="warning",
                description="Symbol library mismatch",
                reference="U1",
            ),
        ],
        error_count=1,
        warning_count=1,
    )
    netlist = NetlistReport(
        ran=True,
        available=True,
        format="kicadxml",
        components=[
            NetlistComponent(reference="U1", value="LM358", lib_id="Amplifier_Operational:LM358")
        ],
        nets=[
            NetlistNet(
                code="1",
                name="+3V3",
                name_kind="explicit",
                nodes=[NetlistNode(reference="U1", pin="8")],
            )
        ],
        component_count=1,
        net_count=1,
    )
    if not with_netlist:
        netlist = NetlistReport(
            ran=False,
            available=False,
            failure_reason="kicad-cli netlist export unavailable.",
        )
    return AnalysisResponse(
        status="partial",
        upload=UploadInfo(
            original_filename="opamp.kicad_sch",
            stored_as="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.kicad_sch",
            format="kicad_sch",
            size_bytes=100,
        ),
        confirmed=ConfirmedFindings(
            symbols=[
                SymbolFinding(
                    reference="U1",
                    value="LM358",
                    lib_id="Amplifier_Operational:LM358",
                    uuid="u1",
                )
            ]
        ),
        erc=erc,
        netlist=netlist,
        limitations=["Test fixture analysis."],
    )


def _datasheet_report_with_fact() -> DatasheetIngestReport:
    raw = RawDatasheetEvidence(
        id="raw-1",
        document_id="doc-1",
        page_number=5,
        text="Recommended operating supply 3 V to 30 V",
    )
    fact = NormalizedDatasheetFact(
        id="fact-1",
        fact_type="supply_voltage_min",
        value=3.0,
        unit="V",
        source_content_sha256="a" * 64,
        page_number=5,
        supporting_evidence_id="raw-1",
        supporting_excerpt="3 V to 30 V",
    )
    return DatasheetIngestReport(
        status="ok",
        source=DatasheetSource(
            document_id="doc-1",
            filename="lm358.pdf",
            content_sha256="a" * 64,
            page_count=1,
            byte_length=10,
        ),
        raw_evidence=[raw],
        facts=[fact],
    )


def test_workflow_analyst_uses_erc_and_netlist_evidence() -> None:
    analysis = _analysis_with_erc()
    report = run_crew_workflow(analysis, datasheet_evidence=None)

    assert report.analyst.status == "completed"
    assert report.analyst.role == "analyst"
    assert "ERC" in report.analyst.summary
    assert "netlist" in report.analyst.summary.lower()

    erc_ids = [e["id"] for e in report.evidence if e.get("kind") == "erc_finding"]
    assert erc_ids == ["erc:0", "erc:1"]
    assert any(e.get("id") == "analysis:netlist" for e in report.evidence)
    assert any(f.get("kind") == "erc" for f in report.findings)
    assert any(f.get("kind") == "netlist" for f in report.findings)


def test_workflow_missing_research_evidence_needs_input() -> None:
    analysis = _analysis_with_erc()
    report = run_crew_workflow(analysis)

    assert report.researcher.status == "needs_input"
    assert report.researcher.error == "missing_datasheet_evidence"
    assert report.status == "needs_input"
    assert any("Datasheet evidence is missing" in q for q in report.unresolved_questions)
    # No fabricated datasheet facts or invented part specs.
    assert not any(
        e.get("kind") == "normalized_datasheet_fact" for e in report.evidence
    )
    unsupported_markers = ("invented", "web search result", "fetched datasheet")
    blob = " ".join(
        [report.researcher.summary]
        + [c.summary for c in report.proposed_changes]
        + report.unresolved_questions
    ).lower()
    assert "fetched datasheet" not in blob
    assert "web search result" not in blob


def test_workflow_unsupported_claims_absent() -> None:
    """Workflow must not invent voltages, connectivity, or executed fixes."""
    analysis = _analysis_with_erc()
    report = run_crew_workflow(analysis)

    text = " ".join(
        [
            report.analyst.summary,
            report.researcher.summary,
            report.proposer.summary,
            *[c.summary for c in report.proposed_changes],
            *[c.details or "" for c in report.proposed_changes],
        ]
    ).lower()
    for banned in (
        "certified safe",
        "voltage measured",
        "auto-fixed",
        "schematic modified",
        "fabricated datasheet",
    ):
        assert banned not in text

    # Net names from the analysis must not be treated as measured voltages in proposals.
    for change in report.proposed_changes:
        assert "+3V3" not in (change.summary + (change.details or ""))
        assert change.suggestion_only is True


def test_workflow_proposals_are_suggestion_only_and_evidence_grounded() -> None:
    analysis = _analysis_with_erc()
    report = run_crew_workflow(analysis, datasheet_evidence=_datasheet_report_with_fact())

    assert report.proposer.status == "completed"
    assert report.proposer.role == "proposer"
    assert len(report.proposed_changes) >= 2  # ERC findings + datasheet cross-check
    assert all(c.suggestion_only for c in report.proposed_changes)
    assert all(c.supporting_evidence_ids for c in report.proposed_changes)

    erc_proposal = next(
        c for c in report.proposed_changes if "power_pin_not_driven" in c.summary
    )
    assert "erc:0" in erc_proposal.supporting_evidence_ids
    assert "Suggestion only" in erc_proposal.summary
    assert erc_proposal.target_reference == "U1"

    # Proposer permission registry unchanged — still cannot request tools.
    assert ACTION_REQUEST_GOVERNED_ACTION not in ROLE_PERMISSIONS["proposer"]


def test_workflow_proposer_never_invokes_tools() -> None:
    analysis = _analysis_with_erc()
    with patch("app.agents.orchestrator.invoke_governed_tool") as mock_invoke:
        report = run_crew_workflow(
            analysis, datasheet_evidence=_datasheet_report_with_fact()
        )
        mock_invoke.assert_not_called()
    assert report.proposer.requested_actions == []
    assert report.proposer.governed_decision is None
    assert all(c.suggestion_only for c in report.proposed_changes)


def test_workflow_with_datasheet_evidence_completes_researcher() -> None:
    analysis = _analysis_with_erc()
    report = run_crew_workflow(
        analysis, datasheet_evidence=_datasheet_report_with_fact()
    )
    assert report.researcher.status == "completed"
    assert any(
        e.get("kind") == "normalized_datasheet_fact" for e in report.evidence
    )
    assert any(
        "cross-check linked datasheet" in c.summary.lower()
        for c in report.proposed_changes
    )


def test_workflow_failure_handling_invalid_analysis() -> None:
    report = run_crew_workflow("not-an-analysis")  # type: ignore[arg-type]
    assert report.status == "error"
    assert report.error == "invalid_analysis"
    assert report.analyst.status == "error"
    assert report.researcher.status == "error"
    assert report.proposer.status == "error"
    assert report.proposed_changes == []
    for limitation in WORKFLOW_LIMITATIONS:
        assert limitation in report.limitations


def test_workflow_failure_handling_internal_exception() -> None:
    analysis = _analysis_with_erc()
    with patch(
        "app.agents.workflow._run_analyst",
        side_effect=RuntimeError("boom"),
    ):
        report = run_crew_workflow(analysis)
    assert report.status == "error"
    assert report.error == "workflow_exception:RuntimeError"
    assert report.proposed_changes == []


def test_workflow_does_not_modify_analysis_or_execute_proposals() -> None:
    analysis = _analysis_with_erc()
    before = analysis.model_dump()
    report = run_crew_workflow(analysis)
    assert analysis.model_dump() == before
    assert all("will not modify" in (c.details or "").lower() or c.suggestion_only for c in report.proposed_changes)


def test_empty_proposal_path_still_permission_safe() -> None:
    """Analysis with no ERC and no datasheet → proposer needs_input, no tools."""
    analysis = AnalysisResponse(
        status="ok",
        confirmed=ConfirmedFindings(
            symbols=[SymbolFinding(reference="R1", value="10k", uuid="r1")]
        ),
        erc=ErcReport(ran=True, available=True, findings=[]),
        netlist=NetlistReport(ran=True, available=True, component_count=1, net_count=0),
    )
    with patch("app.agents.orchestrator.invoke_governed_tool") as mock_invoke:
        report = run_crew_workflow(analysis, datasheet_evidence=None)
        mock_invoke.assert_not_called()
    assert report.proposer.status == "needs_input"
    assert report.proposed_changes == []
    assert report.researcher.status == "needs_input"


def test_single_propose_change_still_works_via_orchestrator() -> None:
    result = run_agent_task(
        AgentTask(
            role="proposer",
            action="propose_change",
            proposal=ProposedChange(summary="Nudge silkscreen"),
        )
    )
    assert result.status == "completed"
    assert result.proposed_changes[0].suggestion_only is True
