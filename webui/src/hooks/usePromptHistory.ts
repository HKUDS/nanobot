import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useClient } from "@/providers/ClientProvider";
import { fetchPromptIndex, fetchWebuiThread } from "@/lib/api";
import { projectThreadEvents } from "@/lib/thread-event-projection";
import { historyContentSnapshot, projectWebuiThreadMessages } from "@/lib/thread-display-projection";
import { joinThreadFragments } from "@/lib/thread-page-fragments";
import { isModelCommandText } from "@/lib/format";
import { isSystemCommandTurnId } from "@/lib/nanobot-client";
import type { PromptIndex, UIMessage, WebuiThreadPersistedPayload } from "@/lib/types";
import { type PromptAnchor, userPromptAnchors } from "@/components/thread/promptNavigation";

interface HistoryPage {
  messages: UIMessage[];
  body: WebuiThreadPersistedPayload;
  details: Map<string, UIMessage[]>;
}

function expandDetails(messages: UIMessage[], details: ReadonlyMap<string, UIMessage[]>): UIMessage[] {
  return messages.flatMap((message) => {
    const rows = message.traceDetail && details.get(message.traceDetail.ref);
    return rows ? rows.map((row) => ({ ...row, activitySegmentId: message.activitySegmentId })) : [message];
  });
}

const HISTORY_PAGE_LIMIT = 3;

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
  /** Pending or failed page read; index errors have no page operation. */
  operation: "jump" | "older" | "newer" | null;
  loading: boolean;
  error: string | null;
  jump: (id: string) => void;
  older: () => void;
  newer: () => void;
  cancel: () => void;
  latest: () => void;
  retry: () => void;
  expandTraceDetail: (ref: string, rows: UIMessage[]) => void;
}

function projectHistoryWindow(pages: HistoryPage[]): NonNullable<PromptHistoryNavigation["window"]> {
  const messages: UIMessage[] = [];
  let boundary: number | null = null;
  for (let index = 0; index < pages.length; index++) {
    const page = pages[index];
    let body = page.body;
    let rows = page.messages;
    const range = body.page?.record_range;
    if (range) {
      let joined = joinThreadFragments([], body);
      const details = new Map(page.details);
      while (pages[index + 1]?.body.page?.record_range?.turn === range.turn) {
        const next = pages[++index];
        joined = joinThreadFragments(joined.pages, next.body);
        for (const [ref, detail] of next.details) details.set(ref, detail);
      }
      body = joined.body;
      rows = expandDetails(projectWebuiThreadMessages(projectThreadEvents(body.events)), details);
    }
    const eventIndex = body.fork_boundary_event_index;
    if (eventIndex !== undefined) boundary = messages.length + projectWebuiThreadMessages(projectThreadEvents(body.events.slice(0, eventIndex))).length;
    messages.push(...rows);
  }
  return { messages, userMessageOffset: pages[0]?.body.page?.user_message_offset ?? 0,
    hasMoreBefore: pages[0]?.body.page?.has_more_before === true,
    hasMoreAfter: pages.at(-1)?.body.page?.has_more_after === true,
    forkBoundaryMessageCount: boundary };
}

