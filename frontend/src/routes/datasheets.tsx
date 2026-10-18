import { Link, createFileRoute } from "@tanstack/react-router";

import { CircuitAnalysisPanel } from "@/components/CircuitAnalysisPanel";
import { DatasheetCheckPanel } from "@/components/DatasheetCheckPanel";
import { AppTopBar } from "@/components/layout/AppTopBar";
import { PageHeader } from "@/components/layout/PageHeader";
import { EmptyState } from "@/components/eda/EmptyState";
import { Button } from "@/components/ui/button";
import { useWorkspace } from "@/lib/workspace";

export const Route = createFileRoute("/datasheets")({
  component: DatasheetsPage,
});

function DatasheetsPage() {
  const { analysis } = useWorkspace();
  const symbols = analysis?.confirmed?.symbols ?? [];

  return (
    <>
      <AppTopBar />
      <div className="flex-1 space-y-6 overflow-auto p-4 md:p-6">
        <PageHeader
          title="Datasheet & circuit analysis"
          description="Link datasheets to components, confirm supply rails, and run whole-circuit electrical checks within declared scope. Outcomes never certify whole-circuit safety. Net names are not voltages."
        />

        {!analysis ? (
          <div className="rounded-xl border border-line bg-panel p-6">
            <EmptyState
              title="Analyze a schematic first"
              description="Datasheet linking and circuit analysis require a schematic file_id from analysis."
              action={
                <Button asChild>
                  <Link to="/schematic">Go to Schematic</Link>
                </Button>
              }
            />
          </div>
        ) : (
          <>
            <div className="rounded-xl border border-line bg-panel">
              <CircuitAnalysisPanel analysis={analysis} />
            </div>
            <div className="rounded-xl border border-line bg-panel">
              <div className="border-b border-line px-4 py-3">
                <h2 className="text-sm font-semibold">Datasheet ingest & link</h2>
                <p className="mt-1 text-[11px] text-muted-foreground">
                  Explicit component↔PDF links still required before supply/pin checks can use
                  datasheet facts.
                </p>
              </div>
              <DatasheetCheckPanel analysis={analysis} symbols={symbols} />
            </div>
          </>
        )}
      </div>
    </>
  );
}
