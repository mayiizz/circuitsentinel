import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createRef } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  SchematicViewer,
  type SchematicViewerHandle,
} from "@/components/eda/SchematicViewer";
import type { AnalysisResponse } from "@/lib/types";
import { mmToPagePercent, panToCenterPagePercent, fitScale } from "@/lib/viewer-math";

const mapping = {
  reliable: true,
  units: "mm" as const,
  view_min_x: 0,
  view_min_y: 0,
  view_width: 297.0022,
  view_height: 210.0072,
  note: "test",
};

function analysisFixture(): AnalysisResponse {
  return {
    status: "ok",
    upload: {
      original_filename: "OPamp-comparator.kicad_sch",
      stored_as: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.kicad_sch",
      format: "kicad_sch",
      size_bytes: 100,
    },
    viewer: {
      file_id: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      format: "kicad_sch",
      source_url: "/api/schematics/files/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      preview_url: "/api/schematics/files/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/preview.svg",
      render_status: "ready",
      render_message: "SVG preview ready",
      content_type: "image/svg+xml",
      coordinate_mapping: mapping,
    },
    confirmed: {
      symbols: [
        { reference: "U1", value: "OPAMP", at_x: 149.86, at_y: 104.14 },
        { reference: "#PWR01", value: "GND", at_x: 135.89, at_y: 186.69 },
      ],
      labels: [],
      connectivity: [],
      hierarchy: [],
    },
    erc: {
      ran: true,
      available: true,
      findings: [],
      error_count: 0,
      warning_count: 0,
      message_count: 0,
    },
    visual: {
      ran: false,
      available: false,
      notes: [],
    },
    stages: {
      parsing: { status: "complete", detail: "ok" },
      rendering: { status: "complete", detail: "ok" },
      erc: { status: "complete", detail: "ok" },
    },
    unverified_suggestions: [],
    validation_errors: [],
    limitations: [],
  } as AnalysisResponse;
}

function mockImageNaturalSize(width: number, height: number) {
  Object.defineProperty(HTMLImageElement.prototype, "naturalWidth", {
    configurable: true,
    get: () => width,
  });
  Object.defineProperty(HTMLImageElement.prototype, "naturalHeight", {
    configurable: true,
    get: () => height,
  });
}

