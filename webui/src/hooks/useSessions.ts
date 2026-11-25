import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { switchModelPreset } from "@/lib/switch-model-preset";
import { useClient } from "@/providers/ClientProvider";
import { useNanobotStream } from "@/hooks/useNanobotStream";
import {
  ApiError,
  deleteSession as apiDeleteSession,
  fetchSessionAutomations,
  listSessions,
} from "@/lib/api";
import { webuiThreadCache } from "@/lib/webui-thread-cache";
import { readReloadSessions, writeReloadCache } from "@/lib/reload-cache";
import type {
  ChatSummary,
  SessionAutomationJob,
  SessionDeleteResult,
  WorkspaceScopePayload,
} from "@/lib/types";

const CHAT_CREATE_TIMEOUT_MS = 60_000;

export function useSessions(): {
  sessions: ChatSummary[];
  archivedKeys: string[];
  archivesLoaded: boolean;
  loadArchived: () => void;
  loading: boolean;
  initialLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  createChat: (
    workspaceScope?: WorkspaceScopePayload | null,
    modelPreset?: string | null,
  ) => Promise<string>;
  forkChat: (sourceChatId: string, beforeUserIndex: number, title?: string) => Promise<string>;
  deleteChat: (
    key: string,
    options?: { deleteAutomations?: boolean },
  ) => Promise<SessionDeleteResult>;
  getSessionAutomations: (key: string) => Promise<SessionAutomationJob[]>;
} {
  const { client, token } = useClient();
  const [activeSessions, setSessions] = useState<ChatSummary[]>(readReloadSessions);
  const [archive, setArchive] = useState<ChatSummary[] | null>(null);
  const includeArchive = useRef(false);
  const archivedKeys = useMemo(() => archive?.map(row => row.key) ?? [], [archive]);
  const sessions = useMemo(() => archive?.length ? [...activeSessions, ...archive] : activeSessions, [activeSessions, archive]);
  const [loadedOnce, setLoadedOnce] = useState(() => sessions.length > 0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const tokenRef = useRef(token);
  const failedDraftRef = useRef<{
    client: typeof client; scope?: WorkspaceScopePayload | null; chatId: string;
  } | null>(null);
  const optimisticKeysRef = useRef<Set<string>>(new Set());
  const refreshPendingRef = useRef(false);
  const refreshInFlightRef = useRef<Promise<void> | null>(null);
  tokenRef.current = token;

  useEffect(() => {
    if (activeSessions.length || !loading) writeReloadCache("activeSessions", activeSessions.slice(0, 200));
  }, [activeSessions, loading]);

  const refresh = useCallback((): Promise<void> => {
    refreshPendingRef.current = true;
    if (refreshInFlightRef.current) return refreshInFlightRef.current;
    const request = (async () => {
      setLoading(true);
      try {
        while (refreshPendingRef.current) {
          refreshPendingRef.current = false;
          try {
            const [rows, archived] = await Promise.all([
              listSessions(tokenRef.current, false),
              includeArchive.current ? listSessions(tokenRef.current, true) : null,
            ]);
            setLoadedOnce(true);
            const serverKeys = new Set(rows.map((row) => row.key));
            setSessions((prev) => {
              const byKey = new Map(prev.map((row) => [row.key, row]));
              const next = [
                ...rows.map((row) => {
                  const previous = byKey.get(row.key);
                  return previous && JSON.stringify(previous) === JSON.stringify(row) ? previous : row;
                }),
                ...prev.filter(
                  (session) =>
                    optimisticKeysRef.current.has(session.key)
                    && !serverKeys.has(session.key),
                ),
              ];
              return next.length === prev.length && next.every((row, index) => row === prev[index]) ? prev : next;
            });
            if (archived !== null) {
              setArchive(archived.filter(row => !serverKeys.has(row.key)));
            }
            for (const key of Array.from(optimisticKeysRef.current)) {
              if (serverKeys.has(key)) optimisticKeysRef.current.delete(key);
            }
            setError(null);
          } catch (e) {
            const msg =
              e instanceof ApiError ? `HTTP ${e.status}` : (e as Error).message;
            setError(msg);
          }
        }
      } finally {
        refreshInFlightRef.current = null;
        setLoading(false);
      }
    })();
    refreshInFlightRef.current = request;
    return request;
  }, []);

  const loadArchived = useCallback(() => {
    if (includeArchive.current) return;
    includeArchive.current = true;
    void refresh();
  }, [refresh]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const scheduleRefresh = () => {
      if (timer !== undefined) return;
      timer = setTimeout(() => {
        timer = undefined;
        void refresh();
      }, 250);
    };
    const unsubscribe = client.onSessionUpdate(scheduleRefresh);
    const unsubscribeArchive = client.onSessionsChanged(scheduleRefresh);
    let opened = false;
    const unsubscribeStatus = client.onStatus(status => {
      if (status !== "open") return;
      if (opened) scheduleRefresh(); // The window may have missed an archive while disconnected.
      opened = true;
    });
    return () => {
      clearTimeout(timer);
      unsubscribeStatus();
      unsubscribeArchive();
      unsubscribe();
    };
  }, [client, refresh]);

  const createChat = useCallback(async (
    workspaceScope?: WorkspaceScopePayload | null,
    modelPreset?: string | null,
  ): Promise<string> => {
    // Claim the draft for one retry; a concurrent creation must get its own ID.
    const draft = failedDraftRef.current;
    failedDraftRef.current = null;
    const chatId = modelPreset && draft?.client === client
      && draft.scope?.project_path === workspaceScope?.project_path
      && draft.scope?.access_mode === workspaceScope?.access_mode
      ? draft.chatId : await client.newChat(CHAT_CREATE_TIMEOUT_MS, workspaceScope);
    const preset = modelPreset ? await switchModelPreset(client, chatId, modelPreset).catch((error: unknown) => {
      if (client.status === "open") failedDraftRef.current = { client, scope: workspaceScope, chatId };
      throw error;
    }) : null;
    const key = `websocket:${chatId}`;
    optimisticKeysRef.current.add(key);
    // Optimistic insert; a subsequent refresh will replace it with the
    // authoritative row once the server persists the session.
    setSessions((prev) => [
      {
        key,
        channel: "websocket",
        chatId,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        title: "",
        preview: "",
        modelPreset: preset,
        workspaceScope: workspaceScope ?? null,
        projectLocked: false,
      },
      ...prev.filter((s) => s.key !== key),
    ]);
    return chatId;
  }, [client]);

  const forkChat = useCallback(async (
    sourceChatId: string,
    beforeUserIndex: number,
    title?: string,
  ): Promise<string> => {
    const chatId = await client.forkChat(
      sourceChatId,
      beforeUserIndex,
      title,
      CHAT_CREATE_TIMEOUT_MS,
    );
    const key = `websocket:${chatId}`;
    optimisticKeysRef.current.add(key);
    setSessions((prev) => [
      {
        key,
        channel: "websocket",
        chatId,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        title: title ?? "",
        preview: "",
        workspaceScope: null,
      },
      ...prev.filter((s) => s.key !== key),
    ]);
    return chatId;
  }, [client]);

  const deleteChat = useCallback(
    async (key: string, options?: { deleteAutomations?: boolean }) => {
      const optimistic = optimisticKeysRef.current.has(key);
      const result = await apiDeleteSession(client, key, options);
      if (result.blocked_by_automations || (!result.deleted && !optimistic)) return result;
      optimisticKeysRef.current.delete(key);
      webuiThreadCache.delete(key);
      setArchive(prev => prev?.filter(row => row.key !== key) ?? null);
      setSessions((prev) => prev.filter((s) => s.key !== key));
      // The gateway may have restarted and forgotten an unpersisted chat's
      // draft scope, but removing that optimistic session is still a deletion.
      return result.deleted ? result : { ...result, deleted: true };
    },
    [client],
  );

  const getSessionAutomations = useCallback(async (key: string) => {
    const result = await fetchSessionAutomations(tokenRef.current, key);
    return result.jobs;
  }, []);

  return {
    sessions,
    archivedKeys,
    archivesLoaded: archive !== null,
    loadArchived,
    loading,
    initialLoading: loading && !loadedOnce,
    error,
    refresh,
    createChat,
    forkChat,
    deleteChat,
    getSessionAutomations,
  };
}

export function useSessionHistory(key: string | null) {
  const { messages, messagesKey, messagesReady, history, refreshHistory, loadOlder } = useNanobotStream(
    null, undefined, false, undefined, undefined, undefined, { key },
  );
  return { messages, messagesKey, messagesReady, ...history, refresh: refreshHistory, loadOlder };
}
