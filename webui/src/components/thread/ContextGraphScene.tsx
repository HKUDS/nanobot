import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useReducedMotion } from "motion/react";
import { Maximize2, Minimize2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Popover, PopoverAnchor, PopoverContent } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { formatCompactTokenCount } from "@/lib/format";
import { createGraphSimulation, updateGraphSimulation, advanceGraphSimulation, startGraphSettlement, type GraphParticle, type GraphPosition } from "@/lib/context-graph-layout";
import type { ContextGraph } from "@/lib/types";
import { createGraphPresentation } from "./graph-presentation";
import { paintGraph, readGraphPalette, type GraphPalette } from "./graph-canvas";

const surface = "context-inspector-surface select-none rounded-[20px] bg-card";

export const ContextGraphScene = memo(function ContextGraphScene({ graph, epoch, expanded, onExpand, onOpenFile, onReady, sidebar = false }: {
  graph: ContextGraph; epoch?: string; expanded: boolean; onExpand?: () => void; onOpenFile?: (path: string) => void; onReady?: (graph: ContextGraph) => void; sidebar?: boolean;
}) {
  const { t } = useTranslation();
  const container = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const paletteProbe = useRef<HTMLSpanElement>(null);
  const palette = useRef<GraphPalette>();
  const nodeElements = useRef(new Map<string, HTMLButtonElement>());
  const focused = useRef<string | null>(null);
  const positions = useRef(new Map<string, GraphPosition>());
  const particles = useRef(new Map<string, GraphParticle>());
  const simulation = useRef<ReturnType<typeof createGraphSimulation>>();
  const settlement = useRef<ReturnType<typeof startGraphSettlement> | null>(null);
  const paintedGraph = useRef<ContextGraph>();
  const [presentation] = useState(createGraphPresentation);
  const [frame, setFrame] = useState(presentation.frame);
  const [size, setSize] = useState({ width: 550, height: 300 });
  const [active, setActive] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const currentNodes = useMemo(() => new Map(graph.nodes.map((node) => [node.path, node])), [graph]);
  const discovered = useMemo(() => new Set(graph.nodes.filter((node) => node.state === "discovered").map((node) => node.path)), [graph]);
  const selected = active ? currentNodes.get(active) : undefined;
  const candidate = active ?? hovered;
  const highlighted = candidate && currentNodes.has(candidate) ? candidate : null;
  const reducedMotion = !!useReducedMotion();
  const clock = useRef({ frame: 0, previous: 0, visible: true, geometry: true });
  const draw = useRef<(time: number) => void>(() => {});
  const view = useRef({ x: 0, y: 0, k: 1 });
  const interacted = useRef(false);
  const fittedSize = useRef("");
  const layoutKey = useRef("");
  const pruneEpoch = useRef(false);
  const previousEpoch = useRef(epoch);
  const pan = useRef<{ id: number; x: number; y: number } | null>(null);
  const dragging = useRef<{ id: number; path: string; x: number; y: number; moved: boolean } | null>(null);
  const restoreNodeFocus = useRef(false);
  const schedule = useCallback(() => {
    if (!clock.current.frame && clock.current.visible && !document.hidden) clock.current.frame = requestAnimationFrame((time) => draw.current(time));
  }, []);
  const setView = useCallback((next: typeof view.current) => {
    view.current = next;
    schedule();
  }, [schedule]);
  draw.current = (time) => {
    const state = clock.current;
    state.frame = 0;
    if (!state.visible || document.hidden) return;
    const elapsed = state.previous ? time - state.previous : 1000 / 60;
    state.previous = time;
    const sim = simulation.current;
    if (settlement.current) {
      if (!settlement.current()) { schedule(); return; }
      settlement.current = null; state.geometry = true;
    }
    const running = !!sim && (sim.alpha() > sim.alphaMin() || sim.alphaTarget() > 0);
    if (sim && running && !reducedMotion) { advanceGraphSimulation(sim, elapsed); state.geometry = true; }
    const change = presentation.advance(elapsed, reducedMotion);
    if (change.removed) {
      setFrame(presentation.frame);
      if (pruneEpoch.current) {
        const retained = new Set(presentation.frame.nodes.map((node) => node.path));
        for (const path of positions.current.keys()) if (!retained.has(path)) positions.current.delete(path);
      }
    }
    if (!change.moving) pruneEpoch.current = false;
    if (state.geometry && sim) for (const particle of sim.nodes()) {
      const point = positions.current.get(particle.path);
      if (point) { point.x = particle.x; point.y = particle.y; }
      else positions.current.set(particle.path, { x: particle.x, y: particle.y });
    }
    const bitmap = canvas.current;
    const context = bitmap?.getContext("2d");
    if (bitmap && context && palette.current) {
      // Keep motion within a pixel budget; the final stationary paint restores
      // native resolution for crisp labels without paying that cost every frame.
      const ratio = running || change.moving
        ? Math.min(window.devicePixelRatio || 1, 1.5, Math.sqrt(1_000_000 / (size.width * size.height)))
        : window.devicePixelRatio || 1;
      const width = Math.round(size.width * ratio), height = Math.round(size.height * ratio);
      if (bitmap.width !== width || bitmap.height !== height) { bitmap.width = width; bitmap.height = height; }
      paintGraph(context, presentation.frame, positions.current, view.current, palette.current, highlighted, focused.current,
        size.width, size.height, ratio, discovered);
      if (paintedGraph.current !== graph) { paintedGraph.current = graph; onReady?.(graph); }
    }
    state.geometry = false;
    if (change.moving || (running && !reducedMotion)) schedule();
    // The next animation starts a new clock; idle time must not consume its labels.
    else state.previous = 0;
  };
  useEffect(() => {
    if (previousEpoch.current === epoch) return;
    previousEpoch.current = epoch;
    pruneEpoch.current = true;
    palette.current?.labels.clear();
    const retained = new Set(graph.nodes.map((node) => node.path));
    for (const node of presentation.frame.nodes) retained.add(node.path);
    for (const path of positions.current.keys()) if (!retained.has(path)) positions.current.delete(path);
  }, [epoch, graph, presentation]);
  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setSize({ width: entry.contentRect.width, height: entry.contentRect.height }));
    observer.observe(element);
    const visibility = () => { clock.current.previous = 0; if (document.hidden) { cancelAnimationFrame(clock.current.frame); clock.current.frame = 0; } else schedule(); };
    document.addEventListener("visibilitychange", visibility);
    window.addEventListener("resize", schedule);
    const intersection = typeof IntersectionObserver === "undefined" ? null : new IntersectionObserver((entries) => {
      // Drawer entry can batch offscreen and onscreen records together. The
      // newest record owns visibility; the first can leave painting suspended.
      const entry = entries[entries.length - 1];
      clock.current.visible = entry.isIntersecting;
      if (entry.isIntersecting) { clock.current.previous = 0; schedule(); }
      else { cancelAnimationFrame(clock.current.frame); clock.current.frame = 0; clock.current.previous = 0; }
    });
    intersection?.observe(element);
    return () => { observer.disconnect(); intersection?.disconnect(); document.removeEventListener("visibilitychange", visibility); window.removeEventListener("resize", schedule); cancelAnimationFrame(clock.current.frame); clock.current.frame = 0; simulation.current?.stop(); };
  }, [schedule]);
  useEffect(() => {
    const sim = simulation.current ?? createGraphSimulation(graph, positions.current, size.width, size.height);
    if (simulation.current) updateGraphSimulation(sim, graph, positions.current, size.width, size.height);
    simulation.current = sim.stop();
    particles.current = new Map(sim.nodes().map((node) => [node.path, node]));
    const nextLayout = JSON.stringify([graph.nodes.map((node) => node.path), graph.edges, size]);
    settlement.current = reducedMotion && (layoutKey.current !== nextLayout || sim.alpha() > sim.alphaMin()) ? startGraphSettlement(sim) : null;
    if (!reducedMotion && layoutKey.current !== nextLayout) sim.alpha(Math.max(sim.alpha(), 0.3));
    layoutKey.current = nextLayout;
    clock.current.geometry = true;
    const key = `${size.width}:${size.height}`;
    if (!interacted.current && graph.nodes.length && fittedSize.current !== key) {
      const radius = Math.sqrt(graph.nodes.length * (60 * 0.36) ** 2 / Math.PI);
      const k = Math.max(0.01, Math.min(1, (size.width - 100) / Math.max(1, radius * 6), (size.height - 80) / Math.max(1, radius * 6)));
      setView({ k, x: size.width / 2 * (1 - k), y: size.height / 2 * (1 - k) });
      fittedSize.current = key;
    }
    schedule();
  }, [graph, size, reducedMotion, schedule, setView]);
  useEffect(() => {
    setActive((path) => path && currentNodes.has(path) ? path : null);
    setHovered((path) => path && currentNodes.has(path) ? path : null);
  }, [currentNodes]);
  useEffect(() => {
    setFrame(presentation.update(graph, highlighted));
    schedule();
  }, [graph, highlighted, presentation, schedule]);
  useLayoutEffect(() => { clock.current.geometry = true; schedule(); }, [frame, schedule]);
  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const wheel = (event: WheelEvent) => {
      event.preventDefault(); interacted.current = true;
      const rect = element.getBoundingClientRect();
      const x = event.clientX - rect.left, y = event.clientY - rect.top, old = view.current;
      const k = Math.max(0.25, Math.min(4, old.k * Math.exp(-event.deltaY * 0.002)));
      setView({ k, x: x - (x - old.x) * k / old.k, y: y - (y - old.y) * k / old.k });
      setActive(null);
    };
    element.addEventListener("wheel", wheel, { passive: false });
    return () => element.removeEventListener("wheel", wheel);
  }, [setView]);
  const anchor = useRef({ getBoundingClientRect: () => new DOMRect() });
  anchor.current.getBoundingClientRect = () => {
    const rect = container.current?.getBoundingClientRect(), point = active ? positions.current.get(active) : undefined;
    return new DOMRect((rect?.x ?? 0) + (point?.x ?? 0) * view.current.k + view.current.x - 22,
      (rect?.y ?? 0) + (point?.y ?? 0) * view.current.k + view.current.y - 22, 44, 44);
  };
  const endDrag = (id: number, cancelled: boolean) => {
    const drag = dragging.current;
    if (!drag || drag.id !== id) return;
    const particle = particles.current.get(drag.path);
    if (particle) {
      if (particle.fx != null) particle.x = particle.fx;
      if (particle.fy != null) particle.y = particle.fy;
      particle.fx = null; particle.fy = null;
      clock.current.geometry = true;
    }
    simulation.current?.alphaTarget(0);
    if (!cancelled && !drag.moved) setActive((path) => path === drag.path ? null : drag.path);
    dragging.current = null;
    schedule();
  };
  const nodeAt = (clientX: number, clientY: number, radius: number) => {
    const rect = container.current?.getBoundingClientRect();
    if (!rect) return null;
    const x = clientX - rect.left, y = clientY - rect.top;
    let closest: string | null = null;
    let distance = Infinity;
    for (let index = presentation.frame.nodes.length - 1; index >= 0; index--) {
      const node = presentation.frame.nodes[index], point = positions.current.get(node.path);
      if (!point || !currentNodes.has(node.path)) continue;
      const candidateDistance = Math.hypot(point.x * view.current.k + view.current.x - x, point.y * view.current.k + view.current.y - y);
      if (candidateDistance <= Math.max(radius, node.radius) && candidateDistance < distance) { closest = node.path; distance = candidateDistance; }
    }
    return closest;
  };
  useLayoutEffect(() => {
    const update = () => { if (paletteProbe.current) palette.current = readGraphPalette(paletteProbe.current); schedule(); };
    update();
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class", "style"] });
    return () => observer.disconnect();
  }, [schedule]);
  const controls = useMemo(() => (<div className="sr-only">
      {graph.nodes.map((node) => <button key={node.path} type="button" data-context-node={node.path} aria-label={node.name} aria-expanded={active === node.path} aria-haspopup="dialog"
        ref={(element) => { if (element) nodeElements.current.set(node.path, element); else nodeElements.current.delete(node.path); }}
        onFocus={(e) => { focused.current = e.currentTarget.matches(":focus-visible") ? node.path : null; setHovered(node.path); schedule(); }}
        onKeyDown={() => { focused.current = node.path; schedule(); }}
        onBlur={() => { focused.current = null; setHovered(null); schedule(); }}
        onClick={() => setActive((path) => path === node.path ? null : node.path)}>{node.name}</button>)}
    </div>), [graph.nodes, active, schedule]);
  return <div ref={container} className={cn(surface, "relative isolate overflow-clip touch-none cursor-grab active:cursor-grabbing", sidebar ? "min-h-0 flex-1" : expanded ? "h-[min(65dvh,600px)]" : "h-[300px]")}
    onPointerDown={(e) => {
      if (!(e.target instanceof Node) || !e.currentTarget.contains(e.target)) return;
      if (e.button !== 0 || !e.isPrimary || (e.target instanceof Element && e.target.closest("button"))) return;
      // Keep the node's managed focus. Touch compatibility mouse events would
      // otherwise focus the drawer and immediately dismiss its node popover.
      e.preventDefault();
      interacted.current = true;
      const path = nodeAt(e.clientX, e.clientY, e.pointerType === "mouse" ? 12 : 22);
      if (path) {
        nodeElements.current.get(path)?.focus({ preventScroll: true });
        dragging.current = { id: e.pointerId, path, x: e.clientX, y: e.clientY, moved: false };
        pan.current = null;
      } else { pan.current = { id: e.pointerId, x: e.clientX, y: e.clientY }; setActive(null); }
      e.currentTarget.setPointerCapture(e.pointerId);
    }}
    onPointerMove={(e) => {
      if (!(e.target instanceof Node) || !e.currentTarget.contains(e.target)) return;
      const drag = dragging.current;
      if (drag && drag.id === e.pointerId) {
        const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
        if (!drag.moved && Math.hypot(dx, dy) < 5) return;
        drag.moved = true; drag.x = e.clientX; drag.y = e.clientY; setActive(null); setHovered(drag.path);
        const particle = particles.current.get(drag.path);
        if (particle) {
          particle.fx = (particle.fx ?? particle.x) + dx / view.current.k; particle.fy = (particle.fy ?? particle.y) + dy / view.current.k;
          if (reducedMotion) { particle.x = particle.fx; particle.y = particle.fy; clock.current.geometry = true; }
          else simulation.current?.alphaTarget(0.25);
          schedule();
        }
      } else if (pan.current?.id === e.pointerId) {
        const old = view.current, previous = pan.current;
        setView({ ...old, x: old.x + e.clientX - previous.x, y: old.y + e.clientY - previous.y });
        pan.current = { id: e.pointerId, x: e.clientX, y: e.clientY };
      } else if (e.pointerType === "mouse") setHovered(nodeAt(e.clientX, e.clientY, 12));
    }}
    onPointerLeave={() => { if (!dragging.current) setHovered(null); }}
    onPointerUp={(e) => { endDrag(e.pointerId, false); if (pan.current?.id === e.pointerId) pan.current = null; }}
    onPointerCancel={(e) => { endDrag(e.pointerId, true); if (pan.current?.id === e.pointerId) pan.current = null; }}
    onLostPointerCapture={(e) => { endDrag(e.pointerId, true); if (pan.current?.id === e.pointerId) pan.current = null; }}
    onDoubleClick={(e) => {
      if (!(e.target instanceof Node) || !e.currentTarget.contains(e.target)) return;
      if ((e.target instanceof Element && e.target.closest("button")) || nodeAt(e.clientX, e.clientY, 22)) return;
      const points = [...particles.current.values()];
      if (!points.length) return;
      const xs = points.map((p) => p.x), ys = points.map((p) => p.y);
      const left = Math.min(...xs), right = Math.max(...xs), top = Math.min(...ys), bottom = Math.max(...ys);
      const k = Math.max(0.01, Math.min(1, (size.width - 140) / Math.max(1, right - left), (size.height - 110) / Math.max(1, bottom - top)));
      interacted.current = false; setView({ k, x: size.width / 2 - (left + right) / 2 * k, y: (size.height + 22) / 2 - (top + bottom) / 2 * k });
    }}>
    <span ref={paletteProbe} aria-hidden className="invisible absolute bg-background text-muted-foreground" />
    {onExpand && <button type="button" onClick={onExpand} aria-label={t(expanded ? "thread.composer.context.collapse" : "thread.composer.context.expand")}
      className="absolute right-2 top-2 z-10 flex size-9 items-center justify-center rounded-full bg-background/90 text-muted-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      {expanded ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
    </button>}
    {!graph.nodes.length && !frame.nodes.length && <p className="absolute inset-0 flex items-center justify-center px-6 text-center text-xs text-muted-foreground">{t("thread.composer.context.noFiles")}</p>}
    <canvas ref={canvas} aria-hidden="true" className="absolute inset-0 size-full" />
    {controls}
    <Popover open={!!selected} onOpenChange={(open) => { if (!open) setActive(null); }}>
      <PopoverAnchor virtualRef={anchor} />
      {selected && <PopoverContent updatePositionStrategy="always" side="bottom" sideOffset={12} collisionPadding={12} onOpenAutoFocus={(e) => e.preventDefault()}
        onEscapeKeyDown={() => { restoreNodeFocus.current = true; }}
        onCloseAutoFocus={(e) => { e.preventDefault(); if (restoreNodeFocus.current) nodeElements.current.get(selected.path)?.focus(); restoreNodeFocus.current = false; }} onInteractOutside={(e) => { if (e.target instanceof Element && container.current?.contains(e.target) && e.target.closest("[data-context-node],canvas")) e.preventDefault(); }} className="flex w-auto select-none items-center gap-4 rounded-xl px-3 py-2.5 font-sans text-ui-label">
        <span className="text-muted-foreground">{t(selected.state === "loaded" ? "thread.composer.context.loaded" : "thread.composer.context.unloaded")}</span>
        {selected.state === "loaded" && <span className="tabular-nums text-muted-foreground">{t("thread.composer.context.estimatedNodeTokens", { value: formatCompactTokenCount(selected.tokens) })}</span>}
        {onOpenFile && <button type="button" className="min-h-8 font-sans text-ui-label text-orange-600 dark:text-orange-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" onClick={() => onOpenFile(selected.path)}>{t("thread.composer.context.openFile")}</button>}
      </PopoverContent>}
    </Popover>
  </div>;
});