describe("SchematicViewer", () => {
  it("fits the page into the canvas on media load and centers it", async () => {
    mockImageNaturalSize(2970, 2100);
    const analysis = analysisFixture();
    const { container } = render(
      <div style={{ width: 800, height: 600 }}>
        <SchematicViewer analysis={analysis} />
      </div>,
    );

    const canvas = container.querySelector(".cad-grid") as HTMLElement;
    Object.defineProperty(canvas, "clientWidth", { configurable: true, value: 800 });
    Object.defineProperty(canvas, "clientHeight", { configurable: true, value: 600 });

    const img = screen.getByAltText("Schematic SVG preview");
    await act(async () => {
      fireEvent.load(img);
    });

    const layer = img.closest(".absolute") as HTMLElement;
    await waitFor(() => {
      expect(layer.style.transform).toMatch(/scale\(/);
    });

    const match = layer.style.transform.match(
      /translate\(([-\d.]+)px,\s*([-\d.]+)px\)\s*scale\(([-\d.]+)\)/,
    );
    expect(match).not.toBeNull();
    const panX = Number(match![1]);
    const panY = Number(match![2]);
    const scale = Number(match![3]);
    const expectedScale = fitScale({ width: 2970, height: 2100 }, { width: 800, height: 600 });
    expect(scale).toBeCloseTo(expectedScale, 3);
    expect(panX).toBeCloseTo((800 - 2970 * scale) / 2, 1);
    expect(panY).toBeCloseTo((600 - 2100 * scale) / 2, 1);
  });

  it("places the locator highlight in page percent space (not viewport percent)", async () => {
    mockImageNaturalSize(2970, 2100);
    const page = mmToPagePercent(147.32, 96.52, mapping)!;
    render(
      <SchematicViewer
        analysis={analysisFixture()}
        highlight={{ page, label: "U1 · pin 3" }}
      />,
    );
    const img = screen.getByAltText("Schematic SVG preview");
    await act(async () => {
      fireEvent.load(img);
    });

    const marker = await screen.findByTestId("schematic-locator-highlight");
    expect(marker.style.left).toBe(`${page.left}%`);
    expect(marker.style.top).toBe(`${page.top}%`);
    // Highlight is a descendant of the white page, so it tracks zoom/pan with the SVG.
    expect(marker.closest(".bg-white")).not.toBeNull();
  });

  it("navigateTo recenters the target and zooms past fit", async () => {
    mockImageNaturalSize(2970, 2100);
    const ref = createRef<SchematicViewerHandle>();
    const { container } = render(
      <div style={{ width: 800, height: 600 }}>
        <SchematicViewer ref={ref} analysis={analysisFixture()} />
      </div>,
    );
    const canvas = container.querySelector(".cad-grid") as HTMLElement;
    Object.defineProperty(canvas, "clientWidth", { configurable: true, value: 800 });
    Object.defineProperty(canvas, "clientHeight", { configurable: true, value: 600 });

    const img = screen.getByAltText("Schematic SVG preview");
    await act(async () => {
      fireEvent.load(img);
    });

    const page = mmToPagePercent(135.89, 186.69, mapping)!;
    await act(async () => {
      ref.current?.navigateTo(page, "#PWR01");
    });

    const layer = img.closest(".absolute") as HTMLElement;
    const match = layer.style.transform.match(
      /translate\(([-\d.]+)px,\s*([-\d.]+)px\)\s*scale\(([-\d.]+)\)/,
    );
    expect(match).not.toBeNull();
    const panX = Number(match![1]);
    const panY = Number(match![2]);
    const scale = Number(match![3]);
    const fit = fitScale({ width: 2970, height: 2100 }, { width: 800, height: 600 });
    expect(scale).toBeGreaterThan(fit);

    const expectedPan = panToCenterPagePercent(
      page,
      { width: 2970, height: 2100 },
      { width: 800, height: 600 },
      scale,
    );
    expect(panX).toBeCloseTo(expectedPan.x, 1);
    expect(panY).toBeCloseTo(expectedPan.y, 1);
    expect(screen.getByTestId("schematic-locator-highlight")).toBeInTheDocument();
  });

  it("fit-to-page control restores centered fit after zoom", async () => {
    mockImageNaturalSize(1000, 800);
    const ref = createRef<SchematicViewerHandle>();
    const { container } = render(
      <div style={{ width: 500, height: 400 }}>
        <SchematicViewer ref={ref} analysis={analysisFixture()} />
      </div>,
    );
    const canvas = container.querySelector(".cad-grid") as HTMLElement;
    Object.defineProperty(canvas, "clientWidth", { configurable: true, value: 500 });
    Object.defineProperty(canvas, "clientHeight", { configurable: true, value: 400 });

    const img = screen.getByAltText("Schematic SVG preview");
    await act(async () => {
      fireEvent.load(img);
      ref.current?.navigateTo({ left: 10, top: 10 }, "tmp");
      ref.current?.fitToPage();
    });

    const layer = img.closest(".absolute") as HTMLElement;
    const match = layer.style.transform.match(/scale\(([-\d.]+)\)/);
    const scale = Number(match![1]);
    expect(scale).toBeCloseTo(
      fitScale({ width: 1000, height: 800 }, { width: 500, height: 400 }),
      3,
    );
  });
});

describe("SchematicViewer missing media", () => {
  it("shows empty state without inventing a highlight", () => {
    const analysis = analysisFixture();
    analysis.viewer.preview_url = null;
    analysis.viewer.source_url = "";
    render(<SchematicViewer analysis={analysis} highlight={null} />);
    expect(screen.getByText(/Upload and analyze/i)).toBeInTheDocument();
    expect(screen.queryByTestId("schematic-locator-highlight")).not.toBeInTheDocument();
  });
});

// Silence unused vi if imports stay for future spies.
void vi;
