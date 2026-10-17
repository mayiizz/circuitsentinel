import { createFileRoute } from "@tanstack/react-router";
import { RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { AppTopBar } from "@/components/layout/AppTopBar";
import { PageHeader } from "@/components/layout/PageHeader";
import { ErrorState } from "@/components/eda/ErrorState";
import { LoadingSkeleton } from "@/components/eda/LoadingSkeleton";
import { StatusBadge } from "@/components/eda/StatusBadge";
import { Button } from "@/components/ui/button";
import { healthCheck } from "@/lib/api";
import { ApiError } from "@/lib/types";

export const Route = createFileRoute("/settings")({
  component: SettingsPage,
});

function SettingsPage() {
  const [health, setHealth] = useState<{ status: string; service: string } | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const result = await healthCheck();
      setHealth(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Health check failed.");
      setHealth(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <>
      <AppTopBar />
      <div className="mx-auto max-w-2xl flex-1 space-y-6 overflow-auto p-4 md:p-6">
        <PageHeader
          title="Settings"
          description="Account and organization settings are not available — no auth API is exposed."
          actions={
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={loading}
              onClick={() => void refresh()}
            >
              <RefreshCw size={14} className={loading ? "animate-spin" : undefined} />
              Refresh
            </Button>
          }
        />

        <section className="cs-panel p-4">
          <h2 className="text-sm font-semibold">API health</h2>
          <p className="mt-1 text-[11px] text-muted-foreground">
            Local FastAPI service status for this workspace.
          </p>
          {loading && (
            <div className="mt-3">
              <LoadingSkeleton rows={2} />
            </div>
          )}
          {error && (
            <div className="mt-3">
              <ErrorState title="Unreachable" message={error} />
            </div>
          )}
          {health && !loading && (
            <div className="mt-4 flex items-center gap-2 text-xs">
              <StatusBadge
                tone={health.status === "ok" ? "good" : "caution"}
                label={health.status}
              />
              <span className="font-mono text-muted-foreground">{health.service}</span>
            </div>
          )}
        </section>

        <section className="cs-panel p-4 text-xs text-muted-foreground">
          <h2 className="text-sm font-semibold text-foreground">About</h2>
          <p className="mt-2 leading-5">
            CircuitSentinel is a read-only investigation workspace. Governed sandbox actions stay
            fail-closed until a human approves a HITL proposal. Projects listed in the UI are local
            browser sessions only.
          </p>
        </section>
      </div>
    </>
  );
}
