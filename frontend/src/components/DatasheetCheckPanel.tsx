/**
 * Phase 3A–4B datasheet workflow: ingest → explicit link → recommended-supply check.
 * Uses only existing backend APIs; never auto-matches components or infers voltage from net names.
 */
import {
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Database,
  ExternalLink,
  FileText,
  HelpCircle,
  Link2,
  Loader2,
  ShieldCheck,
  Zap,
} from "lucide-react";
import { useId, useMemo, useRef, useState, type ChangeEvent } from "react";

import {
  createDatasheetLink,
  ingestDatasheet,
  runRecommendedSupplyCheck,
} from "@/lib/api";
import {
  ApiError,
  type AnalysisResponse,
  type CheckOutcome,
  type DatasheetComponentLinkResponse,
  type DatasheetIngestReport,
  type EngineeringCheckResponse,
  type NormalizedDatasheetFact,
  type SymbolFinding,
} from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

const MAX_DATASHEET_BYTES = 20 * 1024 * 1024;

function factCategory(fact: NormalizedDatasheetFact): string {
  if (fact.qualifiers.includes("recommended_operating")) return "recommended_operating";
  if (fact.qualifiers.includes("absolute_maximum")) return "absolute_maximum";
  if (fact.qualifiers.length) return fact.qualifiers.join(", ");
  return "unclassified";
}

/** Collect exact ``variant:`` names from recommended-operating supply facts. */
export function deviceVariantsFromFacts(facts: NormalizedDatasheetFact[]): string[] {
  const names = new Set<string>();
  for (const fact of facts) {
    if (
      fact.fact_type !== "supply_voltage_min" &&
      fact.fact_type !== "supply_voltage_max"
    ) {
      continue;
    }
    if (!fact.qualifiers.includes("recommended_operating")) continue;
    for (const q of fact.qualifiers) {
      if (!q.startsWith("variant:")) continue;
      const name = q.slice("variant:".length).trim();
      if (name) names.add(name);
    }
  }
  return [...names].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
}

function outcomeStyles(outcome: CheckOutcome): {
  border: string;
  bg: string;
  badgeBg: string;
  badgeText: string;
  label: string;
} {
  switch (outcome) {
    case "no_violation_detected":
      return {
        border: "border-good/40",
        bg: "bg-good/10",
        badgeBg: "bg-good/20",
        badgeText: "text-good",
        label: "No violation detected",
      };
    case "potential_violation":
      return {
        border: "border-danger/40",
        bg: "bg-danger/10",
        badgeBg: "bg-danger/20",
        badgeText: "text-danger",
        label: "Potential violation",
      };
    case "inconclusive":
      return {
        border: "border-caution/40",
        bg: "bg-caution/10",
        badgeBg: "bg-caution/20",
        badgeText: "text-caution",
        label: "Inconclusive",
      };
    case "error":
    default:
      return {
        border: "border-danger/40",
        bg: "bg-danger/10",
        badgeBg: "bg-danger/20",
        badgeText: "text-danger",
        label: "Error",
      };
  }
}

type DatasheetCheckPanelProps = {
  analysis: AnalysisResponse | null;
  symbols: SymbolFinding[];
};

