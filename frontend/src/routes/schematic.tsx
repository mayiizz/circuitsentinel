import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
} from "react";
import { createFileRoute } from "@tanstack/react-router";

import { AppTopBar } from "@/components/layout/AppTopBar";
import { ConfirmDialog } from "@/components/eda/ConfirmDialog";
import { EmptyState } from "@/components/eda/EmptyState";
import { ErrorState } from "@/components/eda/ErrorState";
import { FindingCard } from "@/components/eda/FindingCard";
import { PipelineStageCard } from "@/components/eda/PipelineStageCard";
import {
  SchematicViewer,
  type SchematicViewerHandle,
  type ViewerHighlight,
} from "@/components/eda/SchematicViewer";
import { StatusBadge } from "@/components/eda/StatusBadge";
import { Button } from "@/components/ui/button";
import { analyzeSchematic } from "@/lib/api";
import { ApiError, type ErcFinding, type FindingInterpretation } from "@/lib/types";
import { resolveLocateTarget } from "@/lib/viewer-math";
import { findingSeverityFilter, useWorkspace } from "@/lib/workspace";

export const Route = createFileRoute("/schematic")({
  component: SchematicPage,
});

const MAX_FILE_SIZE = 20 * 1024 * 1024;
const SUPPORTED_EXTENSIONS = [".kicad_sch", ".pdf", ".png", ".jpg", ".jpeg", ".webp"];

