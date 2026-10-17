import { AlertCircle, AlertTriangle, ChevronDown, Info, MapPin } from "lucide-react";
import { useId, useState, type KeyboardEvent } from "react";

import { StatusBadge } from "@/components/eda/StatusBadge";
import type { ErcFinding, FindingInterpretation } from "@/lib/types";

function SeverityIcon({ severity }: { severity: string }) {
  const s = severity.toLowerCase();
  if (s === "error") return <AlertCircle size={14} className="text-danger" />;
  if (s === "warning") return <AlertTriangle size={14} className="text-caution" />;
  return <Info size={14} className="text-muted-foreground" />;
}

function shortSummary(finding: ErcFinding): string {
  const text = finding.description.trim();
  if (text.length <= 96) return text;
  return `${text.slice(0, 93)}…`;
}

export function FindingCard({
  finding,
  interpretation,
  selected,
  onSelect,
  onLocate,
  canLocate,
  locateDisabledReason,
}: {
  finding: ErcFinding;
  interpretation?: FindingInterpretation;
  selected?: boolean;
  onSelect?: () => void;
  onLocate?: () => void;
  canLocate?: boolean;
  locateDisabledReason?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const detailsId = useId();
  const hasDetails = Boolean(interpretation || finding.item_description);

  const activate = () => {
    onSelect?.();
    if (canLocate && onLocate) onLocate();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      activate();
    }
  };

  return (
    <article
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      aria-expanded={hasDetails ? expanded : undefined}
      onClick={activate}
      onKeyDown={onKeyDown}
      className={`rounded-lg border px-3 py-2.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand ${
        selected ? "border-brand/50 bg-accent/40" : "border-line bg-panel-raised hover:border-line"
      }`}
    >
      <div className="flex items-start gap-2">
        <SeverityIcon severity={finding.severity} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge
              tone={
                finding.severity.toLowerCase() === "error"
                  ? "danger"
                  : finding.severity.toLowerCase() === "warning"
                    ? "caution"
                    : "neutral"
              }
              label={finding.severity}
            />
            <span className="font-mono text-[10px] text-muted-foreground">{finding.rule_id}</span>
            <span className="rounded bg-workspace px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-muted-foreground">
              ERC
            </span>
          </div>
          <p className="mt-1 text-xs font-medium leading-5">{shortSummary(finding)}</p>
          <p className="mt-1 font-mono text-[10px] text-muted-foreground">
            {finding.reference || "—"}
            {finding.pin ? ` · pin ${finding.pin}` : ""}
            {finding.x_mm != null && finding.y_mm != null
              ? ` · (${finding.x_mm.toFixed(2)}, ${finding.y_mm.toFixed(2)}) mm`
              : " · no coordinates"}
          </p>
        </div>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        {canLocate && onLocate ? (
          <button
            type="button"
            className="inline-flex items-center gap-1 text-[11px] font-medium text-brand hover:underline"
            onClick={(e) => {
              e.stopPropagation();
              onSelect?.();
              onLocate();
            }}
          >
            <MapPin size={12} /> Locate on schematic
          </button>
        ) : (
          <span
            className="text-[10px] text-muted-foreground"
            title={locateDisabledReason}
          >
            {locateDisabledReason || "Locate unavailable"}
          </span>
        )}
        {hasDetails && (
          <button
            type="button"
            aria-controls={detailsId}
            aria-expanded={expanded}
            className="inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground"
            onClick={(e) => {
              e.stopPropagation();
              setExpanded((v) => !v);
            }}
          >
            <ChevronDown
              size={12}
              className={`transition-transform ${expanded ? "rotate-180" : ""}`}
            />
            {expanded ? "Hide details" : "Details / interpretation"}
          </button>
        )}
      </div>

      {expanded && hasDetails && (
        <div id={detailsId} className="mt-2 space-y-2 border-t border-line pt-2">
          {finding.item_description && (
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                ERC item
              </p>
              <p className="mt-0.5 text-[11px] leading-5 text-foreground/90">
                {finding.item_description}
              </p>
            </div>
          )}
          {finding.description.length > 96 && (
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Full description
              </p>
              <p className="mt-0.5 text-[11px] leading-5">{finding.description}</p>
            </div>
          )}
          {interpretation && (
            <div className="rounded-md border border-dashed border-line bg-workspace/60 px-2 py-2">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-caution">
                Heuristic interpretation (not an ERC result)
              </p>
              <p className="mt-1 text-[11px] leading-5 text-muted-foreground">
                {interpretation.explanation}
              </p>
              <p className="mt-1 text-[10px] italic text-muted-foreground">
                {interpretation.disclaimer}
              </p>
            </div>
          )}
        </div>
      )}
    </article>
  );
}
