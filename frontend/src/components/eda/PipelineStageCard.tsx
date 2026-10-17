import { StatusBadge } from "@/components/eda/StatusBadge";
import type { StageResult } from "@/lib/types";

function toneFor(status: string): "good" | "caution" | "danger" | "neutral" {
  if (status === "complete") return "good";
  if (status === "partial" || status === "unavailable") return "caution";
  if (status === "failed") return "danger";
  return "neutral";
}

export function PipelineStageCard({
  name,
  stage,
  onClick,
}: {
  name: string;
  stage?: StageResult | null;
  onClick?: () => void;
}) {
  const status = stage?.status ?? "skipped";
  return (
    <button
      type="button"
      onClick={onClick}
      className="min-w-[7.5rem] flex-1 rounded-lg border border-line bg-panel-raised px-3 py-2 text-left transition-colors hover:border-brand/40"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[10px] uppercase tracking-wide text-muted-foreground">
          {name}
        </span>
        <StatusBadge tone={toneFor(status)} label={status} />
      </div>
      <p className="mt-1 line-clamp-2 text-[11px] leading-4 text-muted-foreground">
        {stage?.detail || "Not run."}
      </p>
    </button>
  );
}