function SchematicPage() {
  const inputId = useId();
  const fileInput = useRef<HTMLInputElement>(null);
  const viewerRef = useRef<SchematicViewerHandle>(null);
  const {
    analysis,
    file,
    setAnalysis,
    setFile,
    clearWorkspace,
    selectFinding,
    selectSymbol,
    selectedFindingIndex,
    pendingLocate,
    clearPendingLocate,
    requestLocate,
  } = useWorkspace();
  const [step, setStep] = useState<"upload" | "configure" | "analyze">(
    analysis ? "analyze" : "upload",
  );
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState("");
  const [dragActive, setDragActive] = useState(false);
  const [filter, setFilter] = useState<"all" | "error" | "warning">("all");
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [highlight, setHighlight] = useState<ViewerHighlight | null>(null);
  const [locateMessage, setLocateMessage] = useState<string | null>(null);
  const [focusRequest, setFocusRequest] = useState<{
    id: number;
    page: ViewerHighlight["page"];
    label: string;
  } | null>(null);
  const [localPreviewUrl, setLocalPreviewUrl] = useState<string | null>(null);
  const [stageDetail, setStageDetail] = useState<string | null>(null);

  useEffect(() => {
    if (analysis) setStep("analyze");
  }, [analysis]);

  const findings = analysis?.erc?.findings ?? [];
  const filtered = useMemo(() => findingSeverityFilter(findings, filter), [findings, filter]);
  const grouped = useMemo(() => {
    const errors = filtered.filter((f) => f.severity.toLowerCase() === "error");
    const warnings = filtered.filter((f) => f.severity.toLowerCase() === "warning");
    const other = filtered.filter(
      (f) => f.severity.toLowerCase() !== "error" && f.severity.toLowerCase() !== "warning",
    );
    return { errors, warnings, other };
  }, [filtered]);
  const interpretations = analysis?.finding_interpretations ?? [];
  const mapping = analysis?.viewer?.coordinate_mapping;
  const mappingReliable = Boolean(mapping?.reliable);

  const selectCandidate = (candidate?: File) => {
    if (!candidate) return;
    setError("");
    const ext = `.${candidate.name.split(".").pop()?.toLowerCase() ?? ""}`;
    if (!SUPPORTED_EXTENSIONS.includes(ext)) {
      setError("Unsupported type. Use .kicad_sch, PDF, PNG, JPG, or WebP.");
      return;
    }
    if (candidate.size > MAX_FILE_SIZE) {
      setError("File exceeds 20 MB limit.");
      return;
    }
    setFile(candidate);
    setAnalysis(null, candidate);
    setStep("configure");
    if (candidate.type.startsWith("image/") || candidate.type === "application/pdf") {
      setLocalPreviewUrl(URL.createObjectURL(candidate));
    } else {
      setLocalPreviewUrl(null);
    }
  };

  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragActive(false);
    selectCandidate(event.dataTransfer.files?.[0]);
  };

  const runAnalyze = async () => {
    if (!file) return;
    setAnalyzing(true);
    setError("");
    setStep("analyze");
    try {
      const result = await analyzeSchematic(file);
      setAnalysis(result, file);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Analysis failed.");
    } finally {
      setAnalyzing(false);
    }
  };

  const interpretationFor = (
    finding: ErcFinding,
    index: number,
  ): FindingInterpretation | undefined => {
    const byIndex = interpretations[index];
    if (
      byIndex &&
      byIndex.rule_id === finding.rule_id &&
      (byIndex.reference ?? null) === (finding.reference ?? null)
    ) {
      return byIndex;
    }
    return interpretations.find(
      (n) =>
        n.rule_id === finding.rule_id && (n.reference ?? null) === (finding.reference ?? null),
    );
  };

  const syncSymbolForFinding = (finding: ErcFinding) => {
    if (!finding.reference || !analysis?.confirmed?.symbols) {
      selectSymbol(null);
      return;
    }
    const symbol = analysis.confirmed.symbols.find((s) => s.reference === finding.reference);
    selectSymbol(symbol ?? null);
  };

  const locateFinding = (finding: ErcFinding, index: number) => {
    selectFinding(index);
    syncSymbolForFinding(finding);
    requestLocate({
      findingIndex: index,
      reference: finding.reference,
      pin: finding.pin,
      x_mm: finding.x_mm,
      y_mm: finding.y_mm,
      label: finding.reference || finding.rule_id,
    });
  };

  // Consume pending locate from this page or /findings.
  useEffect(() => {
    if (!pendingLocate || !analysis) return;
    const finding =
      pendingLocate.findingIndex != null ? findings[pendingLocate.findingIndex] : null;
    const symbol =
      (pendingLocate.reference &&
        analysis.confirmed?.symbols?.find((s) => s.reference === pendingLocate.reference)) ||
      null;

    if (pendingLocate.findingIndex != null) {
      selectFinding(pendingLocate.findingIndex);
      if (finding) syncSymbolForFinding(finding);
    }

    const resolved = resolveLocateTarget(
      {
        label: pendingLocate.label,
        reference: pendingLocate.reference,
        pin: pendingLocate.pin,
        x_mm: pendingLocate.x_mm,
        y_mm: pendingLocate.y_mm,
        finding,
        symbol,
      },
      mapping,
    );

    if (!resolved.ok) {
      setHighlight(null);
      setFocusRequest(null);
      setLocateMessage(resolved.reason);
      viewerRef.current?.clearHighlight();
      clearPendingLocate();
      return;
    }

    setLocateMessage(null);
    setHighlight({ page: resolved.page, label: resolved.label });
    setFocusRequest({
      id: pendingLocate.id,
      page: resolved.page,
      label: resolved.label,
    });
    clearPendingLocate();
    // syncSymbolForFinding closes over analysis; findings/mapping covered.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingLocate?.id]);

  return (
    <>
      <AppTopBar
        showSchematicActions
        analyzing={analyzing}
        onAnalyze={() => void runAnalyze()}
        onChangeFile={() => fileInput.current?.click()}
        onRemove={() => setConfirmRemove(true)}
      />
      <input
        id={inputId}
        ref={fileInput}
        type="file"
        accept=".kicad_sch,.pdf,.png,.jpg,.jpeg,.webp"
        className="sr-only"
        onChange={(e: ChangeEvent<HTMLInputElement>) => selectCandidate(e.target.files?.[0])}
      />

      <div className="flex flex-1 flex-col overflow-auto">
        {!analysis && step !== "analyze" && (
          <div className="mx-auto w-full max-w-3xl px-4 py-8">
            <ol className="mb-6 flex gap-2 text-[11px] font-medium uppercase tracking-wide">
              {(["upload", "configure", "analyze"] as const).map((s, i) => (
                <li
                  key={s}
                  className={`rounded-full border px-3 py-1 ${
                    step === s ? "border-brand text-brand" : "border-line text-muted-foreground"
                  }`}
                >
                  {i + 1}. {s}
                </li>
              ))}
            </ol>

            {step === "upload" && (
              <div
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragActive(true);
                }}
                onDragLeave={() => setDragActive(false)}
                onDrop={onDrop}
                className={`rounded-xl border border-dashed px-6 py-16 text-center transition-colors ${
                  dragActive
                    ? "border-brand bg-accent/30 shadow-[0_0_40px_#16C8F422]"
                    : "border-line bg-panel hover:border-brand/40"
                }`}
              >
                <p className="text-sm font-semibold">Drag and drop your KiCad schematic here</p>
                <p className="mt-2 text-xs text-muted-foreground">
                  Supported: .kicad_sch, PDF, PNG, JPG, WebP · max 20 MB
                </p>
                <Button type="button" className="mt-6" onClick={() => fileInput.current?.click()}>
                  Choose File
                </Button>
              </div>
            )}

            {step === "configure" && file && (
              <div className="rounded-xl border border-line bg-panel p-5">
                <h2 className="text-sm font-semibold">Selected file</h2>
                <p className="mt-2 font-mono text-xs">{file.name}</p>
                <p className="mt-1 text-[11px] text-muted-foreground">
                  {(file.size / (1024 * 1024)).toFixed(2)} MB · {file.type || "unknown type"}
                </p>
                <div className="mt-5 flex gap-2">
                  <Button type="button" onClick={() => void runAnalyze()} disabled={analyzing}>
                    Analyze
                  </Button>
                  <Button type="button" variant="outline" onClick={() => setStep("upload")}>
                    Back
                  </Button>
                </div>
              </div>
            )}

            {error && (
              <div className="mt-4">
                <ErrorState title="Upload / analysis error" message={error} />
              </div>
            )}
          </div>
        )}

        {(analysis || step === "analyze") && (
          <div className="flex flex-1 flex-col gap-3 p-3 md:p-4">
            {error && <ErrorState title="Analysis error" message={error} />}
            <div className="flex flex-wrap gap-2">
              <PipelineStageCard
                name="PARSE"
                stage={analysis?.stages?.parsing}
                onClick={() => setStageDetail(analysis?.stages?.parsing?.detail ?? null)}
              />
              <PipelineStageCard
                name="RENDER"
                stage={analysis?.stages?.rendering}
                onClick={() => setStageDetail(analysis?.stages?.rendering?.detail ?? null)}
              />
              <PipelineStageCard
                name="ERC"
                stage={analysis?.stages?.erc}
                onClick={() => setStageDetail(analysis?.stages?.erc?.detail ?? null)}
              />
            </div>
            {stageDetail && (
              <p className="rounded-md border border-line bg-panel px-3 py-2 text-[11px] text-muted-foreground">
                {stageDetail}
              </p>
            )}

            {!analysis && analyzing && (
              <EmptyState
                title="Analyzing…"
                description="Waiting for the backend analysis response."
              />
            )}

            {analysis && (
              <div className="grid min-h-[min(70vh,640px)] flex-1 gap-3 lg:min-h-[calc(100vh-9rem)] lg:grid-cols-[1fr_340px]">
                <SchematicViewer
                  ref={viewerRef}
                  analysis={analysis}
                  localPreviewUrl={localPreviewUrl}
                  highlight={highlight}
                  onHighlightChange={setHighlight}
                  locateMessage={locateMessage}
                  focusRequest={focusRequest}
                />
                <aside className="flex max-h-[70vh] flex-col overflow-hidden rounded-lg border border-line bg-panel lg:max-h-none">
                  <div className="border-b border-line px-3 py-3">
                    <div className="flex items-center justify-between">
                      <h2 className="text-sm font-semibold">ERC Findings</h2>
                      <StatusBadge
                        tone={findings.length ? "caution" : "good"}
                        label={`${findings.length} total`}
                      />
                    </div>
                    <div className="mt-2 flex gap-1">
                      {(["all", "error", "warning"] as const).map((f) => (
                        <button
                          key={f}
                          type="button"
                          onClick={() => setFilter(f)}
                          className={`rounded-full px-2 py-0.5 text-[10px] uppercase ${
                            filter === f
                              ? "bg-brand/20 text-brand"
                              : "text-muted-foreground hover:bg-panel-raised"
                          }`}
                        >
                          {f}
                          {f !== "all"
                            ? ` (${findings.filter((x) => x.severity.toLowerCase() === f).length})`
                            : ""}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="flex-1 space-y-3 overflow-auto p-3">
                    {!analysis.erc.ran ? (
                      <p className="text-[11px] text-muted-foreground">
                        {analysis.erc.failure_reason || "ERC did not run for this upload."}
                      </p>
                    ) : filtered.length === 0 ? (
                      <p className="text-[11px] text-muted-foreground">No findings in this filter.</p>
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
                                  mappingReliable &&
                                  finding.x_mm != null &&
                                  finding.y_mm != null;
                                return (
                                  <FindingCard
                                    key={`${finding.rule_id}-${index}`}
                                    finding={finding}
                                    interpretation={interpretationFor(finding, index)}
                                    selected={selectedFindingIndex === index}
                                    onSelect={() => {
                                      selectFinding(index);
                                      syncSymbolForFinding(finding);
                                    }}
                                    canLocate={canLocate}
                                    locateDisabledReason={
                                      !mappingReliable
                                        ? mapping?.note || "Coordinate mapping unavailable"
                                        : finding.x_mm == null
                                          ? "Finding has no millimetre coordinates"
                                          : undefined
                                    }
                                    onLocate={() => locateFinding(finding, index)}
                                  />
                                );
                              })}
                            </div>
                          </div>
                        ),
                      )
                    )}
                  </div>
                  {selectedFindingIndex != null && findings[selectedFindingIndex] && (
                    <div className="border-t border-line px-3 py-3 text-[11px]">
                      <p className="font-semibold">Selected component / location</p>
                      <p className="mt-1 font-mono text-muted-foreground">
                        {findings[selectedFindingIndex].reference || "—"}
                        {findings[selectedFindingIndex].pin
                          ? ` pin ${findings[selectedFindingIndex].pin}`
                          : ""}
                        {findings[selectedFindingIndex].x_mm != null
                          ? ` · (${findings[selectedFindingIndex].x_mm}, ${findings[selectedFindingIndex].y_mm}) mm`
                          : ""}
                      </p>
                    </div>
                  )}
                </aside>
              </div>
            )}
          </div>
        )}
      </div>

      <ConfirmDialog
        open={confirmRemove}
        onOpenChange={setConfirmRemove}
        title="Remove current schematic?"
        description="Clears the in-memory analysis and selected file. Local session history is kept unless you remove it from Projects."
        confirmLabel="Remove"
        onConfirm={() => {
          clearWorkspace();
          setLocalPreviewUrl(null);
          setStep("upload");
          setHighlight(null);
          setLocateMessage(null);
          setConfirmRemove(false);
        }}
      />
    </>
  );
}
