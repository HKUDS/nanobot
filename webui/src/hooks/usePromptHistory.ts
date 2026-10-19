import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useClient } from "@/providers/ClientProvider";
import { fetchPromptIndex, fetchWebuiThread } from "@/lib/api";
import { projectThreadEvents } from "@/lib/thread-event-projection";
import { projectWebuiThreadMessages } from "@/lib/thread-display-projection";
import { isModelCommandText } from "@/lib/format";
import { isSystemCommandTurnId } from "@/lib/nanobot-client";
import type { PromptIndex, UIMessage, WebuiThreadPersistedPayload } from "@/lib/types";
import { type PromptAnchor, userPromptAnchors } from "@/components/thread/promptNavigation";

interface HistoryPage {
  messages: UIMessage[];
  body: WebuiThreadPersistedPayload;
}

export interface PromptHistoryNavigation {
  prompts: PromptAnchor[];
  window: {
    messages: UIMessage[];
    userMessageOffset: number;
    hasMoreBefore: boolean;
    hasMoreAfter: boolean;
    forkBoundaryMessageCount: number | null;
  } | null;
  target: { id: string; sequence: number } | null;
  loading: boolean;
  error: string | null;
  jump: (id: string) => void;
  older: () => void;
  newer: () => void;
  cancel: () => void;
  latest: () => void;
  retry: () => void;
  updateMessages: (update: (messages: UIMessage[]) => UIMessage[]) => void;
}

