import { useCallback, useEffect, useRef } from "react";

import { usePageVisibility } from "@/hooks/usePageVisibility";
import type { WebUIStateResource } from "@/lib/types";
import { useClient } from "@/providers/ClientProvider";

/** Fixed WebUI invalidations share a lifecycle, not a second business-state store. */
export function useStateRefresh<T>(
  resource: WebUIStateResource,
  enabled: boolean,
  load: (signal: AbortSignal, initial: boolean) => Promise<T>,
  legacyIntervalMs: number | ((result: T | undefined) => number) | null,
  scope: string = resource,
): () => void {
  const { client, webuiCapabilities } = useClient();
  const visible = usePageVisibility();
  const events = webuiCapabilities.includes("webui.state-events.v1");
  const loadRef = useRef(load);
  loadRef.current = load;
  const intervalRef = useRef(legacyIntervalMs);
  intervalRef.current = legacyIntervalMs;
  const activeRefresh = useRef<(() => Promise<void>) | null>(null);
  const request = useCallback(() => { void activeRefresh.current?.(); }, []);

  useEffect(() => {
    if (!enabled || !visible) return;
    const controller = new AbortController();
    const { signal } = controller;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let inFlight = false;
    let pending = false;
    let initial = true;
    let retries = 0;
    const refresh = async (): Promise<void> => {
      if (signal.aborted) return;
      if (inFlight) {
        pending = true;
        return;
      }
      clearTimeout(timer);
      inFlight = true;
      let failed = false;
      let result: T | undefined;
      try {
        result = await loadRef.current(signal, initial);
        retries = 0;
      } catch {
        // The view owns its error UI. Retry transient reads without an idle loop.
        failed = true;
      } finally {
        inFlight = false;
        initial = false;
      }
      if (signal.aborted) return;
      if (pending) {
        pending = false;
        void refresh();
        return;
      }
      const interval = intervalRef.current;
      const delay = failed && retries < 3
        ? 1000 * 2 ** retries++
        : events || interval === null ? null : typeof interval === "function" ? interval(result) : interval;
      if (delay !== null) timer = setTimeout(() => void refresh(), delay);
    };
    activeRefresh.current = refresh;
    const requestRefresh = () => { void refresh(); };
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
