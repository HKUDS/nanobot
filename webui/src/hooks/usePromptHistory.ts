import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useClient } from "@/providers/ClientProvider";
import { fetchPromptIndex, fetchWebuiThread } from "@/lib/api";
import { projectThreadEvents } from "@/lib/thread-event-projection";
import { historyContentSnapshot, projectWebuiThreadMessages } from "@/lib/thread-display-projection";
import { joinThreadFragments } from "@/lib/thread-page-fragments";
import { isModelCommandText } from "@/lib/format";
import { isSystemCommandTurnId } from "@/lib/nanobot-client";
import type { PromptIndex, ThreadProjectionEvent, UIMessage, WebuiThreadPersistedPayload } from "@/lib/types";
import { type PromptAnchor, userPromptAnchors } from "@/components/thread/promptNavigation";

interface HistoryPage {
  messages: UIMessage[];
  body: WebuiThreadPersistedPayload;
  details: Map<string, UIMessage[]>;
  /** One terminal record per raw turn, retained when its page leaves the bounded cache. */
  completion?: Extract<ThreadProjectionEvent, { event: "turn_end" }>;
  /** A crossed marker can precede all visible rows until an older page arrives. */
  forkBoundaryBefore?: boolean;
}

function projectionBody(page: HistoryPage): WebuiThreadPersistedPayload {
  return page.forkBoundaryBefore ? { ...page.body, fork_boundary_event_index: 0 } : page.body;
}

function retainFragmentCompletion(pages: HistoryPage[], page: HistoryPage): HistoryPage[] {
  const turn = page.body.page?.record_range?.turn;
  if (turn === undefined || !page.completion) return pages;
  return pages.map((saved) => saved.body.page?.record_range?.turn === turn && saved.completion !== page.completion
    ? { ...saved, completion: page.completion } : saved);
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
    let body = projectionBody(page);
    let rows = page.messages;
    const range = body.page?.record_range;
    if (range) {
      let joined = joinThreadFragments([], body);
      const details = new Map(page.details);
      let completion = page.completion;
      while (pages[index + 1]?.body.page?.record_range?.turn === range.turn) {
        const next = pages[++index];
        joined = joinThreadFragments(joined.pages, projectionBody(next));
        completion = next.completion ?? completion;
        for (const [ref, detail] of next.details) details.set(ref, detail);
      }
      body = joined.body;
      // Completion is data, not a content-ready signal. Replay it through the same
      // reducer even when intervening telemetry or the terminal page was evicted.
      const events = completion && !body.events.some((event) => event.event === "turn_end")
        ? [...body.events, completion] : body.events;
      rows = expandDetails(projectWebuiThreadMessages(projectThreadEvents(events)), details);
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
  const publishPages = useCallback((next: HistoryPage[]) => {
    // Reads and detail expansion share the latest window even within one React batch.
    pagesRef.current = next;
    setPages(next);
  }, []);
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
    publishPages([]);
  }, [cancel, publishPages]);

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
    publishPages(pagesRef.current.map((page) => {
      if (!page.messages.some((message) => message.traceDetail?.ref === ref)) return page;
      const details = new Map(page.details).set(ref, rows);
      return { ...page, messages: expandDetails(page.messages, details), details };
    }));
  }, [publishPages]);

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
        const turn = body.page?.record_range?.turn;
        const page: HistoryPage = { body, messages: projectWebuiThreadMessages(projectThreadEvents(body.events)), details: new Map(),
          completion: body.events.find((event) => event.event === "turn_end")
            ?? (!id && turn !== undefined ? staged.find((saved) => saved.body.page?.record_range?.turn === turn)?.completion : undefined) };
        if (id && !page.messages.some((message) => message.id === id)) {
          setRefresh((value) => value + 1);
          throw new Error("History changed; select the message again");
        }
        // Trace details can finish while this read is pending; preserve those visible updates.
        staged = staged.map((saved) => pagesRef.current.find((current) => current.body === saved.body) ?? saved);
        if (!id && page.completion) {
          staged = retainFragmentCompletion(staged, page);
          const retained = retainFragmentCompletion(pagesRef.current, page);
          if (retained.some((saved, index) => saved !== pagesRef.current[index])) {
            publishPages(retained);
          }
        }
        // Only fragments need the staged raw context. Self-contained pages extend
        // the readable window, not the bookkeeping pages traversed on the way here.
        const source = body.page?.record_range ? staged : pagesRef.current;
        const expanded = id ? [page] : direction === "before" ? [page, ...source] : [...source, page];
        // Compare before eviction: a full window can gain content without growing.
        const previous = projectHistoryWindow(source);
        const prepared = projectHistoryWindow(expanded);
        const ready = id || historyContentSnapshot(prepared.messages, prepared.forkBoundaryMessageCount)
          !== historyContentSnapshot(previous.messages, previous.forkBoundaryMessageCount);
        const nextCursor = direction === "before" ? body.page?.before_cursor : body.page?.after_cursor;
        const more = direction === "before" ? body.page?.has_more_before : body.page?.has_more_after;
        if (!id && more && (!nextCursor || nextCursor === cursor)) throw new Error("History cursor did not advance");
        if (!ready && direction === "before" && body.fork_boundary_event_index !== undefined) {
          // Admit the crossed boundary without ending a pull that still has no
          // visible content before it. It must survive discarded staging pages.
          publishPages(pagesRef.current.map((saved, index) => index === 0 ? { ...saved, forkBoundaryBefore: true } : saved));
        }
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
          publishPages(staged);
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
  }, [getToken, key, publishPages]);

  const first = pages[0]?.body.page;
  const last = pages[pages.length - 1]?.body.page;
  const window = useMemo(() => currentScope && pages.length ? projectHistoryWindow(pages) : null,
    [currentScope, pages]);
  const readBoundary = (direction: "before" | "after") => {
    if (error && operation === (direction === "before" ? "older" : "newer")) {
      retry.current();
      return;
    }
    const cursor = direction === "before" ? first?.before_cursor : last?.after_cursor;
    if (cursor) void read(cursor, direction);
  };

  return { prompts, window, target: currentScope ? target : null, loading: currentScope && loading,
    operation: currentScope && (loading || error) ? operation : null,
    error: currentScope ? error ?? indexError : null, cancel, latest, expandTraceDetail,
    retry: () => error ? retry.current() : setRefresh((value) => value + 1),
    jump: (id) => {
      const prompt = prompts.find((item) => item.id === id);
      if (enabled && prompt?.cursor) void read(prompt.cursor, "after", id);
    },
    older: () => readBoundary("before"),
    newer: () => readBoundary("after"),
  };
}
