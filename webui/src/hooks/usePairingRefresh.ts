import { useCallback, useEffect, useRef } from "react";

import { usePageVisibility } from "@/hooks/usePageVisibility";
import { fetchPairingRequests } from "@/lib/api";
import type { PairingRequestInfo } from "@/lib/types";
import { useClient } from "@/providers/ClientProvider";

/** Re-read the authoritative pairing snapshot when its payload-free notice arrives. */
export function usePairingRefresh(
  onSnapshot: (requests: PairingRequestInfo[]) => void,
): () => Promise<void> {
  const { client, getToken } = useClient();
  const visible = usePageVisibility();
  const onSnapshotRef = useRef(onSnapshot);
  onSnapshotRef.current = onSnapshot;
  const activeRefresh = useRef<(() => Promise<void>) | null>(null);
  const request = useCallback(() => activeRefresh.current?.() ?? Promise.resolve(), []);

  useEffect(() => {
    if (!visible) return;
    const controller = new AbortController();
    const { signal } = controller;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let inFlight: Promise<void> | undefined;
    let pending = false;
    let retries = 0;
    const read = async (): Promise<void> => {
      let failed: boolean;
      let reason: unknown;
      do {
        pending = false;
        failed = false;
        try {
          const payload = await fetchPairingRequests(getToken(), "", signal);
          signal.throwIfAborted();
          if (document.visibilityState === "hidden") return;
          onSnapshotRef.current(Array.isArray(payload.requests) ? payload.requests : []);
          retries = 0;
        } catch (error) {
          failed = true;
          reason = error;
        }
      } while (pending && !signal.aborted && document.visibilityState !== "hidden");
      signal.throwIfAborted();
      if (failed && retries < 3) timer = setTimeout(requestRefresh, 1000 * 2 ** retries++);
      if (failed) throw reason;
    };
    const refresh = (): Promise<void> => {
      if (signal.aborted || document.visibilityState === "hidden") return Promise.resolve();
      clearTimeout(timer);
      // Changes during a read need one follow-up, never a parallel request.
      if (inFlight) pending = true;
      else inFlight = read().finally(() => { inFlight = undefined; });
      return inFlight;
    };
    activeRefresh.current = refresh;
    // Pairing is opportunistic; leave the last snapshot intact on read failures.
    const requestRefresh = () => { void refresh().catch(() => {}); };
    // Subscribe first so an event during the initial read cannot be lost.
    const unsubscribe = client.onPairingChange(requestRefresh);
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
  }, [client, getToken, visible]);
  return request;
}
