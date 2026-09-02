import { useCallback, useEffect, useRef, useState } from "react";

import { useClient } from "@/providers/ClientProvider";
import i18n from "@/i18n";
import {
  ApiError,
  deleteSession as apiDeleteSession,
  fetchSessionAutomations,
  fetchWebuiThread,
  listSessions,
} from "@/lib/api";
import { hasPendingAgentActivity } from "@/lib/activity-timeline";
import { deriveTitle } from "@/lib/format";
import type {
  ChatSummary,
  SessionAutomationJob,
  SessionDeleteResult,
  UIMessage,
  WorkspaceScopePayload,
} from "@/lib/types";

const EMPTY_MESSAGES: UIMessage[] = [];
const INITIAL_HISTORY_PAGE_LIMIT = 80;
const OLDER_HISTORY_PAGE_LIMIT = 120;
const CHAT_CREATE_TIMEOUT_MS = 60_000;

function isAbortError(error: unknown): boolean {
  return (
    typeof error === "object"
    && error !== null
    && "name" in error
    && error.name === "AbortError"
  );
}

export type SessionHistoryContinuity = "initial" | "overlap" | "reset";

function persistedMessagesToUi(messages: UIMessage[]): UIMessage[] {
  return messages.map((m, idx) => ({
    ...m,
    id: m.id ?? `hist-${idx}`,
    createdAt: typeof m.createdAt === "number" ? m.createdAt : Date.now(),
  }));
}

function sameSemanticMessage(a: UIMessage, b: UIMessage): boolean {
  return (
    a.role === b.role
    && (a.kind ?? "") === (b.kind ?? "")
    && a.content === b.content
    && (!a.turnId || !b.turnId || a.turnId === b.turnId)
  );
}

function longestSemanticOverlap(previous: UIMessage[], latest: UIMessage[]): number {
  const maxOverlap = Math.min(previous.length, latest.length);
  for (let overlap = maxOverlap; overlap > 0; overlap -= 1) {
    const previousStart = previous.length - overlap;
    let matches = true;
    for (let index = 0; index < overlap; index += 1) {
      if (!sameSemanticMessage(previous[previousStart + index], latest[index])) {
        matches = false;
        break;
      }
    }
    if (matches) return overlap;
  }
  return 0;
}

function mergeLatestHistory(
  previous: UIMessage[],
  latest: UIMessage[],
  initial: boolean,
): {
  continuity: SessionHistoryContinuity;
  messages: UIMessage[];
  retainedPrefixLength: number;
} {
  if (initial) {
    return {
      continuity: "initial",
      messages: latest,
      retainedPrefixLength: 0,
    };
  }
  const overlapLength = longestSemanticOverlap(previous, latest);
  if (overlapLength === 0) {
    return {
      continuity: "reset",
      messages: latest,
      retainedPrefixLength: 0,
    };
  }
  const retainedPrefixLength = previous.length - overlapLength;
  return {
    continuity: "overlap",
    messages: [...previous.slice(0, retainedPrefixLength), ...latest],
    retainedPrefixLength,
  };
}

function hasPendingToolCallsFromThread(
  body: Awaited<ReturnType<typeof fetchWebuiThread>>,
  messages: UIMessage[],
): boolean {
  if (typeof body?.has_pending_tool_calls === "boolean") {
    return body.has_pending_tool_calls;
  }
  return hasPendingAgentActivity(messages);
}

function completedTurnIdsFromThread(
  body: Awaited<ReturnType<typeof fetchWebuiThread>>,
): string[] {
  if (!Array.isArray(body?.completed_turn_ids)) return [];
  return Array.from(new Set(
    body.completed_turn_ids.filter(
      (turnId): turnId is string => typeof turnId === "string" && turnId.length > 0,
    ),
  ));
}

