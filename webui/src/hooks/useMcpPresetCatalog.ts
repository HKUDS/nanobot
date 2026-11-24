import { createContext, useEffect, useSyncExternalStore } from "react";

import type { ToolsCatalog } from "@/lib/tools-catalog-cache";

export const McpCatalogContext = createContext<ToolsCatalog | null>(null);
const noSubscription = () => () => {};
const emptySnapshot = () => null;

/** Activity, the composer and Settings share one catalog per authenticated client. */
export function useMcpPresetCatalog(catalog: ToolsCatalog | null, demand: number, userRequested = false) {
  const snapshot = useSyncExternalStore(
    demand && catalog ? catalog.subscribe : noSubscription,
    catalog?.getSnapshot ?? emptySnapshot,
  );
  const revision = snapshot?.invalidation;
  useEffect(() => {
    if (!demand || !catalog) return;
    void catalog.requestMcpPresets(userRequested).catch(() => { /* Keep the last successful metadata. */ });
  }, [catalog, demand, revision, userRequested]);
  return snapshot?.mcpPresets;
}
