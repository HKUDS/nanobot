import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { useClient } from "@/providers/ClientProvider";
import { toMediaAttachment } from "@/lib/media";
import {
  mergeToolProgressEvents,
  mergeToolProgressTraceLines,
  normalizeToolProgressEvents,
  toolTraceLinesFromEvents,
} from "@/lib/tool-traces";
import { hasPendingAgentActivity } from "@/lib/activity-timeline";
import type { StreamError } from "@/lib/nanobot-client";
import {
  closeReasoningStream,
  filterCoveredFileEditToolEvents,
  finalizeStreamedTurn,
  findActiveAssistantPlaceholderIndex,
  findFileEditTraceIndex,
  findStreamingAssistantIndex,
  isReasoningOnlyPlaceholder,
  matchesTurn,
  mergeFileEdits,
  replaceMessageAt,
  stampLastAssistantCompletion,
  stripCoveredFileEditToolHintsFromMessages,
  turnFieldsFromEvent,
} from "@/lib/thread-event-projection";
import type { UIMessageTurnFields } from "@/lib/thread-event-projection";
import { formatQuotedUserMessage } from "@/lib/user-message-quote";
import { readLocalPreferences } from "@/lib/local-preferences";
import type {
  InboundEvent,
  OutboundCliAppMention,
  OutboundMcpPresetMention,
  OutboundMedia,
  SessionMention,
  GoalStateWsPayload,
  MessageDeliveryStatus,
  RecoveryState,
  UIMediaAttachment,
  UIMessage,
  WorkspaceScopePayload,
} from "@/lib/types";

interface StreamBuffer {
  /** ID of the assistant message currently receiving deltas (cleared when its segment closes). */
  messageId: string;
}

interface ActiveAssistantCursor {
  id: string;
  index: number;
}

type PendingStreamEvent =
  | { kind: "delta"; text: string; turn: UIMessageTurnFields; source?: UIMessage["source"] }
  | { kind: "reasoning"; text: string; turn: UIMessageTurnFields };

const BACKGROUND_STREAM_FLUSH_INTERVAL_MS = 1_000;

/**
 * Append a reasoning chunk to the last open reasoning stream in ``prev``.
 *
 * Lookup rule: reasoning can only extend the current reasoning placeholder.
 * Once ordinary answer text has appeared, the next reasoning chunk starts a
 * fresh activity surface so streamed output stays in arrival order while the
 * final answer remains the only visible answer bubble.
 */
function attachReasoningChunk(
  prev: UIMessage[],
  chunk: string,
  segments?: {
    ensure: () => string;
  },
  turn: UIMessageTurnFields = {},
): UIMessage[] {
  for (let i = prev.length - 1; i >= 0; i -= 1) {
    const candidate = prev[i];
    // A user turn is a hard boundary: reasoning after it belongs to the new
    // assistant turn, never to an earlier assistant reply.
    if (candidate.role === "user") break;
    // A trace row (e.g. Used tools) is also a phase boundary. Reasoning after
    // tools belongs to the next assistant iteration, not the assistant turn
    // that produced those tool calls.
    if (candidate.kind === "trace") break;
    if (candidate.role !== "assistant") continue;
    if (!matchesTurn(candidate, turn)) break;
    const activitySegmentId = candidate.activitySegmentId ?? segments?.ensure();
    const hasAnswer = candidate.content.length > 0;
    if (hasAnswer) break;
    // ``reasoning_end`` closes this row even though the assistant placeholder
    // stays streaming for the rest of the turn. The next reasoning stream must
    // get its own row when an intervening tool trace is delayed or unavailable.
    if (
      candidate.reasoningStreaming
      || (candidate.isStreaming && candidate.reasoning === undefined)
    ) {
      const merged: UIMessage = {
        ...candidate,
        reasoning: (candidate.reasoning ?? "") + chunk,
        reasoningStreaming: true,
        ...(activitySegmentId ? { activitySegmentId } : {}),
        ...turn,
      };
      return [...prev.slice(0, i), merged, ...prev.slice(i + 1)];
    }
    break;
  }
  const activitySegmentId = segments?.ensure();
  return [
    ...prev,
    {
      id: crypto.randomUUID(),
      role: "assistant",
      content: "",
      isStreaming: true,
      reasoning: chunk,
      reasoningStreaming: true,
      ...(activitySegmentId ? { activitySegmentId } : {}),
      ...turn,
      createdAt: Date.now(),
    },
  ];
}

function absorbCompleteAssistantMessage(
  prev: UIMessage[],
  message: Omit<UIMessage, "id" | "role" | "createdAt">,
): UIMessage[] {
  const last = prev[prev.length - 1];
  if (!last || !isReasoningOnlyPlaceholder(last) || !matchesTurn(last, message)) {
    return [
      ...prev,
      {
        id: crypto.randomUUID(),
        role: "assistant",
        createdAt: Date.now(),
        ...message,
      },
    ];
  }
  return [
    ...prev.slice(0, -1),
    {
      ...last,
      ...message,
      isStreaming: false,
      reasoningStreaming: false,
    },
  ];
}

/**
 * Subscribe to a chat by ID. Returns the in-memory message list for the chat,
 * a streaming flag, and a ``send`` function. Initial history must be seeded
 * separately (e.g. via ``fetchWebuiThread``) since the server only replays
 * live events.
 */
/** Payload passed to ``send`` when the user attaches one or more files.
 *
 * ``media`` is handed to the wire client verbatim; ``preview`` powers the
 * optimistic user bubble. Keeping the two separate lets the bubble re-use the
 * local data URL even after the server persists the file under a different
 * name. */
