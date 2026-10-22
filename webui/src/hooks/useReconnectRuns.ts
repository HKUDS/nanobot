import { useEffect } from "react";

import { persistedCanonicalRunState } from "@/lib/canonical-run-snapshot";
import { fetchLatestWebuiThread } from "@/lib/latest-thread-request";
import type { NanobotClient } from "@/lib/nanobot-client";
import { webuiThreadCache } from "@/lib/webui-thread-cache";

const RECONNECT_READ_CONCURRENCY = 4;

/** Reconcile durable runs even when their threads are not mounted. */
export function useReconnectRuns(client: NanobotClient, getToken: () => string): void {
  useEffect(() => {
    let controller: AbortController | null = null;
    const queued = new Set<string>();
    const inFlight = new Set<string>();
    const refreshPending = new Set<string>();
    const recover = async (chatId: string, signal: AbortSignal) => {
      const generation = client.getRunGeneration(chatId);
      const turnId = client.getRunTurnId(chatId);
      const key = `websocket:${chatId}`;
      const body = await fetchLatestWebuiThread(client, getToken(), key, signal);
      if (!body || signal.aborted) return;
      const { completedTurnIds, snapshot } = persistedCanonicalRunState(body);
      const explicitlyCompleted = turnId !== null && completedTurnIds.includes(turnId);
      const resultRepresented = explicitlyCompleted || (
        !snapshot.hasPendingToolCalls && !snapshot.activeTurnId
        && (turnId === null || snapshot.observedTurnIds.includes(turnId))
      );
      if (resultRepresented && client.canReconcileCanonicalCompletion(chatId, generation, completedTurnIds, snapshot)) {
        // Preserve the result before completion fences prune queued fragments.
        // Returning to an inactive chat can hydrate from this canonical page.
        webuiThreadCache.set(key, body);
        client.reconcileCanonicalCompletion(chatId, generation, completedTurnIds, snapshot);
      }
      if (body.run_state) client.ingestRunSnapshot(chatId, body.run_state);
    };
    const drain = () => {
      if (!controller || controller.signal.aborted) return;
      const signal = controller.signal;
      for (const chatId of queued) {
        if (inFlight.size >= RECONNECT_READ_CONCURRENCY) break;
        const { freshness } = client.getRunState(chatId);
        // Ready establishes legacy unavailability; current hosts also owe a socket baseline.
        if (freshness !== "fresh" && freshness !== "unavailable") continue;
        queued.delete(chatId);
        inFlight.add(chatId);
        void recover(chatId, signal).catch(() => {
          // A failed read leaves this result unresolved; other chats can recover.
        }).finally(() => {
          if (signal !== controller?.signal) return;
          inFlight.delete(chatId);
          if (refreshPending.delete(chatId) && client.getUnsettledRunChatIds().includes(chatId)) queued.add(chatId);
          drain();
        });
      }
    };
    const enqueue = (chatId: string) => {
      if (!controller || !client.getUnsettledRunChatIds().includes(chatId)) return;
      if (inFlight.has(chatId)) refreshPending.add(chatId);
      else queued.add(chatId);
      drain();
    };
    const unsubscribe = client.onStatus((status) => {
      controller?.abort();
      controller = status === "open" ? new AbortController() : null;
      queued.clear();
      inFlight.clear();
      refreshPending.clear();
      if (status === "open") {
        for (const chatId of client.getUnsettledRunChatIds()) queued.add(chatId);
        drain();
      }
    });
    const unsubscribeRuns = client.onRunStatus(drain);
    const unsubscribeCompletion = client.onRunCompletion(enqueue);
    return () => {
      controller?.abort();
      controller = null;
      unsubscribe();
      unsubscribeRuns();
      unsubscribeCompletion();
    };
  }, [client, getToken]);
}
