import { useCallback, useEffect, useRef, useState } from "react";

import { useClient } from "@/providers/ClientProvider";
import { normalizeWorkbenchState } from "@/components/workbench/workbench-model";
import { fetchSidebarState } from "@/lib/api";
import type { ChatSummary, SidebarStatePayload } from "@/lib/types";

const DEFAULT_SIDEBAR_STATE: SidebarStatePayload = {
  schema_version: 1,
  pinned_keys: [],
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

type PendingRename = {
  key: string;
  title: string;
  resolve: () => void;
  reject: (error: unknown) => void;
};

export function useSidebarState(
  sessions: ChatSummary[],
  catalogLoaded: boolean,
) {
  const { client, token } = useClient();
  const tokenRef = useRef(token);
  const stateRef = useRef(DEFAULT_SIDEBAR_STATE);
  const loadedRef = useRef(false);
  const connectionOpenRef = useRef(client.status === "open");
  const dirty = useRef(false);
  const renames = useRef<PendingRename[]>([]);
  const saving = useRef(false);
  const [state, setState] = useState<SidebarStatePayload>(DEFAULT_SIDEBAR_STATE);
  const [loading, setLoading] = useState(true);
  tokenRef.current = token;
  const publish = useCallback((next: SidebarStatePayload) => {
    stateRef.current = next;
    setState(next);
  }, []);

  useEffect(() => {
    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    setLoading(true);
    const load = async () => {
      if (cancelled || loadedRef.current) return;
      try {
        const loaded = normalizeSidebarState(await fetchSidebarState(tokenRef.current));
        if (cancelled || loadedRef.current) return;
        loadedRef.current = true;
        publish(loaded);
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
  }, [publish]);

  const rejectRenames = useCallback((error: unknown) => {
    for (const rename of renames.current.splice(0)) rename.reject(error);
  }, []);

  const flush = useCallback(async () => {
    if (saving.current) return;
    saving.current = true;
    while (connectionOpenRef.current && (dirty.current || renames.current.length)) {
      // Flush optimistic preferences first. Only publish a rename after its acknowledgement.
      const rename = dirty.current ? undefined : renames.current.shift();
      dirty.current = false;
      try {
        const current = stateRef.current;
        const next = rename ? normalizeSidebarState(withTitleOverride(current, rename.key, rename.title)) : current;
        const saved = normalizeSidebarState(await client.setSidebarState(next));
        if (!dirty.current) publish(saved);
        else if (rename) publish(withTitleOverride(stateRef.current, rename.key, saved.title_overrides[rename.key]));
        rename?.resolve();
      } catch (error) {
        if (rename) rename.reject(error);
        else {
          dirty.current = true;
          rejectRenames(error);
          break; // Retry preferences on reconnect; never silently retry a rename.
        }
      }
    }
    saving.current = false;
  }, [client, publish, rejectRenames]);

  useEffect(() => client.onStatus((status) => {
    connectionOpenRef.current = status === "open";
    if (connectionOpenRef.current) void flush();
    else rejectRenames(new Error("WebUI connection is not open"));
  }), [client, flush, rejectRenames]);

  useEffect(() => client.onSidebarStateUpdate((incoming) => {
    if (saving.current || dirty.current) return;
    loadedRef.current = true;
    publish(normalizeSidebarState(incoming));
    setLoading(false);
  }), [client, publish]);

  const update = useCallback(
    (updater: (current: SidebarStatePayload) => SidebarStatePayload) => {
      if (!loadedRef.current) return;
      const next = normalizeSidebarState(updater(stateRef.current));
      if (sameState(next, stateRef.current)) return;
      dirty.current = true;
      publish(next);
      void flush();
    },
    [flush, publish],
  );

  const rename = useCallback((key: string, title: string): Promise<void> => {
    if (!loadedRef.current) return Promise.reject(new Error("Sidebar state is not loaded"));
    if (!connectionOpenRef.current) {
      return Promise.reject(new Error("WebUI connection is not open"));
    }
    return new Promise<void>((resolve, reject) => {
      renames.current.push({ key: key.trim(), title, resolve, reject });
      void flush();
    });
  }, [flush]);

  useEffect(() => {
    if (catalogLoaded && !loading) update(current => pruneMissingSessions(current, sessions));
  }, [loading, sessions, catalogLoaded, state, update]);

  return { state, loading, update, rename };
}
