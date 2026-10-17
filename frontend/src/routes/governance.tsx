import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import { ConfirmDialog } from "@/components/eda/ConfirmDialog";
import { EmptyState } from "@/components/eda/EmptyState";
import { ErrorState } from "@/components/eda/ErrorState";
import { StatusBadge } from "@/components/eda/StatusBadge";
import { AppTopBar } from "@/components/layout/AppTopBar";
import { Button } from "@/components/ui/button";
import {
  approveProposal,
  createDemoProposal,
  createProposal,
  listProposals,
  reconcileProposal,
  rejectProposal,
} from "@/lib/api";
import {
  ApiError,
  type ActionProposal,
  type ProposalStatus,
  type SupportedProposalAction,
} from "@/lib/types";

export const Route = createFileRoute("/governance")({
  component: GovernancePage,
});

function statusTone(
  status: ProposalStatus,
): "good" | "caution" | "danger" | "info" | "neutral" {
  switch (status) {
    case "executed":
      return "good";
    case "pending":
    case "approved":
      return "caution";
    case "rejected":
    case "failed":
    case "uncertain":
      return "danger";
    default:
      return "neutral";
  }
}

function isExpired(proposal: ActionProposal): boolean {
  return Date.parse(proposal.expires_at) <= Date.now();
}

