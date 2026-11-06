import { useEffect, useMemo, useState } from "react";
import type { ContextGraph, ContextGraphSource } from "@/lib/types";

/** A new loader identity denotes a different session/client/credential scope. */
export type ContextGraphLoader = (ref: string, signal: AbortSignal) => Promise<ContextGraph>;

export function useContextGraph(
  source: ContextGraphSource | undefined, active: boolean, epoch: string | undefined,
  loadGraph: ContextGraphLoader | undefined,
) {
  // Keep only four details, and release them on close, compaction or owner change.
  // Resolved bodies never enter the transcript or the persistent reload cache.
  const cache = useMemo(() => new Map<string, ContextGraph>(), [active, epoch, loadGraph]);
  useEffect(() => () => cache.clear(), [cache]);
  const [result, setResult] = useState<{ owner: typeof cache; ref: string; error: boolean }>();
  const [attempt, setAttempt] = useState(0);
  const ref = source?.graphDetailRef;
  const graph = source?.graph ?? (active && ref ? cache.get(ref) : undefined);
  const [displayed, setDisplayed] = useState<{ owner: typeof cache; graph: ContextGraph }>();
  useEffect(() => {
    setDisplayed((previous) => active && graph ? { owner: cache, graph }
      : active && previous?.owner === cache ? previous : undefined);
  }, [active, cache, graph]);
  useEffect(() => {
    if (!active || !ref || !loadGraph || cache.has(ref)) return;
    const controller = new AbortController();
    setResult({ owner: cache, ref, error: false });
    void loadGraph(ref, controller.signal).then((graph) => {
      if (controller.signal.aborted) return;
      cache.set(ref, graph);
      if (cache.size > 4) cache.delete(cache.keys().next().value!);
      setResult({ owner: cache, ref, error: false });
    }, () => {
      if (!controller.signal.aborted) setResult({ owner: cache, ref, error: true });
    });
    return () => controller.abort();
  }, [active, cache, ref, loadGraph, attempt]);
  return {
    graph,
    displayedGraph: active ? graph ?? (displayed?.owner === cache ? displayed.graph : undefined) : undefined,
    error: result?.owner === cache && result.ref === ref && result.error,
    retry: () => setAttempt((value) => value + 1),
  };
}
