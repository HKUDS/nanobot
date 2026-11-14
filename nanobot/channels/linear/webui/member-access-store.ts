import type { WebUIMutationTransport } from "@/lib/api";

import { manageLinearMembers } from "./api";
import type { LinearMembersPayload } from "./types";

type MemberSave = { status: "saving" | "saved" } | { status: "error"; message: string };
interface MemberAccessSnapshot {
  payload: LinearMembersPayload | null;
  loading: boolean;
  error: string | null;
  saves: Record<string, MemberSave>;
}

const FRESH_FOR_MS = 60_000;

/** Display cache only. The server still checks membership and access on every request. */
class LinearMemberAccessStore {
  private snapshot: MemberAccessSnapshot = { payload: null, loading: false, error: null, saves: {} };
  private listeners = new Set<() => void>();
  private readVersion = 0;
  private fetchedAt = 0;
  private generation = 0;

  constructor(private client: WebUIMutationTransport, private organizationId: string) {}

  getSnapshot = () => this.snapshot;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  private update(patch: Partial<MemberAccessSnapshot>) {
    this.snapshot = { ...this.snapshot, ...patch };
    this.listeners.forEach((listener) => listener());
  }

  private get saving() {
    return Object.values(this.snapshot.saves).some((save) => save.status === "saving");
  }

  get canEvict() {
    return !this.listeners.size && !this.saving && !this.snapshot.loading;
  }

  invalidate = () => {
    this.generation += 1;
    this.readVersion += 1;
    this.fetchedAt = 0;
    this.update({ payload: null, loading: false, error: null, saves: {} });
  };

  load = async (force = false) => {
    if (this.snapshot.loading || this.saving) return;
    if (!force && this.snapshot.payload && Date.now() - this.fetchedAt < FRESH_FOR_MS) return;
    const version = ++this.readVersion;
    this.update({ loading: true, error: null });
    try {
      const payload = await manageLinearMembers(this.client, {
        operation: "members", organization_id: this.organizationId,
      });
      if (version !== this.readVersion) return;
      this.fetchedAt = Date.now();
      this.update({ payload, loading: false, saves: {} });
    } catch (error) {
      if (version !== this.readVersion) return;
      this.update({ loading: false, error: error instanceof Error ? error.message : String(error) });
    }
  };

  setAllowed = async (userId: string, allowed: boolean, unconfirmedMessage: string) => {
    const previous = this.snapshot.saves[userId];
    if (previous?.status === "saving" || previous?.status === "error") return;
    if (!this.snapshot.payload?.members.some((member) => member.id === userId)) return;
    const generation = this.generation;
    // An older directory response must not overwrite a newer permission change.
    this.readVersion += 1;
    this.update({ loading: false, saves: { ...this.snapshot.saves, [userId]: { status: "saving" } } });
    try {
      const payload = await manageLinearMembers(this.client, {
        operation: "member_access", organization_id: this.organizationId, user_id: userId, allowed,
      });
      if (generation !== this.generation) return;
      const updated = payload.members.find((member) => member.id === userId);
      if (payload.organization_id !== this.organizationId || !updated || updated.allowed !== allowed) {
        throw new Error(unconfirmedMessage);
      }
      const current = this.snapshot.payload;
      if (!current) return;
      this.update({
        payload: {
          ...current,
          legacy_allow_all: payload.legacy_allow_all,
          members: current.members.map((member) => member.id === userId ? updated : member),
        },
        saves: { ...this.snapshot.saves, [userId]: { status: "saved" } },
      });
    } catch (error) {
      // A timeout can mean the server saved the change. Re-read before retrying this member.
      if (generation !== this.generation) return;
      this.fetchedAt = 0;
      this.update({ saves: { ...this.snapshot.saves, [userId]: {
        status: "error", message: error instanceof Error ? error.message : String(error),
      } } });
    }
  };
}

const caches = new WeakMap<WebUIMutationTransport, {
  token: string;
  stores: Map<string, LinearMemberAccessStore>;
}>();

/** Keep visited lists across panel closes, never across gateways, logins or app configurations. */
export function linearMemberAccessStore(
  client: WebUIMutationTransport, token: string, configScope: string, organizationId: string,
) {
  let cache = caches.get(client);
  if (!cache || cache.token !== token) {
    cache = { token, stores: new Map() };
    caches.set(client, cache);
  }
  const key = JSON.stringify([configScope, organizationId]);
  let store = cache.stores.get(key);
  if (!store) {
    if (cache.stores.size >= 32) {
      for (const [cachedKey, entry] of cache.stores) {
        if (entry.canEvict) { cache.stores.delete(cachedKey); break; }
      }
    }
    store = new LinearMemberAccessStore(client, organizationId);
    cache.stores.set(key, store);
  }
  return store;
}
