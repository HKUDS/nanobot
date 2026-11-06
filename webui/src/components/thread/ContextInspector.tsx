import { lazy, Suspense, useCallback, useEffect, useId, useRef, useState } from "react";
import { LayoutGroup, motion, useReducedMotion } from "motion/react";
import { useTranslation } from "react-i18next";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { formatTurnLatency } from "@/lib/format-time";
import type { ContextGraph, ContextSnapshot } from "@/lib/types";
import type { ComposerContextUsage, ComposerRoundUsage } from "./ComposerUsagePopover";

import { ContextReplayButton } from "./ContextReplayButton";

const ContextGraphScene = lazy(() => import("./ContextGraphScene").then(module => ({ default: module.ContextGraphScene })));

const EMPTY_GRAPH: ContextGraph = { nodes: [], edges: [] };
const surface = "context-inspector-surface select-none rounded-[20px] bg-card";

function latestUsageSnapshot(snapshots: readonly ContextSnapshot[]) {
  for (let index = snapshots.length - 1; index >= 0; index -= 1) {
    const snapshot = snapshots[index];
    if (snapshot.estimatedTokens !== undefined || snapshot.usage !== undefined) return snapshot;
  }
}

export function ContextInspector({ context, rounds, snapshots, onOpenFile, sidebar = false, expandable = true }: {
  context: ComposerContextUsage | null; rounds: readonly ComposerRoundUsage[];
  snapshots: readonly ContextSnapshot[]; onOpenFile?: (path: string) => void; sidebar?: boolean; expandable?: boolean;
}) {
  const { t, i18n } = useTranslation();
  const layoutId = useId();
  const reducedMotion = useReducedMotion();
  const [expanded, setExpanded] = useState(false);
  const [replay, setReplay] = useState<{ frames: readonly ContextSnapshot[]; index: number; startedAt: number; interval: number } | null>(null);
  const [readyGraph, setReadyGraph] = useState<ContextGraph | null>(null);
  const [meterHover, setMeterHover] = useState(false);
  const epoch = snapshots[0]?.id;
  useEffect(() => { setReplay(null); }, [epoch]);
  useEffect(() => {
    if (!replay || readyGraph !== replay.frames[replay.index].graph) return;
    // Keep a shared timeline instead of adding rendering time to every step.
    // Advance only after painting each snapshot, even when catching up.
    const remaining = replay.startedAt + (replay.index + 1) * replay.interval - performance.now();
    const timer = window.setTimeout(() => setReplay((current) => current && current.index + 1 < current.frames.length
      ? { ...current, index: current.index + 1 } : null), Math.max(0, remaining));
    return () => window.clearTimeout(timer);
  }, [replay, readyGraph]);
  const snapshot = replay ? replay.frames[replay.index] : snapshots.at(-1);
  // The live graph advances before usage arrives; replay stays frame-local.
  const usageSnapshot = replay ? snapshot : latestUsageSnapshot(snapshots);
  const latestRound = rounds.at(-1);
  const tokens = usageSnapshot ? usageSnapshot.estimatedTokens ?? usageSnapshot.usage?.context_tokens ?? usageSnapshot.usage?.prompt_tokens : context?.contextTokens;
  const estimated = usageSnapshot ? usageSnapshot.estimatedTokens !== undefined : context?.estimated;
  const windowTokens = usageSnapshot ? usageSnapshot.contextWindowTokens : context?.contextWindowTokens ?? snapshot?.contextWindowTokens;
  const tokenNumbers = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 1 });
  const hasTokenUsage = tokens !== undefined || !!windowTokens;
  const used = tokens !== undefined && windowTokens ? Math.min(100, tokens / windowTokens * 100) : null;
  const cached = usageSnapshot ? usageSnapshot.usage?.cached_tokens : latestRound?.cachedTokens;
  const input = usageSnapshot ? usageSnapshot.usage?.prompt_tokens : latestRound?.inputTokens;
  const cachedWidth = cached !== undefined && windowTokens ? Math.min(used ?? 0, cached / windowTokens * 100) : 0;
  const duration = usageSnapshot ? usageSnapshot.usage?.generation_ms : latestRound?.generationMs;
  const toggleExpanded = useCallback(() => setExpanded((value) => !value), []);
  const openFileCallback = useRef(onOpenFile);
  openFileCallback.current = onOpenFile;
  const openFile = useCallback((path: string) => { setExpanded(false); openFileCallback.current?.(path); }, []);
  const content = (large: boolean) => <motion.div layoutId={layoutId} transition={{ duration: reducedMotion ? 0 : 0.25, ease: [0.2, 0, 0, 1] }} className={cn("flex flex-col gap-3", sidebar && !large && "h-full min-h-0")}>
    <Suspense fallback={<div aria-busy="true" className={cn(surface, "min-h-[300px]", sidebar && !large && "min-h-0 flex-1")} />}>
      <ContextGraphScene graph={snapshot?.graph ?? EMPTY_GRAPH} epoch={epoch} onReady={setReadyGraph} expanded={large} sidebar={sidebar && !large} onExpand={expandable ? toggleExpanded : undefined} onOpenFile={onOpenFile ? openFile : undefined} />
    </Suspense>
    <div className="flex shrink-0 items-center gap-3">
    <div onPointerEnter={() => setMeterHover(true)} onPointerLeave={() => setMeterHover(false)} className={cn(surface, "relative flex h-14 min-w-0 flex-1 items-center gap-4 px-4 transition-transform duration-150 ease-out motion-reduce:transition-none", meterHover && "scale-[1.015]")}>
      <div className="flex h-11 flex-1 items-center">
        <div role="progressbar" aria-label={t("thread.composer.context.contextTitle")} aria-valuemin={0} aria-valuemax={100} aria-valuenow={used === null ? undefined : Math.round(used)} className="relative h-1.5 w-full overflow-hidden rounded-full bg-muted">
          <span className="absolute inset-y-0 left-0 rounded-full bg-muted-foreground/45 transition-[width] duration-150 ease-out motion-reduce:transition-none" style={{ width: `${used ?? 0}%` }} />
          <span className="absolute inset-y-0 left-0 rounded-full bg-orange-500 transition-[width] duration-150 ease-out motion-reduce:transition-none" style={{ width: `${cachedWidth}%` }} />
        </div>
      </div>
      <span className="text-sm tabular-nums">{used === null ? "—" : `${estimated ? "≈" : ""}${Math.round(used)}%`}</span>
      {meterHover && (hasTokenUsage || cached !== undefined || duration !== undefined || replay !== null) && <div className="pointer-events-none absolute bottom-full right-0 z-20 mb-2 min-w-48 rounded-xl bg-popover px-3 py-2.5 font-sans text-xs font-normal leading-5 shadow-lg">
        <dl className="grid grid-cols-[auto_auto] items-baseline gap-x-6 gap-y-1">
          {hasTokenUsage && <><dt className="whitespace-nowrap text-muted-foreground">{t("thread.composer.context.panelTitle")}</dt><dd className="whitespace-nowrap text-right tabular-nums text-popover-foreground">{t("thread.composer.context.tokenUsage", {
            used: tokens === undefined ? "—" : `${estimated ? "≈" : ""}${tokenNumbers.format(tokens / 1000)}k`,
            limit: windowTokens ? `${tokenNumbers.format(windowTokens / 1000)}k` : "—",
          })}</dd></>}
          {cached !== undefined && !!input && <><dt className="text-muted-foreground">{t("thread.composer.context.cacheHitRate")}</dt><dd className="whitespace-nowrap text-right tabular-nums text-popover-foreground">{Math.round(cached / input * 100)}%</dd></>}
          {duration !== undefined && <><dt className="text-muted-foreground">{t("thread.composer.context.duration")}</dt><dd className="whitespace-nowrap text-right tabular-nums text-popover-foreground">{formatTurnLatency(duration)}</dd></>}
          {replay && <><dt className="text-muted-foreground">{t("thread.composer.context.history")}</dt>
            <dd className="text-right tabular-nums text-muted-foreground">{replay.index + 1}/{replay.frames.length}</dd></>}
        </dl>
      </div>}
    </div>
    <ContextReplayButton disabled={replay !== null || snapshots.length < 2}
      onPlay={() => {
        setMeterHover(false);
        // Scale by request count: our replay unit is a snapshot, not a graph edge.
        const stepsPerSecond = Math.min(20, Math.max(5, 0.5 * Math.sqrt(snapshots.length)));
        setReplay({ frames: [...snapshots], index: 0, startedAt: performance.now(), interval: 1000 / stepsPerSecond });
      }} />
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
