import { Link, createFileRoute, useNavigate } from "@tanstack/react-router";
import { FolderKanban } from "lucide-react";
import { useMemo, useState } from "react";

import { AppTopBar } from "@/components/layout/AppTopBar";
import { PageHeader } from "@/components/layout/PageHeader";
import { EmptyState } from "@/components/eda/EmptyState";
import { StatusBadge } from "@/components/eda/StatusBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useWorkspace } from "@/lib/workspace";

export const Route = createFileRoute("/projects")({
  component: ProjectsPage,
});

function ProjectsPage() {
  const { sessions, openSession, removeSession } = useWorkspace();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<"newest" | "name">("newest");

  const filtered = useMemo(() => {
    let list = sessions;
    if (query.trim()) {
      const q = query.toLowerCase();
      list = list.filter((s) => s.filename.toLowerCase().includes(q));
    }
    return [...list].sort((a, b) =>
      sort === "name"
        ? a.filename.localeCompare(b.filename)
        : b.updated_at.localeCompare(a.updated_at),
    );
  }, [sessions, query, sort]);

  return (
    <>
      <AppTopBar />
      <div className="flex-1 overflow-auto px-4 py-6 md:px-8">
        <div className="mx-auto max-w-6xl space-y-5">
          <PageHeader
            title="Projects"
            description="Local browser sessions from analyses on this device — not cloud project storage."
            actions={
              <Button asChild>
                <Link to="/schematic">New Analysis</Link>
              </Button>
            }
          />

          <div className="flex flex-wrap gap-2">
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search sessions…"
              className="max-w-xs bg-panel"
            />
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as "newest" | "name")}
              className="rounded-md border border-line bg-panel px-3 py-2 text-xs"
            >
              <option value="newest">Last modified</option>
              <option value="name">Name</option>
            </select>
          </div>

          {filtered.length === 0 ? (
            <EmptyState
              title="No local sessions yet"
              description="Analyze a schematic to create a local session card. Server-side project persistence is not available."
              action={
                <Button asChild>
                  <Link to="/schematic">Start Analyzing</Link>
                </Button>
              }
            />
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {filtered.map((session) => (
                <article key={session.id} className="cs-panel cs-panel-interactive p-4">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex min-w-0 items-start gap-2.5">
                      <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-md bg-brand/10 text-brand">
                        <FolderKanban size={15} />
                      </span>
                      <h2 className="truncate text-sm font-semibold">{session.filename}</h2>
                    </div>
                    <StatusBadge
                      tone={
                        session.status === "ok"
                          ? "good"
                          : session.status === "partial"
                            ? "caution"
                            : "danger"
                      }
                      label={session.status}
                    />
                  </div>
                  <p className="mt-3 font-mono text-[10px] text-muted-foreground">
                    Updated {new Date(session.updated_at).toLocaleString()}
                  </p>
                  <p className="mt-1 text-[11px] text-muted-foreground">
                    {session.component_count} components · {session.finding_count} findings
                  </p>
                  <div className="mt-4 flex gap-2">
                    <Button
                      size="sm"
                      onClick={() => {
                        if (openSession(session.id)) void navigate({ to: "/schematic" });
                      }}
                    >
                      Open
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => removeSession(session.id)}>
                      Remove
                    </Button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
