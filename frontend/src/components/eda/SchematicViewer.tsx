import { Expand, Focus, Minus, Plus, RotateCcw } from "lucide-react";
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
  useState,
  type PointerEvent,
  type SyntheticEvent,
} from "react";

import { Button } from "@/components/ui/button";
import { assetUrl } from "@/lib/api";
import type { AnalysisResponse } from "@/lib/types";
import {
  centerPan,
  fitCircuitView,
  fitScale,
  locateScale,
  panToCenterPagePercent,
  type PagePercent,
  type Point,
  type Size,
} from "@/lib/viewer-math";

export type ViewerHighlight = {
  page: PagePercent;
  label: string;
};

export type SchematicViewerHandle = {
  fitToPage: () => void;
  fitToCircuit: () => void;
  resetView: () => void;
  navigateTo: (page: PagePercent, label: string) => void;
  clearHighlight: () => void;
};

type SchematicViewerProps = {
  analysis: AnalysisResponse | null;
  localPreviewUrl?: string | null;
  highlight?: ViewerHighlight | null;
  onHighlightChange?: (highlight: ViewerHighlight | null) => void;
  locateMessage?: string | null;
  /** When id changes, zoom/pan to page once content+viewport are ready. */
  focusRequest?: { id: number; page: PagePercent; label: string } | null;
};

function viewportCenterAsPagePercent(
  viewport: Size,
  pan: Point,
  content: Size,
  scale: number,
): PagePercent {
  if (content.width <= 0 || content.height <= 0 || scale <= 0) {
    return { left: 50, top: 50 };
  }
  return {
    left: ((viewport.width / 2 - pan.x) / (content.width * scale)) * 100,
    top: ((viewport.height / 2 - pan.y) / (content.height * scale)) * 100,
  };
}

