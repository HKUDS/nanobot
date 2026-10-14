import { useMemo, useSyncExternalStore } from "react";

import type { NanobotClient } from "@/lib/nanobot-client";

export type GatewayConnectionClient = Pick<NanobotClient, "status" | "onStatus">;

/** Each open connection owns a signal; disconnect invalidates it synchronously. */
export function useGatewayConnection(client: GatewayConnectionClient, active = true): AbortSignal | null {
  const store = useMemo(() => {
    let controller = active && client.status === "open" ? new AbortController() : null;
    return {
      snapshot: () => controller?.signal ?? null,
      subscribe: (changed: () => void) => {
        if (!active) return () => {};
        const unsubscribe = client.onStatus((status) => {
          if (status === "open") {
            if (controller) return;
            controller = new AbortController();
          } else {
            if (!controller) return;
            controller.abort();
            controller = null;
          }
          changed();
        });
        return () => {
          unsubscribe();
          controller?.abort();
          controller = null;
        };
      },
    };
  }, [active, client]);
  return useSyncExternalStore(store.subscribe, store.snapshot, store.snapshot);
}
