import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CircuitAnalysisPanel } from "@/components/CircuitAnalysisPanel";
import type { AnalysisResponse } from "@/lib/types";

vi.mock("@/lib/api", () => ({
  getCircuitRails: vi.fn(),
  putCircuitRails: vi.fn(),
  runCircuitAnalysis: vi.fn(),
}));

import { getCircuitRails } from "@/lib/api";

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

describe("CircuitAnalysisPanel", () => {
  beforeEach(() => {
    vi.mocked(getCircuitRails).mockResolvedValue({
      schematic_file_id: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      rails: [
        {
          net_name: "VCC",
          value_v: null,
          status: "unconfirmed",
          source: "operator",
          suggested: true,
          suggestion_reason: "power pin",
        },
      ],
    });
  });

  it("loads candidate rails without inventing voltages", async () => {
    render(<CircuitAnalysisPanel analysis={baseAnalysis} />);
    await waitFor(() => {
      expect(screen.getByText(/VCC/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/Run circuit analysis/i)).toBeInTheDocument();
    expect(screen.getByText(/never/i)).toBeInTheDocument();
  });
});
