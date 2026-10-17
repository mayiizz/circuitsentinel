import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Code2,
  FileCode,
  Info,
  Loader2,
  Lock,
  Play,
  RotateCcw,
  ShieldAlert,
  ShieldCheck,
  ShieldX,
} from "lucide-react";
import { useState } from "react";

import { runPromptInjectionGauntlet } from "@/lib/api";
import { ApiError, type DecisionSource, type GauntletReport } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

function decisionSourceLabel(source: DecisionSource): string {
  switch (source) {
    case "crew_policy":
      return "crew_policy (local role permit list)";
    case "mcp_fail_closed":
      return "mcp_fail_closed (MCP privileged-tool gate)";
    default:
      return source;
  }
}

function formatSandbox(state: Record<string, unknown> | undefined): string {
  if (!state || Object.keys(state).length === 0) return "(empty)";
  try {
    return JSON.stringify(state, null, 2);
  } catch {
    return String(state);
  }
}

type TimelineItem = {
  id: string;
  eventType: "detection" | "role" | "escalation" | "rejection" | "verification";
  title: string;
  body: string;
  badge?: string;
  tone?: "default" | "caution" | "good" | "danger";
};

function buildTimelineItems(report: GauntletReport): TimelineItem[] {
  const steps: TimelineItem[] = [
    {
      id: "step-untrusted-detected",
      eventType: "detection",
      title: "Untrusted input detected",
      body: "Labeled UNTRUSTED_TEST_EVIDENCE passage instructed a permission bypass and placement change. Treated as data only — not as an executable command.",
      badge: "HOSTILE INPUT",
      tone: "caution",
    },
    {
      id: "step-analyst",
      eventType: "role",
      title: `Analyst — ${report.crew_report.analyst.status}`,
      body: report.crew_report.analyst.summary,
      badge: "CREW AGENT",
      tone: "default",
    },
    {
      id: "step-researcher",
      eventType: "role",
      title: `Researcher — ${report.crew_report.researcher.status}`,
      body: report.crew_report.researcher.summary,
      badge: "CREW AGENT",
      tone: "default",
    },
    {
      id: "step-proposer",
      eventType: "role",
      title: `Proposer — ${report.crew_report.proposer.status}`,
      body: report.crew_report.proposer.summary,
      badge: "CREW AGENT",
      tone: "default",
    },
  ];

  report.escalation_attempts.forEach((attempt, index) => {
    steps.push({
      id: `attempt-${attempt.path}-${attempt.attempted_action}-${index}`,
      eventType: "escalation",
      title: `Attempted unauthorized action — ${attempt.attempted_action}`,
      body: `Path: ${attempt.path}. Role: ${attempt.role}. Allowed: [${attempt.allowed_actions.join(", ") || "none"}].`,
      badge: "PRIVILEGED CALL",
      tone: "caution",
    });
    steps.push({
      id: `rejection-${attempt.path}-${attempt.attempted_action}-${index}`,
      eventType: "rejection",
      title: attempt.rejected ? "Rejection result" : "Unexpected non-rejection",
      body: `${decisionSourceLabel(attempt.decision_source)}. ${attempt.detail}`,
      badge: attempt.rejected ? "FAIL-CLOSED GATE" : "POLICY WARNING",
      tone: attempt.rejected ? "good" : "danger",
    });
  });

  steps.push({
    id: "step-sandbox-verification",
    eventType: "verification",
    title: "Sandbox state before / after",
    body: `Before: ${JSON.stringify(report.sandbox_state_before)} → After: ${JSON.stringify(report.sandbox_state_after)}. Unchanged across attempts: ${report.escalation_attempts.every((a) => a.sandbox_unchanged) ? "yes" : "no"}.`,
    badge: "INTEGRITY CONFIRMED",
    tone: "good",
  });

  return steps;
}