export interface SendAttachment {
  media: OutboundMedia;
  preview: UIMediaAttachment;
}

export interface SendOptions {
  cliApps?: OutboundCliAppMention[];
  mcpPresets?: OutboundMcpPresetMention[];
  sessionMentions?: SessionMention[];
  quotedContext?: string;
  workspaceScope?: WorkspaceScopePayload | null;
  sideChannel?: boolean;
  finalizeActiveTurn?: boolean;
  /** Append guidance to the running turn without detaching its active answer segment. */
  continueActiveTurn?: boolean;
}

export interface SubmittedTurn {
  turnId: string;
  userMessageId: string;
  sideChannel: boolean;
}

function eventTurnId(ev: InboundEvent): string | undefined {
  return "turn_id" in ev && typeof ev.turn_id === "string" ? ev.turn_id : undefined;
}

function transitionTurnDelivery(
  messages: UIMessage[],
  turnId: string,
  status: MessageDeliveryStatus,
): UIMessage[] {
  let changed = false;
  const next = messages.map((message) => {
    if (
      message.role !== "user"
      || message.turnId !== turnId
      || message.deliveryStatus === status
      || (status === "accepted" && message.deliveryStatus !== "sending")
    ) {
      return message;
    }
    changed = true;
    return { ...message, deliveryStatus: status };
  });
  return changed ? next : messages;
}

function appendProjectedSessionInput(
  messages: UIMessage[],
  event: Extract<InboundEvent, { event: "user_message" }>,
): UIMessage[] {
  const sessionMessage = event.provenance?.session_message;
  const messageId = sessionMessage?.message_id?.trim();
  if (!sessionMessage || !messageId) return messages;
  if (messages.some((message) => message.sessionMessage?.message_id === messageId)) return messages;

  const row: UIMessage = {
    id: `session-message:${messageId}`,
    role: "user",
    content: event.text,
    createdAt: typeof event.created_at_ms === "number"
      && Number.isFinite(event.created_at_ms)
      ? event.created_at_ms
      : Date.now(),
    sessionMessage,
    ...turnFieldsFromEvent(event, "user"),
  };
  return [...messages, row];
}

