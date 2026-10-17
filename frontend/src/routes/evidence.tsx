import { Link, createFileRoute } from "@tanstack/react-router";

import { EvidenceGraphView } from "@/components/eda/EvidenceGraphView";
import { EmptyState } from "@/components/eda/EmptyState";
import { AppTopBar } from "@/components/layout/AppTopBar";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { useWorkspace } from "@/lib/workspace";

export const Route = createFileRoute("/evidence")({
  component: EvidencePage,
});

function EvidencePage() {
  const { analysis } = useWorkspace();

  return (
    <>
      <AppTopBar />
      <div className="flex-1 space-y-5 overflow-auto p-4 md:p-6">
        <PageHeader
          title="Evidence Graph"
          description="Provenance-backed relationships only — layered by kind, filterable, no decorative fake edges."
        />
        {!analysis ? (
          <EmptyState
            title="No analysis loaded"
            description="Run schematic analysis to build an evidence graph when the backend provides one."
            action={
              <Button asChild>
                <Link to="/schematic">Go to Schematic</Link>
              </Button>
            }
          />
        ) : (
          <EvidenceGraphView graph={analysis.evidence_graph} />
        )}
      </div>
    </>
  );
}