export function DatasheetCheckPanel({ analysis, symbols }: DatasheetCheckPanelProps) {
  const inputId = useId();
  const fileInput = useRef<HTMLInputElement>(null);

  const [datasheetFile, setDatasheetFile] = useState<File | null>(null);
  const [ingestBusy, setIngestBusy] = useState(false);
  const [ingestReport, setIngestReport] = useState<DatasheetIngestReport | null>(null);
  const [ingestError, setIngestError] = useState("");
  const [showUnresolved, setShowUnresolved] = useState(false);
  const [showSourcePages, setShowSourcePages] = useState(false);

  const [selectedRef, setSelectedRef] = useState("");
  const [linkBusy, setLinkBusy] = useState(false);
  const [linkResult, setLinkResult] = useState<DatasheetComponentLinkResponse | null>(null);
  const [linkError, setLinkError] = useState("");

  const [supplyVolts, setSupplyVolts] = useState("");
  const [supplyNote, setSupplyNote] = useState("");
  const [selectedVariant, setSelectedVariant] = useState("");
  const [checkBusy, setCheckBusy] = useState(false);
  const [checkResult, setCheckResult] = useState<EngineeringCheckResponse | null>(null);
  const [checkError, setCheckError] = useState("");

  const fileId = analysis?.viewer?.file_id ?? "";
  const isKicad = analysis?.upload?.format === "kicad_sch";

  const componentOptions = useMemo(() => {
    const refs = new Set<string>();
    const out: string[] = [];
    for (const sym of symbols) {
      const ref = sym.reference?.trim();
      if (!ref || refs.has(ref)) continue;
      refs.add(ref);
      out.push(ref);
    }
    return out.sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  }, [symbols]);

  const variantOptions = useMemo(() => {
    const facts = linkResult?.facts?.length
      ? linkResult.facts
      : (ingestReport?.facts ?? []);
    return deviceVariantsFromFacts(facts);
  }, [linkResult?.facts, ingestReport?.facts]);
  const variantRequired = variantOptions.length > 1;

  const canLink = Boolean(
    fileId && isKicad && ingestReport?.source && selectedRef && ingestReport.status !== "error",
  );

  const canCheck = Boolean(
    linkResult?.link &&
      linkResult.link.schematic_file_id === fileId &&
      supplyVolts.trim() !== "" &&
      !Number.isNaN(Number(supplyVolts)) &&
      (!variantRequired || selectedVariant.trim() !== ""),
  );

  const onPickDatasheet = (event: ChangeEvent<HTMLInputElement>) => {
    const candidate = event.target.files?.[0];
    setIngestError("");
    setIngestReport(null);
    setLinkResult(null);
    setLinkError("");
    setSelectedVariant("");
    setCheckResult(null);
    setCheckError("");
    if (!candidate) {
      setDatasheetFile(null);
      return;
    }
    if (!candidate.name.toLowerCase().endsWith(".pdf")) {
      setIngestError("Datasheet ingest accepts PDF files only.");
      setDatasheetFile(null);
      return;
    }
    if (candidate.size > MAX_DATASHEET_BYTES) {
      setIngestError("File exceeds the maximum upload size of 20 MB.");
      setDatasheetFile(null);
      return;
    }
    if (candidate.size === 0) {
      setIngestError("Empty file is not allowed.");
      setDatasheetFile(null);
      return;
    }
    setDatasheetFile(candidate);
  };

  const runIngest = async () => {
    if (!datasheetFile) return;
    setIngestBusy(true);
    setIngestError("");
    setLinkResult(null);
    setSelectedVariant("");
    setCheckResult(null);
    try {
      const report = await ingestDatasheet(datasheetFile);
      setIngestReport(report);
      if (report.status === "error") {
        setIngestError(report.failure_reason || "Datasheet ingest failed.");
      }
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Datasheet ingest failed.";
      setIngestError(message);
      if (err instanceof ApiError && err.body && typeof err.body === "object") {
        setIngestReport(err.body as DatasheetIngestReport);
      } else {
        setIngestReport(null);
      }
    } finally {
      setIngestBusy(false);
    }
  };

  const runLink = async () => {
    if (!ingestReport?.source || !fileId || !selectedRef) return;
    setLinkBusy(true);
    setLinkError("");
    setSelectedVariant("");
    setCheckResult(null);
    try {
      const result = await createDatasheetLink({
        schematic_file_id: fileId,
        component_reference: selectedRef,
        document_id: ingestReport.source.document_id,
        content_sha256: ingestReport.source.content_sha256,
      });
      setLinkResult(result);
      if (result.status === "error") {
        setLinkError(result.failure_reason || "Link failed.");
      } else {
        const variants = deviceVariantsFromFacts(result.facts);
        if (variants.length === 1) {
          setSelectedVariant(variants[0] ?? "");
        }
      }
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Datasheet link failed.";
      setLinkError(message);
      setLinkResult(null);
    } finally {
      setLinkBusy(false);
    }
  };

  const runCheck = async () => {
    if (!linkResult?.link) return;
    const value = Number(supplyVolts);
    if (Number.isNaN(value)) {
      setCheckError("Enter a numeric operating supply voltage in volts.");
      return;
    }
    if (variantRequired && !selectedVariant.trim()) {
      setCheckError(
        "Select a device variant from the linked datasheet facts. CircuitSentinel does not infer the variant.",
      );
      return;
    }
    setCheckBusy(true);
    setCheckError("");
    try {
      const result = await runRecommendedSupplyCheck({
        schematic_file_id: linkResult.link.schematic_file_id,
        component_reference: linkResult.link.component_reference,
        document_id: linkResult.link.document_id,
        content_sha256: linkResult.link.content_sha256,
        stated_supply: {
          value_v: value,
          note: supplyNote.trim() || null,
        },
        device_variant: selectedVariant.trim() || null,
      });
      setCheckResult(result);
      if (result.status === "error") {
        setCheckError(result.failure_reason || "Supply check failed.");
      }
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Supply check failed.";
      setCheckError(message);
      if (err instanceof ApiError && err.body && typeof err.body === "object") {
        setCheckResult(err.body as EngineeringCheckResponse);
      } else {
        setCheckResult(null);
      }
    } finally {
      setCheckBusy(false);
    }
  };

  if (!analysis) {
    return (
      <div className="flex flex-col items-center justify-center px-4 py-12 text-center">
        <div className="grid size-12 place-items-center rounded-xl border border-line bg-panel text-caution">
          <HelpCircle size={22} />
        </div>
        <p className="mt-3 text-sm font-semibold text-foreground">
          Analyze a schematic first
        </p>
        <p className="mt-1 max-w-md text-xs leading-relaxed text-muted-foreground">
          Datasheet linking and the recommended-supply check require a KiCad analysis with a
          schematic file id and confirmed component references. Nothing is auto-matched.
        </p>
      </div>
    );
  }

  if (!isKicad || !fileId) {
    return (
      <div className="flex flex-col items-center justify-center px-4 py-12 text-center">
        <div className="grid size-12 place-items-center rounded-xl border border-line bg-panel text-caution">
          <AlertTriangle size={22} />
        </div>
        <p className="mt-3 text-sm font-semibold text-foreground">
          KiCad schematic required
        </p>
        <p className="mt-1 max-w-md text-xs leading-relaxed text-muted-foreground">
          Datasheet→component links apply only to analyzed <code className="text-foreground">.kicad_sch</code> uploads with a server file id.
        </p>
      </div>
    );
  }

  const finding = checkResult?.finding;
  const outcome = checkResult?.status;
  const outcomeLook = outcome ? outcomeStyles(outcome) : null;

  return (
    <div className="space-y-6 p-4 sm:p-5">
      {/* Workflow Stepper Header */}
      <div className="rounded-lg border border-line bg-panel-raised/50 p-3 sm:p-4">
        <div className="grid grid-cols-3 gap-2 text-center text-xs">
          <div
            className={`flex flex-col items-center gap-1 rounded-md p-2 transition-colors ${
              ingestReport?.source ? "bg-panel text-good" : "text-foreground font-medium"
            }`}
          >
            <div className="flex items-center gap-1.5 font-semibold text-xs">
              <span className="grid size-5 place-items-center rounded-full bg-workspace text-[11px] font-mono border border-line">
                {ingestReport?.source ? <Check size={12} className="text-good" /> : "1"}
              </span>
              <span>Ingest PDF</span>
            </div>
            <span className="text-[10px] text-muted-foreground truncate max-w-full">
              {ingestReport?.source ? `${ingestReport.facts.length} facts extracted` : "Extract spec facts"}
            </span>
          </div>

          <div
            className={`flex flex-col items-center gap-1 rounded-md p-2 transition-colors ${
              linkResult?.link ? "bg-panel text-good" : "text-foreground font-medium"
            }`}
          >
            <div className="flex items-center gap-1.5 font-semibold text-xs">
              <span className="grid size-5 place-items-center rounded-full bg-workspace text-[11px] font-mono border border-line">
                {linkResult?.link ? <Check size={12} className="text-good" /> : "2"}
              </span>
              <span>Explicit Link</span>
            </div>
            <span className="text-[10px] text-muted-foreground truncate max-w-full">
              {linkResult?.link ? `Linked ${linkResult.link.component_reference}` : "Confirm RefDes"}
            </span>
          </div>

          <div
            className={`flex flex-col items-center gap-1 rounded-md p-2 transition-colors ${
              checkResult ? "bg-panel text-good" : "text-foreground font-medium"
            }`}
          >
            <div className="flex items-center gap-1.5 font-semibold text-xs">
              <span className="grid size-5 place-items-center rounded-full bg-workspace text-[11px] font-mono border border-line">
                {checkResult ? <Check size={12} className="text-good" /> : "3"}
              </span>
              <span>Supply Check</span>
            </div>
            <span className="text-[10px] text-muted-foreground truncate max-w-full">
              {checkResult ? outcomeLook?.label : "Compare rail to bounds"}
            </span>
          </div>
        </div>
      </div>

      {/* STEP 1: Ingest Datasheet PDF */}
      <section aria-label="Ingest datasheet PDF" className="rounded-lg border border-line bg-panel p-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line pb-3">
          <div>
            <h3 className="text-sm font-semibold tracking-tight text-foreground">
              1. Ingest datasheet PDF
            </h3>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Uses <code className="font-mono text-foreground">POST /api/datasheets/ingest</code>.
              Filename is never treated as a verified part match.
            </p>
          </div>
          {ingestReport?.source && (
            <Badge variant="outline" className="border-good/30 bg-good/10 text-good font-mono text-[10px]">
              Ingested ({ingestReport.source.page_count} pages)
            </Badge>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <input
            id={inputId}
            ref={fileInput}
            type="file"
            accept=".pdf,application/pdf"
            className="sr-only"
            onChange={onPickDatasheet}
          />
          <Button
            variant="outline"
            size="sm"
            className="border-line bg-workspace text-xs hover:border-line/80"
            onClick={() => fileInput.current?.click()}
          >
            <FileText size={14} className="text-brand" />
            <span>Choose PDF</span>
          </Button>
          <Button
            variant="default"
            size="sm"
            className="bg-brand text-brand-foreground hover:bg-brand/90 text-xs"
            disabled={!datasheetFile || ingestBusy}
            onClick={() => void runIngest()}
          >
            {ingestBusy ? <Loader2 size={14} className="animate-spin" /> : <Database size={14} />}
            <span>{ingestBusy ? "Ingesting…" : "Ingest datasheet"}</span>
          </Button>

          {datasheetFile && (
            <span className="text-xs text-muted-foreground font-mono truncate max-w-xs">
              Selected: {datasheetFile.name} ({(datasheetFile.size / 1024).toFixed(1)} KB)
            </span>
          )}
        </div>

        {ingestError && (
          <div role="alert" className="flex items-start gap-2 rounded-md border border-danger/30 bg-danger/10 p-2.5 text-xs text-danger">
            <AlertCircle size={14} className="mt-0.5 shrink-0" />
            <span>{ingestError}</span>
          </div>
        )}

        {ingestReport && (
          <div className="space-y-3 rounded-lg border border-line bg-workspace p-3.5 text-xs">
            {ingestReport.source && (
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 border-b border-line pb-2.5 text-[11px]">
                <div>
                  <span className="text-muted-foreground">Document ID:</span>
                  <div className="font-mono text-foreground truncate" title={ingestReport.source.document_id}>
                    {ingestReport.source.document_id}
                  </div>
                </div>
                <div>
                  <span className="text-muted-foreground">SHA-256:</span>
                  <div className="font-mono text-foreground truncate" title={ingestReport.source.content_sha256}>
                    {ingestReport.source.content_sha256}
                  </div>
                </div>
                <div>
                  <span className="text-muted-foreground">Status / OCR:</span>
                  <div className="text-foreground">
                    {ingestReport.status} {ingestReport.likely_scanned ? "(likely scanned)" : ""}
                  </div>
                </div>
              </div>
            )}

            <div>
              <div className="flex items-center justify-between text-xs font-semibold text-foreground mb-1.5">
                <span>Normalized Facts ({ingestReport.facts.length})</span>
                <span className="text-[10px] text-muted-foreground">Extracted electrical limits</span>
              </div>

              {!ingestReport.facts.length ? (
                <p className="text-muted-foreground text-xs italic">No normalized facts extracted.</p>
              ) : (
                <ul className="max-h-44 space-y-2 overflow-auto pr-1">
                  {ingestReport.facts.map((f) => {
                    const isRec = f.qualifiers.includes("recommended_operating");
                    return (
                      <li
                        key={f.id}
                        className="rounded border border-line bg-panel p-2.5 font-mono text-[11px]"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-1">
                          <span className="font-bold text-foreground">
                            {f.fact_type} = {f.value} {f.unit}
                          </span>
                          <div className="flex items-center gap-1">
                            <Badge
                              variant="outline"
                              className={`text-[9px] ${
                                isRec
                                  ? "border-good/30 bg-good/10 text-good"
                                  : "border-caution/30 bg-caution/10 text-caution"
                              }`}
                            >
                              {factCategory(f)}
                            </Badge>
                            <span className="text-[10px] text-muted-foreground">p. {f.page_number}</span>
                          </div>
                        </div>
                        <div className="mt-1 font-sans text-xs italic text-muted-foreground">
                          “{f.supporting_excerpt}”
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>

            {/* Collapsible unresolved and source pages */}
            {(ingestReport.unresolved.length > 0 || ingestReport.pages.some((p) => p.has_text)) && (
              <div className="flex flex-wrap items-center gap-4 pt-1 border-t border-line text-[11px]">
                {ingestReport.unresolved.length > 0 && (
                  <button
                    type="button"
                    onClick={() => setShowUnresolved((v) => !v)}
                    className="flex items-center gap-1 text-muted-foreground hover:text-foreground"
                  >
                    {showUnresolved ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                    <span>{ingestReport.unresolved.length} Unresolved candidates</span>
                  </button>
                )}
                {ingestReport.pages.some((p) => p.has_text) && (
                  <button
                    type="button"
                    onClick={() => setShowSourcePages((v) => !v)}
                    className="flex items-center gap-1 text-muted-foreground hover:text-foreground"
                  >
                    {showSourcePages ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                    <span>Source pages ({ingestReport.pages.filter((p) => p.has_text).length} with text)</span>
                  </button>
                )}
              </div>
            )}

            {showUnresolved && ingestReport.unresolved.length > 0 && (
              <ul className="rounded border border-line bg-panel p-2 space-y-1 text-[11px] text-muted-foreground">
                {ingestReport.unresolved.map((item) => (
                  <li key={item.id} className="leading-relaxed">
                    • {item.reason}
                    {item.page_number != null ? ` · page ${item.page_number}` : ""}
                    {item.candidate_text ? ` · “${item.candidate_text}”` : ""}
                  </li>
                ))}
              </ul>
            )}

            {showSourcePages && (
              <div className="rounded border border-line bg-panel p-2 grid grid-cols-2 sm:grid-cols-3 gap-1.5 text-[11px] text-muted-foreground">
                {ingestReport.pages
                  .filter((p) => p.has_text)
                  .map((page) => (
                    <div key={page.page_number} className="truncate">
                      Page {page.page_number}: {page.char_count} chars
                    </div>
                  ))}
              </div>
            )}
          </div>
        )}
      </section>

      {/* STEP 2: Confirm Datasheet ↔ Component Link */}
      <section aria-label="Confirm datasheet ↔ component link" className="rounded-lg border border-line bg-panel p-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line pb-3">
          <div>
            <h3 className="text-sm font-semibold tracking-tight text-foreground">
              2. Confirm datasheet ↔ component link
            </h3>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Explicit user confirmation only. CircuitSentinel never infers a match from filename or fuzzy text.
            </p>
          </div>
          {linkResult?.link && (
            <Badge variant="outline" className="border-good/30 bg-good/10 text-good font-mono text-[10px]">
              Active Link: {linkResult.link.component_reference}
            </Badge>
          )}
        </div>

        <div className="grid gap-3 sm:grid-cols-[1fr_auto] items-end">
          <div>
            <label className="block text-xs font-medium text-foreground mb-1" htmlFor={`${inputId}-ref`}>
              Component reference (from analyzed schematic)
            </label>
            <select
              id={`${inputId}-ref`}
              className="w-full rounded-md border border-line bg-workspace px-3 py-2 text-xs font-mono text-foreground focus:outline-none focus:ring-1 focus:ring-brand"
              value={selectedRef}
              onChange={(event) => {
                setSelectedRef(event.target.value);
                setLinkResult(null);
                setLinkError("");
                setCheckResult(null);
              }}
              disabled={!componentOptions.length}
            >
              <option value="">Select a parsed component…</option>
              {componentOptions.map((ref) => (
                <option key={ref} value={ref}>
                  {ref}
                </option>
              ))}
            </select>
          </div>

          <Button
            variant="default"
            size="sm"
            className="bg-brand text-brand-foreground hover:bg-brand/90 text-xs h-9"
            disabled={!canLink || linkBusy}
            onClick={() => void runLink()}
          >
            {linkBusy ? <Loader2 size={14} className="animate-spin" /> : <Link2 size={14} />}
            <span>{linkBusy ? "Linking…" : "Confirm link"}</span>
          </Button>
        </div>

        {linkError && (
          <div role="alert" className="flex items-start gap-2 rounded-md border border-danger/30 bg-danger/10 p-2.5 text-xs text-danger">
            <AlertCircle size={14} className="mt-0.5 shrink-0" />
            <span>{linkError}</span>
          </div>
        )}

        {linkResult && linkResult.status !== "error" && linkResult.link && (
          <div className="rounded-lg border border-line bg-workspace p-3 text-xs">
            <div className="flex items-center justify-between border-b border-line pb-1.5">
              <span className="font-semibold text-foreground">
                Link {linkResult.status === "duplicate" ? "already existed (duplicate)" : "created"}
              </span>
              <span className="font-mono text-[10px] text-good">{linkResult.link.provenance}</span>
            </div>
            <div className="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-2 text-[11px] text-muted-foreground font-mono">
              <div>Ref: <strong className="text-foreground">{linkResult.link.component_reference}</strong></div>
              <div>Doc: <span className="truncate block" title={linkResult.link.document_id}>{linkResult.link.document_id}</span></div>
              <div className="col-span-full">Link ID: <span className="text-foreground">{linkResult.link.id}</span></div>
            </div>
            {linkResult.failure_reason && linkResult.status === "duplicate" && (
              <p className="mt-2 text-caution text-[11px]">{linkResult.failure_reason}</p>
            )}
          </div>
        )}
      </section>

      {/* STEP 3: Recommended-Supply Check */}
      <section aria-label="Recommended-supply check" className="rounded-lg border border-line bg-panel p-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line pb-3">
          <div>
            <h3 className="text-sm font-semibold tracking-tight text-foreground">
              3. Recommended-supply check
            </h3>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Compares a <strong className="text-foreground">user-stated</strong> operating supply to datasheet facts tagged <code className="font-mono text-foreground">recommended_operating</code>.
              Net names are never treated as voltages. Device variants are never inferred.
            </p>
          </div>
          {checkResult && (
            <Badge
              variant="outline"
              className={`font-mono text-[10px] ${outcomeLook?.badgeBg} ${outcomeLook?.badgeText} border-current`}
            >
              {checkResult.status}
            </Badge>
          )}
        </div>

        {variantOptions.length > 0 && (
          <div>
            <label className="block text-xs font-medium text-foreground mb-1" htmlFor={`${inputId}-variant`}>
              Device variant{variantRequired ? " (required)" : " (optional)"}
            </label>
            <select
              id={`${inputId}-variant`}
              className="w-full rounded-md border border-line bg-workspace px-3 py-2 text-xs font-mono text-foreground focus:outline-none focus:ring-1 focus:ring-brand"
              value={selectedVariant}
              onChange={(event) => {
                setSelectedVariant(event.target.value);
                setCheckResult(null);
                setCheckError("");
              }}
              disabled={!linkResult?.link}
            >
              <option value="">
                {variantRequired
                  ? "Select a variant from linked datasheet facts…"
                  : "No variant filter"}
              </option>
              {variantOptions.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
            <p className="mt-1 text-[11px] text-muted-foreground">
              Options extracted from <code className="font-mono text-foreground">variant:</code> qualifiers. Exact match required (LM358 ≠ LM358B).
            </p>
          </div>
        )}

        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="block text-xs font-medium text-foreground mb-1" htmlFor={`${inputId}-v`}>
              Operating supply voltage (V)
            </label>
            <input
              id={`${inputId}-v`}
              type="number"
              step="any"
              className="w-full rounded-md border border-line bg-workspace px-3 py-2 text-xs font-mono text-foreground focus:outline-none focus:ring-1 focus:ring-brand"
              value={supplyVolts}
              onChange={(event) => {
                setSupplyVolts(event.target.value);
                setCheckResult(null);
                setCheckError("");
              }}
              placeholder="e.g. 3.3 or 5.0"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-foreground mb-1" htmlFor={`${inputId}-note`}>
              Note (optional provenance)
            </label>
            <input
              id={`${inputId}-note`}
              type="text"
              className="w-full rounded-md border border-line bg-workspace px-3 py-2 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-brand"
              value={supplyNote}
              onChange={(event) => setSupplyNote(event.target.value)}
              placeholder="e.g. Regulated 3.3V rail from LDO U2"
            />
          </div>
        </div>

        <Button
          variant="default"
          size="sm"
          className="bg-brand text-brand-foreground hover:bg-brand/90 text-xs"
          disabled={!canCheck || checkBusy}
          onClick={() => void runCheck()}
        >
          {checkBusy ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
          <span>{checkBusy ? "Checking…" : "Run supply check"}</span>
        </Button>

        {checkError && (
          <div role="alert" className="flex items-start gap-2 rounded-md border border-danger/30 bg-danger/10 p-2.5 text-xs text-danger">
            <AlertCircle size={14} className="mt-0.5 shrink-0" />
            <span>{checkError}</span>
          </div>
        )}

        {/* Check Result Report Card */}
        {checkResult && outcomeLook && (
          <div className={`mt-4 rounded-lg border ${outcomeLook.border} ${outcomeLook.bg} p-4 text-xs space-y-3`}>
            <div className="flex items-center justify-between border-b border-line/40 pb-2">
              <div className="flex items-center gap-2 font-semibold text-sm">
                {outcome === "potential_violation" ? (
                  <AlertCircle size={16} className="text-danger" />
                ) : outcome === "inconclusive" ? (
                  <HelpCircle size={16} className="text-caution" />
                ) : outcome === "no_violation_detected" ? (
                  <CheckCircle2 size={16} className="text-good" />
                ) : (
                  <AlertTriangle size={16} className="text-danger" />
                )}
                <span>{outcomeLook.label}</span>
                <span className="font-mono text-xs font-normal text-muted-foreground">
                  ({checkResult.status})
                </span>
              </div>
            </div>

            {finding ? (
              <>
                <p className="text-foreground text-xs leading-relaxed">{finding.explanation}</p>

                {/* Metric Comparison HUD */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 rounded-md border border-line bg-workspace/60 p-2.5 text-[11px]">
                  <div>
                    <span className="text-muted-foreground">Stated Supply:</span>
                    <div className="font-mono font-bold text-foreground">
                      {finding.stated_supply_v != null ? `${finding.stated_supply_v} V` : "N/A"}
                    </div>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Datasheet Min:</span>
                    <div className="font-mono text-foreground">
                      {finding.datasheet_supply_min_v != null ? `${finding.datasheet_supply_min_v} V` : "—"}
                    </div>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Datasheet Max:</span>
                    <div className="font-mono text-foreground">
                      {finding.datasheet_supply_max_v != null ? `${finding.datasheet_supply_max_v} V` : "—"}
                    </div>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Device Variant:</span>
                    <div className="font-mono text-brand truncate">
                      {finding.selected_device_variant || "(none)"}
                    </div>
                  </div>
                </div>

                <div className="grid gap-1 text-[11px] text-muted-foreground">
                  <div>
                    <span className="text-foreground font-medium">Check ID:</span>{" "}
                    <code className="text-foreground">{finding.check_id}</code>
                  </div>
                  <div>
                    <span className="text-foreground font-medium">Component:</span>{" "}
                    <span className="font-mono text-foreground font-semibold">
                      {finding.component_reference}
                    </span>
                  </div>
                  {finding.evidence_references.some((r) => r.page_number != null) && (
                    <div>
                      <span className="text-foreground font-medium">Source page(s):</span>{" "}
                      {[
                        ...new Set(
                          finding.evidence_references
                            .map((r) => r.page_number)
                            .filter((n): n is number => n != null),
                        ),
                      ].join(", ")}
                    </div>
                  )}
                </div>

                {/* Supporting evidence */}
                {finding.evidence_references.length > 0 && (
                  <div className="space-y-1.5 pt-1">
                    <span className="text-xs font-semibold text-foreground">Supporting Evidence</span>
                    <ul className="space-y-1.5">
                      {finding.evidence_references.map((ref, idx) => (
                        <li
                          key={`ev-${ref.fact_id ?? "ref"}-${idx}`}
                          className="rounded border border-line bg-workspace p-2 font-mono text-[11px]"
                        >
                          <div className="flex flex-wrap items-center justify-between gap-1">
                            <span className="font-semibold text-foreground">{ref.fact_type ?? "fact"}</span>
                            <span className="text-muted-foreground">
                              {ref.qualifiers?.join(", ")} · page {ref.page_number ?? "?"}
                            </span>
                          </div>
                          {ref.excerpt && (
                            <div className="mt-1 font-sans text-xs italic text-muted-foreground">
                              “{ref.excerpt}”
                            </div>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Assumptions */}
                {finding.assumptions.length > 0 && (
                  <div>
                    <span className="text-xs font-semibold text-foreground">Assumptions</span>
                    <ul className="mt-1 list-disc pl-4 text-[11px] text-muted-foreground space-y-0.5">
                      {finding.assumptions.map((a, i) => (
                        <li key={`as-${i}`}>{a}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Missing information */}
                {finding.missing_information.length > 0 && (
                  <div>
                    <span className="text-xs font-semibold text-caution">Missing Information</span>
                    <ul className="mt-1 list-disc pl-4 text-[11px] text-muted-foreground space-y-0.5">
                      {finding.missing_information.map((m, i) => (
                        <li key={`mi-${i}`}>{m}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </>
            ) : (
              <p className="text-muted-foreground">{checkResult.failure_reason || "No finding payload returned."}</p>
            )}

            {outcome === "no_violation_detected" && (
              <div className="rounded border border-caution/40 bg-caution/10 p-2.5 text-[11px] text-foreground leading-relaxed">
                <strong className="text-caution">Important safety caveat:</strong>{" "}
                <code className="text-foreground">no_violation_detected</code> applies only to this single
                recommended-supply check. It does <strong className="text-foreground">not</strong> establish
                whole-circuit safety or replace electrical simulation and physical hardware testing.
              </div>
            )}

            {checkResult.limitations.length > 0 && (
              <p className="text-[10px] text-muted-foreground border-t border-line/40 pt-2">
                Limitations: {checkResult.limitations.join(" ")}
              </p>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
