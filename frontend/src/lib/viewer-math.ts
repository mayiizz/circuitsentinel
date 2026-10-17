/** Pure geometry for schematic viewer fit / pan / locate (no React). */

import type { CoordinateMapping, ErcFinding, SymbolFinding } from "@/lib/types";

export type Size = { width: number; height: number };
export type Point = { x: number; y: number };

export type PagePercent = { left: number; top: number };

export type LocateResolveOk = {
  ok: true;
  page: PagePercent;
  label: string;
  reference: string | null;
  pin: string | null;
  x_mm: number;
  y_mm: number;
};

export type LocateResolveFail = {
  ok: false;
  reason: string;
  label: string;
  reference: string | null;
  pin: string | null;
};

export type LocateResolveResult = LocateResolveOk | LocateResolveFail;

const FIT_PADDING_PX = 24;
const LOCATE_ZOOM_MIN = 1.4;
const LOCATE_ZOOM_MAX = 4;

/** Map schematic mm → percentage of the SVG/page content box. */
export function mmToPagePercent(
  xMm: number,
  yMm: number,
  mapping: CoordinateMapping | null | undefined,
): PagePercent | null {
  if (
    !mapping?.reliable ||
    mapping.view_min_x == null ||
    mapping.view_min_y == null ||
    mapping.view_width == null ||
    mapping.view_height == null ||
    mapping.view_width === 0 ||
    mapping.view_height === 0
  ) {
    return null;
  }
  return {
    left: ((xMm - mapping.view_min_x) / mapping.view_width) * 100,
    top: ((yMm - mapping.view_min_y) / mapping.view_height) * 100,
  };
}

/** Uniform scale so content fits inside the viewport with padding. */
export function fitScale(
  content: Size,
  viewport: Size,
  paddingPx: number = FIT_PADDING_PX,
): number {
  if (content.width <= 0 || content.height <= 0) return 1;
  if (viewport.width <= 0 || viewport.height <= 0) return 1;
  const availW = Math.max(1, viewport.width - paddingPx * 2);
  const availH = Math.max(1, viewport.height - paddingPx * 2);
  return Math.min(availW / content.width, availH / content.height);
}

/** Pan (transform-origin 0 0) so scaled content is centered in the viewport. */
export function centerPan(content: Size, viewport: Size, scale: number): Point {
  const w = content.width * scale;
  const h = content.height * scale;
  return {
    x: (viewport.width - w) / 2,
    y: (viewport.height - h) / 2,
  };
}

/**
 * Pan so a page-percent point sits at the viewport center.
 * Uses transform: translate(pan) scale(scale) with origin top-left.
 */
export function panToCenterPagePercent(
  page: PagePercent,
  content: Size,
  viewport: Size,
  scale: number,
): Point {
  const cx = (page.left / 100) * content.width;
  const cy = (page.top / 100) * content.height;
  return {
    x: viewport.width / 2 - cx * scale,
    y: viewport.height / 2 - cy * scale,
  };
}

/** Prefer a readable locate zoom without exceeding max. */
export function locateScale(fit: number): number {
  const bumped = Math.max(fit * LOCATE_ZOOM_MIN, fit * 2);
  return Math.min(Math.max(bumped, fit), Math.max(fit, LOCATE_ZOOM_MAX));
}

/** Axis-aligned bounds of symbols that have grounded at_x/at_y (mm). */
export function circuitBoundsMm(
  symbols: SymbolFinding[],
): { minX: number; minY: number; maxX: number; maxY: number } | null {
  const pts = symbols.filter(
    (s): s is SymbolFinding & { at_x: number; at_y: number } =>
      typeof s.at_x === "number" && typeof s.at_y === "number",
  );
  if (pts.length === 0) return null;
  let minX = pts[0].at_x;
  let minY = pts[0].at_y;
  let maxX = pts[0].at_x;
  let maxY = pts[0].at_y;
  for (const p of pts) {
    minX = Math.min(minX, p.at_x);
    minY = Math.min(minY, p.at_y);
    maxX = Math.max(maxX, p.at_x);
    maxY = Math.max(maxY, p.at_y);
  }
  // Pad so a single symbol still has extent.
  if (maxX - minX < 1) {
    minX -= 10;
    maxX += 10;
  }
  if (maxY - minY < 1) {
    minY -= 10;
    maxY += 10;
  }
  return { minX, minY, maxX, maxY };
}

