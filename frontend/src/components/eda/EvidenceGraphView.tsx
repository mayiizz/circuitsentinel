import { useMemo, useState } from "react";

import { EmptyState } from "@/components/eda/EmptyState";
import type { EvidenceGraph, EvidenceNode } from "@/lib/types";

const KIND_COLOR: Record<string, string> = {
  component: "#16C8F4",
  finding: "#FF5364",
  datasheet_document: "#168BFF",
  net: "#19D49A",
  pin: "#FFBE3B",
};

function layoutNodes(nodes: EvidenceNode[], width: number, height: number) {
  const cx = width / 2;
  const cy = height / 2;
  const r = Math.min(width, height) * 0.36;
  if (nodes.length === 0) return [];
  if (nodes.length === 1) return [{ ...nodes[0], x: cx, y: cy }];
  return nodes.map((node, i) => {
    const angle = (i / nodes.length) * Math.PI * 2 - Math.PI / 2;
    return {
      ...node,
      x: cx + Math.cos(angle) * r,
      y: cy + Math.sin(angle) * r,
    };
  });
}

export function EvidenceGraphView({ graph }: { graph: EvidenceGraph | null | undefined }) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const width = 720;
  const height = 420;

  const positioned = useMemo(
    () => layoutNodes(graph?.nodes ?? [], width, height),
    [graph?.nodes],
  );
  const byId = useMemo(() => new Map(positioned.map((n) => [n.id, n])), [positioned]);
  const selected = positioned.find((n) => n.id === selectedId) ?? null;

  if (!graph || graph.nodes.length === 0) {
    return (
      <EmptyState
        title="No evidence graph"
        description="Analyze a KiCad schematic to build provenance-linked evidence nodes and edges. Relationships are never fabricated."
      />
    );
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_280px]">
      <div className="overflow-auto rounded-lg border border-line bg-workspace">
        <svg viewBox={`0 0 ${width} ${height}`} className="h-[420px] w-full min-w-[480px]">
          {graph.edges.map((edge) => {
            const s = byId.get(edge.source_id);
            const t = byId.get(edge.target_id);
            if (!s || !t) return null;
            return (
              <line
                key={edge.id}
                x1={s.x}
                y1={s.y}
                x2={t.x}
                y2={t.y}
                stroke="#1D3448"
                strokeWidth={1.5}
              />
            );
          })}
          {positioned.map((node) => (
            <g
              key={node.id}
              transform={`translate(${node.x}, ${node.y})`}
              className="cursor-pointer"
              onClick={() => setSelectedId(node.id)}
            >
              <circle
                r={selectedId === node.id ? 16 : 12}
                fill={KIND_COLOR[node.kind] ?? "#8FA8BF"}
                opacity={0.9}
                stroke="#EAF4FF"
                strokeWidth={selectedId === node.id ? 2 : 1}
              />
              <text
                y={28}
                textAnchor="middle"
                className="fill-[#EAF4FF] text-[10px]"
                style={{ fontSize: 10 }}
              >
                {(node.label || node.id).slice(0, 18)}
              </text>
            </g>
          ))}
        </svg>
        <div className="flex flex-wrap gap-3 border-t border-line px-3 py-2 text-[10px] text-muted-foreground">
          {Object.entries(KIND_COLOR).map(([kind, color]) => (
            <span key={kind} className="inline-flex items-center gap-1.5">
              <span className="size-2 rounded-full" style={{ background: color }} />
              {kind}
            </span>
          ))}
        </div>
      </div>
      <aside className="rounded-lg border border-line bg-panel px-3 py-3 text-xs">
        <h3 className="text-sm font-semibold">Node detail</h3>
        {selected ? (
          <div className="mt-3 space-y-2 text-[11px] leading-5 text-muted-foreground">
            <p>
              <span className="text-foreground">Label:</span> {selected.label}
            </p>
            <p>
              <span className="text-foreground">Kind:</span> {selected.kind}
            </p>
            <p>
              <span className="text-foreground">Provenance:</span> {selected.provenance}
            </p>
            <p className="font-mono break-all">{selected.id}</p>
            {graph.limitations.slice(0, 2).map((l) => (
              <p key={l} className="italic">
                {l}
              </p>
            ))}
          </div>
        ) : (
          <p className="mt-2 text-[11px] text-muted-foreground">Select a node to inspect evidence.</p>
        )}
      </aside>
    </div>
  );
}