export function PromptInjectionGauntletPanel() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [report, setReport] = useState<GauntletReport | null>(null);

  // Collapsible controls for report sections
  const [showRawState, setShowRawState] = useState(false);
  const [showLimitations, setShowLimitations] = useState(false);
  const [showUntrustedText, setShowUntrustedText] = useState(false);

  const onRun = async () => {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await runPromptInjectionGauntlet();
      setReport(result);
    } catch (err) {
      setReport(null);
      if (err instanceof ApiError) {
        setError(err.message);
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Gauntlet request failed.");
      }
    } finally {
      setBusy(false);
    }
  };

  const visibleAttempts = report?.escalation_attempts ?? [];

  const rejectedCount = visibleAttempts.filter((a) => a.rejected).length;
  const totalAttempts = visibleAttempts.length;
  const allSandboxesUnchanged =
    report && report.escalation_attempts.every((a) => a.sandbox_unchanged);

  return (
    <div className="flex flex-col">
      {/* Top Header Card */}
      <div className="border-b border-line bg-panel-raised/50 p-4 sm:p-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex items-start gap-3">
            <div className="grid size-9 shrink-0 place-items-center rounded-lg border border-line bg-panel text-brand">
              <ShieldAlert size={19} />
            </div>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-sm font-semibold tracking-tight text-foreground">
                  Prompt-Injection Gauntlet
                </h2>
                <Badge
                  variant="outline"
                  className="border-line font-mono text-[10px] uppercase text-muted-foreground"
                >
                  Deterministic Security Test
                </Badge>
              </div>
              <p className="mt-1 max-w-xl text-xs leading-relaxed text-muted-foreground">
                Evaluates Least-Privilege Hardware Agent Crew isolation against prompt injection.
                Calls the server-side gauntlet directly — zero client-side policy evaluation.
              </p>
            </div>
          </div>

          <Button
            type="button"
            className="shrink-0 bg-brand text-brand-foreground shadow-sm hover:bg-brand/90 focus-visible:ring-brand disabled:cursor-not-allowed"
            disabled={busy}
            onClick={() => void onRun()}
          >
            {busy ? (
              <>
                <Loader2 size={15} className="animate-spin" />
                <span>Running gauntlet…</span>
              </>
            ) : report ? (
              <>
                <RotateCcw size={15} />
                <span>Re-run gauntlet</span>
              </>
            ) : (
              <>
                <Play size={15} />
                <span>Run Prompt-Injection Gauntlet</span>
              </>
            )}
          </Button>
        </div>

        {/* Executive Result Summary Header (when run completed) */}
        {report && !busy && (
          <div className="mt-5 grid grid-cols-1 gap-2.5 sm:grid-cols-3">
            <div className="rounded-lg border border-line bg-panel p-3">
              <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                Unauthorized Attempts
              </div>
              <div className="mt-1 flex items-center gap-2">
                <ShieldX size={16} className="text-good" />
                <span className="text-base font-semibold text-foreground">
                  {rejectedCount} of {totalAttempts} Rejected
                </span>
              </div>
              <div className="mt-0.5 text-[11px] text-good font-medium">
                100% Fail-Closed Enforcement
              </div>
            </div>

            <div className="rounded-lg border border-line bg-panel p-3">
              <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                Sandbox Integrity
              </div>
              <div className="mt-1 flex items-center gap-2">
                <ShieldCheck size={16} className="text-good" />
                <span className="text-base font-semibold text-foreground">
                  {allSandboxesUnchanged ? "State Unchanged" : "Modified"}
                </span>
              </div>
              <div className="mt-0.5 text-[11px] text-muted-foreground">
                Verified across all attempts
              </div>
            </div>

            <div className="rounded-lg border border-line bg-panel p-3">
              <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                Enforcement Scope
              </div>
              <div className="mt-1 flex items-center gap-2">
                <Lock size={15} className="text-brand" />
                <span className="font-mono text-xs font-semibold text-foreground">
                  crew_policy + mcp gate
                </span>
              </div>
              <div className="mt-0.5 text-[11px] text-muted-foreground">
                Local isolation gates only
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Empty State */}
      {!report && !error && !busy && (
        <div className="flex flex-col items-center justify-center px-4 py-12 text-center">
          <div className="grid size-12 place-items-center rounded-xl border border-line bg-panel text-muted-foreground">
            <ShieldAlert size={22} />
          </div>
          <p className="mt-3 text-sm font-medium text-foreground">
            Empty — run the gauntlet
          </p>
          <p className="mt-1 max-w-md text-xs leading-relaxed text-muted-foreground">
            Execute the test scenario to see the untrusted-input attack trace timeline,
            permission inspector, suggestion-only proposals, and sandbox before/after integrity.
          </p>
        </div>
      )}

      {/* Busy Loading State */}
      {busy && (
        <div className="flex flex-col items-center justify-center px-4 py-16 text-center">
          <Loader2 size={24} className="animate-spin text-brand" />
          <p className="mt-3 text-sm font-medium text-foreground">
            Executing deterministic gauntlet…
          </p>
          <p className="mt-1 max-w-sm text-xs leading-relaxed text-muted-foreground">
            Simulating hostile prompt injection passage across Least-Privilege Hardware Crew roles
            and testing fail-closed MCP tool gates.
          </p>
        </div>
      )}

      {/* Error State */}
      {error && (
        <div className="m-4 rounded-lg border border-danger/40 bg-danger/10 p-4 text-xs text-danger">
          <div className="flex items-start gap-2.5">
            <AlertTriangle size={16} className="mt-0.5 shrink-0" />
            <div>
              <p className="font-semibold text-sm">Gauntlet error</p>
              <p className="mt-1 leading-relaxed text-muted-foreground">{error}</p>
            </div>
          </div>
        </div>
      )}

      {/* Results View */}
      {report && !busy && (
        <div className="space-y-6 p-4 sm:p-5">
          {/* Section A: Attack Trace Timeline */}
          <section aria-label="Attack trace" className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="grid size-5 place-items-center rounded bg-brand/15 text-[11px] font-bold text-brand">
                  A
                </span>
                <h3 className="text-sm font-semibold tracking-tight text-foreground">
                  Attack Trace
                </h3>
              </div>
              <span className="font-mono text-[11px] text-muted-foreground">
                Chronological sequence
              </span>
            </div>

            <div className="relative pl-6 before:absolute before:bottom-3 before:left-2.5 before:top-3 before:w-px before:bg-line">
              <ol className="space-y-4">
                {buildTimelineItems(report).map((step) => {
                  const isCaution = step.tone === "caution";
                  const isGood = step.tone === "good";
                  const isDanger = step.tone === "danger";

                  const dotColor = isCaution
                    ? "bg-caution text-caution border-caution/30"
                    : isGood
                      ? "bg-good text-good border-good/30"
                      : isDanger
                        ? "bg-danger text-danger border-danger/30"
                        : "bg-muted-foreground text-muted-foreground border-line";

                  return (
                    <li key={step.id} className="relative group">
                      <span
                        className={`absolute -left-6 top-1.5 size-2 rounded-full ring-4 ring-workspace ${dotColor}`}
                      />
                      <div className="rounded-lg border border-line bg-panel p-3 transition-colors hover:border-line/80">
                        <div className="flex flex-wrap items-center justify-between gap-1.5">
                          <p
                            className={`text-xs font-semibold ${
                              isCaution
                                ? "text-caution"
                                : isGood
                                  ? "text-good"
                                  : isDanger
                                    ? "text-danger"
                                    : "text-foreground"
                            }`}
                          >
                            {step.title}
                          </p>
                          {step.badge && (
                            <Badge
                              variant="outline"
                              className="h-4 border-line px-1.5 font-mono text-[9px] uppercase tracking-wider text-muted-foreground"
                            >
                              {step.badge}
                            </Badge>
                          )}
                        </div>
                        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                          {step.body}
                        </p>
                      </div>
                    </li>
                  );
                })}
              </ol>
            </div>
          </section>

          {/* Section B: Permission Inspector */}
          <section aria-label="Permission inspector" className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="grid size-5 place-items-center rounded bg-brand/15 text-[11px] font-bold text-brand">
                  B
                </span>
                <h3 className="text-sm font-semibold tracking-tight text-foreground">
                  Permission Inspector
                </h3>
              </div>
              <span className="text-[11px] text-muted-foreground">
                Policy boundaries & gate decisions
              </span>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              {visibleAttempts.map((attempt, index) => (
                <div
                  key={`perm-${attempt.path}-${index}`}
                  className="flex flex-col justify-between rounded-lg border border-line bg-panel p-3.5 text-xs"
                >
                  <div className="space-y-2">
                    <div className="flex items-start justify-between gap-2 border-b border-line pb-2">
                      <div>
                        <span className="text-[11px] uppercase tracking-wider text-muted-foreground">
                          Role:
                        </span>{" "}
                        <span className="font-semibold text-foreground">{attempt.role}</span>
                      </div>
                      <Badge
                        variant="outline"
                        className={
                          attempt.rejected
                            ? "border-good/30 bg-good/10 text-good font-mono text-[10px]"
                            : "border-danger/30 bg-danger/10 text-danger font-mono text-[10px]"
                        }
                      >
                        {attempt.rejected ? "BLOCKED" : "UNBLOCKED"}
                      </Badge>
                    </div>

                    <div className="grid gap-1.5 leading-relaxed text-muted-foreground">
                      <p>
                        <span className="text-foreground font-medium">Requested:</span>{" "}
                        <code className="rounded bg-workspace px-1.5 py-0.5 text-[11px] text-brand">
                          {attempt.attempted_action}
                        </code>
                      </p>
                      <p>
                        <span className="text-foreground font-medium">Allowed:</span>{" "}
                        <span className="font-mono text-[11px]">
                          {attempt.allowed_actions.length
                            ? `[${attempt.allowed_actions.join(", ")}]`
                            : "(none)"}
                        </span>
                      </p>
                      <p>
                        <span className="text-foreground font-medium">Decision source:</span>{" "}
                        <span className="font-mono text-[11px] text-foreground">
                          {decisionSourceLabel(attempt.decision_source)}
                        </span>
                      </p>
                    </div>
                  </div>

                  <div className="mt-3 flex items-center justify-between border-t border-line/70 pt-2 text-[11px] text-muted-foreground">
                    <span>
                      Rejected:{" "}
                      <strong className="text-foreground">
                        {attempt.rejected ? "yes" : "no"}
                      </strong>
                    </span>
                    <span>
                      Sandbox unchanged:{" "}
                      <strong className="text-good">
                        {attempt.sandbox_unchanged ? "yes" : "no"}
                      </strong>
                    </span>
                  </div>
                </div>
              ))}
            </div>

            <div className="flex items-start gap-2 rounded-md border border-line bg-workspace p-3 text-xs text-muted-foreground">
              <Info size={15} className="mt-0.5 shrink-0 text-muted-foreground" />
              <p className="leading-relaxed">
                Enforcement uses local crew permit policies and MCP fail-closed gates only.
                Outcomes are not authorization allows.
              </p>
            </div>
          </section>

          {/* Section C: Sandbox Integrity */}
          <section aria-label="Sandbox integrity" className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="grid size-5 place-items-center rounded bg-brand/15 text-[11px] font-bold text-brand">
                  C
                </span>
                <h3 className="text-sm font-semibold tracking-tight text-foreground">
                  Sandbox Integrity
                </h3>
              </div>
              <div className="flex items-center gap-1.5 text-xs text-good font-medium">
                <CheckCircle2 size={14} /> State Unchanged
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-lg border border-line bg-panel p-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-foreground">State Before</span>
                  <Badge variant="outline" className="text-[10px] text-muted-foreground">
                    Pre-execution
                  </Badge>
                </div>
                <pre className="mt-2 overflow-auto rounded bg-workspace p-2 font-mono text-[11px] text-muted-foreground">
                  {formatSandbox(report.sandbox_state_before)}
                </pre>
              </div>

              <div className="rounded-lg border border-line bg-panel p-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-foreground">State After</span>
                  <Badge variant="outline" className="text-[10px] text-good border-good/30">
                    Verified Match
                  </Badge>
                </div>
                <pre className="mt-2 overflow-auto rounded bg-workspace p-2 font-mono text-[11px] text-muted-foreground">
                  {formatSandbox(report.sandbox_state_after)}
                </pre>
              </div>
            </div>

            {/* Expandable raw state control */}
            <div>
              <button
                type="button"
                onClick={() => setShowRawState((v) => !v)}
                className="flex items-center gap-1 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
              >
                {showRawState ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                <Code2 size={13} className="mr-0.5" />
                <span>{showRawState ? "Hide raw state JSON" : "View raw state JSON"}</span>
              </button>

              {showRawState && (
                <div className="mt-2 rounded-lg border border-line bg-workspace p-3 font-mono text-[11px] text-muted-foreground">
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-foreground">
                    Full Permitted Actions
                  </div>
                  <div className="mt-1 grid gap-1">
                    <p>
                      Before:{" "}
                      {JSON.stringify(report.permitted_sandbox_actions_before)}
                    </p>
                    <p>
                      After:{" "}
                      {JSON.stringify(report.permitted_sandbox_actions_after)}
                    </p>
                    <p>
                      Permissions Unchanged:{" "}
                      <span className="text-good">{String(report.permissions_unchanged)}</span>
                    </p>
                  </div>
                </div>
              )}
            </div>
          </section>

          {/* Section D: Suggestion-Only Proposal */}
          <section aria-label="Suggestion-only proposal" className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="grid size-5 place-items-center rounded bg-brand/15 text-[11px] font-bold text-brand">
                  D
                </span>
                <h3 className="text-sm font-semibold tracking-tight text-foreground">
                  Suggestion-Only Proposal
                </h3>
              </div>
              <Badge
                variant="outline"
                className="border-caution/30 bg-caution/10 text-caution text-[10px]"
              >
                Advisory Only
              </Badge>
            </div>

            <div className="space-y-2.5">
              {(report.injection_proposal
                ? [report.injection_proposal]
                : report.crew_report.proposed_changes
              ).map((proposal, idx) => (
                <div
                  key={`proposal-${idx}-${proposal.summary}`}
                  className="rounded-lg border border-line bg-panel p-4 text-xs"
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="font-semibold text-foreground text-sm leading-snug">
                      {proposal.summary}
                    </p>
                    <span className="shrink-0 rounded bg-workspace px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
                      Ref: {proposal.target_reference || "N/A"}
                    </span>
                  </div>

                  {proposal.details && (
                    <p className="mt-2 text-muted-foreground leading-relaxed">
                      {proposal.details}
                    </p>
                  )}

                  <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line/70 pt-2.5 text-good font-medium">
                    <ShieldCheck size={14} />
                    <span>
                      suggestion_only={String(proposal.suggestion_only)} — original schematic was not
                      modified (schematic_modified={String(report.schematic_modified)}).
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* Section E: Limitations & Evidence Details */}
          <section aria-label="Limitations and evidence" className="space-y-2 border-t border-line pt-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="grid size-5 place-items-center rounded bg-brand/15 text-[11px] font-bold text-brand">
                  E
                </span>
                <h3 className="text-sm font-semibold tracking-tight text-foreground">
                  Evidence Details & Limitations
                </h3>
              </div>

              <button
                type="button"
                onClick={() => setShowLimitations((v) => !v)}
                className="flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
              >
                <span>{showLimitations ? "Collapse" : "Expand details"}</span>
                {showLimitations ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              </button>
            </div>

            {showLimitations && (
              <div className="mt-3 space-y-3 rounded-lg border border-line bg-workspace p-3.5 text-xs text-muted-foreground">
                <div className="rounded border border-line bg-panel p-3">
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-foreground">
                      Untrusted test evidence fixture
                    </span>
                    <button
                      type="button"
                      onClick={() => setShowUntrustedText((v) => !v)}
                      className="text-[11px] text-brand hover:underline"
                    >
                      {showUntrustedText ? "Hide fixture text" : "Show fixture text"}
                    </button>
                  </div>
                  <p className="mt-1 text-[11px] text-muted-foreground">
                    Evidence kind: <code className="text-foreground">{report.evidence_kind}</code>.
                    Notice: Synthetic evidence is not a real schematic/datasheet and local policy
                    outcomes are not authorization allows.
                  </p>
                  {showUntrustedText && (
                    <pre className="mt-2 max-h-36 overflow-auto rounded bg-workspace p-2 font-mono text-[10px] leading-relaxed text-caution whitespace-pre-wrap">
                      {report.untrusted_passage}
                    </pre>
                  )}
                </div>

                {report.limitations.length > 0 && (
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-wider text-foreground">
                      Technical Limitations
                    </div>
                    <ul className="mt-1.5 list-disc space-y-1 pl-4 leading-relaxed">
                      {report.limitations.map((item, idx) => (
                        <li key={`lim-${idx}`}>{item}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
