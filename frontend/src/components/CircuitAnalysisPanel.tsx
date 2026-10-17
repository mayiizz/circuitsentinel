/**
 * Circuit-level electrical analysis: operator-confirmed rails + whole-circuit report.
 * Never treats net names as voltages. Does not claim whole-circuit safety.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, Play, Save } from "lucide-react";

import {
  getCircuitRails,
  putCircuitRails,
  runCircuitAnalysis,
} from "@/lib/api";
import { ApiError, type AnalysisResponse, type CircuitAnalysisReport, type CircuitCheckStatus, type RailEntry } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

function assessmentStyles(assessment: CircuitAnalysisReport["assessment"]) {
  switch (assessment) {
    case "violations_detected":
      return "border-danger/40 bg-danger/10 text-danger";
    case "no_violations_found_within_scope":
      return "border-good/40 bg-good/10 text-good";
    case "inconclusive":
      return "border-caution/40 bg-caution/10 text-caution";
    default:
      return "border-line bg-panel-raised text-muted-foreground";
  }
}

function statusBadge(status: CircuitCheckStatus) {
  const map: Record<CircuitCheckStatus, { label: string; className: string }> = {
    passed: { label: "passed", className: "bg-good/20 text-good" },
    violation: { label: "violation", className: "bg-danger/20 text-danger" },
    inconclusive: { label: "inconclusive", className: "bg-caution/20 text-caution" },
    not_performed: { label: "not performed", className: "bg-muted text-muted-foreground" },
    warning: { label: "warning", className: "bg-caution/20 text-caution" },
  };
  return map[status];
}

export function CircuitAnalysisPanel({ analysis }: { analysis: AnalysisResponse }) {
  const fileId = analysis.viewer?.file_id ?? null;
  const [rails, setRails] = useState<RailEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState("");
  const [report, setReport] = useState<CircuitAnalysisReport | null>(null);
  const [filter, setFilter] = useState<"all" | CircuitCheckStatus>("all");
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);

  const load = useCallback(async () => {
    if (!fileId) return;
    setLoading(true);
    setError("");
    try {
      const map = await getCircuitRails(fileId);
      setRails(map.rails);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load rails.");
    } finally {
      setLoading(false);
    }
  }, [fileId]);

  useEffect(() => {
    void load();
  }, [load]);

  const updateRail = (index: number, patch: Partial<RailEntry>) => {
    setRails((prev) => prev.map((r, i) => (i === index ? { ...r, ...patch } : r)));
  };

  const saveRails = async () => {
    if (!fileId) return;
    setSaving(true);
    setError("");
    try {
      const map = await putCircuitRails(fileId, rails);
      setRails(map.rails);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to save rails.");
    } finally {
      setSaving(false);
    }
  };

  const runAnalysis = async () => {
    if (!fileId) return;
    setAnalyzing(true);
    setError("");
    try {
      await putCircuitRails(fileId, rails);
      const result = await runCircuitAnalysis(fileId, { rails });
      setReport(result);
      setSelectedIdx(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Circuit analysis failed.");
    } finally {
      setAnalyzing(false);
    }
  };

  const filtered = useMemo(() => {
    if (!report) return [];
    if (filter === "all") return report.findings;
    return report.findings.filter((f) => f.status === filter);
  }, [report, filter]);

  if (!fileId) {
    return (
      <p className="p-4 text-xs text-muted-foreground">
        Circuit analysis requires a KiCad schematic file_id from analysis.
      </p>
    );
  }

  return (
    <div className="space-y-6 p-4 md:p-5">
      <div>
        <h2 className="text-sm font-semibold">Circuit electrical analysis</h2>
        <p className="mt-1 text-[11px] leading-5 text-muted-foreground">
          Confirm supply rail voltages explicitly. Net names like VCC or +5V are never treated as
          verified volts. Results never certify that the whole circuit is safe.
        </p>
      </div>

      {error && (
        <p className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger">
          {error}
        </p>
      )}

      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Operator-confirmed rails
          </h3>
          <div className="flex gap-2">
            <Button type="button" size="sm" variant="outline" onClick={() => void load()} disabled={loading}>
              Refresh
            </Button>
            <Button type="button" size="sm" variant="outline" onClick={() => void saveRails()} disabled={saving}>
              {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
              Save rails
            </Button>
          </div>
        </div>

        {loading ? (
          <p className="text-xs text-muted-foreground">Loading candidate nets…</p>
        ) : rails.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            No candidate supply nets found. Ensure KiCad netlist export succeeded during analyze.
          </p>
        ) : (
          <div className="overflow-auto rounded-lg border border-line">
            <table className="w-full min-w-[640px] text-left text-xs">
              <thead className="border-b border-line bg-panel-raised text-[10px] uppercase text-muted-foreground">
                <tr>
                  <th className="px-3 py-2">Net</th>
                  <th className="px-3 py-2">Voltage (V)</th>
                  <th className="px-3 py-2">Reference</th>
                  <th className="px-3 py-2">Status</th>
                  <th className="px-3 py-2">Suggestion</th>
                </tr>
              </thead>
              <tbody>
                {rails.map((rail, index) => (
                  <tr key={rail.net_name} className="border-b border-line/60">
                    <td className="px-3 py-2 font-mono">{rail.net_name}</td>
                    <td className="px-3 py-2">
                      <Input
                        type="number"
                        step="any"
                        className="h-8 max-w-[7rem] bg-workspace"
                        value={rail.value_v ?? ""}
                        onChange={(e) => {
                          const raw = e.target.value;
                          updateRail(index, {
                            value_v: raw === "" ? null : Number(raw),
                          });
                        }}
                        placeholder="—"
                      />
                    </td>
                    <td className="px-3 py-2">
                      <Input
                        className="h-8 max-w-[8rem] bg-workspace font-mono"
                        value={rail.reference_net ?? ""}
                        onChange={(e) =>
                          updateRail(index, { reference_net: e.target.value || null })
                        }
                        placeholder="GND"
                      />
                    </td>
                    <td className="px-3 py-2">
                      <select
                        className="rounded-md border border-line bg-workspace px-2 py-1.5 text-xs"
                        value={rail.status}
                        onChange={(e) =>
                          updateRail(index, {
                            status: e.target.value as RailEntry["status"],
                          })
                        }
                      >
                        <option value="unconfirmed">unconfirmed</option>
                        <option value="confirmed">confirmed</option>
                        <option value="unknown">unknown</option>
                      </select>
                    </td>
                    <td className="max-w-[14rem] px-3 py-2 text-[10px] text-muted-foreground">
                      {rail.suggestion_reason || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <div className="flex flex-wrap gap-2">
        <Button type="button" onClick={() => void runAnalysis()} disabled={analyzing}>
          {analyzing ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
          Run circuit analysis
        </Button>
      </div>

      {report && (
        <section className="space-y-4">
          <div className={`rounded-lg border px-4 py-3 ${assessmentStyles(report.assessment)}`}>
            <p className="text-sm font-semibold">{report.assessment.replaceAll("_", " ")}</p>
            <p className="mt-1 text-[11px] leading-5 opacity-90">{report.scope}</p>
            <p className="mt-2 font-mono text-[10px]">
              components {report.counts.components_total} · evaluated{" "}
              {report.counts.components_evaluated} · unresolved{" "}
              {report.counts.components_unresolved} · passed {report.counts.checks_passed} ·
              violations {report.counts.checks_violations} · inconclusive{" "}
              {report.counts.checks_inconclusive} · not performed{" "}
              {report.counts.checks_not_performed}
            </p>
          </div>

          <div className="flex flex-wrap gap-1">
            {(
              ["all", "violation", "passed", "inconclusive", "not_performed", "warning"] as const
            ).map((f) => (
              <button
                key={f}
                type="button"
                onClick={() => setFilter(f)}
                className={`rounded-full px-2.5 py-1 text-[10px] uppercase ${
                  filter === f ? "bg-brand/20 text-brand" : "border border-line text-muted-foreground"
                }`}
              >
                {f.replaceAll("_", " ")}
              </button>
            ))}
          </div>

          <div className="grid gap-3 lg:grid-cols-[1fr_320px]">
            <div className="space-y-2">
              {filtered.map((finding, i) => {
                const badge = statusBadge(finding.status);
                const realIndex = report.findings.indexOf(finding);
                return (
                  <button
                    key={`${finding.check_id}-${i}-${finding.component_refs.join(",")}`}
                    type="button"
                    onClick={() => setSelectedIdx(realIndex)}
                    className={`w-full rounded-lg border px-3 py-2.5 text-left transition-colors ${
                      selectedIdx === realIndex
                        ? "border-brand/50 bg-accent/40"
                        : "border-line bg-panel-raised hover:border-line"
                    }`}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={`rounded px-1.5 py-0.5 text-[10px] ${badge.className}`}>
                        {badge.label}
                      </span>
                      <span className="font-mono text-[10px] text-muted-foreground">
                        {finding.check_id}
                      </span>
                      {finding.component_refs.length > 0 && (
                        <span className="font-mono text-[10px]">
                          {finding.component_refs.join(", ")}
                        </span>
                      )}
                    </div>
                    <p className="mt-1 text-xs leading-5">{finding.explanation}</p>
                  </button>
                );
              })}
            </div>

            <aside className="rounded-lg border border-line bg-panel p-3 text-xs">
              <h3 className="text-sm font-semibold">Finding detail</h3>
              {selectedIdx != null && report.findings[selectedIdx] ? (
                <div className="mt-3 space-y-2 text-muted-foreground">
                  <p className="font-mono text-[10px] text-foreground">
                    {report.findings[selectedIdx].check_id}
                  </p>
                  {report.findings[selectedIdx].assumed_conditions.length > 0 && (
                    <div>
                      <p className="text-[10px] font-semibold uppercase">Assumed conditions</p>
                      <ul className="mt-1 list-disc pl-4">
                        {report.findings[selectedIdx].assumed_conditions.map((a) => (
                          <li key={a}>{a}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {report.findings[selectedIdx].limits.length > 0 && (
                    <div>
                      <p className="text-[10px] font-semibold uppercase">Limits</p>
                      <ul className="mt-1 list-disc pl-4 font-mono text-[10px]">
                        {report.findings[selectedIdx].limits.map((a) => (
                          <li key={a}>{a}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {report.findings[selectedIdx].missing_information.length > 0 && (
                    <div>
                      <p className="text-[10px] font-semibold uppercase">Missing</p>
                      <ul className="mt-1 list-disc pl-4">
                        {report.findings[selectedIdx].missing_information.map((a) => (
                          <li key={a}>{a}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {report.findings[selectedIdx].evidence_references.length > 0 && (
                    <div>
                      <p className="text-[10px] font-semibold uppercase">Evidence</p>
                      <ul className="mt-1 space-y-1">
                        {report.findings[selectedIdx].evidence_references.map((ev, j) => (
                          <li key={`${ev.fact_id}-${j}`} className="rounded border border-line px-2 py-1">
                            <Badge variant="outline" className="text-[9px]">
                              p.{ev.page_number ?? "—"} · {ev.fact_type}
                            </Badge>
                            <p className="mt-1 text-[10px] leading-4">{ev.excerpt}</p>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              ) : (
                <p className="mt-2 text-muted-foreground">Select a finding.</p>
              )}
            </aside>
          </div>

          {report.limitations.length > 0 && (
            <div className="rounded-md border border-line px-3 py-2 text-[10px] text-muted-foreground">
              <p className="font-semibold text-foreground">Limitations</p>
              <ul className="mt-1 list-disc pl-4">
                {report.limitations.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
