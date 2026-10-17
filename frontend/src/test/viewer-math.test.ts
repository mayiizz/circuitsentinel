import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import type { CoordinateMapping, ErcFinding, SymbolFinding } from "@/lib/types";
import {
  centerPan,
  circuitBoundsMm,
  fitCircuitView,
  fitScale,
  locateScale,
  mmToPagePercent,
  panToCenterPagePercent,
  resolveLocateTarget,
} from "@/lib/viewer-math";

/** Mirrors tests/fixtures/schematics/erc_opamp.json + KiCad A4 SVG extents. */
const OPAMP_MAPPING: CoordinateMapping = {
  reliable: true,
  units: "mm",
  view_min_x: 0,
  view_min_y: 0,
  view_width: 297.0022,
  view_height: 210.0072,
  note: "fixture",
};

const OPAMP_FINDINGS: ErcFinding[] = [
  {
    rule_id: "power_pin_not_driven",
    severity: "error",
    description: "Input Power pin not driven by any Output Power pins",
    reference: "#PWR01",
    pin: "1",
    x_mm: 135.89,
    y_mm: 186.69,
    source: "kicad",
  },
  {
    rule_id: "power_pin_not_driven",
    severity: "error",
    description: "Input Power pin not driven by any Output Power pins",
    reference: "U1",
    pin: "3",
    x_mm: 147.32,
    y_mm: 96.52,
    source: "kicad",
  },
  {
    rule_id: "power_pin_not_driven",
    severity: "error",
    description: "Input Power pin not driven by any Output Power pins",
    reference: "U1",
    pin: "4",
    x_mm: 147.32,
    y_mm: 111.76,
    source: "kicad",
  },
  {
    rule_id: "lib_symbol_mismatch",
    severity: "warning",
    description: "Symbol 'OPAMP' doesn't match copy in library 'Simulation_SPICE'",
    reference: "U1",
    pin: null,
    x_mm: 149.86,
    y_mm: 104.14,
    source: "kicad",
  },
];

describe("viewer-math fit / pan", () => {
  it("fits content into the viewport while preserving aspect ratio", () => {
    const content = { width: 2970, height: 2100 }; // A4-like landscape
    const viewport = { width: 800, height: 600 };
    const scale = fitScale(content, viewport, 24);
    expect(content.width * scale).toBeLessThanOrEqual(viewport.width - 48 + 0.01);
    expect(content.height * scale).toBeLessThanOrEqual(viewport.height - 48 + 0.01);
    // Landscape should be width-limited or height-limited — both edges touch padding box on one axis.
    const fittedW = content.width * scale;
    const fittedH = content.height * scale;
    const touchesWidth = Math.abs(fittedW - (viewport.width - 48)) < 0.5;
    const touchesHeight = Math.abs(fittedH - (viewport.height - 48)) < 0.5;
    expect(touchesWidth || touchesHeight).toBe(true);
  });

  it("centers content for fit-to-page", () => {
    const content = { width: 400, height: 200 };
    const viewport = { width: 800, height: 600 };
    const scale = fitScale(content, viewport, 0);
    const pan = centerPan(content, viewport, scale);
    expect(pan.x).toBeCloseTo((800 - 400 * scale) / 2);
    expect(pan.y).toBeCloseTo((600 - 200 * scale) / 2);
  });

  it("pans so a page-percent target lands at viewport center", () => {
    const content = { width: 1000, height: 500 };
    const viewport = { width: 400, height: 300 };
    const scale = 0.5;
    const page = { left: 25, top: 40 }; // 250, 200 in content px
    const pan = panToCenterPagePercent(page, content, viewport, scale);
    const screenX = pan.x + 250 * scale;
    const screenY = pan.y + 200 * scale;
    expect(screenX).toBeCloseTo(viewport.width / 2);
    expect(screenY).toBeCloseTo(viewport.height / 2);
  });

  it("recomputes fit when the viewport resizes", () => {
    const content = { width: 1000, height: 800 };
    const small = fitScale(content, { width: 400, height: 300 });
    const large = fitScale(content, { width: 1200, height: 900 });
    expect(large).toBeGreaterThan(small);
  });

  it("locateScale zooms in from fit without exceeding max", () => {
    expect(locateScale(0.5)).toBeGreaterThan(0.5);
    expect(locateScale(0.5)).toBeLessThanOrEqual(4);
  });
});