export const SchematicViewer = forwardRef<SchematicViewerHandle, SchematicViewerProps>(
  function SchematicViewer(
    {
      analysis,
      localPreviewUrl,
      highlight,
      onHighlightChange,
      locateMessage,
      focusRequest,
    },
    ref,
  ) {
    const canvasRef = useRef<HTMLDivElement>(null);
    const [viewport, setViewport] = useState<Size>({ width: 0, height: 0 });
    const [content, setContent] = useState<Size>({ width: 0, height: 0 });
    /** Scale relative to fit-to-page (1 = fully fitted). */
    const [userZoom, setUserZoom] = useState(1);
    const [pan, setPan] = useState<Point>({ x: 0, y: 0 });
    const [panning, setPanning] = useState(false);
    const panStart = useRef<{ x: number; y: number; panX: number; panY: number } | null>(null);
    const [internalHighlight, setInternalHighlight] = useState<ViewerHighlight | null>(null);
    /** Keep center page % across resizes. */
    const centerPageRef = useRef<PagePercent>({ left: 50, top: 50 });

    const viewer = analysis?.viewer;
    const preview = viewer?.preview_url ? assetUrl(viewer.preview_url) : null;
    const source = viewer?.source_url ? assetUrl(viewer.source_url) : localPreviewUrl ?? null;
    const isSvgPreview = Boolean(preview);
    const isPdf = viewer?.format === "pdf" || source?.toLowerCase().includes(".pdf");
    const mediaUrl = isSvgPreview ? preview : !isPdf ? source : null;
    const activeHighlight = highlight ?? internalHighlight;
    const mapping = viewer?.coordinate_mapping;
    const symbols = analysis?.confirmed?.symbols ?? [];

    const baseFit =
      content.width > 0 && viewport.width > 0 ? fitScale(content, viewport) : 1;
    const scale = baseFit * userZoom;

    const measureViewport = useCallback(() => {
      const el = canvasRef.current;
      if (!el) return;
      const next = { width: el.clientWidth, height: el.clientHeight };
      setViewport((prev) =>
        prev.width === next.width && prev.height === next.height ? prev : next,
      );
    }, []);

    useLayoutEffect(() => {
      measureViewport();
      const el = canvasRef.current;
      if (!el || typeof ResizeObserver === "undefined") return;
      const ro = new ResizeObserver(() => measureViewport());
      ro.observe(el);
      return () => ro.disconnect();
    }, [measureViewport, mediaUrl]);

    // After viewport or content changes, keep the previous page-center in view.
    useEffect(() => {
      if (content.width <= 0 || viewport.width <= 0) return;
      const nextFit = fitScale(content, viewport);
      const nextScale = nextFit * userZoom;
      setPan(panToCenterPagePercent(centerPageRef.current, content, viewport, nextScale));
    }, [viewport.width, viewport.height, content.width, content.height, userZoom]);

    const onMediaLoad = (event: SyntheticEvent<HTMLImageElement>) => {
      const img = event.currentTarget;
      const next = { width: img.naturalWidth, height: img.naturalHeight };
      if (next.width <= 0 || next.height <= 0) return;
      const measured = canvasRef.current
        ? {
            width: canvasRef.current.clientWidth,
            height: canvasRef.current.clientHeight,
          }
        : viewport;
      const size =
        measured.width > 0 && measured.height > 0
          ? measured
          : { width: 800, height: 600 };
      setViewport(size);
      setContent(next);
      setUserZoom(1);
      centerPageRef.current = { left: 50, top: 50 };
      setPan(centerPan(next, size, fitScale(next, size)));
    };

    useEffect(() => {
      setContent({ width: 0, height: 0 });
      setUserZoom(1);
      setInternalHighlight(null);
      onHighlightChange?.(null);
      centerPageRef.current = { left: 50, top: 50 };
      // eslint-disable-next-line react-hooks/exhaustive-deps -- only reset when media changes
    }, [mediaUrl]);

    const fitToPage = useCallback(() => {
      if (content.width <= 0 || viewport.width <= 0) return;
      setUserZoom(1);
      centerPageRef.current = { left: 50, top: 50 };
      setPan(centerPan(content, viewport, fitScale(content, viewport)));
    }, [content, viewport]);

    const fitToCircuit = useCallback(() => {
      if (content.width <= 0 || viewport.width <= 0) return;
      const fitted = fitCircuitView(symbols, mapping, content, viewport);
      if (!fitted) {
        fitToPage();
        return;
      }
      const fit = fitScale(content, viewport);
      setUserZoom(fitted.scale / fit);
      centerPageRef.current = viewportCenterAsPagePercent(
        viewport,
        fitted.pan,
        content,
        fitted.scale,
      );
      setPan(fitted.pan);
    }, [content, fitToPage, mapping, symbols, viewport]);

    const clearHighlight = useCallback(() => {
      setInternalHighlight(null);
      onHighlightChange?.(null);
    }, [onHighlightChange]);

    const resetView = useCallback(() => {
      fitToPage();
      clearHighlight();
    }, [clearHighlight, fitToPage]);

    const navigateTo = useCallback(
      (page: PagePercent, label: string) => {
        if (content.width <= 0 || viewport.width <= 0) return;
        const fit = fitScale(content, viewport);
        const nextScale = locateScale(fit);
        setUserZoom(nextScale / fit);
        centerPageRef.current = page;
        setPan(panToCenterPagePercent(page, content, viewport, nextScale));
        const next = { page, label };
        setInternalHighlight(next);
        onHighlightChange?.(next);
      },
      [content, onHighlightChange, viewport],
    );

    useImperativeHandle(
      ref,
      () => ({
        fitToPage,
        fitToCircuit,
        resetView,
        navigateTo,
        clearHighlight,
      }),
      [clearHighlight, fitToCircuit, fitToPage, navigateTo, resetView],
    );

    // Apply external locate requests after media has measured (covers race on route entry).
    useEffect(() => {
      if (!focusRequest) return;
      if (content.width <= 0 || viewport.width <= 0) return;
      navigateTo(focusRequest.page, focusRequest.label);
    }, [focusRequest?.id, content.width, content.height, viewport.width, viewport.height, navigateTo]);

    const zoomBy = (deltaPercent: number) => {
      if (content.width <= 0 || viewport.width <= 0) return;
      const currentCenter = viewportCenterAsPagePercent(viewport, pan, content, scale);
      centerPageRef.current = currentCenter;
      setUserZoom((z) => {
        const next = Math.min(8, Math.max(0.15, z * (1 + deltaPercent / 100)));
        const nextScale = baseFit * next;
        setPan(panToCenterPagePercent(currentCenter, content, viewport, nextScale));
        return next;
      });
    };

    const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
      if (event.button !== 0) return;
      setPanning(true);
      panStart.current = { x: event.clientX, y: event.clientY, panX: pan.x, panY: pan.y };
      event.currentTarget.setPointerCapture(event.pointerId);
    };
    const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
      if (!panning || !panStart.current) return;
      const next = {
        x: panStart.current.panX + (event.clientX - panStart.current.x),
        y: panStart.current.panY + (event.clientY - panStart.current.y),
      };
      setPan(next);
      centerPageRef.current = viewportCenterAsPagePercent(viewport, next, content, scale);
    };
    const endPan = (event: PointerEvent<HTMLDivElement>) => {
      setPanning(false);
      panStart.current = null;
      try {
        event.currentTarget.releasePointerCapture(event.pointerId);
      } catch {
        /* ignore */
      }
    };

    const zoomPercent = Math.round(userZoom * 100);
    const canPanZoom = Boolean(mediaUrl) && content.width > 0;

    return (
      <div className="flex h-full min-h-[280px] flex-col overflow-hidden rounded-lg border border-line bg-workspace">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
          <span className="text-[11px] text-muted-foreground">Schematic viewer</span>
          <div className="flex flex-wrap items-center gap-1">
            <Button
              type="button"
              size="sm"
              variant="ghost"
              title="Zoom out"
              disabled={!canPanZoom}
              onClick={() => zoomBy(-15)}
            >
              <Minus size={14} />
            </Button>
            <span className="min-w-[3rem] text-center font-mono text-[11px]">{zoomPercent}%</span>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              title="Zoom in"
              disabled={!canPanZoom}
              onClick={() => zoomBy(15)}
            >
              <Plus size={14} />
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              title="Fit to page"
              disabled={!canPanZoom}
              onClick={fitToPage}
            >
              <Expand size={14} />
              <span className="hidden sm:inline">Fit page</span>
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              title="Fit to circuit"
              disabled={!canPanZoom}
              onClick={fitToCircuit}
            >
              <Focus size={14} />
              <span className="hidden sm:inline">Fit circuit</span>
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              title="Reset view"
              disabled={!canPanZoom}
              onClick={resetView}
            >
              <RotateCcw size={14} />
            </Button>
          </div>
        </div>

        <div
          ref={canvasRef}
          className="cad-grid relative min-h-0 flex-1 cursor-grab overflow-hidden active:cursor-grabbing"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={endPan}
          onPointerCancel={endPan}
        >
          {!mediaUrl && !isPdf ? (
            <div className="grid h-full place-items-center px-6 text-center text-xs text-muted-foreground">
              Upload and analyze a schematic to preview it here.
            </div>
          ) : isPdf && source ? (
            <iframe title="PDF schematic" src={source} className="h-full w-full bg-white" />
          ) : mediaUrl ? (
            <div
              className="absolute left-0 top-0 will-change-transform"
              style={{
                width: content.width || undefined,
                height: content.height || undefined,
                transform: `translate(${pan.x}px, ${pan.y}px) scale(${scale})`,
                transformOrigin: "0 0",
              }}
            >
              <div className="relative inline-block bg-white shadow-[0_0_0_1px_#1d3448]">
                {/* eslint-disable-next-line jsx-a11y/alt-text */}
                <img
                  src={mediaUrl}
                  alt="Schematic SVG preview"
                  className="block max-w-none select-none"
                  draggable={false}
                  onLoad={onMediaLoad}
                />
                {activeHighlight && (
                  <div
                    className="pointer-events-none absolute z-10 size-10 -translate-x-1/2 -translate-y-1/2"
                    style={{
                      left: `${activeHighlight.page.left}%`,
                      top: `${activeHighlight.page.top}%`,
                    }}
                    data-testid="schematic-locator-highlight"
                  >
                    <span className="absolute inset-0 rounded-full border-2 border-brand bg-brand/15" />
                    <span className="absolute inset-0 animate-reticle-ping rounded-full border border-brand" />
                    <span className="absolute left-1/2 top-11 -translate-x-1/2 whitespace-nowrap rounded bg-panel px-1.5 py-0.5 font-mono text-[10px] text-foreground shadow">
                      {activeHighlight.label}
                    </span>
                  </div>
                )}
              </div>
            </div>
          ) : null}
        </div>

        {(locateMessage || viewer?.render_message) && (
          <p className="border-t border-line px-3 py-2 text-[10px] text-muted-foreground">
            {locateMessage || viewer?.render_message}
          </p>
        )}
      </div>
    );
  },
);
