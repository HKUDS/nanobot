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
        const mounted = client.hasTranscript(chatId);
        if (body.page?.record_range) {
          if (!Array.isArray(body.completed_turn_ids)) return;
          if (client.canReconcileCanonicalCompletion(chatId, generation, completedTurnIds, snapshot)) {
            webuiThreadCache.set(key, body);
          }
          // A mounted owner must accept (or stage) the fragment before settling.
          // Explicit completion is otherwise independent of a newer run, but the
          // fragment is not proof that its WS content is covered.
          if (!mounted) client.settleCompletedRunLifecycle(chatId, completedTurnIds);
          return;
        }
        const explicitlyCompleted = turnId !== null && completedTurnIds.includes(turnId);
        const canCache = (explicitlyCompleted || (!snapshot.hasPendingToolCalls && !snapshot.activeTurnId))
          && (!turnId || explicitlyCompleted || snapshot.observedTurnIds.includes(turnId))
          && client.canReconcileCanonicalCompletion(chatId, generation, completedTurnIds, snapshot);
        // Preserve adoptable history before notifying completion subscribers.
        if (canCache) webuiThreadCache.set(key, body);
        // Full-page completion facts belong to the ledger regardless of whether
        // a transcript can adopt this page. Retain content for its later owner.
        client.settleCompletedRunLifecycle(chatId, completedTurnIds);
        // Mounted owners alone adopt whole snapshots. Only an idle snapshot can
        // settle activity without a named identity.
        if (!mounted && canCache && !snapshot.hasPendingToolCalls && !snapshot.activeTurnId) {
          client.reconcileCanonicalCompletion(chatId, generation, completedTurnIds, snapshot);
        }
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
