import { useCallback, useEffect, useRef, useState, type PointerEvent } from "react";
import { Minus, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";

type Point = { x: number; y: number };
type View = Point & { scale: number };
const FIT: View = { x: 0, y: 0, scale: 1 };
const MAX_SCALE = 8;
const PAN_STEP = 40;
const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));
const midpoint = (a: Point, b: Point): Point => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
const distance = (a: Point, b: Point) => Math.hypot(a.x - b.x, a.y - b.y);

export interface ImageViewportProps {
  src: string;
  alt: string;
  /** Styles for the bounded viewport; controls are a separate sibling. */
  className?: string;
  imageClassName?: string;
  controlsClassName?: string;
  testId?: string;
  /** Disable when a surrounding gallery owns the arrow keys. */
  panWithArrows?: boolean;
}

/** Image-local gestures and controls. Provide viewport dimensions and remount per image. */
export function ImageViewport({
  src,
  alt,
  className,
  imageClassName,
  controlsClassName,
  testId = "image-viewport",
  panWithArrows = true,
}: ImageViewportProps) {
  const { t } = useTranslation();
  const viewport = useRef<HTMLDivElement>(null);
  const image = useRef<HTMLImageElement>(null);
  const pointers = useRef(new Map<number, Point>());
  const viewRef = useRef(FIT);
  const [view, setView] = useState(FIT);
  const [dragging, setDragging] = useState(false);

  const apply = useCallback((next: View) => {
    const scale = clamp(next.scale, 1, MAX_SCALE);
    const maxX = Math.max(0, ((image.current?.offsetWidth ?? 0) * scale - (viewport.current?.clientWidth ?? 0)) / 2);
    const maxY = Math.max(0, ((image.current?.offsetHeight ?? 0) * scale - (viewport.current?.clientHeight ?? 0)) / 2);
    const bounded = { scale, x: clamp(next.x, -maxX, maxX), y: clamp(next.y, -maxY, maxY) };
    viewRef.current = bounded;
    setView(bounded);
  }, []);

  const zoom = useCallback((scale: number, from?: Point, to = from) => {
    const rect = viewport.current?.getBoundingClientRect();
    const current = viewRef.current;
    const next = clamp(scale, 1, MAX_SCALE);
    const center = rect ? { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 } : { x: 0, y: 0 };
    const origin = from ?? center;
    const target = to ?? origin;
    apply({
      scale: next,
      x: target.x - center.x - (origin.x - center.x - current.x) * next / current.scale,
      y: target.y - center.y - (origin.y - center.y - current.y) * next / current.scale,
    });
  }, [apply]);

  useEffect(() => {
    const element = viewport.current;
    if (!element) return;
    const activePointers = pointers.current;
    // React's wheel listener is passive; cancel browser zoom only over this viewport.
    const onWheel = (event: WheelEvent) => {
      if (event.ctrlKey) {
        event.preventDefault();
        zoom(viewRef.current.scale * Math.exp(-clamp(event.deltaY, -50, 50) * 0.01), { x: event.clientX, y: event.clientY });
      } else if (viewRef.current.scale > 1) {
        event.preventDefault();
        const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? element.clientHeight : 1;
        apply({ ...viewRef.current, x: viewRef.current.x - event.deltaX * unit, y: viewRef.current.y - event.deltaY * unit });
      }
    };
    element.addEventListener("wheel", onWheel, { passive: false });
    const resize = new ResizeObserver(() => apply(viewRef.current));
    resize.observe(element);
    return () => {
      element.removeEventListener("wheel", onWheel);
      resize.disconnect();
      for (const pointerId of activePointers.keys()) {
        if (element.hasPointerCapture(pointerId)) element.releasePointerCapture(pointerId);
      }
      activePointers.clear();
    };
  }, [apply, zoom]);

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 || pointers.current.size >= 2) return;
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragging(true);
  };
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!pointers.current.has(event.pointerId)) return;
    const before = [...pointers.current.values()];
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
    const after = [...pointers.current.values()];
    if (before.length === 2) {
      const previousDistance = distance(before[0], before[1]);
      if (previousDistance > 0) zoom(viewRef.current.scale * distance(after[0], after[1]) / previousDistance,
        midpoint(before[0], before[1]), midpoint(after[0], after[1]));
    } else if (viewRef.current.scale > 1) {
      apply({ ...viewRef.current, x: viewRef.current.x + after[0].x - before[0].x, y: viewRef.current.y + after[0].y - before[0].y });
    }
  };
  const endPointer = (event: PointerEvent<HTMLDivElement>) => {
    pointers.current.delete(event.pointerId);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    setDragging(pointers.current.size > 0);
  };
  const buttonClass = "grid size-9 shrink-0 place-items-center rounded-full transition-colors hover:text-foreground disabled:opacity-30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

  return <>
    <div ref={viewport} data-testid={testId} tabIndex={0} role="group" aria-label={t("lightbox.gestures")}
      className={cn("flex min-h-0 min-w-0 touch-none select-none items-center justify-center overflow-hidden focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring", view.scale > 1 ? dragging ? "cursor-grabbing" : "cursor-grab" : "cursor-zoom-in", className)}
      onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={endPointer} onPointerCancel={endPointer} onLostPointerCapture={endPointer}
      onDoubleClick={(event) => zoom(viewRef.current.scale > 1 ? 1 : 2, { x: event.clientX, y: event.clientY })}
      onKeyDown={(event) => {
        if (event.ctrlKey || event.metaKey || event.altKey) return;
        const current = viewRef.current;
        if (event.key === "+" || event.key === "=") zoom(current.scale * 1.5);
        else if (event.key === "-") zoom(current.scale / 1.5);
        else if (event.key === "0") apply(FIT);
        else if (panWithArrows && event.key === "ArrowLeft") apply({ ...current, x: current.x + PAN_STEP });
        else if (panWithArrows && event.key === "ArrowRight") apply({ ...current, x: current.x - PAN_STEP });
        else if (panWithArrows && event.key === "ArrowUp") apply({ ...current, y: current.y + PAN_STEP });
        else if (panWithArrows && event.key === "ArrowDown") apply({ ...current, y: current.y - PAN_STEP });
        else return;
        event.preventDefault();
        event.stopPropagation();
      }}>
      <img ref={image} src={src} alt={alt} decoding="async" draggable={false} onLoad={() => apply(viewRef.current)}
        className={cn("max-h-full max-w-full select-none object-contain will-change-transform", imageClassName)}
        style={{ transform: `translate3d(${view.x}px, ${view.y}px, 0) scale(${view.scale})` }} />
    </div>
    <div className={cn("flex items-center justify-center gap-1 rounded-full p-1 text-muted-foreground", controlsClassName)}>
      <button type="button" aria-label={t("lightbox.zoomOut")} title={t("lightbox.zoomOut")} disabled={view.scale <= 1} className={buttonClass} onClick={() => zoom(viewRef.current.scale / 1.5)}><Minus className="size-4" aria-hidden /></button>
      <button type="button" aria-label={t("lightbox.resetZoom")} title={t("lightbox.resetZoom")}
        className="h-9 min-w-14 rounded-full px-2 text-xs font-medium tabular-nums focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" onClick={() => apply(FIT)}>
        {Math.round(view.scale * 100)}%
      </button>
      <button type="button" aria-label={t("lightbox.zoomIn")} title={t("lightbox.zoomIn")} disabled={view.scale >= MAX_SCALE} className={buttonClass} onClick={() => zoom(viewRef.current.scale * 1.5)}><Plus className="size-4" aria-hidden /></button>
    </div>
  </>;
}
