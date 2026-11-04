import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { LayoutGroup, motion, useReducedMotion } from "motion/react";
import { Maximize2, Minimize2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { formatCompactTokenCount } from "@/lib/format";
import { formatTurnLatency } from "@/lib/format-time";
import { createGraphSimulation, updateGraphSimulation, settleGraphSimulation, type GraphPosition } from "@/lib/context-graph";
import type { ContextGraph, ContextSnapshot } from "@/lib/types";
import type { ComposerContextUsage, ComposerRoundUsage } from "./ComposerUsagePopover";

import { ContextReplayButton } from "./ContextReplayButton";
import { useGraphPresentation, type GraphPresentation } from "./useGraphPresentation";

const EMPTY_GRAPH: ContextGraph = { nodes: [], edges: [] };
const surface = "context-inspector-surface select-none rounded-[20px] bg-card";

function FileGraph({ graph, expanded, onExpand, onOpenFile, sidebar = false }: {
  graph: ContextGraph; expanded: boolean; sidebar?: boolean; onExpand: () => void; onOpenFile?: (path: string) => void;
}) {
  const { t } = useTranslation();
  const container = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 550, height: 300 });
  const nodeElements = useRef(new Map<string, { button: HTMLButtonElement; circle: HTMLElement; label: HTMLElement }>());
  const edgeElements = useRef(new Map<string, SVGLineElement>());
  const presented = useRef<GraphPresentation>({ nodes: [], edges: [] });
  const paint = useRef<() => void>(() => {});
  const previousPositions = useRef(new Map<string, GraphPosition>());
  const simulation = useRef<ReturnType<typeof createGraphSimulation>>();
  const view = useRef({ x: 0, y: 0, k: 1 });
  const setView = (update: typeof view.current | ((old: typeof view.current) => typeof view.current)) => {
    view.current = typeof update === "function" ? update(view.current) : update;
    paint.current();
  };
  const viewInteracted = useRef(false);
  const fitView = useRef<() => void>(() => {});
  const previousLayout = useRef("");
  const fittedSize = useRef("");
  const reducedMotion = !!useReducedMotion();
  const pan = useRef<{ id: number; x: number; y: number } | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const dragging = useRef<{ path: string; x: number; y: number; moved: boolean } | null>(null);
  useEffect(() => {
    const element = container.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => setSize({ width: entry.contentRect.width, height: entry.contentRect.height }));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    const sim = simulation.current ?? createGraphSimulation(graph, previousPositions.current, size.width, size.height);
    if (simulation.current) updateGraphSimulation(sim, graph, previousPositions.current, size.width, size.height);
    simulation.current = sim;
    const layoutKey = JSON.stringify([graph.nodes.map((node) => node.path), graph.edges, size]);
    const sameLayout = previousLayout.current === layoutKey;
    previousLayout.current = layoutKey;
    const sizeKey = `${size.width}:${size.height}`;
    sim.stop();
    if (reducedMotion) settleGraphSimulation(sim);
    else if (!sameLayout) sim.alpha(Math.max(sim.alpha(), 0.3));
    const draw = () => {
      for (const node of sim.nodes()) previousPositions.current.set(node.path, { x: node.x, y: node.y });
      paint.current();
    };
    fitView.current = () => {
      const points = new Map(sim.nodes().map((node) => [node.path, { x: node.x, y: node.y }]));
      if (points.size) {
        const xs = [...points.values()].map((point) => point.x), ys = [...points.values()].map((point) => point.y);
        const left = Math.min(...xs), right = Math.max(...xs), top = Math.min(...ys), bottom = Math.max(...ys);
        const k = Math.min(1, (size.width - 140) / Math.max(1, right - left), (size.height - 110) / Math.max(1, bottom - top));
        setView({ k, x: size.width / 2 - (left + right) / 2 * k, y: (size.height + 22) / 2 - (top + bottom) / 2 * k });
      }
    };
    sim.on("tick", draw);
    if (!reducedMotion && sim.alpha() > sim.alphaMin()) sim.restart();
    draw();
    if (!viewInteracted.current && graph.nodes.length && fittedSize.current !== sizeKey) {
      // Fixed initial camera: framing must not amplify the force simulation's motion.
      const radius = Math.sqrt(graph.nodes.length * (60 * 0.36) ** 2 / Math.PI);
      const k = Math.min(1, (size.width - 100) / Math.max(1, radius * 6), (size.height - 80) / Math.max(1, radius * 6));
      setView({ k, x: size.width / 2 * (1 - k), y: size.height / 2 * (1 - k) });
      fittedSize.current = sizeKey;
    }
    return () => { sim.stop(); };
  }, [graph, size.width, size.height, reducedMotion]);
  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      viewInteracted.current = true;
      const rect = element.getBoundingClientRect();
      const x = event.clientX - rect.left, y = event.clientY - rect.top;
      setView((old) => {
        const k = Math.max(0.25, Math.min(4, old.k * Math.exp(-event.deltaY * 0.002)));
        return { k, x: x - (x - old.x) * k / old.k, y: y - (y - old.y) * k / old.k };
      });
      setActive(null);
    };
    element.addEventListener("wheel", wheel, { passive: false });
    return () => element.removeEventListener("wheel", wheel);
  }, []);
  const candidate = active ?? hovered;
  const highlighted = graph.nodes.some((node) => node.path === candidate) ? candidate : null;
  // Match quartz-graph.js: labels fade in above 1× zoom; the hovered node stays legible.
  const labelOpacity = Math.max((view.current.k - 1) / 3.75, 0);
  const presentation = useGraphPresentation(graph, highlighted, reducedMotion, (frame) => {
    presented.current = frame;
    paint.current();
  });
  presented.current = presentation;
  paint.current = () => {
    const { x, y, k } = view.current;
    for (const node of presented.current.nodes) {
      const elements = nodeElements.current.get(node.path);
      const point = previousPositions.current.get(node.path);
      if (!elements || !point) continue;
      elements.button.style.transform = `translate3d(${point.x * k + x - 22}px,${point.y * k + y - 22}px,0)`;
      elements.button.style.opacity = String(node.presence * node.emphasis);
      elements.circle.style.width = `${node.radius * 2}px`;
      elements.circle.style.height = `${node.radius * 2}px`;
      elements.circle.style.borderColor = `color-mix(in srgb, hsl(var(--muted-foreground)), #f97316 ${node.focus * 100}%)`;
      elements.circle.style.backgroundColor = `color-mix(in srgb, hsl(var(--background)), color-mix(in srgb, hsl(var(--muted-foreground)), #f97316 ${node.focus * 100}%) ${node.loaded * 100}%)`;
      elements.label.style.opacity = String(node.path === highlighted ? 1 : Math.max((k - 1) / 3.75, 0));
    }
    for (const edge of presented.current.edges) {
      const element = edgeElements.current.get(JSON.stringify([edge.source, edge.target]));
      const a = previousPositions.current.get(edge.source), b = previousPositions.current.get(edge.target);
      if (!element || !a || !b) continue;
      element.setAttribute("x1", String(a.x * k + x)); element.setAttribute("y1", String(a.y * k + y));
      element.setAttribute("x2", String(b.x * k + x)); element.setAttribute("y2", String(b.y * k + y));
      element.setAttribute("opacity", String(edge.presence * edge.emphasis * 0.7));
    }
  };
  useLayoutEffect(() => { paint.current(); });
  const currentPaths = new Set(graph.nodes.map((node) => node.path));
  return <div ref={container} className={cn(surface, "relative isolate overflow-clip touch-none cursor-grab active:cursor-grabbing", sidebar ? "min-h-0 flex-1" : expanded ? "h-[min(65dvh,600px)]" : "h-[300px]")}
    onPointerDown={(e) => { if (e.button !== 0 || (e.target as HTMLElement).closest("button")) return; viewInteracted.current = true; pan.current = { id: e.pointerId, x: e.clientX, y: e.clientY }; e.currentTarget.setPointerCapture(e.pointerId); setActive(null); }}
    onPointerMove={(e) => { if (dragging.current) return; const previous = pan.current; if (!previous || previous.id !== e.pointerId) return; const dx = e.clientX - previous.x, dy = e.clientY - previous.y; pan.current = { id: e.pointerId, x: e.clientX, y: e.clientY }; setView((old) => ({ ...old, x: old.x + dx, y: old.y + dy })); }}
    onPointerUp={() => { pan.current = null; }} onPointerCancel={() => { pan.current = null; }} onLostPointerCapture={() => { pan.current = null; }}
    onDoubleClick={(e) => { if (!(e.target as HTMLElement).closest("button")) { viewInteracted.current = false; fitView.current(); } }}>
    <button type="button" onClick={onExpand} aria-label={t(expanded ? "thread.composer.context.collapse" : "thread.composer.context.expand")}
      className="absolute right-2 top-2 z-10 flex size-9 items-center justify-center rounded-full bg-background/90 text-muted-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      {expanded ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
    </button>
    {!graph.nodes.length && !presentation.nodes.length && <p className="absolute inset-0 flex items-center justify-center px-6 text-center text-xs text-muted-foreground">{t("thread.composer.context.noFiles")}</p>}
    <div className="absolute inset-0">
    <svg className="pointer-events-none absolute inset-0 size-full" aria-hidden="true">
      <g>
      {presentation.edges.map((edge) => {
        const a = previousPositions.current.get(edge.source), b = previousPositions.current.get(edge.target);
        if (!a || !b) return null;
        const target = graph.nodes.find((node) => node.path === edge.target);
        return <line key={JSON.stringify([edge.source, edge.target])} ref={(element) => { const key = JSON.stringify([edge.source, edge.target]); if (element) edgeElements.current.set(key, element); else edgeElements.current.delete(key); }} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
          className="stroke-orange-500" strokeWidth={1} strokeDasharray={target?.state === "discovered" ? "3 5" : undefined}
          opacity={edge.presence * edge.emphasis * 0.7} />;
      })}
      </g>
    </svg>
    {presentation.nodes.map((node) => {
      const p = previousPositions.current.get(node.path);
      if (!p) return null;
      const radius = node.radius;
      const present = currentPaths.has(node.path);
      return <Popover key={node.path} open={present && active === node.path} onOpenChange={(open) => setActive(open ? node.path : null)}>
        <PopoverTrigger asChild>
          <button type="button" onPointerEnter={(e) => { if (e.pointerType === "mouse") setHovered(node.path); }} onPointerLeave={() => setHovered(null)}
            onFocus={() => setHovered(node.path)} onBlur={() => setHovered(null)}
            onPointerDown={(e) => { if (e.button !== 0) return; e.stopPropagation(); pan.current = null; viewInteracted.current = true; dragging.current = { path: node.path, x: e.clientX, y: e.clientY, moved: false }; e.currentTarget.setPointerCapture(e.pointerId); }}
            onPointerMove={(e) => {
              const drag = dragging.current;
              if (!drag || drag.path !== node.path) return;
              e.stopPropagation();
              const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
              if (!drag.moved && Math.hypot(dx, dy) < 5) return;
              drag.moved = true; drag.x = e.clientX; drag.y = e.clientY; setActive(null); setHovered(node.path);
              const particle = simulation.current?.nodes().find((item) => item.path === node.path);
              if (particle) { particle.fx = (particle.fx ?? particle.x) + dx / view.current.k; particle.fy = (particle.fy ?? particle.y) + dy / view.current.k; simulation.current?.alphaTarget(0.25).restart(); }
            }}
            onPointerUp={(e) => { const particle = simulation.current?.nodes().find((item) => item.path === node.path); if (particle) { particle.fx = null; particle.fy = null; } simulation.current?.alphaTarget(0); if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId); }}
            onPointerCancel={() => { const particle = simulation.current?.nodes().find((item) => item.path === node.path); if (particle) { particle.fx = null; particle.fy = null; } simulation.current?.alphaTarget(0); dragging.current = null; }}
            onClick={(e) => { if (dragging.current?.moved) { e.preventDefault(); setActive(null); } dragging.current = null; }}
            ref={(button) => {
              if (button) nodeElements.current.set(node.path, { button, circle: button.querySelector("span span")!, label: button.lastElementChild as HTMLElement });
              else nodeElements.current.delete(node.path);
            }}
            aria-label={node.name} aria-hidden={!present || undefined} tabIndex={present ? 0 : -1} disabled={!present}
            className="absolute flex size-11 touch-none cursor-grab active:cursor-grabbing items-center justify-center rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            style={{ left: 0, top: 0, transform: `translate3d(${p.x * view.current.k + view.current.x - 22}px,${p.y * view.current.k + view.current.y - 22}px,0)`, pointerEvents: "none", opacity: node.presence * node.emphasis }}>
            <span aria-hidden="true" className="absolute inset-0 [clip-path:circle(50%)] [@media(pointer:fine)]:inset-[10px]" style={{ pointerEvents: present ? "auto" : "none" }} />
            <span className="flex h-8 items-center justify-center"><span className="block rounded-full border" style={{
              pointerEvents: present ? "auto" : "none",
              width: radius * 2, height: radius * 2,
              borderColor: `color-mix(in srgb, hsl(var(--muted-foreground)), #f97316 ${node.focus * 100}%)`,
              backgroundColor: `color-mix(in srgb, hsl(var(--background)), color-mix(in srgb, hsl(var(--muted-foreground)), #f97316 ${node.focus * 100}%) ${node.loaded * 100}%)`,
            }} /></span>
            <span aria-hidden="true" className="pointer-events-none absolute top-[calc(50%+16px)] left-1/2 max-w-32 -translate-x-1/2 truncate px-0.5 text-[10px] leading-4 text-foreground transition-opacity duration-150 ease-out motion-reduce:transition-none" style={{ opacity: highlighted === node.path ? 1 : labelOpacity }}>{node.name}</span>
          </button>
        </PopoverTrigger>
        <PopoverContent side="bottom" sideOffset={12} collisionPadding={12} onOpenAutoFocus={(e) => e.preventDefault()}
          onCloseAutoFocus={(e) => e.preventDefault()}
          className="flex w-auto select-none items-center gap-4 rounded-xl px-3 py-2.5 font-sans text-ui-label">
          <span className="text-muted-foreground">{t(node.state === "loaded" ? "thread.composer.context.loaded" : "thread.composer.context.unloaded")}</span>
          {node.state === "loaded" && <span className="tabular-nums text-muted-foreground">{t("thread.composer.context.estimatedNodeTokens", { value: formatCompactTokenCount(node.tokens) })}</span>}
          {onOpenFile && <button type="button" className="min-h-8 font-sans text-ui-label text-orange-600 dark:text-orange-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" onClick={() => onOpenFile(node.path)}>{t("thread.composer.context.openFile")}</button>}
        </PopoverContent>
      </Popover>;
    })}
    </div>
  </div>;
}

