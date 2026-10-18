import { Link, createFileRoute, useNavigate } from "@tanstack/react-router";
import { useMemo, useState } from "react";

import { AppTopBar } from "@/components/layout/AppTopBar";
import { PageHeader } from "@/components/layout/PageHeader";
import { EmptyState } from "@/components/eda/EmptyState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { SymbolFinding } from "@/lib/types";
import { useWorkspace } from "@/lib/workspace";

export const Route = createFileRoute("/components")({
  component: ComponentsPage,
});

function ComponentsPage() {
  const { analysis, selectSymbol, selectedSymbol, requestLocate } = useWorkspace();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");

  const symbols = analysis?.confirmed?.symbols ?? [];
  const filtered = useMemo(() => {
    if (!query.trim()) return symbols;
    const q = query.toLowerCase();
    return symbols.filter(
      (s) =>
        (s.reference || "").toLowerCase().includes(q) ||
        (s.value || "").toLowerCase().includes(q) ||
        (s.lib_id || "").toLowerCase().includes(q),
    );
  }, [symbols, query]);

  const netlistComponent = analysis?.netlist?.components?.find(
    (c) => c.reference === selectedSymbol?.reference,
  );

  if (!analysis) {
    return (
      <>
        <AppTopBar />
        <div className="p-6">
          <EmptyState
            title="No components"
            description="Analyze a schematic to list parsed symbols."
            action={
              <Button asChild>
                <Link to="/schematic">Go to Schematic</Link>
              </Button>
            }
          />
        </div>
      </>
    );
  }

  return (
    <>
      <AppTopBar />
      <div className="grid flex-1 gap-4 overflow-auto p-4 lg:grid-cols-[1fr_320px]">
        <div>
          <PageHeader
            title="Components"
            description="Parsed symbols from the schematic. Datasheet parameters are never invented from reference designators."
          />
          <Input
            className="mt-3 max-w-sm bg-panel"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search reference, value, lib…"
          />
          <div className="mt-4 overflow-auto rounded-lg border border-line">
            <table className="w-full min-w-[640px] text-left text-xs">
              <thead className="border-b border-line bg-panel-raised text-[10px] uppercase text-muted-foreground">
                <tr>
                  <th className="px-3 py-2">Reference</th>
                  <th className="px-3 py-2">Value</th>
                  <th className="px-3 py-2">Lib</th>
                  <th className="px-3 py-2">Position</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((symbol: SymbolFinding, i) => (
                  <tr
                    key={`${symbol.uuid ?? symbol.reference ?? i}`}
                    className={`cursor-pointer border-b border-line/60 hover:bg-accent/30 ${
                      selectedSymbol?.reference === symbol.reference ? "bg-accent/40" : ""
                    }`}
                    onClick={() => selectSymbol(symbol)}
                  >
                    <td className="px-3 py-2 font-mono">{symbol.reference || "—"}</td>
                    <td className="px-3 py-2">{symbol.value || "—"}</td>
                    <td className="px-3 py-2 font-mono text-[10px] text-muted-foreground">
                      {symbol.lib_id || "—"}
                    </td>
                    <td className="px-3 py-2 font-mono text-[10px] text-muted-foreground">
                      {symbol.at_x != null ? `${symbol.at_x}, ${symbol.at_y}` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <aside className="rounded-lg border border-line bg-panel p-4 text-xs">
          <h2 className="text-sm font-semibold">Component details</h2>
          {selectedSymbol ? (
            <div className="mt-3 space-y-2 text-muted-foreground">
              <p className="font-medium text-foreground">
                {selectedSymbol.reference} — {selectedSymbol.value || "no value"}
              </p>
              <p className="font-mono text-[10px]">{selectedSymbol.lib_id || "—"}</p>
              <p>
                Position:{" "}
                {selectedSymbol.at_x != null
                  ? `${selectedSymbol.at_x}, ${selectedSymbol.at_y}`
                  : "unavailable"}
              </p>
              {netlistComponent && (
                <div className="pt-2">
                  <p className="text-foreground">Netlist pins (from KiCad export)</p>
                  <ul className="mt-1 space-y-0.5 font-mono text-[10px]">
                    {(netlistComponent.pins ?? []).map((p) => (
                      <li key={p.number}>
                        {p.number}
                        {p.unit ? ` · unit ${p.unit}` : ""}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <p className="text-[10px] italic">
                Pin electrical ratings and datasheet parameters are not invented here — use Datasheets
                after an explicit link.
              </p>
              <Button
                size="sm"
                className="mt-2"
                onClick={() => {
                  requestLocate({
                    findingIndex: null,
                    reference: selectedSymbol.reference,
                    x_mm: selectedSymbol.at_x,
                    y_mm: selectedSymbol.at_y,
                    label: selectedSymbol.reference || "component",
                  });
                  void navigate({ to: "/schematic" });
                }}
              >
                Locate on schematic
              </Button>
            </div>
          ) : (
            <p className="mt-2 text-muted-foreground">Select a component row.</p>
          )}
        </aside>
      </div>
    </>
  );
}