/** Sidebar state: fetches the full session list and exposes create / delete actions. */
export function useSessions(): {
  sessions: ChatSummary[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  createChat: (workspaceScope?: WorkspaceScopePayload | null) => Promise<string>;
  forkChat: (sourceChatId: string, beforeUserIndex: number, title?: string) => Promise<string>;
  deleteChat: (
    key: string,
    options?: { deleteAutomations?: boolean },
  ) => Promise<SessionDeleteResult>;
  getSessionAutomations: (key: string) => Promise<SessionAutomationJob[]>;
} {
  const { client, token } = useClient();
  const [sessions, setSessions] = useState<ChatSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const tokenRef = useRef(token);
  const optimisticKeysRef = useRef<Set<string>>(new Set());
  const refreshPendingRef = useRef(false);
  const refreshInFlightRef = useRef<Promise<void> | null>(null);
  tokenRef.current = token;

  const refresh = useCallback((): Promise<void> => {
    refreshPendingRef.current = true;
    if (refreshInFlightRef.current) return refreshInFlightRef.current;
    const request = (async () => {
      setLoading(true);
      try {
        while (refreshPendingRef.current) {
          refreshPendingRef.current = false;
          try {
            const rows = await listSessions(tokenRef.current);
            const serverKeys = new Set(rows.map((row) => row.key));
            setSessions((prev) => [
              ...rows,
              ...prev.filter(
                (session) =>
                  optimisticKeysRef.current.has(session.key)
                  && !serverKeys.has(session.key),
              ),
            ]);
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

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    let disposed = false;
    let refreshQueued = false;
    const unsubscribe = client.onSessionUpdate(() => {
      if (refreshQueued) return;
      refreshQueued = true;
      queueMicrotask(() => {
        refreshQueued = false;
        if (!disposed) void refresh();
      });
    });
    return () => {
      disposed = true;
      unsubscribe();
    };
  }, [client, refresh]);

  const createChat = useCallback(async (workspaceScope?: WorkspaceScopePayload | null): Promise<string> => {
    const chatId = await client.newChat(CHAT_CREATE_TIMEOUT_MS, workspaceScope);
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
        workspaceScope: workspaceScope ?? null,
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
    loading,
    error,
    refresh,
    createChat,
    forkChat,
    deleteChat,
    getSessionAutomations,
  };
}

/** Lazy-load a session's on-disk messages the first time the UI displays it. */
export function useSessionHistory(key: string | null): {
  messages: UIMessage[];
  loading: boolean;
  loadingOlder: boolean;
  error: string | null;
  refresh: () => void;
  loadOlder: () => Promise<void>;
  hasMoreBefore: boolean;
  userMessageOffset: number;
  version: number;
  forkBoundaryMessageCount: number | null;
  /** ``true`` when the server reports that the turn is still in flight. */
  hasPendingToolCalls: boolean;
  /** Turn identities backed by explicit persisted completion events. */
  completedTurnIds: string[];
  /** Relationship between the latest canonical page and its predecessor. */
  continuity: SessionHistoryContinuity;
  /** Stable across overlapping latest pages; changes on initial load or reset. */
  lineage: number;
  /** Exact active turn when supplied by a current gateway. */
  activeTurnId: string | null;
} {
  const { getToken } = useClient();
  const loadingOlderRef = useRef(false);
  const olderRequestAbortRef = useRef<AbortController | null>(null);
  const historyVersionRef = useRef(0);
  const [refreshSeq, setRefreshSeq] = useState(0);
  const refresh = useCallback(() => {
    setRefreshSeq((value) => value + 1);
  }, []);
  const [state, setState] = useState<{
    key: string | null;
    messages: UIMessage[];
    loading: boolean;
    loadingOlder: boolean;
    error: string | null;
    hasPendingToolCalls: boolean;
    completedTurnIds: string[];
    forkBoundaryMessageCount: number | null;
    beforeCursor: string | null;
    hasMoreBefore: boolean;
    userMessageOffset: number;
    version: number;
    continuity: SessionHistoryContinuity;
    lineage: number;
    activeTurnId: string | null;
  }>({
    key: null,
    messages: [],
    loading: false,
    loadingOlder: false,
    error: null,
    hasPendingToolCalls: false,
    completedTurnIds: [],
    forkBoundaryMessageCount: null,
    beforeCursor: null,
    hasMoreBefore: false,
    userMessageOffset: 0,
    version: 0,
    continuity: "initial",
    lineage: 0,
    activeTurnId: null,
  });

  useEffect(() => () => {
    olderRequestAbortRef.current?.abort();
    olderRequestAbortRef.current = null;
    loadingOlderRef.current = false;
  }, []);

  useEffect(() => {
    if (!key) {
      olderRequestAbortRef.current?.abort();
      olderRequestAbortRef.current = null;
      loadingOlderRef.current = false;
      setState({
        key: null,
        messages: [],
        loading: false,
        loadingOlder: false,
        error: null,
        hasPendingToolCalls: false,
        completedTurnIds: [],
        forkBoundaryMessageCount: null,
        beforeCursor: null,
        hasMoreBefore: false,
        userMessageOffset: 0,
        version: 0,
        continuity: "initial",
        lineage: 0,
        activeTurnId: null,
      });
      return;
    }
    let cancelled = false;
    const controller = new AbortController();
    olderRequestAbortRef.current?.abort();
    olderRequestAbortRef.current = null;
    loadingOlderRef.current = false;
    // Mark the new key as loading immediately so callers never see stale
    // messages from the previous session during the render right after a switch.
    setState((prev) => prev.key === key
      ? { ...prev, loading: true, loadingOlder: false, error: null }
      : {
          key,
          messages: [],
          loading: true,
          loadingOlder: false,
          error: null,
          hasPendingToolCalls: false,
          completedTurnIds: [],
          forkBoundaryMessageCount: null,
          beforeCursor: null,
          hasMoreBefore: false,
          userMessageOffset: 0,
          version: 0,
          continuity: "initial",
          lineage: 0,
          activeTurnId: null,
        });
    (async () => {
      try {
        const body = await fetchWebuiThread(getToken(), key, {
          limit: INITIAL_HISTORY_PAGE_LIMIT,
          direction: "latest",
          signal: controller.signal,
        });
        if (cancelled) return;
        historyVersionRef.current += 1;
        const responseVersion = historyVersionRef.current;
        const completedTurnIds = completedTurnIdsFromThread(body);
        const ui = persistedMessagesToUi(body?.messages ?? []);
        const hasPending = hasPendingToolCallsFromThread(body, ui);
        const forkBoundary = typeof body?.fork_boundary_message_count === "number"
          ? Math.max(0, Math.min(body.fork_boundary_message_count, ui.length))
          : null;
        setState((prev) => {
          const merged = prev.key === key
            ? mergeLatestHistory(prev.messages, ui, prev.lineage === 0)
            : mergeLatestHistory([], ui, true);
          const retainedPrefix = merged.retainedPrefixLength > 0;
          const retainedForkBoundary = (
            retainedPrefix
            && prev.forkBoundaryMessageCount !== null
            && prev.forkBoundaryMessageCount <= merged.retainedPrefixLength
          )
            ? prev.forkBoundaryMessageCount
            : null;
          return {
            key,
            messages: merged.messages,
            loading: false,
            loadingOlder: false,
            error: null,
            hasPendingToolCalls: hasPending,
            completedTurnIds,
            forkBoundaryMessageCount: forkBoundary === null
              ? retainedForkBoundary
              : forkBoundary + merged.retainedPrefixLength,
            beforeCursor: retainedPrefix
              ? prev.beforeCursor
              : body?.page?.before_cursor ?? null,
            hasMoreBefore: retainedPrefix
              ? prev.hasMoreBefore
              : body?.page?.has_more_before === true,
            userMessageOffset: retainedPrefix
              ? prev.userMessageOffset
              : Math.max(0, body?.page?.user_message_offset ?? 0),
            version: responseVersion,
            continuity: merged.continuity,
            lineage: merged.continuity === "overlap"
              ? prev.lineage
              : responseVersion,
            activeTurnId: typeof body?.active_turn_id === "string"
              ? body.active_turn_id
              : null,
          };
        });
      } catch (e) {
        if (cancelled || isAbortError(e)) return;
        if (e instanceof ApiError && e.status === 404) {
          historyVersionRef.current += 1;
          const responseVersion = historyVersionRef.current;
          setState((prev) => {
            const continuity = prev.key === key && prev.lineage > 0
              ? "reset"
              : "initial";
            return {
              key,
              messages: [],
              loading: false,
              loadingOlder: false,
              error: null,
              hasPendingToolCalls: false,
              completedTurnIds: [],
              forkBoundaryMessageCount: null,
              beforeCursor: null,
              hasMoreBefore: false,
              userMessageOffset: 0,
              version: responseVersion,
              continuity,
              lineage: responseVersion,
              activeTurnId: null,
            };
          });
        } else {
          setState((prev) => ({
            key,
            messages: [],
            loading: false,
            loadingOlder: false,
            error: (e as Error).message,
            hasPendingToolCalls: false,
            completedTurnIds: [],
            forkBoundaryMessageCount: null,
            beforeCursor: null,
            hasMoreBefore: false,
            userMessageOffset: 0,
            version: prev.key === key ? prev.version : 0,
            continuity: prev.key === key ? prev.continuity : "initial",
            lineage: prev.key === key ? prev.lineage : 0,
            activeTurnId: prev.key === key ? prev.activeTurnId : null,
          }));
        }
      }
    })();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [getToken, key, refreshSeq]);

  const loadOlder = useCallback(async () => {
    if (!key || loadingOlderRef.current) return;
    const requestKey = key;
    const requestLineage = state.key === requestKey ? state.lineage : 0;
    const beforeCursor = state.key === requestKey ? state.beforeCursor : null;
    if (!beforeCursor || !state.hasMoreBefore || requestLineage === 0) return;
    const matchesRequest = (candidate: typeof state) => (
      candidate.key === requestKey
      && candidate.lineage === requestLineage
      && candidate.beforeCursor === beforeCursor
    );
    loadingOlderRef.current = true;
    const controller = new AbortController();
    olderRequestAbortRef.current = controller;
    setState((prev) => matchesRequest(prev)
      ? { ...prev, loadingOlder: true, error: null }
      : prev);
    try {
      const body = await fetchWebuiThread(getToken(), requestKey, {
        limit: OLDER_HISTORY_PAGE_LIMIT,
        before: beforeCursor,
        signal: controller.signal,
      });
      setState((prev) => {
        if (!matchesRequest(prev)) return prev;
        if (!body?.messages?.length) {
          return {
            ...prev,
            loadingOlder: false,
            hasMoreBefore: false,
            beforeCursor: null,
          };
        }
        const older = persistedMessagesToUi(body.messages);
        const olderBoundary = typeof body.fork_boundary_message_count === "number"
          ? Math.max(0, Math.min(body.fork_boundary_message_count, older.length))
          : null;
        const shiftedBoundary = prev.forkBoundaryMessageCount === null
          ? null
          : prev.forkBoundaryMessageCount + older.length;
        const nextMessages = [...older, ...prev.messages];
        // An older page cannot change the authoritative latest-turn lifecycle
        // state or masquerade as a completed latest-page refresh.
        return {
          ...prev,
          messages: nextMessages,
          loadingOlder: false,
          error: null,
          forkBoundaryMessageCount: olderBoundary ?? shiftedBoundary,
          beforeCursor: body.page?.before_cursor ?? null,
          hasMoreBefore: body.page?.has_more_before === true,
          userMessageOffset: Math.max(0, body.page?.user_message_offset ?? 0),
        };
      });
    } catch (e) {
      if (isAbortError(e)) return;
      setState((prev) => matchesRequest(prev)
        ? {
            ...prev,
            loadingOlder: false,
            error: (e as Error).message,
          }
        : prev);
    } finally {
      if (olderRequestAbortRef.current === controller) {
        olderRequestAbortRef.current = null;
        loadingOlderRef.current = false;
      }
    }
  }, [
    key,
    state.beforeCursor,
    state.hasMoreBefore,
    state.key,
    state.lineage,
    getToken,
  ]);

  if (!key) {
    return {
      messages: EMPTY_MESSAGES,
      loading: false,
      loadingOlder: false,
      error: null,
      refresh,
      loadOlder,
      hasMoreBefore: false,
      userMessageOffset: 0,
      version: 0,
      forkBoundaryMessageCount: null,
      hasPendingToolCalls: false,
      completedTurnIds: [],
      continuity: "initial",
      lineage: 0,
      activeTurnId: null,
    };
  }

  // Even before the effect above commits its loading state, never surface the
  // previous session's payload for a brand-new key.
  if (state.key !== key) {
    return {
      messages: EMPTY_MESSAGES,
      loading: true,
      loadingOlder: false,
      error: null,
      refresh,
      loadOlder,
      hasMoreBefore: false,
      userMessageOffset: 0,
      version: 0,
      forkBoundaryMessageCount: null,
      hasPendingToolCalls: false,
      completedTurnIds: [],
      continuity: "initial",
      lineage: 0,
      activeTurnId: null,
    };
  }

  return {
    messages: state.messages,
    loading: state.loading,
    loadingOlder: state.loadingOlder,
    error: state.error,
    refresh,
    loadOlder,
    hasMoreBefore: state.hasMoreBefore,
    userMessageOffset: state.userMessageOffset,
    version: state.version,
    forkBoundaryMessageCount: state.forkBoundaryMessageCount,
    hasPendingToolCalls: state.hasPendingToolCalls,
    completedTurnIds: state.completedTurnIds,
    continuity: state.continuity,
    lineage: state.lineage,
    activeTurnId: state.activeTurnId,
  };
}

/** Produce a compact display title for a session. */
export function sessionTitle(
  session: ChatSummary,
  firstUserMessage?: string,
): string {
  return deriveTitle(
    session.title || firstUserMessage || session.preview,
    i18n.t("chat.newChat"),
  );
}
