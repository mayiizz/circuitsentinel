import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  DatasheetCheckPanel,
  deviceVariantsFromFacts,
} from "@/components/DatasheetCheckPanel";
import type { AnalysisResponse, NormalizedDatasheetFact } from "@/lib/types";

const baseAnalysis = {
  status: "ok",
  upload: {
    original_filename: "sample.kicad_sch",
    stored_as: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.kicad_sch",
    format: "kicad_sch",
    size_bytes: 100,
  },
  viewer: {
    file_id: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    format: "kicad_sch",
    source_url: "/api/schematics/files/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    preview_url: null,
    render_status: "unavailable",
    render_message: "stub",
    content_type: "application/x-kicad-schematic",
    coordinate_mapping: { reliable: false },
  },
  confirmed: {
    symbols: [{ reference: "U1", value: "OPAMP", lib_id: "X:Y", uuid: "u1" }],
    labels: [],
    connectivity: [],
    hierarchy: [],
  },
  erc: {
    ran: false,
    available: false,
    findings: [],
    error_count: 0,
    warning_count: 0,
    message_count: 0,
  },
  visual: { observations: [], disclaimer: "" },
  unverified_suggestions: [],
  validation_errors: [],
  limitations: [],
} satisfies AnalysisResponse;

function fact(
  partial: Partial<NormalizedDatasheetFact> & Pick<NormalizedDatasheetFact, "qualifiers" | "fact_type">,
): NormalizedDatasheetFact {
  return {
    id: "f1",
    value: 30,
    unit: "V",
    source_content_sha256: "a".repeat(64),
    page_number: 5,
    supporting_evidence_id: "e1",
    supporting_excerpt: "excerpt",
    provenance: "datasheet_normalized",
    ...partial,
  };
}

describe("DatasheetCheckPanel", () => {
  it("prompts to analyze when no analysis is present", () => {
    render(<DatasheetCheckPanel analysis={null} symbols={[]} />);
    expect(screen.getByText(/Analyze a schematic first/i)).toBeInTheDocument();
  });

  it("shows ingest and explicit link steps for a KiCad analysis", () => {
    render(
      <DatasheetCheckPanel
        analysis={baseAnalysis}
        symbols={baseAnalysis.confirmed.symbols}
      />,
    );
    expect(screen.getByText(/Ingest datasheet PDF/i)).toBeInTheDocument();
    expect(screen.getByText(/Confirm datasheet ↔ component link/i)).toBeInTheDocument();
    expect(screen.getByText(/Recommended-supply check/i)).toBeInTheDocument();
    expect(screen.getByText(/never infers a match/i)).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "U1" })).toBeInTheDocument();
  });
});

describe("deviceVariantsFromFacts", () => {
  it("collects exact variant names from recommended-operating supply facts only", () => {
    const names = deviceVariantsFromFacts([
      fact({
        fact_type: "supply_voltage_max",
        qualifiers: ["recommended_operating", "variant:LM358", "variant:LM358A"],
      }),
      fact({
        fact_type: "supply_voltage_max",
        qualifiers: ["recommended_operating", "variant:LM358B"],
      }),
      fact({
        fact_type: "supply_voltage_max",
        qualifiers: ["absolute_maximum", "variant:IGNORE"],
      }),
      fact({
        fact_type: "input_voltage_max",
        qualifiers: ["recommended_operating", "variant:NOTSUPPLY"],
      }),
    ]);
    expect(names).toEqual(["LM358", "LM358A", "LM358B"]);
    expect(names).not.toContain("IGNORE");
    expect(names).not.toContain("NOTSUPPLY");
  });

  it("does not invent hardcoded LM358 variants when facts lack them", () => {
    expect(
      deviceVariantsFromFacts([
        fact({
          fact_type: "supply_voltage_max",
          qualifiers: ["recommended_operating"],
        }),
      ]),
    ).toEqual([]);
  });
});
