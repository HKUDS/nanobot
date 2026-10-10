import { fetchProviderModels } from "@/lib/api";
import type { ProviderModelsPayload } from "@/lib/types";

interface CatalogSnapshot {
  payload: ProviderModelsPayload | null;
  pending: boolean;
  failed: boolean;
}

export function isCatalogAvailable(payload: ProviderModelsPayload | null): boolean {
  return payload?.status === "available" && payload.error_kind !== "auth_required";
}

function catalogFailed(payload: ProviderModelsPayload): boolean {
  return payload.status === "error" || Boolean(payload.error_kind)
    || payload.source === "stale" || payload.source === "fallback";
}

function createCatalog(token: string, provider: string) {
  let snapshot: CatalogSnapshot = { payload: null, pending: false, failed: false };
  let request: Promise<void> | null = null;
  const listeners = new Set<() => void>();
  const publish = () => listeners.forEach((listener) => listener());

  const load = (refresh = false): Promise<void> => {
    if (request) return request;
    snapshot = { ...snapshot, pending: true };
    publish();
    request = fetchProviderModels(token, provider, "", { refresh })
      .then((payload) => {
        const retainCatalog = payload.status === "error"
          && payload.error_kind !== "auth_required" && isCatalogAvailable(snapshot.payload);
        snapshot = {
          payload: retainCatalog ? snapshot.payload : payload,
          pending: true,
          failed: catalogFailed(payload),
        };
      }, () => {
        snapshot = { ...snapshot, failed: true };
      })
      .finally(() => {
        request = null;
        snapshot = { ...snapshot, pending: false };
        publish();
      });
    return request;
  };

  return {
    getSnapshot: () => snapshot,
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
    load,
  };
}

type Catalog = ReturnType<typeof createCatalog>;

// A full settings response replaces provider rows, including after logging back
// into the same account. Usage updates retain them. Weak keys release catalogs
// belonging to superseded configurations without persisting browser-side data.
const catalogs = new WeakMap<object, Map<string, Catalog>>();

export function getProviderModelCatalog(revision: object, token: string, provider: string): Catalog {
  let entries = catalogs.get(revision);
  if (!entries) {
    entries = new Map();
    catalogs.set(revision, entries);
  }
  const key = JSON.stringify([token, provider]);
  let catalog = entries.get(key);
  if (!catalog) {
    catalog = createCatalog(token, provider);
    entries.set(key, catalog);
  }
  return catalog;
}