export function ContextInspector({ context, rounds, snapshots, onOpenFile, sidebar = false }: {
  context: ComposerContextUsage | null; rounds: readonly ComposerRoundUsage[];
  snapshots: readonly ContextSnapshot[]; onOpenFile?: (path: string) => void; sidebar?: boolean;
}) {
  const { t } = useTranslation();
  const layoutId = useId();
  const reducedMotion = useReducedMotion();
  const [expanded, setExpanded] = useState(false);
  const [replay, setReplay] = useState<{ frames: readonly ContextSnapshot[]; index: number } | null>(null);
  const [meterHover, setMeterHover] = useState(false);
  const epoch = snapshots[0]?.id;
  useEffect(() => { setReplay(null); }, [epoch]);
  useEffect(() => {
    if (!replay) return;
    const timer = window.setTimeout(() => setReplay((current) => current && current.index + 1 < current.frames.length
      ? { ...current, index: current.index + 1 } : null), 750);
    return () => window.clearTimeout(timer);
  }, [replay]);
  const snapshot = replay ? replay.frames[replay.index] : snapshots.at(-1);
  const latestRound = rounds.at(-1);
  const tokens = snapshot?.estimatedTokens ?? snapshot?.usage?.context_tokens ?? snapshot?.usage?.prompt_tokens ?? context?.contextTokens;
  const estimated = snapshot?.estimatedTokens !== undefined || (!snapshot?.usage && context?.estimated);
  const windowTokens = snapshot?.contextWindowTokens ?? context?.contextWindowTokens;
  const used = tokens !== undefined && windowTokens ? Math.min(100, tokens / windowTokens * 100) : null;
  const cached = snapshot ? snapshot.usage?.cached_tokens : latestRound?.cachedTokens;
  const input = snapshot ? snapshot.usage?.prompt_tokens : latestRound?.inputTokens;
  const cachedWidth = cached !== undefined && windowTokens ? Math.min(used ?? 0, cached / windowTokens * 100) : 0;
  const duration = snapshot ? snapshot.usage?.generation_ms : latestRound?.generationMs;
  const content = (large: boolean) => <motion.div layoutId={layoutId} transition={{ duration: reducedMotion ? 0 : 0.25, ease: [0.2, 0, 0, 1] }} className={cn("flex flex-col gap-3", sidebar && !large && "h-full min-h-0")}>
    <FileGraph graph={snapshot?.graph ?? EMPTY_GRAPH} expanded={large} sidebar={sidebar && !large} onExpand={() => setExpanded(!large)} onOpenFile={onOpenFile ? (path) => { setExpanded(false); onOpenFile(path); } : undefined} />
    <div className="flex shrink-0 items-center gap-3">
    <div onPointerEnter={() => setMeterHover(true)} onPointerLeave={() => setMeterHover(false)} className={cn(surface, "relative flex h-14 min-w-0 flex-1 items-center gap-4 px-4 transition-transform duration-150 ease-out motion-reduce:transition-none", meterHover && "scale-[1.015]")}>
      <div className="flex h-11 flex-1 items-center">
        <div role="progressbar" aria-label={t("thread.composer.context.contextTitle")} aria-valuemin={0} aria-valuemax={100} aria-valuenow={used === null ? undefined : Math.round(used)} className="relative h-1.5 w-full overflow-hidden rounded-full bg-muted">
          <span className="absolute inset-y-0 left-0 rounded-full bg-muted-foreground/45 transition-[width] duration-150 ease-out motion-reduce:transition-none" style={{ width: `${used ?? 0}%` }} />
          <span className="absolute inset-y-0 left-0 rounded-full bg-orange-500 transition-[width] duration-150 ease-out motion-reduce:transition-none" style={{ width: `${cachedWidth}%` }} />
        </div>
      </div>
      <span className="text-sm tabular-nums">{used === null ? "—" : `${estimated ? "≈" : ""}${Math.round(used)}%`}</span>
      {meterHover && (cached !== undefined || duration !== undefined || replay !== null) && <div className="pointer-events-none absolute bottom-full right-0 z-20 mb-2 min-w-48 rounded-xl bg-popover px-3 py-2.5 font-sans text-xs font-normal leading-5 shadow-lg">
        <dl className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-6 gap-y-1">
          {cached !== undefined && !!input && <><dt className="text-muted-foreground">{t("thread.composer.context.cacheHitRate")}</dt><dd className="whitespace-nowrap text-right tabular-nums text-popover-foreground">{Math.round(cached / input * 100)}%</dd></>}
          {duration !== undefined && <><dt className="text-muted-foreground">{t("thread.composer.context.duration")}</dt><dd className="whitespace-nowrap text-right tabular-nums text-popover-foreground">{formatTurnLatency(duration)}</dd></>}
          {replay && <><dt className="text-muted-foreground">{t("thread.composer.context.history")}</dt>
            <dd className="text-right tabular-nums text-muted-foreground">{replay.index + 1}/{replay.frames.length}</dd></>}
        </dl>
      </div>}
    </div>
    <ContextReplayButton disabled={replay !== null || snapshots.length < 2}
      onPlay={() => { setMeterHover(false); setReplay({ frames: [...snapshots], index: 0 }); }} />
    </div>
  </motion.div>;
  return <LayoutGroup>
    {!expanded && content(false)}
    <Dialog open={expanded} onOpenChange={setExpanded}>
      <DialogContent showCloseButton={false} aria-describedby={undefined} overlayClassName="context-expanded-overlay bg-background/30 backdrop-blur-md" className="w-[min(960px,calc(100vw-2rem))] max-w-none border-0 bg-transparent p-0 shadow-none !animate-none">
        <DialogTitle className="sr-only">{t("thread.composer.context.panelTitle")}</DialogTitle>
        {content(true)}
      </DialogContent>
    </Dialog>
  </LayoutGroup>;
}