/**
 * Fit scale + pan so a mm bounding box fills the viewport (letterboxed).
 * Falls back to full-page fit when bounds or mapping are unusable.
 */
export function fitCircuitView(
  symbols: SymbolFinding[],
  mapping: CoordinateMapping | null | undefined,
  content: Size,
  viewport: Size,
): { scale: number; pan: Point } | null {
  const bounds = circuitBoundsMm(symbols);
  if (!bounds || !mapping?.reliable) return null;
  const tl = mmToPagePercent(bounds.minX, bounds.minY, mapping);
  const br = mmToPagePercent(bounds.maxX, bounds.maxY, mapping);
  if (!tl || !br) return null;

  const left = Math.min(tl.left, br.left) / 100;
  const top = Math.min(tl.top, br.top) / 100;
  const right = Math.max(tl.left, br.left) / 100;
  const bottom = Math.max(tl.top, br.top) / 100;
  const boxW = Math.max(0.02, right - left) * content.width;
  const boxH = Math.max(0.02, bottom - top) * content.height;
  const scale = fitScale({ width: boxW, height: boxH }, viewport, FIT_PADDING_PX);
  const boxCenter: PagePercent = {
    left: ((left + right) / 2) * 100,
    top: ((top + bottom) / 2) * 100,
  };
  return {
    scale,
    pan: panToCenterPagePercent(boxCenter, content, viewport, scale),
  };
}

export type NavigateTarget = {
  label: string;
  reference?: string | null;
  pin?: string | null;
  x_mm?: number | null;
  y_mm?: number | null;
  /** Prefer exact finding coordinates when present. */
  finding?: ErcFinding | null;
  /** Fall back to symbol at_x/at_y when finding lacks coordinates. */
  symbol?: SymbolFinding | null;
};

/**
 * Resolve a finding/component target to page-percent highlight coordinates.
 * Never invents positions — returns a clear reason when mapping is unavailable.
 */
export function resolveLocateTarget(
  target: NavigateTarget,
  mapping: CoordinateMapping | null | undefined,
): LocateResolveResult {
  const label = target.label;
  const reference = target.reference ?? target.finding?.reference ?? target.symbol?.reference ?? null;
  const pin = target.pin ?? target.finding?.pin ?? null;

  const xMm =
    target.x_mm ??
    target.finding?.x_mm ??
    (typeof target.symbol?.at_x === "number" ? target.symbol.at_x : null);
  const yMm =
    target.y_mm ??
    target.finding?.y_mm ??
    (typeof target.symbol?.at_y === "number" ? target.symbol.at_y : null);

  if (xMm == null || yMm == null) {
    return {
      ok: false,
      reason:
        reference != null
          ? `No grounded coordinates for ${reference}${pin ? ` pin ${pin}` : ""}. ` +
            "The analysis did not report millimetre positions for this target."
          : "No grounded coordinates for this target.",
      label,
      reference,
      pin,
    };
  }

  if (!mapping?.reliable) {
    return {
      ok: false,
      reason:
        mapping?.note ||
        "Coordinate mapping is unreliable for this render. Locator is disabled to avoid inventing a position.",
      label,
      reference,
      pin,
    };
  }

  const page = mmToPagePercent(xMm, yMm, mapping);
  if (!page) {
    return {
      ok: false,
      reason: "Could not convert millimetre coordinates into page space.",
      label,
      reference,
      pin,
    };
  }

  if (page.left < -5 || page.left > 105 || page.top < -5 || page.top > 105) {
    return {
      ok: false,
      reason: `Mapped position (${page.left.toFixed(1)}%, ${page.top.toFixed(1)}%) lies outside the schematic page. Mapping refused.`,
      label,
      reference,
      pin,
    };
  }

  return {
    ok: true,
    page,
    label: reference ? `${reference}${pin ? ` · pin ${pin}` : ""}` : label,
    reference,
    pin,
    x_mm: xMm,
    y_mm: yMm,
  };
}

export function clampZoomPercent(percent: number): number {
  return Math.min(800, Math.max(10, percent));
}
