import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useClient } from "@/providers/ClientProvider";
import { normalizeWorkbenchState } from "@/components/workbench/workbench-model";
import { fetchSidebarState } from "@/lib/api";
import type { ChatSummary, SidebarStatePayload } from "@/lib/types";

const DEFAULT_SIDEBAR_STATE: SidebarStatePayload = {
  schema_version: 1,
  pinned_keys: [],
  archived_keys: [],
  session_order: [],
  title_overrides: {},
  project_name_overrides: {},
  tags_by_key: {},
  collapsed_groups: {},
  workbench: { version: 1, tabs: {} },
  view: {
    density: "comfortable",
    show_archived: false,
    sort: "updated_desc",
  },
  updated_at: null,
};

function uniqueStrings(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const out: string[] = [];
  const seen = new Set<string>();
  for (const item of value) {
    if (typeof item !== "string") continue;
    const cleaned = item.trim();
    if (!cleaned || seen.has(cleaned)) continue;
    seen.add(cleaned);
    out.push(cleaned);
  }
  return out;
}

function stringMap(value: unknown): Record<string, string> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const out: Record<string, string> = {};
  for (const [key, raw] of Object.entries(value)) {
    if (typeof raw !== "string") continue;
    const cleanedKey = key.trim();
    const cleanedValue = raw.trim();
    if (!cleanedKey || !cleanedValue) continue;
    out[cleanedKey] = cleanedValue;
  }
  return out;
}

function tagsMap(value: unknown): Record<string, string[]> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const out: Record<string, string[]> = {};
  for (const [key, raw] of Object.entries(value)) {
    const cleanedKey = key.trim();
    if (!cleanedKey) continue;
    const tags = uniqueStrings(raw).slice(0, 12);
    if (tags.length) out[cleanedKey] = tags;
  }
  return out;
}

function boolMap(value: unknown): Record<string, boolean> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const out: Record<string, boolean> = {};
  for (const [key, raw] of Object.entries(value)) {
    const cleanedKey = key.trim();
    if (cleanedKey) out[cleanedKey] = Boolean(raw);
  }
  return out;
}

function normalizeSidebarState(raw: unknown): SidebarStatePayload {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return { ...DEFAULT_SIDEBAR_STATE, view: { ...DEFAULT_SIDEBAR_STATE.view } };
  }
  const value = raw as Partial<SidebarStatePayload>;
  const view = value.view && typeof value.view === "object"
    ? value.view
    : DEFAULT_SIDEBAR_STATE.view;
  const density = view.density === "compact" ? "compact" : "comfortable";
  const sort = ["updated_desc", "created_desc", "title_asc", "manual"].includes(view.sort)
    ? view.sort
    : "updated_desc";
  return {
    schema_version: 1,
    pinned_keys: uniqueStrings(value.pinned_keys),
    archived_keys: uniqueStrings(value.archived_keys),
    session_order: uniqueStrings(value.session_order),
    title_overrides: stringMap(value.title_overrides),
    project_name_overrides: stringMap(value.project_name_overrides),
    tags_by_key: tagsMap(value.tags_by_key),
    collapsed_groups: boolMap(value.collapsed_groups),
    workbench: normalizeWorkbenchState(value.workbench),
    view: {
      density,
      show_archived: Boolean(view.show_archived),
      sort,
    },
    updated_at: typeof value.updated_at === "string" ? value.updated_at : null,
  };
}

function pruneMissingSessions(
  state: SidebarStatePayload,
  sessions: ChatSummary[],
): SidebarStatePayload {
  const valid = new Set(sessions.map((session) => session.key));
  const filterKeys = (keys: string[]) => keys.filter((key) => valid.has(key));
  const filterMap = <T,>(map: Record<string, T>): Record<string, T> => {
    const out: Record<string, T> = {};
    for (const [key, value] of Object.entries(map)) {
      if (valid.has(key)) out[key] = value;
    }
    return out;
  };
  return {
    ...state,
    pinned_keys: filterKeys(state.pinned_keys),
    archived_keys: filterKeys(state.archived_keys),
    session_order: filterKeys(state.session_order),
    title_overrides: filterMap(state.title_overrides),
    tags_by_key: filterMap(state.tags_by_key),
  };
}

function sameState(a: SidebarStatePayload, b: SidebarStatePayload): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

function withTitleOverride(
  state: SidebarStatePayload,
  key: string,
  title: string | undefined,
): SidebarStatePayload {
  const titles = { ...state.title_overrides };
  if (title === undefined) delete titles[key];
  else titles[key] = title;
  return { ...state, title_overrides: titles };
}

// Prepare once against the state being saved. Reconcile with any optimistic
// edits that arrived while this confirmed write was in flight.
type PrepareSidebarSave = (state: SidebarStatePayload) => (
  (state: SidebarStatePayload, saved?: SidebarStatePayload) => SidebarStatePayload
) | null;

type PendingSidebarSave = {
  prepare: PrepareSidebarSave;
  resolve: () => void;
  reject: (error: unknown) => void;
};

