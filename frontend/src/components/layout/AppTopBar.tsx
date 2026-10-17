import { Loader2, Trash2, Upload } from "lucide-react";

import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/eda/StatusBadge";
import { useWorkspace } from "@/lib/workspace";

type AppTopBarProps = {
  onAnalyze?: () => void;
  onChangeFile?: () => void;
  onRemove?: () => void;
  analyzing?: boolean;
  showSchematicActions?: boolean;
};

export function AppTopBar({
  onAnalyze,
  onChangeFile,
  onRemove,
  analyzing = false,
  showSchematicActions = false,
}: AppTopBarProps) {
  const { analysis, file } = useWorkspace();
  const title =
    file?.name ?? analysis?.upload?.original_filename ?? "CircuitSentinel workspace";
  const status = analysis?.status;
  const componentCount = analysis?.confirmed?.symbols?.length ?? 0;
  const findingCount = analysis?.erc?.findings?.length ?? 0;

  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-line bg-panel/95 px-4 backdrop-blur-sm">
      <div className="min-w-0">
        <p className="truncate text-sm font-semibold tracking-tight">{title}</p>
        <div className="mt-0.5 flex flex-wrap items-center gap-2">
          {status ? (
            <StatusBadge
              tone={status === "ok" ? "good" : status === "partial" ? "caution" : "danger"}
              label={status === "ok" ? "Analyzed" : status === "partial" ? "Partial" : "Error"}
            />
          ) : (
            <span className="text-[11px] text-muted-foreground">No analysis loaded</span>
          )}
          {analysis?.upload?.format && (
            <span className="rounded border border-line bg-workspace px-1.5 py-0.5 font-mono text-[10px] uppercase text-muted-foreground">
              {analysis.upload.format}
            </span>
          )}
          {analysis && (
            <span className="hidden text-[11px] text-muted-foreground sm:inline">
              {componentCount} components · {findingCount} findings
            </span>
          )}
        </div>
      </div>

      {showSchematicActions && (
        <div className="flex shrink-0 items-center gap-2">
          <Button
            type="button"
            size="sm"
            disabled={!file || analyzing}
            onClick={onAnalyze}
            className="min-w-[8.5rem]"
          >
            {analyzing ? (
              <>
                <Loader2 size={14} className="animate-spin" /> Analyzing…
              </>
            ) : (
              "Analyze Schematic"
            )}
          </Button>
          <Button type="button" size="sm" variant="outline" disabled={analyzing} onClick={onChangeFile}>
            <Upload size={14} /> Change
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={analyzing || (!file && !analysis)}
            onClick={onRemove}
            className="border-danger/40 text-danger hover:bg-danger/10"
          >
            <Trash2 size={14} /> Remove
          </Button>
        </div>
      )}
    </header>
  );
}
