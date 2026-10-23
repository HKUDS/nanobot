import { useCallback, useLayoutEffect, useRef } from "react";

import { usePageVisibility } from "@/hooks/usePageVisibility";
import type { WebUIStateResource } from "@/lib/types";
import { useClient } from "@/providers/ClientProvider";

/** Fixed WebUI invalidations share a lifecycle, not a second business-state store. */
export function useStateRefresh(
  resource: WebUIStateResource,
  enabled: boolean,
  load: (signal: AbortSignal, initial: boolean) => Promise<void>,
  scope: string = resource,
): () => Promise<void> {
  const { client } = useClient();
  const visible = usePageVisibility();
  const loadRef = useRef(load);
  loadRef.current = load;
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
      do {
        pending = false;
        failed = false;
        try {
          await loadRef.current(signal, initial);
          retries = 0;
        } catch (error) {
          failed = true;
          reason = error;
        }
        initial = false;
      } while (pending && !signal.aborted && document.visibilityState !== "hidden");
      signal.throwIfAborted();
      if (failed && retries < 3) timer = setTimeout(requestRefresh, 1000 * 2 ** retries++);
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
    const unsubscribe = client.onStateChange(resource, requestRefresh);
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
  }, [client, enabled, resource, scope, visible]);
  return request;
}
