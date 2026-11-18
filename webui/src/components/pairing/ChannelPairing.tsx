import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { usePageVisibility } from "@/hooks/usePageVisibility";
import { fetchPairingRequests, runPairingAction } from "@/lib/api";
import type { PairingRequestInfo } from "@/lib/types";
import { useClient } from "@/providers/ClientProvider";
import { PairingCodePopup } from "./PairingCodePopup";

const PAIRING_POLL_INTERVAL_MS = 5_000;
const PAIRING_IDLE_POLL_INTERVAL_MS = 15_000;
const PAIRING_DISMISS_SNOOZE_MS = 30_000;

export function ChannelPairing() {
  const { client, getToken } = useClient();
  const pageVisible = usePageVisibility();
  const [pairingRequests, setPairingRequests] = useState<PairingRequestInfo[]>([]);
  const [pairingBusyCode, setPairingBusyCode] = useState<string | null>(null);
  const [pairingError, setPairingError] = useState<string | null>(null);
  const pairingRefreshRef = useRef<Promise<number> | null>(null);
  const pairingRefreshPendingRef = useRef(false);
  const [snoozedPairingCodes, setSnoozedPairingCodes] = useState<Map<string, {
    until: number;
    deliveryStatus: PairingRequestInfo["delivery_status"];
  }>>(
    () => new Map(),
  );

  const refreshPairingRequests = useCallback((): Promise<number> => {
    if (pairingRefreshRef.current) {
      // An earlier snapshot may predate the notice or completed mutation.
      pairingRefreshPendingRef.current = true;
      return pairingRefreshRef.current;
    }

    const request = (async () => {
      let requestCount: number;
      do {
        pairingRefreshPendingRef.current = false;
        try {
          const payload = await fetchPairingRequests(getToken());
          const requests = Array.isArray(payload.requests) ? payload.requests : [];
          setPairingRequests(requests);
          setSnoozedPairingCodes((current) => {
            if (current.size === 0) return current;
            const activeRequests = new Map(requests.map((request) => [request.code, request]));
            const now = Date.now();
            const next = new Map(
              Array.from(current).filter(
                ([code, snooze]) => activeRequests.has(code)
                  && snooze.until > now
                  && activeRequests.get(code)?.delivery_status === snooze.deliveryStatus,
              ),
            );
            return next.size === current.size ? current : next;
          });
          requestCount = requests.length;
        } catch {
          // Pairing is an opportunistic WebUI affordance. The slash command path
          // remains available if this polling request fails.
          requestCount = 0;
        }
      } while (pairingRefreshPendingRef.current);
      return requestCount;
    })();
    const clearRequest = () => {
      if (pairingRefreshRef.current === request) pairingRefreshRef.current = null;
    };
    pairingRefreshRef.current = request;
    void request.then(clearRequest, clearRequest);
    return request;
  }, [getToken]);

  useEffect(() => {
    if (!pageVisible) return undefined;

    let disposed = false;
    let timer: number | null = null;
    const poll = async () => {
      const requestCount = await refreshPairingRequests();
      if (disposed) return;
      if (timer !== null) window.clearTimeout(timer);
      timer = window.setTimeout(
        () => void poll(),
        requestCount > 0 ? PAIRING_POLL_INTERVAL_MS : PAIRING_IDLE_POLL_INTERVAL_MS,
      );
    };
    const requestRefresh = () => { void poll(); };
    const unsubscribePairing = client.onPairingChange(requestRefresh);
    const unsubscribeReady = client.onReady(requestRefresh);
    void poll();
    return () => {
      disposed = true;
      pairingRefreshPendingRef.current = false;
      if (timer !== null) window.clearTimeout(timer);
      unsubscribePairing();
      unsubscribeReady();
    };
  }, [client, pageVisible, refreshPairingRequests]);

  const visiblePairingRequests = useMemo(
    () => {
      const now = Date.now();
      return pairingRequests.filter((request) => {
        const snooze = snoozedPairingCodes.get(request.code);
        return !snooze || snooze.until <= now;
      });
    },
    [pairingRequests, snoozedPairingCodes],
  );

  const onPairingAction = useCallback(
    async (action: "approve" | "deny", code: string) => {
      setPairingBusyCode(code);
      setPairingError(null);
      try {
        const payload = await runPairingAction(client, action, code);
        setPairingRequests(Array.isArray(payload.requests) ? payload.requests : []);
        setSnoozedPairingCodes((current) => {
          if (!current.has(code)) return current;
          const next = new Map(current);
          next.delete(code);
          return next;
        });
      } catch (e) {
        setPairingError((e as Error).message);
      } finally {
        setPairingBusyCode(null);
        // A mutation reply can be older than an already-delivered notification.
        void refreshPairingRequests();
      }
    },
    [client, refreshPairingRequests],
  );

  const onDismissPairingRequest = useCallback((request: PairingRequestInfo) => {
    setSnoozedPairingCodes((current) => {
      const next = new Map(current);
      next.set(request.code, {
        until: Date.now() + PAIRING_DISMISS_SNOOZE_MS,
        deliveryStatus: request.delivery_status,
      });
      return next;
    });
  }, []);

  return (
    <PairingCodePopup
      requests={visiblePairingRequests}
      total={visiblePairingRequests.length}
      busyCode={pairingBusyCode}
      error={pairingError}
      onApprove={(code) => void onPairingAction("approve", code)}
      onDismiss={onDismissPairingRequest}
    />
  );
}
