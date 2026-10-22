import { useCallback, useLayoutEffect, useRef } from "react";

import { usePageVisibility } from "@/hooks/usePageVisibility";
import type { WebUIStateResource } from "@/lib/types";
import { useClient } from "@/providers/ClientProvider";

/** Fixed WebUI invalidations share a lifecycle, not a second business-state store. */
export function useStateRefresh<T>(
  resource: WebUIStateResource,
  enabled: boolean,
  load: (signal: AbortSignal, initial: boolean) => Promise<T>,
  legacyIntervalMs: number | ((result: T | undefined) => number | null) | null,
  scope: string = resource,
): () => Promise<void> {
  const { client, webuiCapabilities } = useClient();
  const visible = usePageVisibility();
  const events = webuiCapabilities.includes("webui.state-events.v1");
  const loadRef = useRef(load);
  loadRef.current = load;
  const intervalRef = useRef(legacyIntervalMs);
  intervalRef.current = legacyIntervalMs;
  const activeRefresh = useRef<(() => Promise<void>) | null>(null);
  const request = useCallback(() => activeRefresh.current?.() ?? Promise.resolve(), []);

  // Own the lifetime before child views can request a read from their effects.
  useLayoutEffect(() => {
    if (!enabled || !visible) return;
    const controller = new AbortController();
    const { signal } = controller;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let inFlight: Promise<void> | undefined;
    let pending = false;
    let initial = true;
    let retries = 0;
    const read = async (): Promise<void> => {
      let failed: boolean;
      let reason: unknown;
      let result: T | undefined;
      do {
        pending = false;
        failed = false;
        try {
          result = await loadRef.current(signal, initial);
          retries = 0;
        } catch (error) {
          failed = true;
          reason = error;
        }
        initial = false;
      } while (pending && !signal.aborted && document.visibilityState !== "hidden");
      signal.throwIfAborted();
      const interval = intervalRef.current;
      const delay = failed && retries < 3
        ? 1000 * 2 ** retries++
        : events || interval === null ? null : typeof interval === "function" ? interval(result) : interval;
      if (delay !== null) timer = setTimeout(requestRefresh, delay);
      if (failed) throw reason;
    };
    const refresh = (): Promise<void> => {
      if (signal.aborted || document.visibilityState === "hidden") return Promise.resolve();
      clearTimeout(timer);
      if (inFlight) pending = true;
      else inFlight = read().finally(() => { inFlight = undefined; });
      return inFlight;
    };
    activeRefresh.current = refresh;
    // Views own read errors; automatic requests retry without unhandled rejections.
    const requestRefresh = () => { void refresh().catch(() => {}); };
    // Register before the first read so a change during that read gets a follow-up.
    const unsubscribe = events ? client.onStateChange(resource, requestRefresh) : () => {};
    let wasOpen = client.status === "open";
    const unsubscribeStatus = client.onStatus((status) => {
      if (status === "open" && !wasOpen) requestRefresh();
      wasOpen = status === "open";
    });
    const onFocus = () => {
      if (document.visibilityState !== "hidden") requestRefresh();
    };
    window.addEventListener("focus", onFocus);
    requestRefresh();
    return () => {
      if (activeRefresh.current === refresh) activeRefresh.current = null;
      controller.abort();
      clearTimeout(timer);
      unsubscribe();
      unsubscribeStatus();
      window.removeEventListener("focus", onFocus);
    };
  }, [client, enabled, events, resource, scope, visible]);
  return request;
}