/** Browsing pages never replace the canonical latest page or live turn state. */
export function usePromptHistory(key: string | null, version: number, messages: UIMessage[]): PromptHistoryNavigation {
  const { client, getToken, webuiCapabilities } = useClient();
  const enabled = !!key && webuiCapabilities.includes("webui.prompt-navigation.v1");
  const [index, setIndex] = useState<{ key: string; prompts: PromptAnchor[] } | null>(null);
  const indexSnapshot = useRef<PromptIndex>();
  const [pages, setPages] = useState<HistoryPage[]>([]);
  const [target, setTarget] = useState<PromptHistoryNavigation["target"]>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [indexError, setIndexError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const request = useRef<AbortController | null>(null);
  const sequence = useRef(0);
  const retry = useRef<() => void>(() => setRefresh((value) => value + 1));
  const scope = useRef({ key, client });
  const currentScope = scope.current.key === key && scope.current.client === client;

  const cancel = useCallback(() => {
    request.current?.abort();
    request.current = null;
    setTarget(null);
    setLoading(false);
    setError(null);
  }, []);

  const latest = useCallback(() => {
    cancel();
    setPages([]);
  }, [cancel]);

  useEffect(() => {
    scope.current = { key, client };
    latest();
    setIndex(null);
    indexSnapshot.current = undefined;
    setIndexError(null);
    return () => request.current?.abort();
  }, [key, client, enabled, latest]);

  useEffect(() => {
    if (!enabled || !key) return;
    const controller = new AbortController();
    void fetchPromptIndex(getToken(), key, controller.signal, indexSnapshot.current).then((snapshot) => {
      if (controller.signal.aborted) return;
      if (snapshot === indexSnapshot.current) { setIndexError(null); return; }
      indexSnapshot.current = snapshot;
      setIndex({ key, prompts: snapshot.prompts.filter((item) => !isSystemCommandTurnId(item.turnId) && !isModelCommandText(item.preview)).map((item, position) => ({ ...item, index: position,
        label: item.preview.replace(/\s+/g, " ").slice(0, 80) || `Prompt ${position + 1}`,
      })) });
      setIndexError(null);
    }).catch((cause: unknown) => {
      if (controller.signal.aborted) return;
      setIndexError(cause instanceof Error ? cause.message : String(cause));
    });
    return () => controller.abort();
  }, [client, enabled, getToken, key, version, refresh]);

  const indexed = useMemo(() => {
    const ids = new Set<string>();
    const turns = new Map<string, PromptAnchor | null>();
    for (const prompt of index?.prompts ?? []) {
      ids.add(prompt.id);
      if (prompt.turnId) turns.set(prompt.turnId, turns.has(prompt.turnId) ? null : prompt);
    }
    return { ids, turns };
  }, [index]);
  const localCache = useRef<{ index: typeof index; users: UIMessage[]; prompts: PromptAnchor[] }>();
  const prompts = useMemo(() => {
    if (!enabled) return userPromptAnchors(messages);
    if (!currentScope || index?.key !== key) return [];
    // Live rows can still have optimistic render ids after admission. Match the
    // host's unambiguous original transport id and content, not text alone.
    const users = messages.filter((message) => {
      if (message.role !== "user" || indexed.ids.has(message.id)) return false;
      const admitted = message.turnId ? indexed.turns.get(message.turnId) : null;
      return !admitted || admitted.preview !== message.content.trim().slice(0, 320);
    });
    if (!users.length) return index.prompts;
    const cached = localCache.current;
    if (cached?.index === index && users.length === cached.users.length
      && users.every((user, position) => user === cached.users[position])) return cached.prompts;
    const localIds = new Set(users.map((message) => message.id));
    const local = userPromptAnchors(messages).filter((prompt) => localIds.has(prompt.id));
    // Directory order is logical admission order. Unknown legacy times are zero,
    // not a reason to move an old prompt ahead of its preceding inputs.
    const merged = [...index.prompts, ...local].map((prompt, position) => ({ ...prompt, index: position }));
    localCache.current = { index, users, prompts: merged };
    return merged;
  }, [currentScope, enabled, index, indexed, key, messages]);

  const updateMessages = useCallback((update: (messages: UIMessage[]) => UIMessage[]) => {
    setPages((current) => current.map((page) => ({ ...page, messages: update(page.messages) })));
  }, []);

  const read = useCallback(async (cursor: string, direction: "before" | "after", id?: string) => {
    if (!key) return;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setLoading(true);
    setError(null);
    retry.current = () => { void read(cursor, direction, id); };
    try {
      const body = await fetchWebuiThread(getToken(), key, {
        [direction]: cursor, limit: 24, signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      if (!body) throw new Error("History is no longer available");
      const page = { body, messages: projectWebuiThreadMessages(projectThreadEvents(body.events)) };
      if (id && !page.messages.some((message) => message.id === id)) {
        setRefresh((value) => value + 1);
        throw new Error("History changed; select the message again");
      }
      // At most three bounded server pages, even after many navigations.
      setPages((previous) => id ? [page] : direction === "before"
        ? [page, ...previous].slice(0, 3) : [...previous, page].slice(-3));
      if (id) setTarget({ id, sequence: ++sequence.current });
    } catch (cause) {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      if (request.current === controller) {
        request.current = null;
        setLoading(false);
      }
    }
  }, [getToken, key]);

  const first = pages[0]?.body.page;
  const last = pages[pages.length - 1]?.body.page;
  const window = useMemo(() => {
    if (!currentScope || !pages.length) return null;
    let count = 0;
    let boundary: number | null = null;
    for (const page of pages) {
      const eventIndex = page.body.fork_boundary_event_index;
      if (eventIndex !== undefined) boundary = count + projectWebuiThreadMessages(projectThreadEvents(page.body.events.slice(0, eventIndex))).length;
      count += page.messages.length;
    }
    return { messages: pages.flatMap((page) => page.messages),
      userMessageOffset: first?.user_message_offset ?? 0,
      hasMoreBefore: first?.has_more_before === true, hasMoreAfter: last?.has_more_after === true,
      forkBoundaryMessageCount: boundary };
  }, [currentScope, pages, first, last]);

  return { prompts, window, target: currentScope ? target : null, loading: currentScope && loading,
    error: currentScope ? error ?? indexError : null, cancel, latest, updateMessages,
    retry: () => error ? retry.current() : setRefresh((value) => value + 1),
    jump: (id) => {
      const prompt = prompts.find((item) => item.id === id);
      if (enabled && prompt?.cursor) void read(prompt.cursor, "after", id);
    },
    older: () => { if (!loading && first?.before_cursor) void read(first.before_cursor, "before"); },
    newer: () => { if (!loading && last?.after_cursor) void read(last.after_cursor, "after"); },
  };
}