export function useSidebarState(
  sessions: ChatSummary[],
  sessionsLoaded: boolean,
): {
  state: SidebarStatePayload;
  loading: boolean;
  update: (
    updater: (state: SidebarStatePayload) => SidebarStatePayload,
  ) => Promise<void>;
  save: (prepare: PrepareSidebarSave) => Promise<void>;
  rename: (key: string, title: string) => Promise<void>;
} {
  const { client, token } = useClient();
  const tokenRef = useRef(token);
  const stateRef = useRef(DEFAULT_SIDEBAR_STATE);
  const loadedRef = useRef(false);
  const connectionOpenRef = useRef(client.status === "open");
  const pendingPersistenceRef = useRef<SidebarStatePayload | null>(null);
  const pendingSavesRef = useRef<PendingSidebarSave[]>([]);
  const persistenceInFlightRef = useRef(false);
  const flushPersistenceRef = useRef<() => void>(() => {});
  const [state, setState] = useState<SidebarStatePayload>(DEFAULT_SIDEBAR_STATE);
  const [loading, setLoading] = useState(true);
  tokenRef.current = token;
  stateRef.current = state;

  useEffect(() => {
    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    setLoading(true);
    const load = async () => {
      if (cancelled || loadedRef.current) return;
      try {
        const loaded = normalizeSidebarState(await fetchSidebarState(tokenRef.current));
        if (cancelled || loadedRef.current) return;
        stateRef.current = loaded;
        loadedRef.current = true;
        setState(loaded);
        setLoading(false);
      } catch {
        if (cancelled || loadedRef.current) return;
        // A failed read is not an empty store. Keep writes blocked until a
        // retry can load the saved state, including after gateway restarts.
        retryTimer = setTimeout(() => void load(), 3_000);
      }
    };
    void load();
    return () => {
      cancelled = true;
      clearTimeout(retryTimer);
    };
  }, []);

  const rejectPendingSaves = useCallback((error: unknown) => {
    for (const request of pendingSavesRef.current.splice(0)) request.reject(error);
  }, []);

  const flushPersistence = useCallback(() => {
    if (
      !loadedRef.current
      || persistenceInFlightRef.current
      || !connectionOpenRef.current
    ) return;

    const pending = pendingPersistenceRef.current;
    // Optimistic snapshots must drain before a confirmed edit takes its own snapshot.
    const request = pending === null ? pendingSavesRef.current.shift() : undefined;
    const apply = request?.prepare(stateRef.current);
    const next = apply ? normalizeSidebarState(apply(stateRef.current)) : pending;
    if (next === null) {
      if (request) {
        request.resolve();
        queueMicrotask(() => flushPersistenceRef.current());
      }
      return;
    }
    pendingPersistenceRef.current = null;
    persistenceInFlightRef.current = true;
    void client.setSidebarState(next)
      .then((saved) => {
        const canonical = normalizeSidebarState(saved);
        if (apply && pendingPersistenceRef.current !== null) {
          const reconciled = apply(stateRef.current, canonical);
          pendingPersistenceRef.current = reconciled;
          stateRef.current = reconciled;
          setState(reconciled);
        } else if (pendingPersistenceRef.current === null) {
          stateRef.current = canonical;
          setState(canonical);
        }
        request?.resolve();
      })
      .catch((error: unknown) => {
        if (request) {
          request.reject(error);
        } else {
          if (pendingPersistenceRef.current === null) pendingPersistenceRef.current = next;
          rejectPendingSaves(error);
        }
        // Leave the failed optimistic snapshot queued for reconnection.
        return !request;
      })
      .then((retryOnReconnect) => {
        persistenceInFlightRef.current = false;
        if (!retryOnReconnect) flushPersistenceRef.current();
      });
  }, [client, rejectPendingSaves]);
  flushPersistenceRef.current = flushPersistence;

  const persist = useCallback((next: SidebarStatePayload) => {
    pendingPersistenceRef.current = next;
    flushPersistence();
  }, [flushPersistence]);

  useEffect(() => client.onStatus((status) => {
    connectionOpenRef.current = status === "open";
    if (status === "open") flushPersistence();
    else rejectPendingSaves(new Error("WebUI connection is not open"));
  }), [client, flushPersistence, rejectPendingSaves]);

  useEffect(() => client.onSidebarStateUpdate((incoming) => {
    if (
      persistenceInFlightRef.current
      || pendingPersistenceRef.current !== null
    ) return;
    const loaded = normalizeSidebarState(incoming);
    stateRef.current = loaded;
    loadedRef.current = true;
    setState(loaded);
    setLoading(false);
  }), [client]);

  const update = useCallback(
    async (updater: (current: SidebarStatePayload) => SidebarStatePayload) => {
      if (!loadedRef.current) return;
      const next = normalizeSidebarState(updater(stateRef.current));
      if (sameState(next, stateRef.current)) return;
      stateRef.current = next;
      setState(next);
      persist(next);
    },
    [persist],
  );

  const save = useCallback((prepare: PrepareSidebarSave): Promise<void> => {
    if (!loadedRef.current) return Promise.reject(new Error("Sidebar state is not loaded"));
    if (!connectionOpenRef.current) {
      return Promise.reject(new Error("WebUI connection is not open"));
    }
    return new Promise<void>((resolve, reject) => {
      pendingSavesRef.current.push({ prepare, resolve, reject });
      flushPersistence();
    });
  }, [flushPersistence]);

  const rename = useCallback((rawKey: string, title: string) => {
    const key = rawKey.trim();
    return save(() => (current, saved) => withTitleOverride(current, key, saved ? saved.title_overrides[key] : title));
  }, [save]);

  const pruned = useMemo(() => {
    if (!sessionsLoaded || loading) return state;
    return pruneMissingSessions(state, sessions);
  }, [loading, sessions, sessionsLoaded, state]);

  useEffect(() => {
    if (!sessionsLoaded || loading || sameState(pruned, state)) return;
    void update(() => pruned);
  }, [loading, pruned, sessionsLoaded, state, update]);

  return { state, loading, update, save, rename };
}
