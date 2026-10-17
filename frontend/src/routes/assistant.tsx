import { Link, createFileRoute } from "@tanstack/react-router";
import { MessageSquare, Sparkles } from "lucide-react";
import { useState } from "react";

import { ErrorState } from "@/components/eda/ErrorState";
import { StatusBadge } from "@/components/eda/StatusBadge";
import { AppTopBar } from "@/components/layout/AppTopBar";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { assistantChat } from "@/lib/api";
import { ApiError, type AssistantChatResponse } from "@/lib/types";
import { useWorkspace } from "@/lib/workspace";

export const Route = createFileRoute("/assistant")({
  component: AssistantPage,
});

const PROMPTS = [
  {
    label: "Sandbox status",
    message: "What is the sandbox component status?",
    createProposal: false,
    action: "none" as const,
  },
  {
    label: "ERC & rails",
    message: "Please summarize ERC and supply rails for this schematic.",
    createProposal: false,
    action: "none" as const,
  },
  {
    label: "Read proposal",
    message: "Propose a read of the sandbox component status",
    createProposal: true,
    action: "get_component_status" as const,
  },
  {
    label: "Placement proposal",
    message: "Please propose a sandbox placement",
    createProposal: true,
    action: "simulate_unverified_placement" as const,
  },
];

export function AssistantPage() {
  const { analysis } = useWorkspace();
  const fileId = analysis?.upload?.file_id ?? null;
  const [message, setMessage] = useState("Summarize the sandbox component status.");
  const [createProposal, setCreateProposal] = useState(false);
  const [proposedAction, setProposedAction] = useState<
    "none" | "get_component_status" | "simulate_unverified_placement"
  >("none");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<AssistantChatResponse | null>(null);

  const onAsk = async () => {
    setBusy(true);
    setError("");
    try {
      const response = await assistantChat({
        message,
        schematic_file_id: fileId,
        create_proposal: createProposal,
        proposed_action: createProposal ? proposedAction : "none",
        proposed_params:
          createProposal && proposedAction === "simulate_unverified_placement"
            ? { reference: "ASSIST-R1", x_mm: 10, y_mm: 20 }
            : {},
      });
      setResult(response);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Assistant request failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <AppTopBar />
      <div className="flex-1 space-y-6 overflow-auto p-4 md:p-6">
        <PageHeader
          title="AI assistant"
          description="Ask about the current circuit or sandbox. The assistant may call allowlisted read-only tools and create pending HITL proposals — it cannot approve or execute."
          meta={
            fileId ? (
              <p className="font-mono text-[11px] text-muted-foreground">
                schematic_file_id={fileId}
              </p>
            ) : (
              <p className="text-xs text-caution">
                No schematic loaded — circuit analysis context will be skipped. Sandbox questions
                still work.
              </p>
            )
          }
        />

        <section className="cs-panel space-y-4 p-4 md:p-5">
          <div>
            <p className="mb-2 text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
              Try a prompt
            </p>
            <div className="flex flex-wrap gap-2">
              {PROMPTS.map((prompt) => (
                <button
                  key={prompt.label}
                  type="button"
                  className="cs-prompt-chip"
                  onClick={() => {
                    setMessage(prompt.message);
                    setCreateProposal(prompt.createProposal);
                    setProposedAction(prompt.action);
                  }}
                >
                  {prompt.label}
                </button>
              ))}
            </div>
          </div>

          <label className="block text-xs text-muted-foreground">
            Question
            <textarea
              className="mt-1.5 min-h-28 w-full rounded-lg border border-line bg-panel-raised px-3 py-2.5 text-sm text-foreground outline-none transition-colors focus:border-brand/50 focus:ring-2 focus:ring-brand/20"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
            />
          </label>

          <div className="rounded-lg border border-line/80 bg-workspace/50 p-3">
            <label className="flex items-start gap-2.5 text-xs">
              <input
                type="checkbox"
                className="mt-0.5"
                checked={createProposal}
                onChange={(e) => setCreateProposal(e.target.checked)}
              />
              <span>
                <span className="font-medium text-foreground">
                  Also create a pending HITL proposal
                </span>
                <span className="mt-0.5 block text-muted-foreground">
                  Creates a proposal only — never executes. Approve from Governance.
                </span>
              </span>
            </label>
            {createProposal && (
              <label className="mt-3 block text-xs text-muted-foreground">
                Proposed action
                <select
                  className="mt-1.5 w-full rounded-md border border-line bg-panel-raised px-2.5 py-2 text-sm text-foreground"
                  value={proposedAction}
                  onChange={(e) =>
                    setProposedAction(
                      e.target.value as
                        | "none"
                        | "get_component_status"
                        | "simulate_unverified_placement",
                    )
                  }
                >
                  <option value="none">Infer read-only (get_component_status)</option>
                  <option value="get_component_status">get_component_status</option>
                  <option value="simulate_unverified_placement">
                    simulate_unverified_placement (sandbox only)
                  </option>
                </select>
              </label>
            )}
          </div>

          {error && <ErrorState title="Assistant error" message={error} />}

          <div className="flex flex-wrap items-center gap-3">
            <Button disabled={busy || !message.trim()} onClick={() => void onAsk()}>
              <Sparkles size={14} />
              {busy ? "Working…" : "Ask assistant"}
            </Button>
            <p className="text-[11px] text-muted-foreground">
              Read tools only · proposals require human approval
            </p>
          </div>
        </section>

        {result && (
          <section className="cs-panel cs-fade-up space-y-4 p-4 md:p-5">
            <div className="flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center gap-1.5 text-xs font-medium text-foreground">
                <MessageSquare size={14} className="text-brand" /> Response
              </span>
              <StatusBadge
                tone={result.mode === "demo" ? "caution" : "info"}
                label={result.mode === "demo" ? "deterministic-demo" : "llm"}
              />
              {result.proposal_created && result.proposal_id && (
                <StatusBadge tone="caution" label={`proposal:${result.proposal_status}`} />
              )}
            </div>

            <div className="rounded-lg border border-line bg-panel-raised/70 px-4 py-3">
              <p className="text-sm leading-6 whitespace-pre-wrap">{result.answer}</p>
            </div>

            {result.tools_used.length > 0 && (
              <p className="text-xs text-muted-foreground">
                Tools used:{" "}
                <span className="font-mono text-foreground/80">{result.tools_used.join(", ")}</span>
              </p>
            )}

            {result.uncertainty.length > 0 && (
              <div>
                <h3 className="text-xs font-medium">Uncertainty</h3>
                <ul className="mt-1 list-disc pl-4 text-xs text-muted-foreground">
                  {result.uncertainty.map((u) => (
                    <li key={u}>{u}</li>
                  ))}
                </ul>
              </div>
            )}

            {result.proposal_created && result.proposal_id && (
              <div className="rounded-lg border border-caution/30 bg-caution/5 px-3 py-2.5 text-xs">
                Pending proposal{" "}
                <Link
                  to="/governance"
                  className="font-mono text-brand underline underline-offset-2"
                >
                  {result.proposal_id}
                </Link>{" "}
                — open Governance to approve or reject. The assistant cannot approve it.
              </div>
            )}

            <p className="font-mono text-[10px] leading-4 text-muted-foreground">
              graph: {result.graph_path.join(" → ")}
            </p>
          </section>
        )}
      </div>
    </>
  );
}