/** Browsing pages never replace the canonical latest page or live turn state. */
export function usePromptHistory(key: string | null, version: number, messages: UIMessage[]): PromptHistoryNavigation {
  const { client, getToken, webuiCapabilities } = useClient();
  const enabled = !!key && webuiCapabilities.includes("webui.prompt-navigation.v1");
  const [index, setIndex] = useState<{ key: string; prompts: PromptAnchor[] } | null>(null);
  const indexSnapshot = useRef<PromptIndex>();
  const [pages, setPages] = useState<HistoryPage[]>([]);
  const pagesRef = useRef(pages);
  pagesRef.current = pages;
  const [target, setTarget] = useState<PromptHistoryNavigation["target"]>(null);
  const [operation, setOperation] = useState<PromptHistoryNavigation["operation"]>(null);
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
    const inputIds = new Set<string>();
    const turns = new Map<string, PromptAnchor | null>();
    for (const prompt of index?.prompts ?? []) {
      ids.add(prompt.id);
      if (prompt.inputId) inputIds.add(prompt.inputId);
      if (prompt.turnId) turns.set(prompt.turnId, turns.has(prompt.turnId) ? null : prompt);
    }
    return { ids, inputIds, turns };
  }, [index]);
  const localCache = useRef<{ index: typeof index; users: UIMessage[]; responses: string; prompts: PromptAnchor[] }>();
  const prompts = useMemo(() => {
    if (!enabled) return userPromptAnchors(messages);
    if (!currentScope || index?.key !== key) return [];
    // Live rows can still have optimistic render ids after admission. Match the
    // host's unambiguous original transport id and content, not text alone.
    const users = messages.filter((message) => {
      if (message.role !== "user" || indexed.ids.has(message.id)
        || (message.inputId && indexed.inputIds.has(message.inputId))) return false;
      const admitted = message.turnId ? indexed.turns.get(message.turnId) : null;
      return !admitted || admitted.preview !== message.content.trim().slice(0, 320);
    });
    if (!users.length) return index.prompts;
    // Refresh consumed-input previews at response boundaries, not on every token.
    const responses = JSON.stringify(messages.filter((message) => message.responseInputIds !== undefined)
      .map((message) => [message.id, message.responseInputIds, message.isStreaming ? null : message.content.slice(0, 240)]));
    const cached = localCache.current;
    if (cached?.index === index && cached.responses === responses && users.length === cached.users.length
      && users.every((user, position) => user === cached.users[position])) return cached.prompts;
    const localIds = new Set(users.map((message) => message.id));
    const local = userPromptAnchors(messages).filter((prompt) => localIds.has(prompt.id));
    // Directory order is logical admission order. Unknown legacy times are zero,
    // not a reason to move an old prompt ahead of its preceding inputs.
    const merged = [...index.prompts, ...local].map((prompt, position) => ({ ...prompt, index: position }));
    localCache.current = { index, users, responses, prompts: merged };
    return merged;
  }, [currentScope, enabled, index, indexed, key, messages]);

  const expandTraceDetail = useCallback((ref: string, rows: UIMessage[]) => {
    setPages((current) => current.map((page) => {
      if (!page.messages.some((message) => message.traceDetail?.ref === ref)) return page;
      const details = new Map(page.details).set(ref, rows);
      return { ...page, messages: expandDetails(page.messages, details), details };
    }));
  }, []);

  const read = useCallback(async (cursor: string, direction: "before" | "after", id?: string, resume?: HistoryPage[]) => {
    // Boundary inputs can arrive before loading renders; only a new jump supersedes a read.
    if (!key || (!id && request.current)) return;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setOperation(id ? "jump" : direction === "before" ? "older" : "newer");
    setLoading(true);
    setError(null);
    let staged = resume ?? pagesRef.current;
    try {
      while (true) {
        const requestedCursor = cursor;
        const retryPages = staged;
        retry.current = () => { void read(requestedCursor, direction, id, retryPages); };
        const body = await fetchWebuiThread(getToken(), key, {
          [direction]: cursor, limit: 24, signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        if (!body) throw new Error("History is no longer available");
        const generation = body.page?.history_generation;
        const previousGeneration = staged[0]?.body.page?.history_generation;
        if (!id && generation && previousGeneration && generation !== previousGeneration) {
          throw new Error("History changed; select the message again");
        }
        const page = { body, messages: projectWebuiThreadMessages(projectThreadEvents(body.events)), details: new Map<string, UIMessage[]>() };
        if (id && !page.messages.some((message) => message.id === id)) {
          setRefresh((value) => value + 1);
          throw new Error("History changed; select the message again");
        }
        // Trace details can finish while this read is pending; preserve those visible updates.
        staged = staged.map((saved) => pagesRef.current.find((current) => current.body === saved.body) ?? saved);
        const expanded = id ? [page] : direction === "before" ? [page, ...staged] : [...staged, page];
        // Compare before eviction: a full window can gain content without growing.
        const ready = id || historyContentSnapshot(projectHistoryWindow(expanded).messages)
          !== historyContentSnapshot(projectHistoryWindow(staged).messages);
        const nextCursor = direction === "before" ? body.page?.before_cursor : body.page?.after_cursor;
        const more = direction === "before" ? body.page?.has_more_before : body.page?.has_more_after;
        if (!id && more && (!nextCursor || nextCursor === cursor)) throw new Error("History cursor did not advance");
        // At most three bounded server pages; intermediate pages do not complete the operation.
        staged = direction === "before" ? expanded.slice(0, HISTORY_PAGE_LIMIT) : expanded.slice(-HISTORY_PAGE_LIMIT);
        if (ready || !more) {
          // Reaching the end through bookkeeping must not evict the readable window.
          if (!ready) staged = pagesRef.current.map((saved, index, current) => {
            if (index !== (direction === "before" ? 0 : current.length - 1)) return saved;
            const boundary = direction === "before"
              ? { before_cursor: nextCursor ?? null, has_more_before: false }
              : { after_cursor: nextCursor ?? null, has_more_after: false };
            return { ...saved, body: { ...saved.body, page: { ...saved.body.page, ...boundary } } };
          });
          pagesRef.current = staged;
          setPages(staged);
          if (id) setTarget({ id, sequence: ++sequence.current });
          break;
        }
        cursor = nextCursor!;
      }
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
  const window = useMemo(() => currentScope && pages.length ? projectHistoryWindow(pages) : null,
    [currentScope, pages]);

  return { prompts, window, target: currentScope ? target : null, loading: currentScope && loading,
    operation: currentScope && (loading || error) ? operation : null,
    error: currentScope ? error ?? indexError : null, cancel, latest, expandTraceDetail,
    retry: () => error ? retry.current() : setRefresh((value) => value + 1),
    jump: (id) => {
      const prompt = prompts.find((item) => item.id === id);
      if (enabled && prompt?.cursor) void read(prompt.cursor, "after", id);
    },
    older: () => { if (first?.before_cursor) void read(first.before_cursor, "before"); },
    newer: () => { if (last?.after_cursor) void read(last.after_cursor, "after"); },
  };
}