describe("viewer-math locator (OPamp fixture coords)", () => {
  it("maps all four ERC findings into page percent within the A4 SVG", () => {
    for (const finding of OPAMP_FINDINGS) {
      const page = mmToPagePercent(finding.x_mm!, finding.y_mm!, OPAMP_MAPPING);
      expect(page).not.toBeNull();
      expect(page!.left).toBeGreaterThanOrEqual(0);
      expect(page!.left).toBeLessThanOrEqual(100);
      expect(page!.top).toBeGreaterThanOrEqual(0);
      expect(page!.top).toBeLessThanOrEqual(100);
      expect(page!.left).toBeCloseTo((finding.x_mm! / 297.0022) * 100, 1);
      expect(page!.top).toBeCloseTo((finding.y_mm! / 210.0072) * 100, 1);
    }
  });

  it("resolves successive findings to distinct page positions", () => {
    const a = resolveLocateTarget({ finding: OPAMP_FINDINGS[0], label: "a" }, OPAMP_MAPPING);
    const b = resolveLocateTarget({ finding: OPAMP_FINDINGS[1], label: "b" }, OPAMP_MAPPING);
    expect(a.ok && b.ok).toBe(true);
    if (a.ok && b.ok) {
      expect(a.page.left).not.toBeCloseTo(b.page.left, 1);
      expect(a.reference).toBe("#PWR01");
      expect(b.reference).toBe("U1");
      expect(b.pin).toBe("3");
    }
  });

  it("refuses locate when mapping is unreliable", () => {
    const result = resolveLocateTarget(
      { finding: OPAMP_FINDINGS[0], label: "x" },
      { reliable: false, note: "no mm attrs" },
    );
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toMatch(/no mm attrs|unreliable|unavailable|disabled/i);
  });

  it("explains missing coordinates without inventing a position", () => {
    const finding: ErcFinding = {
      ...OPAMP_FINDINGS[0],
      x_mm: null,
      y_mm: null,
    };
    const result = resolveLocateTarget({ finding, label: "x" }, OPAMP_MAPPING);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toMatch(/No grounded coordinates/);
  });

  it("falls back to symbol at_x/at_y when finding lacks coords", () => {
    const finding: ErcFinding = { ...OPAMP_FINDINGS[1], x_mm: null, y_mm: null };
    const symbol: SymbolFinding = {
      reference: "U1",
      at_x: 147.32,
      at_y: 96.52,
    };
    const result = resolveLocateTarget(
      { finding, symbol, label: "U1", reference: "U1" },
      OPAMP_MAPPING,
    );
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.page.left).toBeCloseTo((147.32 / 297.0022) * 100, 1);
    }
  });

  it("aligns with backend fixture ERC JSON when present on disk", () => {
    const path = resolve(__dirname, "../../../tests/fixtures/schematics/erc_opamp.json");
    const raw = JSON.parse(readFileSync(path, "utf8")) as {
      sheets: Array<{
        violations: Array<{
          items: Array<{ pos: { x: number; y: number } }>;
        }>;
      }>;
    };
    const positions = raw.sheets[0].violations.map((v) => v.items[0].pos);
    expect(positions).toHaveLength(4);
    for (const [i, pos] of positions.entries()) {
      expect(OPAMP_FINDINGS[i].x_mm).toBeCloseTo(pos.x);
      expect(OPAMP_FINDINGS[i].y_mm).toBeCloseTo(pos.y);
      const page = mmToPagePercent(pos.x, pos.y, OPAMP_MAPPING);
      expect(page).not.toBeNull();
    }
  });
});

describe("viewer-math fit-to-circuit", () => {
  it("computes circuit bounds from grounded symbol positions", () => {
    const symbols: SymbolFinding[] = [
      { reference: "R1", at_x: 10, at_y: 20 },
      { reference: "U1", at_x: 100, at_y: 80 },
    ];
    const bounds = circuitBoundsMm(symbols);
    expect(bounds).toEqual({ minX: 10, minY: 20, maxX: 100, maxY: 80 });
  });

  it("returns null fit-to-circuit without grounded symbols", () => {
    expect(
      fitCircuitView([], OPAMP_MAPPING, { width: 1000, height: 700 }, { width: 800, height: 600 }),
    ).toBeNull();
  });
});
