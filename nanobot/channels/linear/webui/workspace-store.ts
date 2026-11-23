import type { WebUIMutationTransport } from "@/lib/api";

import { getLinearWorkspaceProfile, manageLinearWorkspace } from "./api";
import type { LinearInstallationSummary } from "./types";

interface WorkspaceSnapshot {
  installations: LinearInstallationSummary[] | null;
  logos: Record<string, string | null>;
  loading: boolean;
  error: string | null;
}

/** Display cache only: access writes and request admission still validate on the server. */
class LinearWorkspaceStore {
  private snapshot: WorkspaceSnapshot = { installations: null, logos: {}, loading: false, error: null };
  private listeners = new Set<() => void>();
  private version = 0;
  private fetchedAt = 0;

  constructor(private client: WebUIMutationTransport) {}
  getSnapshot = () => this.snapshot;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };
  get canEvict() { return !this.listeners.size && !this.snapshot.loading; }
  private update(patch: Partial<WorkspaceSnapshot>) {
    this.snapshot = { ...this.snapshot, ...patch };
    this.listeners.forEach(listener => listener());
  }

  replace = (installations: LinearInstallationSummary[]) => {
    this.version += 1;
    this.fetchedAt = Date.now();
    const ids = new Set(installations.map(item => item.organization_id));
    this.update({ installations, loading: false, error: null,
      logos: Object.fromEntries(Object.entries(this.snapshot.logos).filter(([id]) => ids.has(id))),
    });
  };

  load = async (force = false) => {
    if (this.snapshot.loading) return;
    if (!force && this.snapshot.installations && Date.now() - this.fetchedAt < 60_000) return;
    const version = ++this.version;
    this.update({ loading: true, error: null });
    try {
      const payload = await manageLinearWorkspace(this.client, { operation: "inspect" });
      if (version !== this.version) return;
      this.fetchedAt = Date.now();
      const installations = payload.installations ?? [];
      const ids = new Set(installations.map(item => item.organization_id));
      this.update({ installations, loading: false,
        logos: Object.fromEntries(Object.entries(this.snapshot.logos).filter(([id]) => ids.has(id))),
      });
      // Logos must never delay cards, member lists, or other workspace logos.
      for (const installation of installations) void this.loadLogo(installation.organization_id, version);
    } catch (error) {
      if (version === this.version) this.update({ loading: false,
        error: error instanceof Error ? error.message : String(error),
      });
    }
  };

  private async loadLogo(id: string, version: number) {
    try {
      const profile = await getLinearWorkspaceProfile(this.client, id);
      if (version !== this.version || profile.organization_id !== id
        || !this.snapshot.installations?.some(item => item.organization_id === id)) return;
      this.update({ logos: { ...this.snapshot.logos, [id]: profile.logo_url } });
    } catch { /* Cosmetic metadata failure must not hide a usable workspace. */ }
  }
}

const caches = new WeakMap<WebUIMutationTransport, { token: string; stores: Map<string, LinearWorkspaceStore> }>();

export function linearWorkspaceStore(client: WebUIMutationTransport, token: string, configScope: string) {
  let cache = caches.get(client);
  if (!cache || cache.token !== token) {
    cache = { token, stores: new Map() };
    caches.set(client, cache);
  }
  let store = cache.stores.get(configScope);
  if (!store) {
    if (cache.stores.size >= 16) {
      for (const [key, entry] of cache.stores) {
        if (entry.canEvict) { cache.stores.delete(key); break; }
      }
    }
    store = new LinearWorkspaceStore(client);
    cache.stores.set(configScope, store);
  }
  return store;
}
