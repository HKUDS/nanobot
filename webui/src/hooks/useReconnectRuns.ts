import { useEffect } from "react";

import { fetchWebuiThread } from "@/lib/api";
import { persistedCanonicalRunState } from "@/lib/canonical-run-snapshot";
import type { NanobotClient } from "@/lib/nanobot-client";
import { webuiThreadCache } from "@/lib/webui-thread-cache";

/** Reconcile durable runs even when their threads are not mounted. */
export function useReconnectRuns(client: NanobotClient, getToken: () => string): void {
  useEffect(() => {
    let epoch = 0;
    let controller: AbortController | null = null;
    const unsubscribe = client.onStatus((status) => {
      const requestEpoch = ++epoch;
      controller?.abort();
      controller = null;
      if (status !== "open") return;
      const chats = client.getUnsettledRunChatIds();
      if (chats.length === 0) return;
      controller = new AbortController();
      const signal = controller.signal;
      void Promise.allSettled(chats.map(async (chatId) => {
        const generation = client.getRunGeneration(chatId);
        const turnId = client.getRunTurnId(chatId);
        const key = `websocket:${chatId}`;
        const body = await fetchWebuiThread(getToken(), key, {
          limit: 40,
          direction: "latest",
          signal,
        });
        if (!body || signal.aborted || requestEpoch !== epoch || client.status !== "open") return;
        const { completedTurnIds, snapshot } = persistedCanonicalRunState(body);
        const explicitlyCompleted = turnId !== null && completedTurnIds.includes(turnId);
        if (!explicitlyCompleted && (snapshot.hasPendingToolCalls || snapshot.activeTurnId)) return;
        if (turnId && !explicitlyCompleted && !snapshot.observedTurnIds.includes(turnId)) return;
        if (!client.canReconcileCanonicalCompletion(chatId, generation, completedTurnIds, snapshot)) return;
        // Preserve the result before completion fences prune queued fragments.
        // Returning to an inactive chat can hydrate from this canonical page.
        webuiThreadCache.set(key, body);
        client.reconcileCanonicalCompletion(chatId, generation, completedTurnIds, snapshot);
      }));
    });
    return () => {
      epoch += 1;
      controller?.abort();
      unsubscribe();
    };
  }, [client, getToken]);
}