export function GovernancePage() {
  const [proposals, setProposals] = useState<ActionProposal[]>([]);
  const [statusFilter, setStatusFilter] = useState<ProposalStatus | "all">("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [listError, setListError] = useState("");
  const [listLoading, setListLoading] = useState(true);
  const [actionBusy, setActionBusy] = useState(false);
  const [confirm, setConfirm] = useState<{
    kind: "approve" | "reject" | "reconcile";
    id: string;
  } | null>(null);

  const [createAction, setCreateAction] = useState<SupportedProposalAction>("get_component_status");
  const [reference, setReference] = useState("TEST-R1");
  const [xMm, setXMm] = useState("10");
  const [yMm, setYMm] = useState("20");
  const [prompt, setPrompt] = useState("");
  const [createError, setCreateError] = useState("");

  const selected = proposals.find((p) => p.id === selectedId) ?? null;

  const refreshProposals = async () => {
    setListLoading(true);
    setListError("");
    try {
      const data = await listProposals(statusFilter === "all" ? undefined : statusFilter);
      setProposals(data.proposals);
      if (selectedId && !data.proposals.some((p) => p.id === selectedId)) {
        setSelectedId(null);
      }
    } catch (err) {
      setListError(err instanceof ApiError ? err.message : "Failed to load proposals.");
    } finally {
      setListLoading(false);
    }
  };

  useEffect(() => {
    void refreshProposals();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- refresh when filter changes
  }, [statusFilter]);

  const onCreate = async () => {
    setCreateError("");
    setActionBusy(true);
    try {
      const params =
        createAction === "get_component_status"
          ? {}
          : {
              reference,
              x_mm: Number(xMm),
              y_mm: Number(yMm),
            };
      const created = await createProposal({
        action: createAction,
        params,
        prompt: prompt.trim() || null,
      });
      setSelectedId(created.id);
      await refreshProposals();
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : "Create proposal failed.");
    } finally {
      setActionBusy(false);
    }
  };

  const onDemo = async () => {
    setCreateError("");
    setActionBusy(true);
    try {
      const created = await createDemoProposal("read_status");
      setSelectedId(created.id);
      await refreshProposals();
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : "Demo proposal failed.");
    } finally {
      setActionBusy(false);
    }
  };

  const runConfirm = async () => {
    if (!confirm) return;
    const { kind, id } = confirm;
    setConfirm(null);
    setActionBusy(true);
    setListError("");
    try {
      // Decision routes submit proposal ID only — never replacement action params.
      const updated =
        kind === "approve"
          ? await approveProposal(id)
          : kind === "reject"
            ? await rejectProposal(id)
            : await reconcileProposal(id, {
                reason: "Operator marked interrupted approval as uncertain",
              });
      setSelectedId(updated.id);
      await refreshProposals();
    } catch (err) {
      setListError(err instanceof ApiError ? err.message : `${kind} failed.`);
    } finally {
      setActionBusy(false);
    }
  };

  return (
    <>
      <AppTopBar />
      <div className="flex-1 space-y-8 overflow-auto p-4 md:p-6">
        <section className="rounded-xl border border-line bg-panel p-4 md:p-6">
          <h1 className="text-lg font-semibold">HITL proposals</h1>
          <p className="mt-1 max-w-2xl text-xs text-muted-foreground">
            Create pending proposals, then approve or reject by ID. Approval executes the
            server-stored sandbox action only (in-memory placement — not a KiCad schematic edit).
            The browser is not the security boundary.
          </p>

          <div className="mt-4 grid gap-4 md:grid-cols-2">
            <div className="space-y-3 rounded-lg border border-line bg-panel-raised p-3">
              <h2 className="text-sm font-medium">Create proposal</h2>
              <label className="block text-xs text-muted-foreground">
                Action
                <select
                  className="mt-1 w-full rounded border border-line bg-panel px-2 py-1.5 text-sm"
                  value={createAction}
                  onChange={(e) => setCreateAction(e.target.value as SupportedProposalAction)}
                >
                  <option value="get_component_status">get_component_status (read-only)</option>
                  <option value="simulate_unverified_placement">
                    simulate_unverified_placement (sandbox mutate)
                  </option>
                </select>
              </label>
              {createAction === "simulate_unverified_placement" && (
                <div className="grid grid-cols-3 gap-2">
                  <label className="text-xs text-muted-foreground">
                    Reference
                    <input
                      className="mt-1 w-full rounded border border-line bg-panel px-2 py-1 text-sm"
                      value={reference}
                      onChange={(e) => setReference(e.target.value)}
                    />
                  </label>
                  <label className="text-xs text-muted-foreground">
                    x_mm
                    <input
                      className="mt-1 w-full rounded border border-line bg-panel px-2 py-1 text-sm"
                      value={xMm}
                      onChange={(e) => setXMm(e.target.value)}
                    />
                  </label>
                  <label className="text-xs text-muted-foreground">
                    y_mm
                    <input
                      className="mt-1 w-full rounded border border-line bg-panel px-2 py-1 text-sm"
                      value={yMm}
                      onChange={(e) => setYMm(e.target.value)}
                    />
                  </label>
                </div>
              )}
              <label className="block text-xs text-muted-foreground">
                Prompt (optional)
                <input
                  className="mt-1 w-full rounded border border-line bg-panel px-2 py-1.5 text-sm"
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                />
              </label>
              {createError && <ErrorState title="Create failed" message={createError} />}
              <div className="flex flex-wrap gap-2">
                <Button disabled={actionBusy} onClick={() => void onCreate()}>
                  {actionBusy ? "Working…" : "Create proposal"}
                </Button>
                <Button variant="outline" disabled={actionBusy} onClick={() => void onDemo()}>
                  Demo proposal
                </Button>
              </div>
            </div>

            <div className="space-y-3 rounded-lg border border-line bg-panel-raised p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-sm font-medium">Proposals</h2>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={listLoading || actionBusy}
                  onClick={() => void refreshProposals()}
                >
                  Refresh
                </Button>
              </div>
              <div className="flex flex-wrap gap-1">
                {(["all", "pending", "executed", "rejected", "failed", "uncertain"] as const).map(
                  (f) => (
                    <button
                      key={f}
                      type="button"
                      onClick={() => setStatusFilter(f)}
                      className={`rounded-full px-2.5 py-0.5 text-[10px] uppercase ${
                        statusFilter === f
                          ? "bg-brand/20 text-brand"
                          : "border border-line text-muted-foreground"
                      }`}
                    >
                      {f}
                    </button>
                  ),
                )}
              </div>
              {listError && <ErrorState title="Proposal error" message={listError} />}
              {listLoading ? (
                <p className="text-xs text-muted-foreground">Loading proposals…</p>
              ) : proposals.length === 0 ? (
                <EmptyState
                  title="No proposals"
                  description="Create a proposal or run the deterministic demo path."
                />
              ) : (
                <ul className="max-h-64 space-y-2 overflow-auto">
                  {proposals.map((p) => (
                    <li key={p.id}>
                      <button
                        type="button"
                        onClick={() => setSelectedId(p.id)}
                        className={`w-full rounded border px-3 py-2 text-left text-xs ${
                          selectedId === p.id
                            ? "border-brand bg-brand/10"
                            : "border-line bg-panel hover:border-brand/40"
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-mono text-[11px]">{p.action}</span>
                          <StatusBadge tone={statusTone(p.status)} label={p.status} />
                        </div>
                        <p className="mt-1 truncate font-mono text-[10px] text-muted-foreground">
                          {p.id}
                        </p>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          {selected && (
            <div className="mt-4 space-y-3 rounded-lg border border-line bg-panel-raised p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-sm font-medium">Proposal detail</h2>
                <StatusBadge tone={statusTone(selected.status)} label={selected.status} />
              </div>
              <dl className="grid gap-2 text-xs md:grid-cols-2">
                <div>
                  <dt className="text-muted-foreground">ID</dt>
                  <dd className="font-mono break-all">{selected.id}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Content hash</dt>
                  <dd className="font-mono break-all text-[10px]">{selected.content_hash}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Expires</dt>
                  <dd>
                    {selected.expires_at}
                    {isExpired(selected) ? (
                      <span className="ml-2 text-danger">expired</span>
                    ) : null}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Params</dt>
                  <dd className="font-mono text-[10px]">{JSON.stringify(selected.params)}</dd>
                </div>
                {selected.prompt && (
                  <div className="md:col-span-2">
                    <dt className="text-muted-foreground">Prompt</dt>
                    <dd>{selected.prompt}</dd>
                  </div>
                )}
                {selected.failure_reason && (
                  <div className="md:col-span-2">
                    <dt className="text-muted-foreground">Failure</dt>
                    <dd className="text-danger">{selected.failure_reason}</dd>
                  </div>
                )}
                {selected.execution_result != null && (
                  <div className="md:col-span-2">
                    <dt className="text-muted-foreground">Execution result</dt>
                    <dd className="font-mono text-[10px] whitespace-pre-wrap break-all">
                      {JSON.stringify(selected.execution_result, null, 2)}
                    </dd>
                  </div>
                )}
              </dl>
              {selected.status === "uncertain" && (
                <ErrorState
                  title="Uncertain execution outcome"
                  message="This proposal was claimed for execution but the outcome is ambiguous. Do not retry automatically. Investigate sandbox state, then leave it uncertain or open a new proposal if needed."
                />
              )}
              {selected.status === "pending" && (
                <div className="flex flex-wrap gap-2">
                  <Button
                    disabled={actionBusy || isExpired(selected)}
                    onClick={() => setConfirm({ kind: "approve", id: selected.id })}
                  >
                    Approve &amp; execute
                  </Button>
                  <Button
                    variant="outline"
                    disabled={actionBusy}
                    onClick={() => setConfirm({ kind: "reject", id: selected.id })}
                  >
                    Reject
                  </Button>
                </div>
              )}
              {selected.status === "approved" && (
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    className="border-danger/40"
                    disabled={actionBusy}
                    onClick={() => setConfirm({ kind: "reconcile", id: selected.id })}
                  >
                    Mark uncertain (no re-exec)
                  </Button>
                </div>
              )}
            </div>
          )}
        </section>
      </div>

      <ConfirmDialog
        open={confirm !== null}
        title={
          confirm?.kind === "approve"
            ? "Approve and execute?"
            : confirm?.kind === "reconcile"
              ? "Mark proposal uncertain?"
              : "Reject proposal?"
        }
        description={
          confirm?.kind === "approve"
            ? "Approval sends only this proposal ID. The server executes the stored sandbox action and parameters. This does not edit KiCad schematics."
            : confirm?.kind === "reconcile"
              ? "Use this after an interrupted approval claim. It never re-executes the tool."
              : "Rejection never executes the proposed tool."
        }
        confirmLabel={
          confirm?.kind === "approve"
            ? "Approve"
            : confirm?.kind === "reconcile"
              ? "Mark uncertain"
              : "Reject"
        }
        onConfirm={() => void runConfirm()}
        onOpenChange={(open) => {
          if (!open) setConfirm(null);
        }}
      />
    </>
  );
}