export function useNanobotStream(
  chatId: string | null,
  initialMessages: UIMessage[] = [],
  hasPendingToolCalls = false,
  onTurnEnd?: () => void,
): {
  messages: UIMessage[];
  /** Whether ``messages`` belongs to the current ``chatId`` after a session switch. */
  messagesReady: boolean;
  isStreaming: boolean;
  /** Unix epoch seconds when the current user turn started (WebSocket ``goal_status``). */
  runStartedAt: number | null;
  /** Latest sustained goal for this ``chatId`` (``goal_state`` WS events). */
  goalState: GoalStateWsPayload | undefined;
  recoveryState: RecoveryState | null;
  continueRecovery: () => Promise<void>;
  dismissRecovery: () => Promise<void>;
  send: (
    content: string,
    images?: SendAttachment[],
    options?: SendOptions,
  ) => SubmittedTurn | null;
  transcribeAudio: (dataUrl: string, options?: { durationMs?: number }) => Promise<string>;
  stop: () => void;
  /** Mark an accepted canonical snapshot as the definitive end of the active turn. */
  reconcileTurnComplete: () => void;
  setMessages: React.Dispatch<React.SetStateAction<UIMessage[]>>;
  /** Latest transport-level fault raised since the last ``dismissStreamError``.
   * ``null`` when there is nothing to show. */
  streamError: StreamError | null;
  /** Clear the current ``streamError`` (e.g. after the user dismisses the
   * notification or starts a fresh action). */
  dismissStreamError: () => void;
} {
  const { client } = useClient();
  const { t } = useTranslation();
  const initialRunStartedAt = chatId ? client.getRunStartedAt(chatId) : null;
  const [messages, setMessages] = useState<UIMessage[]>(initialMessages);
  const [messageOwnerChatId, setMessageOwnerChatId] = useState(chatId);
  /** If history ends in unfinished agent activity, keep the loading spinner alive. */
  const initialStreaming = hasPendingAgentActivity(initialMessages);
  const [isStreaming, setIsStreaming] = useState(
    initialStreaming || hasPendingToolCalls || initialRunStartedAt !== null,
  );
  /** Unix epoch seconds when the current user turn started; cleared on ``idle``. */
  const [runStartedAt, setRunStartedAt] = useState<number | null>(initialRunStartedAt);
  const [goalState, setGoalState] = useState<GoalStateWsPayload | undefined>(undefined);
  const [recoveryState, setRecoveryState] = useState<RecoveryState | null>(null);
  const [streamError, setStreamError] = useState<StreamError | null>(null);
  const buffer = useRef<StreamBuffer | null>(null);
  const activeAssistantRef = useRef<ActiveAssistantCursor | null>(null);
  const closedAssistantStreamIdsRef = useRef<Set<string>>(new Set());
  const activitySegmentRef = useRef<string | null>(null);
  const fileEditSegmentRef = useRef<string | null>(null);
  const activitySegmentCounterRef = useRef(0);
  const pendingStreamEventsRef = useRef<PendingStreamEvent[]>([]);
  const streamFrameRef = useRef<number | null>(null);
  const streamTimerRef = useRef<number | null>(null);
  const suppressStreamUntilTurnEndRef = useRef(false);
  const sideChannelTurnIdsRef = useRef<Set<string>>(new Set());

  const dismissStreamError = useCallback(() => setStreamError(null), []);

  const notifyInBackground = useCallback((body: string) => {
    if (
      typeof Notification === "undefined"
      || Notification.permission !== "granted"
      || document.visibilityState === "visible"
      || !readLocalPreferences().browserNotifications
    ) return;
    new Notification("nanobot", { body });
  }, []);

  const clearPendingStreamWork = useCallback(() => {
    if (streamFrameRef.current !== null) {
      window.cancelAnimationFrame(streamFrameRef.current);
      streamFrameRef.current = null;
    }
    if (streamTimerRef.current !== null) {
      window.clearTimeout(streamTimerRef.current);
      streamTimerRef.current = null;
    }
    pendingStreamEventsRef.current = [];
  }, []);

  const isSideChannelEvent = useCallback((ev: InboundEvent) => {
    const turnId = eventTurnId(ev);
    return turnId !== undefined && sideChannelTurnIdsRef.current.has(turnId);
  }, []);

  const createActivitySegmentId = useCallback((activate = true) => {
    activitySegmentCounterRef.current += 1;
    const id = `activity-${activitySegmentCounterRef.current}`;
    if (activate) activitySegmentRef.current = id;
    return id;
  }, []);

  const freshActivitySegmentId = useCallback(
    () => createActivitySegmentId(true),
    [createActivitySegmentId],
  );

  const detachedActivitySegmentId = useCallback(
    () => createActivitySegmentId(false),
    [createActivitySegmentId],
  );

  const ensureActivitySegmentId = useCallback(() => {
    if (activitySegmentRef.current) return activitySegmentRef.current;
    return freshActivitySegmentId();
  }, [freshActivitySegmentId]);

  const clearActivitySegment = useCallback(() => {
    activitySegmentRef.current = null;
    fileEditSegmentRef.current = null;
  }, []);

  const closeActiveAssistantStream = useCallback(() => {
    const closedStreamId = buffer.current?.messageId ?? activeAssistantRef.current?.id;
    if (closedStreamId) closedAssistantStreamIdsRef.current.add(closedStreamId);
    buffer.current = null;
    activeAssistantRef.current = null;
    return !!closedStreamId;
  }, []);

  const applyStreamError = useCallback((err: StreamError) => {
    // One multiplexed client serves every thread. A correlated send fault
    // belongs only to its target chat. An uncorrelated transport close can
    // still be shown in the mounted thread, but cannot roll back any turn.
    if (!chatId || (err.chatId && err.chatId !== chatId)) return;
    setStreamError(err);
    if (!err.turnId) return;

    const rejectedTurnId = err.turnId;
    pendingStreamEventsRef.current = pendingStreamEventsRef.current.filter(
      (event) => event.turn.turnId !== rejectedTurnId,
    );
    sideChannelTurnIdsRef.current.delete(rejectedTurnId);
    setMessages((prev) => {
      const rejectedRows = prev.filter((message) => message.turnId === rejectedTurnId);
      if (rejectedRows.length === 0) return prev;
      const rejectedIds = new Set(rejectedRows.map((message) => message.id));
      const rejectedSegments = new Set(
        rejectedRows
          .map((message) => message.activitySegmentId)
          .filter((segmentId): segmentId is string => typeof segmentId === "string"),
      );
      if (
        activeAssistantRef.current
        && rejectedIds.has(activeAssistantRef.current.id)
      ) {
        activeAssistantRef.current = null;
      }
      if (buffer.current && rejectedIds.has(buffer.current.messageId)) {
        buffer.current = null;
      }
      for (const id of rejectedIds) closedAssistantStreamIdsRef.current.delete(id);
      if (
        activitySegmentRef.current
        && rejectedSegments.has(activitySegmentRef.current)
      ) {
        activitySegmentRef.current = null;
      }
      if (
        fileEditSegmentRef.current
        && rejectedSegments.has(fileEditSegmentRef.current)
      ) {
        fileEditSegmentRef.current = null;
      }
      return prev.flatMap((message) => {
        if (message.turnId !== rejectedTurnId) return [message];
        if (message.role !== "user") return [];
        return [{
          ...message,
          deliveryStatus: "failed",
          deliveryErrorKind: err.kind,
        }];
      });
    });

    const remainingStartedAt = client.getRunStartedAt(chatId);
    const hasRemainingRun = (
      remainingStartedAt !== null
      || client.hasUnsettledRun(chatId)
    );
    setRunStartedAt(remainingStartedAt);
    setIsStreaming(hasRemainingRun);
    if (!hasRemainingRun) suppressStreamUntilTurnEndRef.current = false;
  }, [chatId, client]);

  useEffect(() => client.onError(applyStreamError), [applyStreamError, client]);

  const resolveActiveAssistantIndex = useCallback((
    prev: UIMessage[],
    turn: UIMessageTurnFields = {},
  ): number | null => {
    const cursor = activeAssistantRef.current;
    if (!cursor) return null;
    const indexed = prev[cursor.index];
    if (
      indexed?.id === cursor.id
      && indexed.role === "assistant"
      && indexed.kind !== "trace"
      && indexed.isStreaming
      && matchesTurn(indexed, turn)
    ) {
      return cursor.index;
    }
    const idx = prev.findIndex((m) => m.id === cursor.id);
    if (idx === -1) {
      activeAssistantRef.current = null;
      return null;
    }
    const found = prev[idx];
    if (
      found.role !== "assistant"
      || found.kind === "trace"
      || !found.isStreaming
      || !matchesTurn(found, turn)
    ) {
      activeAssistantRef.current = null;
      return null;
    }
    activeAssistantRef.current = { id: cursor.id, index: idx };
    return idx;
  }, []);

  const appendAnswerChunk = useCallback(
    (
      prev: UIMessage[],
      chunk: string,
      turn: UIMessageTurnFields = {},
      source?: UIMessage["source"],
    ): UIMessage[] => {
      let next = prev;
      let targetIndex = resolveActiveAssistantIndex(next, turn);

      if (targetIndex === null) {
        targetIndex = findActiveAssistantPlaceholderIndex(next, turn);
      }
      if (targetIndex === null) {
        targetIndex = findStreamingAssistantIndex(next, closedAssistantStreamIdsRef.current, turn);
      }
      if (targetIndex === null) {
        const id = crypto.randomUUID();
        next = [
          ...next,
          {
            id,
            role: "assistant",
            content: "",
            isStreaming: true,
            createdAt: Date.now(),
          },
        ];
        targetIndex = next.length - 1;
      }

      const target = next[targetIndex];
      const merged: UIMessage = {
        ...target,
        content: target.content + chunk,
        isStreaming: true,
        ...turn,
        ...(source ? { source } : {}),
      };
      closedAssistantStreamIdsRef.current.delete(merged.id);
      activeAssistantRef.current = { id: merged.id, index: targetIndex };
      buffer.current = { messageId: merged.id };
      return replaceMessageAt(next, targetIndex, merged);
    },
    [resolveActiveAssistantIndex],
  );

  const applyPendingStreamEvents = useCallback(
    (prev: UIMessage[], events: PendingStreamEvent[]): UIMessage[] => {
      let next = prev;
      for (const event of events) {
        if (event.kind === "delta") {
          next = appendAnswerChunk(next, event.text, event.turn, event.source);
        } else {
          if (closeActiveAssistantStream()) clearActivitySegment();
          next = attachReasoningChunk(
            next,
            event.text,
            { ensure: ensureActivitySegmentId },
            event.turn,
          );
        }
      }
      return next;
    },
    [appendAnswerChunk, clearActivitySegment, closeActiveAssistantStream, ensureActivitySegmentId],
  );

  const flushPendingStreamEvents = useCallback((options?: {
    closeAnswerSegment?: boolean;
    finalAnswerText?: string;
    turn?: UIMessageTurnFields;
    source?: UIMessage["source"];
  }) => {
    if (streamFrameRef.current !== null) {
      window.cancelAnimationFrame(streamFrameRef.current);
      streamFrameRef.current = null;
    }
    if (streamTimerRef.current !== null) {
      window.clearTimeout(streamTimerRef.current);
      streamTimerRef.current = null;
    }
    const events = pendingStreamEventsRef.current;
    const finalAnswerText = options?.finalAnswerText;
    const turn = options?.turn ?? {};
    const source = options?.source;
    if (events.length === 0 && finalAnswerText === undefined && source === undefined) {
      if (options?.closeAnswerSegment) closeActiveAssistantStream();
      return;
    }
    pendingStreamEventsRef.current = [];
    setMessages((prev) => {
      let next = events.length > 0 ? applyPendingStreamEvents(prev, events) : prev;
      if (finalAnswerText !== undefined) {
        const targetIndex =
          resolveActiveAssistantIndex(next, turn)
          ?? findStreamingAssistantIndex(next, closedAssistantStreamIdsRef.current, turn);
        if (targetIndex !== null) {
          const target = next[targetIndex];
          const merged = {
            ...target,
            content: finalAnswerText,
            isStreaming: true,
            ...turn,
            ...(source ? { source } : {}),
          };
          next = replaceMessageAt(next, targetIndex, merged);
          if (!options?.closeAnswerSegment) {
            closedAssistantStreamIdsRef.current.delete(merged.id);
            activeAssistantRef.current = { id: merged.id, index: targetIndex };
            buffer.current = { messageId: merged.id };
          }
        } else {
          const id = crypto.randomUUID();
          next = [
            ...next,
            {
              id,
              role: "assistant",
              content: finalAnswerText,
              isStreaming: true,
              ...turn,
              ...(source ? { source } : {}),
              createdAt: Date.now(),
            },
          ];
          if (options?.closeAnswerSegment) {
            closedAssistantStreamIdsRef.current.add(id);
          } else {
            activeAssistantRef.current = { id, index: next.length - 1 };
            buffer.current = { messageId: id };
          }
        }
      } else if (source) {
        const targetIndex =
          resolveActiveAssistantIndex(next, turn)
          ?? findStreamingAssistantIndex(next, closedAssistantStreamIdsRef.current, turn);
        if (targetIndex !== null) {
          const target = next[targetIndex];
          next = replaceMessageAt(next, targetIndex, {
            ...target,
            ...turn,
            source,
          });
        }
      }
      if (options?.closeAnswerSegment) closeActiveAssistantStream();
      return next;
    });
  }, [applyPendingStreamEvents, closeActiveAssistantStream, resolveActiveAssistantIndex]);

  const schedulePendingStreamFlush = useCallback(() => {
    if (streamFrameRef.current !== null || streamTimerRef.current !== null) return;
    if (document.visibilityState === "hidden") {
      streamTimerRef.current = window.setTimeout(() => {
        streamTimerRef.current = null;
        const events = pendingStreamEventsRef.current;
        if (events.length === 0) return;
        pendingStreamEventsRef.current = [];
        setMessages((prev) => applyPendingStreamEvents(prev, events));
      }, BACKGROUND_STREAM_FLUSH_INTERVAL_MS);
      return;
    }
    streamFrameRef.current = window.requestAnimationFrame(() => {
      streamFrameRef.current = null;
      const events = pendingStreamEventsRef.current;
      if (events.length === 0) return;
      pendingStreamEventsRef.current = [];
      setMessages((prev) => applyPendingStreamEvents(prev, events));
    });
  }, [applyPendingStreamEvents]);

  useEffect(() => {
    const flushOnReturn = () => {
      if (document.visibilityState !== "visible") return;
      if (pendingStreamEventsRef.current.length === 0) return;
      flushPendingStreamEvents();
    };
    document.addEventListener("visibilitychange", flushOnReturn);
    return () => document.removeEventListener("visibilitychange", flushOnReturn);
  }, [flushPendingStreamEvents]);

  // Reset local state when switching chats. Do not reset on every
  // ``initialMessages`` update: a brand-new chat can receive an empty/404
  // history response after the optimistic first message has already rendered.
  useEffect(() => {
    const restoredRunStartedAt = chatId ? client.getRunStartedAt(chatId) : null;
    setMessages(initialMessages);
    setMessageOwnerChatId(chatId);
    setIsStreaming(
      hasPendingAgentActivity(initialMessages)
      || hasPendingToolCalls
      || restoredRunStartedAt !== null,
    );
    setStreamError(null);
    setRunStartedAt(restoredRunStartedAt);
    setGoalState(chatId ? client.getGoalState(chatId) : undefined);
    setRecoveryState(null);
    buffer.current = null;
    activeAssistantRef.current = null;
    closedAssistantStreamIdsRef.current.clear();
    clearActivitySegment();
    clearPendingStreamWork();
    sideChannelTurnIdsRef.current.clear();
    suppressStreamUntilTurnEndRef.current = false;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatId, client, clearActivitySegment, clearPendingStreamWork]);

  useEffect(() => {
    if (hasPendingToolCalls) setIsStreaming(true);
  }, [hasPendingToolCalls]);

  useEffect(() => {
    if (!chatId) return;

    const handle = (ev: InboundEvent) => {
      if (ev.event === "error") {
        if (ev.detail === "message_too_big") {
          applyStreamError({
            kind: "message_too_big",
            chatId,
            turnId: ev.turn_id,
          });
        } else if (ev.detail === "workspace_scope_rejected") {
          applyStreamError({
            kind: "workspace_scope_rejected",
            reason: ev.reason,
            chatId,
            turnId: ev.turn_id,
          });
        } else if (ev.turn_id) {
          applyStreamError({
            kind: "turn_rejected",
            detail: ev.detail,
            reason: ev.reason,
            chatId,
            turnId: ev.turn_id,
          });
        }
        return;
      }
      const turnId = eventTurnId(ev);
      if (turnId) {
        setMessages((prev) => transitionTurnDelivery(prev, turnId, "accepted"));
      }
      if (ev.event === "message_accepted") return;
      if (ev.event === "user_message") {
        if (ev.provenance?.session_message) {
          flushPendingStreamEvents({ closeAnswerSegment: true });
          clearActivitySegment();
          setIsStreaming(true);
          setMessages((prev) => appendProjectedSessionInput(prev, ev));
          return;
        }
        setMessages((prev) => {
          if (ev.turn_id && prev.some((message) => (
            message.role === "user" && message.turnId === ev.turn_id
          ))) return prev;
          return [
            ...prev,
            {
              id: crypto.randomUUID(),
              role: "user",
              content: ev.text,
              ...(ev.turn_id ? { turnId: ev.turn_id } : {}),
              turnPhase: "user",
              turnSeq: 0,
              deliveryStatus: "accepted",
              createdAt: typeof ev.created_at_ms === "number"
                && Number.isFinite(ev.created_at_ms)
                ? ev.created_at_ms
                : Date.now(),
              ...(ev.media_urls?.length ? { media: ev.media_urls } : {}),
              ...(ev.cli_apps?.length ? { cliApps: ev.cli_apps } : {}),
              ...(ev.mcp_presets?.length ? { mcpPresets: ev.mcp_presets } : {}),
              ...(ev.session_mentions?.length
                ? { sessionMentions: ev.session_mentions }
                : {}),
            },
          ];
        });
        if (ev.active_turn_id || ev.starts_turn) {
          setIsStreaming(true);
          if (typeof ev.started_at === "number") setRunStartedAt(ev.started_at);
        }
        return;
      }
      const sideChannelEvent = isSideChannelEvent(ev);
      if (ev.event === "delta") {
        if (suppressStreamUntilTurnEndRef.current) return;
        const chunk = typeof ev.text === "string" ? ev.text : "";
        if (!chunk) return;
        clearActivitySegment();
        setIsStreaming(true);
        pendingStreamEventsRef.current.push({
          kind: "delta",
          text: chunk,
          turn: turnFieldsFromEvent(ev, "answer"),
          source: ev.source,
        });
        schedulePendingStreamFlush();
        return;
      }

      if (ev.event === "reasoning_delta") {
        if (suppressStreamUntilTurnEndRef.current) return;
        const chunk = ev.text;
        if (!chunk) return;
        if (fileEditSegmentRef.current) clearActivitySegment();
        setIsStreaming(true);
        pendingStreamEventsRef.current.push({
          kind: "reasoning",
          text: chunk,
          turn: turnFieldsFromEvent(ev, "reasoning"),
        });
        schedulePendingStreamFlush();
        return;
      }

      if (ev.event === "stream_end") {
        const turn = turnFieldsFromEvent(ev, "answer");
        const mergeNext = ev.resuming === true && ev.merge_next === true;
        flushPendingStreamEvents({
          closeAnswerSegment: !mergeNext,
          ...(typeof ev.text === "string" ? { finalAnswerText: ev.text } : {}),
          turn,
          source: ev.source,
        });
        if (suppressStreamUntilTurnEndRef.current) return;
        if (ev.resuming) {
          setIsStreaming(true);
          return;
        }
        // ``stream_end`` closes the current answer segment, not the turn.
        // Tools and follow-up model segments may still arrive before the
        // definitive ``turn_end`` event.
        setIsStreaming(true);
        return;
      }

      const shouldCloseAnswerBeforeEvent =
        ev.event === "file_edit"
        || (
          ev.event === "message"
          && (ev.kind === "tool_hint" || ev.kind === "progress")
        );
      flushPendingStreamEvents({ closeAnswerSegment: shouldCloseAnswerBeforeEvent });

      if (ev.event === "reasoning_end") {
        if (suppressStreamUntilTurnEndRef.current) return;
        setMessages((prev) => closeReasoningStream(prev, Date.now()));
        return;
      }

      if (ev.event === "goal_state") {
        setGoalState(ev.goal_state);
        return;
      }

      if (ev.event === "goal_status") {
        if (ev.status === "running" && typeof ev.started_at === "number") {
          setRunStartedAt(ev.started_at);
          setIsStreaming(true);
        } else {
          setRunStartedAt(null);
          setIsStreaming(false);
        }
        return;
      }

      if (ev.event === "turn_end") {
        if ("goal_state" in ev && ev.goal_state != null && typeof ev.goal_state === "object") {
          setGoalState(ev.goal_state);
        }
        setRunStartedAt(null);
        // Definitive signal that the turn is fully complete, so stop the
        // loading indicator immediately.
        setIsStreaming(false);
        const completedAt = Date.now();
        setMessages((prev) => {
          let finalized = prev.map((m) => (m.isStreaming ? { ...m, isStreaming: false } : m));
          const latencyMs =
            typeof ev.latency_ms === "number" && ev.latency_ms >= 0
              ? Math.round(ev.latency_ms)
              : undefined;
          finalized = stampLastAssistantCompletion(
            finalized,
            {
              ...(latencyMs !== undefined ? { latencyMs } : {}),
              ...(ev.usage ? { usage: ev.usage } : {}),
              ...(typeof ev.context_window_tokens === "number"
                ? { contextWindowTokens: ev.context_window_tokens }
                : {}),
              completedAt,
            },
            ev.turn_id,
          );
          buffer.current = null;
          activeAssistantRef.current = null;
          clearActivitySegment();
          closedAssistantStreamIdsRef.current.clear();
          return finalized;
        });
        suppressStreamUntilTurnEndRef.current = false;
        notifyInBackground(t("recovery.completed", { defaultValue: "Task completed" }));
        onTurnEnd?.();
        return;
      }

      if (ev.event === "recovery_state") {
        const next: RecoveryState = {
          status: ev.status,
          recovery_id: ev.recovery_id,
          ...(ev.reason ? { reason: ev.reason } : {}),
          ...(typeof ev.attempts === "number" ? { attempts: ev.attempts } : {}),
          ...(typeof ev.can_continue === "boolean"
            ? { can_continue: ev.can_continue }
            : {}),
        };
        setRecoveryState(next);
        if (ev.status === "resuming") {
          setRunStartedAt((current) => current ?? Date.now() / 1000);
          setIsStreaming(true);
        }
        if (
          ev.status === "awaiting_user"
          || ev.status === "recovered"
          || ev.status === "failed"
        ) {
          // Recovery is an explicit boundary. The interrupted turn is no
          // longer running, so do not let the stale start time keep the
          // activity clock (or composer stop state) alive underneath the
          // recovery notice.
          setRunStartedAt(null);
          setIsStreaming(false);
          client.finishRunLocally(chatId);
          clearPendingStreamWork();
          closeActiveAssistantStream();
          clearActivitySegment();
          if (ev.status !== "recovered") {
            notifyInBackground(
              ev.status === "failed"
                ? t("recovery.failed", { defaultValue: "Task recovery failed" })
                : t("recovery.interrupted", { defaultValue: "Task interrupted" }),
            );
          }
        }
        return;
      }

      if (ev.event === "attached") {
        setRecoveryState(ev.recovery_state ?? null);
        if (ev.recovery_state?.status === "resuming") {
          setRunStartedAt((current) => current ?? Date.now() / 1000);
          setIsStreaming(true);
        } else if (
          ev.recovery_state?.status === "awaiting_user"
          || ev.recovery_state?.status === "failed"
        ) {
          setRunStartedAt(null);
          setIsStreaming(false);
          client.finishRunLocally(chatId);
          clearPendingStreamWork();
          closeActiveAssistantStream();
          clearActivitySegment();
        }
        return;
      }

      if (ev.event === "message") {
        if (
          suppressStreamUntilTurnEndRef.current &&
          (ev.kind === "tool_hint" || ev.kind === "progress" || ev.kind === "reasoning")
        ) {
          return;
        }
        // Back-compat: a legacy ``kind: "reasoning"`` message (no streaming
        // partner) is treated as one complete delta + immediate end so the
        // bubble renders identically to the streaming path.
        if (ev.kind === "reasoning") {
          const line = ev.text;
          if (!line) return;
          if (fileEditSegmentRef.current) clearActivitySegment();
          setMessages((prev) => closeReasoningStream(
            attachReasoningChunk(
              prev,
              line,
              { ensure: ensureActivitySegmentId },
              turnFieldsFromEvent(ev, "reasoning"),
            ),
            Date.now(),
          ));
          return;
        }
        // Intermediate agent breadcrumbs (tool-call hints, raw progress).
        // Attach them to the last trace row if it was the last emitted item
        // so a sequence of calls collapses into one compact trace group.
        if (ev.kind === "tool_hint" || ev.kind === "progress") {
          const structuredEvents = normalizeToolProgressEvents(ev.tool_events);
          const turn = turnFieldsFromEvent(ev, "activity");
          setMessages((prev) => {
            const segmentId = ensureActivitySegmentId();
            const base = prev;
            const visibleStructuredEvents = filterCoveredFileEditToolEvents(base, structuredEvents);
            const structuredLines = toolTraceLinesFromEvents(visibleStructuredEvents);
            const lines = structuredLines.length > 0
              ? structuredLines
              : structuredEvents.length > 0
                ? []
                : ev.text
                  ? [ev.text]
                  : [];
            if (lines.length === 0) return base;
            const last = base[base.length - 1];
            if (
              last
              && last.kind === "trace"
              && !last.isStreaming
              && (!last.activitySegmentId || last.activitySegmentId === segmentId)
            ) {
              const previousTraces = last.traces?.length
                ? last.traces
                : last.content
                  ? [last.content]
                  : [];
              const mergedEvents = visibleStructuredEvents.length > 0
                ? mergeToolProgressEvents(last.toolEvents, visibleStructuredEvents)
                : last.toolEvents;
              const mergedLines = visibleStructuredEvents.length > 0
                ? mergeToolProgressTraceLines(
                    previousTraces,
                    last.toolEvents,
                    structuredLines,
                    visibleStructuredEvents,
                  )
                : null;
              const merged: UIMessage = {
                ...last,
                traces: mergedLines ?? [...previousTraces, ...lines],
                content: mergedLines
                  ? mergedLines[mergedLines.length - 1]
                  : lines[lines.length - 1],
                toolEvents: mergedEvents,
                activitySegmentId: last.activitySegmentId ?? segmentId,
                ...turn,
              };
              return [...base.slice(0, -1), merged];
            }
            return [
              ...base,
              {
                id: crypto.randomUUID(),
                role: "tool",
                kind: "trace",
                content: lines[lines.length - 1],
                traces: lines,
                ...(visibleStructuredEvents.length ? { toolEvents: visibleStructuredEvents } : {}),
                activitySegmentId: segmentId,
                ...turn,
                createdAt: Date.now(),
              },
            ];
          });
          return;
        }

        const media = ev.media_urls?.length
          ? ev.media_urls.map((m) => toMediaAttachment(m))
          : ev.media?.map((url) => toMediaAttachment({ url }));
        const hasMedia = !!media && media.length > 0;
        if (sideChannelEvent) {
          setMessages((prev) => absorbCompleteAssistantMessage(prev, {
            content: ev.text,
            ...(hasMedia ? { media } : {}),
            ...(ev.source ? { source: ev.source } : {}),
            ...turnFieldsFromEvent(ev, "answer"),
          }));
          if (typeof ev.turn_id === "string") sideChannelTurnIdsRef.current.delete(ev.turn_id);
          return;
        }

        // A complete (non-streamed) assistant message. If a stream was in
        // flight, drop the placeholder so we don't render the text twice.
        // ``turn_end`` is the turn boundary. ``stream_end`` only closes the
        // current text segment so a following tool/reasoning segment remains
        // part of the same live activity surface.
        clearActivitySegment();
        setMessages((prev) => {
          const activeId = buffer.current?.messageId;
          buffer.current = null;
          activeAssistantRef.current = null;
          const filtered = activeId ? prev.filter((m) => m.id !== activeId) : prev;
          const content = ev.text;
          const lat =
            typeof ev.latency_ms === "number" && ev.latency_ms >= 0
              ? Math.round(ev.latency_ms)
              : undefined;
          return absorbCompleteAssistantMessage(filtered, {
            content,
            ...(hasMedia ? { media } : {}),
            ...(lat !== undefined ? { latencyMs: lat } : {}),
            ...(ev.source ? { source: ev.source } : {}),
            ...turnFieldsFromEvent(ev, "answer"),
          });
        });
        if (hasMedia) {
          suppressStreamUntilTurnEndRef.current = true;
        }
        return;
      }
      if (ev.event === "file_edit") {
        const edits = Array.isArray(ev.edits) ? ev.edits : [];
        if (edits.length === 0) return;
        const normalized = mergeFileEdits(undefined, edits);
        if (normalized.length === 0) return;
        const turn = turnFieldsFromEvent(ev, "activity");
        const opensFileEditPhase = normalized.some(
          (edit) => edit.status === "editing" || edit.phase === "start",
        );
        let eventSegmentId = fileEditSegmentRef.current;
        if (!eventSegmentId && opensFileEditPhase) {
          eventSegmentId = detachedActivitySegmentId();
          fileEditSegmentRef.current = eventSegmentId;
        }
        setMessages((prev) => {
          let segmentId = eventSegmentId;
          const base = stripCoveredFileEditToolHintsFromMessages(prev, normalized, turn);
          const targetIndex = findFileEditTraceIndex(base, segmentId, normalized);
          if (targetIndex !== null) {
            const target = base[targetIndex];
            segmentId = target.activitySegmentId ?? segmentId ?? detachedActivitySegmentId();
            if (opensFileEditPhase) fileEditSegmentRef.current = segmentId;
            const merged: UIMessage = {
              ...target,
              fileEdits: mergeFileEdits(target.fileEdits, normalized),
              activitySegmentId: segmentId,
              ...turn,
            };
            return replaceMessageAt(base, targetIndex, merged);
          }
          segmentId = segmentId ?? detachedActivitySegmentId();
          if (opensFileEditPhase) fileEditSegmentRef.current = segmentId;
          return [
            ...base,
            {
              id: crypto.randomUUID(),
              role: "tool",
              kind: "trace",
              content: "",
              traces: [],
              fileEdits: normalized,
              activitySegmentId: segmentId,
              ...turn,
              createdAt: Date.now(),
            },
          ];
        });
        return;
      }
    };

    const unsub = client.onChat(chatId, handle);
    return () => {
      unsub();
      buffer.current = null;
      activeAssistantRef.current = null;
      closedAssistantStreamIdsRef.current.clear();
      clearActivitySegment();
      clearPendingStreamWork();
    };
  }, [
    applyStreamError,
    chatId,
    closeActiveAssistantStream,
    client,
    clearActivitySegment,
    clearPendingStreamWork,
    detachedActivitySegmentId,
    ensureActivitySegmentId,
    flushPendingStreamEvents,
    isSideChannelEvent,
    notifyInBackground,
    onTurnEnd,
    schedulePendingStreamFlush,
    t,
  ]);

  const send = useCallback(
    (content: string, images?: SendAttachment[], options?: SendOptions) => {
      if (!chatId) return null;
      const hasAttachments = !!images && images.length > 0;
      // Text is optional when files are attached — the agent will still see
      // them via ``media`` paths.
      if (!hasAttachments && !content.trim()) return null;

      const sideChannel = options?.sideChannel === true;
      const finalizeActiveTurn = options?.finalizeActiveTurn === true;
      const continueActiveTurn = options?.continueActiveTurn === true;
      const outboundContent = options?.quotedContext
        ? formatQuotedUserMessage(content, options.quotedContext)
        : content;
      flushPendingStreamEvents();
      if (finalizeActiveTurn) {
        setIsStreaming(false);
      }
      const turnId = crypto.randomUUID();
      const userMessageId = crypto.randomUUID();
      if (sideChannel) sideChannelTurnIdsRef.current.add(turnId);
      const previews = hasAttachments ? images!.map((i) => i.preview) : undefined;
      setMessages((prev) => {
        if ((!sideChannel && !continueActiveTurn) || finalizeActiveTurn) {
          buffer.current = null;
          activeAssistantRef.current = null;
          closedAssistantStreamIdsRef.current.clear();
          clearActivitySegment();
          suppressStreamUntilTurnEndRef.current = false;
        } else if (continueActiveTurn) {
          // Guidance belongs to the active backend turn. Preserve the answer
          // cursor so its resuming stream_end can finalize the text already
          // shown before the new user row, while starting fresh activity after it.
          clearActivitySegment();
        }
        const base = finalizeActiveTurn ? finalizeStreamedTurn(prev) : prev;
        return [
          ...base,
          {
            id: userMessageId,
            role: "user",
            content: outboundContent,
            turnId,
            turnPhase: "user",
            turnSeq: 0,
            deliveryStatus: "sending",
            createdAt: Date.now(),
            ...(previews ? { media: previews } : {}),
            ...(options?.cliApps?.length ? { cliApps: options.cliApps } : {}),
            ...(options?.mcpPresets?.length ? { mcpPresets: options.mcpPresets } : {}),
            ...(options?.sessionMentions?.length
              ? { sessionMentions: options.sessionMentions }
              : {}),
          },
        ];
      });
      if (!sideChannel) setIsStreaming(true);
      const wireMedia = hasAttachments ? images!.map((i) => i.media) : undefined;
      const clientOptions = {
        ...options,
        turnId,
        ...((sideChannel || continueActiveTurn) ? { startsNewRun: false } : {}),
      };
      delete clientOptions.quotedContext;
      delete clientOptions.sideChannel;
      delete clientOptions.finalizeActiveTurn;
      delete clientOptions.continueActiveTurn;
      client.sendMessage(chatId, outboundContent, wireMedia, clientOptions);
      return { turnId, userMessageId, sideChannel };
    },
    [chatId, clearActivitySegment, client, flushPendingStreamEvents],
  );

  const stop = useCallback(() => {
    if (!chatId) return;
    flushPendingStreamEvents();
    setIsStreaming(false);
    setMessages((prev) => {
      buffer.current = null;
      activeAssistantRef.current = null;
      closedAssistantStreamIdsRef.current.clear();
      clearActivitySegment();
      return prev.map((m) => (m.isStreaming ? { ...m, isStreaming: false } : m));
    });
    suppressStreamUntilTurnEndRef.current = false;
    setRunStartedAt(null);
    client.finishRunLocally(chatId);
    client.sendMessage(chatId, "/stop");
  }, [chatId, clearActivitySegment, client, flushPendingStreamEvents]);

  const reconcileTurnComplete = useCallback(() => {
    clearPendingStreamWork();
    buffer.current = null;
    activeAssistantRef.current = null;
    closedAssistantStreamIdsRef.current.clear();
    clearActivitySegment();
    suppressStreamUntilTurnEndRef.current = false;
    setRunStartedAt(null);
    setIsStreaming(false);
  }, [clearActivitySegment, clearPendingStreamWork]);

  const transcribeAudio = useCallback(
    (dataUrl: string, options?: { durationMs?: number }) =>
      client.transcribeAudio(dataUrl, options),
    [client],
  );

  const recoveryAction = useCallback(async (action: "continue" | "dismiss") => {
    if (!chatId || !recoveryState) return;
    await client.requestMutation(`recovery.${action}`, {
      chat_id: chatId,
      recovery_id: recoveryState.recovery_id,
    });
  }, [chatId, client, recoveryState]);

  const continueRecovery = useCallback(
    () => recoveryAction("continue"),
    [recoveryAction],
  );
  const dismissRecovery = useCallback(
    () => recoveryAction("dismiss"),
    [recoveryAction],
  );

  return {
    messages,
    messagesReady: messageOwnerChatId === chatId,
    isStreaming,
    runStartedAt,
    goalState,
    recoveryState,
    continueRecovery,
    dismissRecovery,
    send,
    transcribeAudio,
    stop,
    reconcileTurnComplete,
    setMessages,
    streamError,
    dismissStreamError,
  };
}
