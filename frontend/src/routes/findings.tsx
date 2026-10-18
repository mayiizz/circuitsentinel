import { Link, createFileRoute, useNavigate } from "@tanstack/react-router";
import { useMemo, useState } from "react";

import { AppTopBar } from "@/components/layout/AppTopBar";
import { PageHeader } from "@/components/layout/PageHeader";
import { EmptyState } from "@/components/eda/EmptyState";
import { FindingCard } from "@/components/eda/FindingCard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { findingSeverityFilter, useWorkspace } from "@/lib/workspace";

export const Route = createFileRoute("/findings")({
  component: FindingsPage,
});

function FindingsPage() {
  const {
    analysis,
    selectFinding,
    selectSymbol,
    selectedFindingIndex,
    requestLocate,
  } = useWorkspace();
  const navigate = useNavigate();
  const [filter, setFilter] = useState<"all" | "error" | "warning">("all");
  const [query, setQuery] = useState("");

  const findings = analysis?.erc?.findings ?? [];
  const filtered = useMemo(() => {
    let list = findingSeverityFilter(findings, filter);
    if (query.trim()) {
      const q = query.toLowerCase();
      list = list.filter(
        (f) =>
          f.description.toLowerCase().includes(q) ||
          f.rule_id.toLowerCase().includes(q) ||
          (f.reference || "").toLowerCase().includes(q),
      );
    }
    return list;
  }, [findings, filter, query]);

  const grouped = useMemo(() => {
    const errors = filtered.filter((f) => f.severity.toLowerCase() === "error");
    const warnings = filtered.filter((f) => f.severity.toLowerCase() === "warning");
    const other = filtered.filter(
      (f) => f.severity.toLowerCase() !== "error" && f.severity.toLowerCase() !== "warning",
    );
    return { errors, warnings, other };
  }, [filtered]);

  const selected = selectedFindingIndex != null ? findings[selectedFindingIndex] : null;
  const interpretation =
    selected &&
    analysis?.finding_interpretations?.find(
      (n) =>
        n.rule_id === selected.rule_id &&
        (n.reference ?? null) === (selected.reference ?? null),
    );

  const mapping = analysis?.viewer?.coordinate_mapping;
  const mappingReliable = Boolean(mapping?.reliable);

  const locate = (index: number) => {
    const finding = findings[index];
    if (!finding) return;
    selectFinding(index);
    const symbol = analysis?.confirmed?.symbols?.find((s) => s.reference === finding.reference);
    selectSymbol(symbol ?? null);
    requestLocate({
      findingIndex: index,
      reference: finding.reference,
      pin: finding.pin,
      x_mm: finding.x_mm,
      y_mm: finding.y_mm,
      label: finding.reference || finding.rule_id,
    });
    void navigate({ to: "/schematic" });
  };

  if (!analysis) {
    return (
      <>
        <AppTopBar />
        <div className="p-6">
          <EmptyState
            title="No analysis loaded"
            description="Analyze a schematic first to review ERC findings."
            action={
              <Button asChild>
                <Link to="/schematic">Go to Schematic</Link>
              </Button>
            }
          />
        </div>
      </>
    );
  }

  return (
    <>
      <AppTopBar />
      <div className="grid flex-1 gap-4 overflow-auto p-4 lg:grid-cols-[1fr_360px]">
        <div>
          <PageHeader
            title="Findings"
            description="KiCad ERC findings from the last analysis. Missing ERC is never treated as a clean pass."
          />
          <div className="mt-3 flex flex-wrap gap-2">
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search findings…"
              className="max-w-xs bg-panel"
            />
            {(["all", "error", "warning"] as const).map((f) => (
              <button
                key={f}
                type="button"
                onClick={() => setFilter(f)}
                className={`rounded-full px-3 py-1 text-[11px] uppercase ${
                  filter === f ? "bg-brand/20 text-brand" : "border border-line text-muted-foreground"
                }`}
              >
                {f}
              </button>
            ))}
          </div>
          <div className="mt-4 space-y-3">
            {!analysis.erc.ran ? (
              <p className="text-xs text-muted-foreground">
                {analysis.erc.failure_reason || "ERC did not run."}
              </p>
            ) : filtered.length === 0 ? (
              <p className="text-xs text-muted-foreground">No findings match.</p>
            ) : (
              (
                [
                  ["Errors", grouped.errors],
                  ["Warnings", grouped.warnings],
                  ["Other", grouped.other],
                ] as const
              ).map(([title, list]) =>
                list.length === 0 ? null : (
                  <div key={title}>
                    <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                      {title} ({list.length})
                    </p>
                    <div className="space-y-2">
                      {list.map((finding) => {
                        const index = findings.indexOf(finding);
                        const canLocate =
                          mappingReliable && finding.x_mm != null && finding.y_mm != null;
                        const interp = analysis.finding_interpretations?.find(
                          (n) =>
                            n.rule_id === finding.rule_id &&
                            (n.reference ?? null) === (finding.reference ?? null),
                        );
                        return (
                          <FindingCard
                            key={`${finding.rule_id}-${index}`}
                            finding={finding}
                            interpretation={interp}
                            selected={selectedFindingIndex === index}
                            onSelect={() => {
                              selectFinding(index);
                              const symbol = analysis.confirmed?.symbols?.find(
                                (s) => s.reference === finding.reference,
                              );
                              selectSymbol(symbol ?? null);
                            }}
                            canLocate={canLocate}
                            locateDisabledReason={
                              !mappingReliable
                                ? mapping?.note || "Coordinate mapping unavailable"
                                : finding.x_mm == null
                                  ? "Finding has no millimetre coordinates"
                                  : undefined
                            }
                            onLocate={() => locate(index)}
                          />
                        );
                      })}
                    </div>
                  </div>
                ),
              )
            )}
          </div>
        </div>
        <aside className="rounded-lg border border-line bg-panel p-4 text-xs">
          <h2 className="text-sm font-semibold">Finding detail</h2>
          {selected ? (
            <div className="mt-3 space-y-2 leading-5 text-muted-foreground">
              <p className="font-medium text-foreground">{selected.description}</p>
              <p className="font-mono text-[10px]">{selected.rule_id}</p>
              <p>
                Component: {selected.reference || "—"}
                {selected.pin ? ` · pin ${selected.pin}` : ""}
              </p>
              {selected.x_mm != null && (
                <p className="font-mono text-[10px]">
                  ({selected.x_mm}, {selected.y_mm}) mm
                </p>
              )}
              {interpretation ? (
                <div className="rounded-md border border-dashed border-line px-2 py-2">
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-caution">
                    Heuristic interpretation
                  </p>
                  <p className="mt-1 text-foreground">{interpretation.explanation}</p>
                  <p className="mt-1 text-[10px] italic">{interpretation.disclaimer}</p>
                </div>
              ) : (
                <p className="italic">No additional interpretation attached to this finding.</p>
              )}
            </div>
          ) : (
            <p className="mt-2 text-muted-foreground">Select a finding to inspect details.</p>
          )}
        </aside>
      </div>
    </>
  );
}
