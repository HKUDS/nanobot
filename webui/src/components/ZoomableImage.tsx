import { useCallback, useEffect, useRef, useState, type PointerEvent } from "react";
import { Minus, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";

type Point = { x: number; y: number };
type View = Point & { scale: number };
const FIT: View = { x: 0, y: 0, scale: 1 };
const MAX_SCALE = 8;
const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));
const midpoint = (a: Point, b: Point): Point => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
const distance = (a: Point, b: Point) => Math.hypot(a.x - b.x, a.y - b.y);

/** Image-local gestures; the surrounding page retains normal browser zoom. Remount per image. */
export function ZoomableImage({ src, alt }: { src: string; alt: string }) {
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
    // React's wheel listener is passive; cancel browser zoom only over this image viewport.
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
    return () => { element.removeEventListener("wheel", onWheel); resize.disconnect(); };
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
  const buttonClass = "grid size-9 shrink-0 place-items-center rounded-full text-white/90 transition-colors hover:bg-white/10 hover:text-white disabled:opacity-30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70";

  return <>
    <div ref={viewport} data-testid="image-zoom-viewport" tabIndex={0} role="group" aria-label={t("lightbox.gestures")}
      className={cn("absolute inset-x-3 bottom-[calc(4rem+env(safe-area-inset-bottom))] top-14 flex touch-none select-none items-center justify-center overflow-hidden focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-white/40 sm:inset-x-8", view.scale > 1 ? dragging ? "cursor-grabbing" : "cursor-grab" : "cursor-zoom-in")}
      onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={endPointer} onPointerCancel={endPointer} onLostPointerCapture={endPointer}
      onDoubleClick={(event) => zoom(view.scale > 1 ? 1 : 2, { x: event.clientX, y: event.clientY })}
      onKeyDown={(event) => {
        if (event.key === "+" || event.key === "=") zoom(view.scale * 1.5);
        else if (event.key === "-") zoom(view.scale / 1.5);
        else if (event.key === "0") apply(FIT);
        else return;
        event.preventDefault();
      }}>
      <img ref={image} src={src} alt={alt} decoding="async" draggable={false} onLoad={() => apply(viewRef.current)}
        className="max-h-full max-w-full select-none rounded-compact object-contain shadow-2xl will-change-transform"
        style={{ transform: `translate3d(${view.x}px, ${view.y}px, 0) scale(${view.scale})` }} />
    </div>
    <div className="absolute bottom-[calc(1rem+env(safe-area-inset-bottom))] left-1/2 flex -translate-x-1/2 items-center gap-1 rounded-full bg-black/55 p-1 backdrop-blur-sm">
      <button type="button" aria-label={t("lightbox.zoomOut")} title={t("lightbox.zoomOut")} disabled={view.scale <= 1} className={buttonClass} onClick={() => zoom(view.scale / 1.5)}><Minus className="size-4" aria-hidden /></button>
      <button type="button" aria-label={t("lightbox.resetZoom")} title={t("lightbox.resetZoom")}
        className="h-9 min-w-14 rounded-full px-2 text-xs font-medium tabular-nums text-white/90 hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70" onClick={() => apply(FIT)}>
        {Math.round(view.scale * 100)}%
      </button>
      <button type="button" aria-label={t("lightbox.zoomIn")} title={t("lightbox.zoomIn")} disabled={view.scale >= MAX_SCALE} className={buttonClass} onClick={() => zoom(view.scale * 1.5)}><Plus className="size-4" aria-hidden /></button>
    </div>
  </>;
}
