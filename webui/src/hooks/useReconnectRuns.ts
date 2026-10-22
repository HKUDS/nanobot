import { useEffect } from "react";

import { persistedCanonicalRunState } from "@/lib/canonical-run-snapshot";
import { fetchLatestWebuiThread } from "@/lib/latest-thread-request";
import type { NanobotClient, RunState } from "@/lib/nanobot-client";
import { webuiThreadCache } from "@/lib/webui-thread-cache";

const RECONNECT_READ_CONCURRENCY = 4;

/** Reconcile durable runs even when their threads are not mounted. */
export function useReconnectRuns(client: NanobotClient, getToken: () => string): void {
  useEffect(() => {
    let controller: AbortController | null = null;
    let workers = 0;
    const queued = new Set<string>();
    const inFlight = new Set<string>();
    const retry = new Set<string>();
    const freshness = new Map<string, RunState["freshness"]>();
    const needsFreshRetry = new Set<string>();
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
      if (body.run_state) {
        const pendingFreshRetry = needsFreshRetry.delete(chatId);
        if (!client.ingestRunSnapshot(chatId, body.run_state) && pendingFreshRetry) {
          // A pre-ready response can belong to the process that just exited.
          // Once the socket baseline is fresh, replace that rejected page once.
          if (freshness.get(chatId) === "fresh") retry.add(chatId);
          else needsFreshRetry.add(chatId);
        }
      }
    };
    const drain = () => {
      if (!controller || controller.signal.aborted) return;
      const signal = controller.signal;
      while (workers < RECONNECT_READ_CONCURRENCY && queued.size > 0) {
        const chatId = queued.values().next().value!;
        queued.delete(chatId);
        inFlight.add(chatId);
        workers += 1;
        void recover(chatId, signal).catch(() => {
          // A failed read leaves this result unresolved; other chats can recover.
        }).finally(() => {
          if (signal !== controller?.signal) return;
          workers -= 1;
          inFlight.delete(chatId);
          if (retry.delete(chatId) && client.getUnsettledRunChatIds().includes(chatId)) queued.add(chatId);
          drain();
        });
      }
    };
    const enqueue = (chatId: string) => {
      if (!controller || !client.getUnsettledRunChatIds().includes(chatId)) return;
      if (inFlight.has(chatId)) retry.add(chatId);
      else queued.add(chatId);
      drain();
    };
    const unsubscribe = client.onStatus((status) => {
      controller?.abort();
      controller = status === "open" ? new AbortController() : null;
      workers = 0;
      queued.clear();
      inFlight.clear();
      retry.clear();
      freshness.clear();
      needsFreshRetry.clear();
      if (status === "open") for (const chatId of client.getUnsettledRunChatIds()) {
        needsFreshRetry.add(chatId);
        enqueue(chatId);
      }
    });
    const unsubscribeRuns = client.onRunStatus((chatId, state) => {
      const previous = freshness.get(chatId);
      freshness.set(chatId, state.freshness);
      // Socket open precedes the authenticated ready pin. Retry reads/ingestion
      // after a fresh baseline, never granting HTTP snapshots their own epoch.
      if (state.freshness === "fresh" && previous !== "fresh" && !inFlight.has(chatId) && needsFreshRetry.delete(chatId)) enqueue(chatId);
    });
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
