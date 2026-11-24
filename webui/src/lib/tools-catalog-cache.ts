import { fetchCliApps, fetchMcpPresets } from "./api";
import type { CliAppsPayload, McpPresetsPayload } from "./types";

export const TOOLS_CATALOG_TTL_MS = 30_000;

function createToolsCatalog(token: string) {
  let snapshot: { cliApps: CliAppsPayload | null; mcpPresets: McpPresetsPayload | null; invalidation: number } = {
    cliApps: null, mcpPresets: null, invalidation: 0,
  };
  let cliUpdated = 0;
  let mcpUpdated = 0;
  let cliRevision = 0;
  let mcpRevision = 0;
  let mcpRetryAfter = 0;
  let pendingRecheckAfter = 0;
  let cliRequest: Promise<void> | null = null;
  let mcpRequest: Promise<void> | null = null;
  const listeners = new Set<() => void>();
  const publish = () => listeners.forEach(listener => listener());
  const setCliApps = (cliApps: CliAppsPayload) => {
    cliRevision++;
    cliUpdated = Date.now();
    snapshot = { ...snapshot, cliApps };
    publish();
  };
  const setMcpPresets = (mcpPresets: McpPresetsPayload) => {
    mcpRevision++;
    mcpRetryAfter = 0;
    mcpUpdated = Date.now();
    snapshot = { ...snapshot, mcpPresets };
    publish();
  };
  const mcpFresh = () => snapshot.mcpPresets !== null && Date.now() - mcpUpdated < TOOLS_CATALOG_TTL_MS;
  function loadMcpPresets(): Promise<void> {
    if (mcpRequest) return mcpRequest;
    const revision = mcpRevision;
    const request = fetchMcpPresets(token).then(payload => {
      if (revision === mcpRevision) setMcpPresets(payload);
    }, error => {
      if (revision === mcpRevision) {
        mcpRetryAfter = Date.now() + TOOLS_CATALOG_TTL_MS;
        throw error;
      }
    }).finally(() => { if (mcpRequest === request) mcpRequest = null; });
    mcpRequest = request;
    return request;
  }
  return {
    getSnapshot: () => snapshot,
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
    setCliApps,
    setMcpPresets,
    invalidate() {
      cliUpdated = mcpUpdated = -Infinity;
      pendingRecheckAfter = mcpRetryAfter = 0;
      cliRevision++;
      mcpRevision++;
      cliRequest = mcpRequest = null;
      snapshot = { ...snapshot, invalidation: snapshot.invalidation + 1 };
      publish();
    },
    invalidateMcpPresets() {
      mcpUpdated = -Infinity;
      pendingRecheckAfter = mcpRetryAfter = 0;
      mcpRevision++;
      mcpRequest = null;
      snapshot = { ...snapshot, invalidation: snapshot.invalidation + 1 };
      publish();
    },
    cliFresh: () => snapshot.cliApps !== null && Date.now() - cliUpdated < TOOLS_CATALOG_TTL_MS,
    mcpFresh,
    loadCliApps(): Promise<void> {
      if (cliRequest) return cliRequest;
      const revision = cliRevision;
      const request = fetchCliApps(token).then(payload => {
        // A mutation response supersedes an earlier catalog read.
        if (revision === cliRevision) setCliApps(payload);
      }, error => {
        if (revision === cliRevision) throw error;
      }).finally(() => { if (cliRequest === request) cliRequest = null; });
      cliRequest = request;
      return request;
    },
    loadMcpPresets,
    async requestMcpPresets(userRequested: boolean): Promise<void> {
      if (mcpRequest) return mcpRequest;
      const now = Date.now();
      if (!userRequested && now < mcpRetryAfter) return;
      if (mcpFresh()) {
        // A settings/history read can precede the handshake. On the next tool
        // call allow one early recheck, not a poll for every unbranded server.
        if (userRequested || now < pendingRecheckAfter || !snapshot.mcpPresets?.presets.some(
          preset => preset.runtime_status === "connecting" && !preset.icons?.length,
        )) return;
        pendingRecheckAfter = now + TOOLS_CATALOG_TTL_MS;
      }
      return loadMcpPresets();
    },
  };
}

// App creates a client per host connection. Keep only its current auth scope;
// superseded clients and credentials never persist in browser storage.
const catalogs = new WeakMap<object, { token: string; catalog: ToolsCatalog }>();
export type ToolsCatalog = ReturnType<typeof createToolsCatalog>;

export function getToolsCatalog(client: object, token: string): ToolsCatalog {
  const existing = catalogs.get(client);
  if (existing?.token === token) return existing.catalog;
  const catalog = createToolsCatalog(token);
  catalogs.set(client, { token, catalog });
  return catalog;
}

export function invalidateToolsCatalog(client: object): void {
  catalogs.get(client)?.catalog.invalidate();
}
