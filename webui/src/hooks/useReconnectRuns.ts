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
    const unsubscribe = client.onStatus((status) => {
      controller?.abort();
      controller = null;
      if (status !== "open") return;
      const chats = client.getUnsettledRunChatIds();
      if (chats.length === 0) return;
      controller = new AbortController();
      const signal = controller.signal;
      const jobs = chats.map((chatId) => ({
        chatId,
        generation: client.getRunGeneration(chatId),
        turnId: client.getRunTurnId(chatId),
      }));
      const recover = async ({ chatId, generation, turnId }: typeof jobs[number]) => {
        const key = `websocket:${chatId}`;
        const body = await fetchLatestWebuiThread(client, getToken(), key, signal);
        if (!body || signal.aborted) return;
        const { completedTurnIds, snapshot } = persistedCanonicalRunState(body);
        const explicitlyCompleted = turnId !== null && completedTurnIds.includes(turnId);
        if (!explicitlyCompleted && (snapshot.hasPendingToolCalls || snapshot.activeTurnId)) return;
        if (turnId && !explicitlyCompleted && !snapshot.observedTurnIds.includes(turnId)) return;
        if (!client.canReconcileCanonicalCompletion(chatId, generation, completedTurnIds, snapshot)) return;
        // Preserve the result before completion fences prune queued fragments.
        // Returning to an inactive chat can hydrate from this canonical page.
        webuiThreadCache.set(key, body);
        client.reconcileCanonicalCompletion(chatId, generation, completedTurnIds, snapshot);
      };
      let nextJob = 0;
      const worker = async () => {
        while (!signal.aborted) {
          const job = jobs[nextJob++];
          if (!job) return;
          try {
            await recover(job);
          } catch {
            // A failed read leaves this run unresolved; other chats can recover.
          }
        }
      };
      void Promise.allSettled(Array.from({ length: Math.min(RECONNECT_READ_CONCURRENCY, jobs.length) }, worker));
    });
    return () => {
      controller?.abort();
      unsubscribe();
    };
  }, [client, getToken]);
}
