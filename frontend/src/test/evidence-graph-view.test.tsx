import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EvidenceGraphView } from "@/components/eda/EvidenceGraphView";
import type { EvidenceGraph } from "@/lib/types";

const SAMPLE: EvidenceGraph = {
  nodes: [
    {
      id: "c1",
      kind: "component",
      label: "U1 LM358",
      provenance: "parser",
    },
    {
      id: "p1",
      kind: "pin",
      label: "U1 pin 1",
      provenance: "parser",
    },
    {
      id: "n1",
      kind: "net",
      label: "V+",
      provenance: "kicad_netlist",
    },
    {
      id: "f1",
      kind: "finding",
      label: "error: power_pin",
      provenance: "kicad_erc",
    },
  ],
  edges: [
    {
      id: "e1",
      source_id: "c1",
      target_id: "p1",
      kind: "has_pin",
      provenance: "parser",
    },
    {
      id: "e2",
      source_id: "p1",
      target_id: "n1",
      kind: "connected_to",
      provenance: "kicad_netlist",
    },
    {
      id: "e3",
      source_id: "f1",
      target_id: "c1",
      kind: "mentions_component",
      provenance: "kicad_erc",
    },
  ],
  citations: [],
  limitations: ["Demo limitation"],
};

describe("EvidenceGraphView", () => {
  it("hides pins by default and shows layered graph chrome", () => {
    render(<EvidenceGraphView graph={SAMPLE} />);
    expect(screen.getByText(/pins hidden/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Evidence graph")).toBeInTheDocument();
    expect(screen.getByText(/Showing 3\/4 nodes/i)).toBeInTheDocument();
  });

  it("shows node detail when a component is selected", () => {
    render(<EvidenceGraphView graph={SAMPLE} />);
    fireEvent.click(screen.getByText("U1 LM358"));
    expect(screen.getByText("Node detail")).toBeInTheDocument();
    expect(screen.getByText("Provenance:")).toBeInTheDocument();
    expect(screen.getByText("c1")).toBeInTheDocument();
    expect(screen.getByText(/Connections \(1\)/)).toBeInTheDocument();
  });

  it("can enable pins via filter chip", () => {
    render(<EvidenceGraphView graph={SAMPLE} />);
    fireEvent.click(screen.getByRole("button", { name: /pin/i }));
    expect(screen.getByText(/Showing 4\/4 nodes/i)).toBeInTheDocument();
  });
});
