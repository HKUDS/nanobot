import { acceptsCompactionPhase } from "../../../packages/client-events/notifications";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useThreadVisibility } from "@/hooks/useThreadVisibility";

import { useClient } from "@/providers/ClientProvider";
import { resolveModelRequestFailureCopy } from "@/lib/model-request-failure";
import { hasPendingAgentActivity } from "@/lib/activity-timeline";
import type { StreamError } from "@/lib/nanobot-client";
import {
  clearThreadProjectionActivity,
  closeThreadProjectionAnswer,
  createThreadProjectionState,
  finalizeStreamedTurn,
  projectThreadEvent,
  resetThreadProjectionCursor,
  turnFieldsFromEvent,
} from "@/lib/thread-event-projection";
import type {
  ThreadProjectionEvent,
  ThreadProjectionState,
  UIMessageTurnFields,
} from "@/lib/thread-event-projection";
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
  RetryStatus,
  UIMediaAttachment,
  UIMessage,
  WorkspaceScopePayload,
} from "@/lib/types";

type PendingStreamEvent =
  | { kind: "delta"; text: string; turn: UIMessageTurnFields; source?: UIMessage["source"]; responseSources?: UIMessage["responseSources"] }
  | { kind: "reasoning"; text: string; turn: UIMessageTurnFields };

const BACKGROUND_STREAM_FLUSH_INTERVAL_MS = 1_000;
// Markdown and layout work must leave room for input between visible updates.
const VISIBLE_STREAM_FLUSH_INTERVAL_MS = 50;

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
  intent?: "create_automation";
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
  onStreamDetach?: (messages: UIMessage[]) => void,
): {
  messages: UIMessage[];
  /** Whether ``messages`` belongs to the current ``chatId`` after a session switch. */
  messagesReady: boolean;
  isStreaming: boolean;
  /** Unix epoch seconds when the current user turn started (WebSocket ``goal_status``). */
  runStartedAt: number | null;
  /** Transient model retry state for the active turn. */
  retryStatus: RetryStatus | null;
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
  const threadVisible = useThreadVisibility();
  const threadVisibleRef = useRef(threadVisible);
  threadVisibleRef.current = threadVisible;
  const { t } = useTranslation();
  const initialRunStartedAt = chatId ? client.getRunStartedAt(chatId) : null;
  const [messages, setRenderedMessages] = useState<UIMessage[]>(initialMessages);
  const messagesRef = useRef(messages);
  // Keep received state ahead of React's batched render: navigation can unmount
  // this hook after a stream flush but before the queued render commits.
  const setMessages = useCallback<React.Dispatch<React.SetStateAction<UIMessage[]>>>((update) => {
    const next = typeof update === "function" ? update(messagesRef.current) : update;
    messagesRef.current = next;
    setRenderedMessages(next);
  }, []);
  const [messageOwnerChatId, setMessageOwnerChatId] = useState(chatId);
  /** If history ends in unfinished agent activity, keep the loading spinner alive. */
  const initialStreaming = hasPendingAgentActivity(initialMessages);
  const [isStreaming, setIsStreaming] = useState(
    initialStreaming || hasPendingToolCalls || initialRunStartedAt !== null,
  );
  /** Unix epoch seconds when the current user turn started; cleared on ``idle``. */
  const [runStartedAt, setRunStartedAt] = useState<number | null>(initialRunStartedAt);
  const [retryStatus, setRetryStatus] = useState<RetryStatus | null>(null);
  const [goalState, setGoalState] = useState<GoalStateWsPayload | undefined>(undefined);
  const [recoveryState, setRecoveryState] = useState<RecoveryState | null>(null);
  const [streamError, setStreamError] = useState<StreamError | null>(null);
  const projectionRef = useRef<ThreadProjectionState>(
    createThreadProjectionState(initialMessages),
  );
  const pendingStreamEventsRef = useRef<PendingStreamEvent[]>([]);
  const streamFrameRef = useRef<number | null>(null);
  const streamTimerRef = useRef<number | null>(null);
  const lastStreamFlushRef = useRef(0);
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
    lastStreamFlushRef.current = 0;
  }, []);

  const isSideChannelEvent = useCallback((ev: InboundEvent) => {
    const turnId = eventTurnId(ev);
    return turnId !== undefined && sideChannelTurnIdsRef.current.has(turnId);
  }, []);

  const clearActivitySegment = useCallback(() => {
    projectionRef.current = clearThreadProjectionActivity(projectionRef.current);
  }, []);

  const closeActiveAssistantStream = useCallback(() => {
    const hadActiveAssistant = projectionRef.current.activeAssistantId !== null;
    projectionRef.current = closeThreadProjectionAnswer(projectionRef.current);
    return hadActiveAssistant;
  }, []);

  const applyStreamError = useCallback((err: StreamError) => {
    // One multiplexed client serves every thread. A correlated send fault
    // belongs only to its target chat. An uncorrelated transport close can
    // still be shown in the mounted thread, but cannot roll back any turn.
    if (!chatId || (err.chatId && err.chatId !== chatId)) return;
    setStreamError(err);
    if (err.kind === "model_request_failed") return;
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
      const projection = projectionRef.current;
      const closedAssistantIds = new Set(projection.closedAssistantIds);
      for (const id of rejectedIds) closedAssistantIds.delete(id);
      const nextMessages = prev.flatMap<UIMessage>((message) => {
        if (message.turnId !== rejectedTurnId) return [message];
        if (message.role !== "user") return [];
        return [{
          ...message,
          deliveryStatus: "failed" as const,
          deliveryErrorKind: err.kind,
        }];
      });
      projectionRef.current = {
        ...projection,
        messages: nextMessages,
        activeAssistantId: projection.activeAssistantId
          && rejectedIds.has(projection.activeAssistantId)
          ? null
          : projection.activeAssistantId,
        closedAssistantIds,
        activitySegmentId: projection.activitySegmentId
          && rejectedSegments.has(projection.activitySegmentId)
          ? null
          : projection.activitySegmentId,
        fileEditSegmentId: projection.fileEditSegmentId
          && rejectedSegments.has(projection.fileEditSegmentId)
          ? null
          : projection.fileEditSegmentId,
      };
      return nextMessages;
    });

    const remainingStartedAt = client.getRunStartedAt(chatId);
    const hasRemainingRun = (
      remainingStartedAt !== null
      || client.hasUnsettledRun(chatId)
    );
    setRunStartedAt(remainingStartedAt);
    setIsStreaming(hasRemainingRun);
    if (!hasRemainingRun) {
      projectionRef.current = {
        ...projectionRef.current,
        suppressUntilTurnEnd: false,
      };
    }
  }, [chatId, client, setMessages]);

  useEffect(() => client.onError(applyStreamError), [applyStreamError, client]);

  const applyPendingStreamEvents = useCallback(
    (prev: UIMessage[], events: PendingStreamEvent[]): UIMessage[] => {
      let projection = { ...projectionRef.current, messages: prev };
      for (let index = 0; index < events.length; index++) {
        const event = events[index];
        const chunks = [event.text];
        let turn = event.turn;
        while (index + 1 < events.length) {
          const nextEvent = events[index + 1];
          if (nextEvent.kind !== event.kind
            || nextEvent.turn.turnId !== event.turn.turnId
            || nextEvent.turn.turnPhase !== event.turn.turnPhase
            || (nextEvent.kind === "delta" && event.kind === "delta"
              && (nextEvent.source !== event.source
                || JSON.stringify(nextEvent.responseSources) !== JSON.stringify(event.responseSources)))) break;
          chunks.push(nextEvent.text);
          turn = { ...turn, ...nextEvent.turn };
          index++;
        }
        const text = chunks.join("");
        const projectedEvent: ThreadProjectionEvent = event.kind === "delta"
          ? {
              event: "delta",
              chat_id: chatId ?? "",
              text,
              turn_id: turn.turnId,
              turn_phase: turn.turnPhase,
              turn_seq: turn.turnSeq,
              source: event.source,
              response_sources: event.responseSources,
            }
          : {
              event: "reasoning_delta",
              chat_id: chatId ?? "",
              text,
              turn_id: turn.turnId,
              turn_phase: turn.turnPhase,
              turn_seq: turn.turnSeq,
            };
        projection = projectThreadEvent(projection, projectedEvent, {
          createId: () => crypto.randomUUID(),
          now: Date.now(),
        });
      }
      projectionRef.current = projection;
      return projection.messages;
    },
    [chatId],
  );

  const flushPendingStreamEvents = useCallback((options?: {
    closeAnswerSegment?: boolean;
    mergeReasoning?: boolean;
    finalAnswerText?: string;
    turn?: UIMessageTurnFields;
    source?: UIMessage["source"];
    responseSources?: UIMessage["responseSources"];
  }) => {
    lastStreamFlushRef.current = 0;
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
    const responseSources = options?.responseSources;
    if (events.length === 0 && finalAnswerText === undefined && source === undefined && responseSources === undefined
      && !options?.mergeReasoning) {
      if (options?.closeAnswerSegment) closeActiveAssistantStream();
      return;
    }
    pendingStreamEventsRef.current = [];
    setMessages((prev) => {
      const nextMessages = events.length > 0 ? applyPendingStreamEvents(prev, events) : prev;
      let projection = { ...projectionRef.current, messages: nextMessages };
      if (
        finalAnswerText !== undefined
        || source !== undefined
        || responseSources !== undefined
        || options?.mergeReasoning
        || options?.closeAnswerSegment
      ) {
        projection = projectThreadEvent(projection, {
          event: "stream_end",
          chat_id: chatId ?? "",
          ...(finalAnswerText !== undefined ? { text: finalAnswerText } : {}),
          ...(source ? { source } : {}),
          ...(responseSources !== undefined ? { response_sources: responseSources } : {}),
          ...(options?.mergeReasoning ? { resuming: true, merge_next: true } : {}),
          turn_id: turn.turnId,
          turn_phase: turn.turnPhase,
          turn_seq: turn.turnSeq,
        }, {
          createId: () => crypto.randomUUID(),
          now: Date.now(),
        });
      }
      projectionRef.current = projection;
      return projection.messages;
    });
  }, [applyPendingStreamEvents, chatId, closeActiveAssistantStream, setMessages]);

  const schedulePendingStreamFlush = useCallback(function schedule() {
    if (streamFrameRef.current !== null || streamTimerRef.current !== null) return;
    if (document.visibilityState === "hidden" || !threadVisibleRef.current) {
      streamTimerRef.current = window.setTimeout(() => {
        streamTimerRef.current = null;
        const events = pendingStreamEventsRef.current;
        if (events.length === 0) return;
        pendingStreamEventsRef.current = [];
        setMessages((prev) => applyPendingStreamEvents(prev, events));
      }, BACKGROUND_STREAM_FLUSH_INTERVAL_MS);
      return;
    }
    const delay = VISIBLE_STREAM_FLUSH_INTERVAL_MS
      - (performance.now() - lastStreamFlushRef.current);
    if (delay > 0) {
      streamTimerRef.current = window.setTimeout(() => {
        streamTimerRef.current = null;
        schedule();
      }, delay);
      return;
    }
    streamFrameRef.current = window.requestAnimationFrame(() => {
      streamFrameRef.current = null;
      const events = pendingStreamEventsRef.current;
      if (events.length === 0) return;
      pendingStreamEventsRef.current = [];
      lastStreamFlushRef.current = performance.now();
      setMessages((prev) => applyPendingStreamEvents(prev, events));
    });
  }, [applyPendingStreamEvents, setMessages]);

  useEffect(() => {
    if (threadVisible) {
      flushPendingStreamEvents();
    } else if (streamFrameRef.current !== null || streamTimerRef.current !== null) {
      if (streamFrameRef.current !== null) window.cancelAnimationFrame(streamFrameRef.current);
      streamFrameRef.current = null;
      if (streamTimerRef.current !== null) window.clearTimeout(streamTimerRef.current);
      streamTimerRef.current = null;
      schedulePendingStreamFlush();
    }
  }, [threadVisible, flushPendingStreamEvents, schedulePendingStreamFlush]);

  useEffect(() => {
    const onVisibilityChange = () => {
      if (pendingStreamEventsRef.current.length === 0) return;
      if (document.visibilityState === "visible" && threadVisibleRef.current) {
        flushPendingStreamEvents();
      } else {
        if (streamFrameRef.current !== null) window.cancelAnimationFrame(streamFrameRef.current);
        streamFrameRef.current = null;
        if (streamTimerRef.current !== null) window.clearTimeout(streamTimerRef.current);
        streamTimerRef.current = null;
        schedulePendingStreamFlush();
      }
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => document.removeEventListener("visibilitychange", onVisibilityChange);
  }, [flushPendingStreamEvents, schedulePendingStreamFlush]);

  useEffect(() => {
    if (!chatId) return;
    return client.onRunStatus((runChatId, startedAt) => {
      if (runChatId !== chatId) return;
      if (startedAt !== null) {
        setRunStartedAt(startedAt);
        setIsStreaming(true);
        return;
      }
      flushPendingStreamEvents();
      setMessages((prev) => {
        const settled = prev.map((message) => (
          message.isStreaming ? { ...message, isStreaming: false } : message
        ));
        projectionRef.current = resetThreadProjectionCursor(
          projectionRef.current,
          settled,
        );
        return settled;
      });
      setRunStartedAt(null);
      setIsStreaming(false);
    });
  }, [chatId, client, clearActivitySegment, flushPendingStreamEvents, setMessages]);

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
    setRetryStatus(null);
    setGoalState(chatId ? client.getGoalState(chatId) : undefined);
    setRecoveryState(null);
    projectionRef.current = createThreadProjectionState(initialMessages);
    clearPendingStreamWork();
    sideChannelTurnIdsRef.current.clear();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatId, client, clearActivitySegment, clearPendingStreamWork, setMessages]);

  useEffect(() => {
    if (hasPendingToolCalls) setIsStreaming(true);
  }, [hasPendingToolCalls]);

  const applyProjectionEvent = useCallback((
    event: ThreadProjectionEvent,
    options?: { sideChannel?: boolean },
  ) => {
    setMessages((prev) => {
      const projection = projectThreadEvent(
        { ...projectionRef.current, messages: prev },
        event,
        {
          createId: () => crypto.randomUUID(),
          now: Date.now(),
          sideChannel: options?.sideChannel,
        },
      );
      projectionRef.current = projection;
      return projection.messages;
    });
  }, [setMessages]);

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
      if (ev.event === "context_compaction") {
        flushPendingStreamEvents({ closeAnswerSegment: true });
        clearActivitySegment();
        const compaction = {
          id: ev.compaction_id,
          phase: ev.phase,
          announce: true,
        };
        setMessages((prev) => {
          const id = `compaction-${ev.compaction_id}`;
          const existing = prev.findIndex((message) => message.id === id);
          if (!acceptsCompactionPhase(prev[existing]?.compaction?.phase, ev.phase)) return prev;
          const next = {
            id,
            role: "assistant" as const,
            content: "",
            kind: "compaction" as const,
            createdAt: Date.now(),
            compaction,
            ...turnFieldsFromEvent(ev, "activity"),
          };
          if (existing < 0) return [...prev, next];
          return prev.map((message, index) => (
            index === existing
              ? { ...next, createdAt: message.createdAt }
              : message
          ));
        });
        return;
      }
      if (
        ev.event === "delta"
        || ev.event === "message"
        || ev.event === "file_edit"
        || ev.event === "reasoning_delta"
        || ev.event === "stream_end"
      ) setRetryStatus(null);
      if (ev.event === "delta") {
        if (projectionRef.current.suppressUntilTurnEnd) return;
        const chunk = typeof ev.text === "string" ? ev.text : "";
        if (!chunk) return;
        setIsStreaming(true);
        pendingStreamEventsRef.current.push({
          kind: "delta",
          text: chunk,
          turn: turnFieldsFromEvent(ev, "answer"),
          source: ev.source,
          responseSources: ev.response_sources,
        });
        schedulePendingStreamFlush();
        return;
      }

      if (ev.event === "reasoning_delta") {
        if (projectionRef.current.suppressUntilTurnEnd) return;
        const chunk = ev.text;
        if (!chunk) return;
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
          mergeReasoning: mergeNext,
          ...(typeof ev.text === "string" ? { finalAnswerText: ev.text } : {}),
          turn,
          source: ev.source,
          responseSources: ev.response_sources,
        });
        if (projectionRef.current.suppressUntilTurnEnd) return;
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

      flushPendingStreamEvents();

      if (ev.event === "reasoning_end") {
        if (projectionRef.current.suppressUntilTurnEnd) return;
        applyProjectionEvent(ev);
        return;
      }

      if (ev.event === "goal_state") {
        setGoalState(ev.goal_state);
        return;
      }

      if (ev.event === "goal_status") {
        if (ev.status === "running" && typeof ev.started_at === "number") {
          setStreamError(null);
          setRunStartedAt(ev.started_at);
          setIsStreaming(true);
        } else {
          setRunStartedAt(null);
          setIsStreaming(false);
          setRetryStatus(null);
        }
        return;
      }

      if (ev.event === "retry_status") {
        const activeTurnId = client.getRunTurnId(chatId);
        if (ev.turn_id && activeTurnId && ev.turn_id !== activeTurnId) return;
        if (ev.state === "recovered" || ev.state === "cleared") {
          setRetryStatus(null);
        } else {
          const retryAfterSeconds =
            typeof ev.retry_after_s === "number" &&
            Number.isFinite(ev.retry_after_s) &&
            ev.retry_after_s >= 0
              ? ev.retry_after_s
              : undefined;
          setRetryStatus({
            state: ev.state,
            attempt: ev.attempt,
            error_kind: ev.error_kind,
            ...(typeof ev.max_attempts === "number"
              ? { max_attempts: ev.max_attempts }
              : {}),
            ...(retryAfterSeconds !== undefined
              ? { next_retry_at: Date.now() / 1000 + retryAfterSeconds }
              : {}),
            ...(ev.turn_id ? { turn_id: ev.turn_id } : {}),
          });
          setIsStreaming(true);
        }
        return;
      }

      if (ev.event === "turn_end") {
        if (typeof ev.turn_id === "string") sideChannelTurnIdsRef.current.delete(ev.turn_id);
        if ("goal_state" in ev && ev.goal_state != null && typeof ev.goal_state === "object") {
          setGoalState(ev.goal_state);
        }
        setRunStartedAt(null);
        setRetryStatus(null);
        // Definitive signal that the turn is fully complete, so stop the
        // loading indicator immediately.
        setIsStreaming(false);
        const modelRequestFailed = ev.outcome === "failed" && ev.failure_kind === "model";
        const failureAttempts =
          typeof ev.failure_attempts === "number"
          && Number.isInteger(ev.failure_attempts)
          && ev.failure_attempts > 0
            ? ev.failure_attempts
            : undefined;
        const modelFailure = modelRequestFailed
          ? {
              kind: "model_request_failed" as const,
              chatId,
              ...(ev.turn_id ? { turnId: ev.turn_id } : {}),
              ...(typeof ev.failure_error_kind === "string"
                ? { errorKind: ev.failure_error_kind }
                : {}),
              ...(failureAttempts !== undefined ? { attempts: failureAttempts } : {}),
            }
          : null;
        if (modelFailure) setStreamError(modelFailure);
        applyProjectionEvent(ev);
        notifyInBackground(
          modelFailure
            ? resolveModelRequestFailureCopy(modelFailure, t).body
            : ev.outcome === "failed"
              ? ev.failure_message || "This turn failed and has ended."
            : t("recovery.completed", { defaultValue: "Task completed" }),
        );
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
          setRetryStatus(null);
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
        applyProjectionEvent(ev, { sideChannel: sideChannelEvent });
        if (sideChannelEvent && typeof ev.turn_id === "string") {
          sideChannelTurnIdsRef.current.delete(ev.turn_id);
        }
        return;
      }
      if (ev.event === "file_edit") {
        applyProjectionEvent(ev);
        return;
      }
    };

    const unsub = client.onChat(chatId, handle);
    return () => {
      unsub();
      // Navigation may happen before the throttled paint. Snapshot the pending
      // deltas synchronously while they still belong to this subscription.
      const pending = pendingStreamEventsRef.current;
      const snapshot = pending.length > 0
        ? applyPendingStreamEvents(messagesRef.current, pending)
        : messagesRef.current;
      onStreamDetach?.(snapshot);
      if (pending.length > 0) setMessages(snapshot);
      projectionRef.current = resetThreadProjectionCursor(projectionRef.current);
      clearPendingStreamWork();
    };
  }, [
    applyProjectionEvent,
    applyPendingStreamEvents,
    applyStreamError,
    chatId,
    closeActiveAssistantStream,
    client,
    clearActivitySegment,
    clearPendingStreamWork,
    flushPendingStreamEvents,
    isSideChannelEvent,
    notifyInBackground,
    onTurnEnd,
    onStreamDetach,
    schedulePendingStreamFlush,
    setMessages,
    t,
  ]);

  const send = useCallback(
    (content: string, images?: SendAttachment[], options?: SendOptions) => {
      if (!chatId) return null;
      const hasAttachments = !!images && images.length > 0;
      // Text is optional when files are attached — the agent will still see
      // them via ``media`` paths.
      if (!hasAttachments && !content.trim()) return null;

      setStreamError(null);
      const sideChannel = options?.sideChannel === true;
      const finalizeActiveTurn = options?.finalizeActiveTurn === true;
      const continueActiveTurn = options?.continueActiveTurn === true;
      const outboundContent = options?.quotedContext
        ? formatQuotedUserMessage(content, options.quotedContext)
        : content;
      flushPendingStreamEvents();
      if (finalizeActiveTurn) {
        setIsStreaming(false);
        setRetryStatus(null);
      }
      const turnId = crypto.randomUUID();
      const userMessageId = crypto.randomUUID();
      if (sideChannel) sideChannelTurnIdsRef.current.add(turnId);
      const previews = hasAttachments ? images!.map((i) => i.preview) : undefined;
      setMessages((prev) => {
        let projection = { ...projectionRef.current, messages: prev };
        if ((!sideChannel && !continueActiveTurn) || finalizeActiveTurn) {
          projection = resetThreadProjectionCursor(projection, prev);
        } else if (continueActiveTurn) {
          // Guidance belongs to the active backend turn. Preserve the answer
          // cursor so its resuming stream_end can finalize the text already
          // shown before the new user row, while starting fresh activity after it.
          projection = clearThreadProjectionActivity(projection);
        }
        const base = finalizeActiveTurn ? finalizeStreamedTurn(prev) : prev;
        const next: UIMessage[] = [
          ...base,
          {
            id: userMessageId,
            role: "user" as const,
            content: outboundContent,
            turnId,
            turnPhase: "user",
            turnSeq: 0,
            deliveryStatus: "sending" as const,
            createdAt: Date.now(),
            ...(previews ? { media: previews } : {}),
            ...(options?.cliApps?.length ? { cliApps: options.cliApps } : {}),
            ...(options?.mcpPresets?.length ? { mcpPresets: options.mcpPresets } : {}),
            ...(options?.sessionMentions?.length
              ? { sessionMentions: options.sessionMentions }
              : {}),
            },
        ];
        projectionRef.current = { ...projection, messages: next };
        return next;
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
    [chatId, clearActivitySegment, client, flushPendingStreamEvents, setMessages],
  );

  const stop = useCallback(() => {
    if (!chatId) return;
    flushPendingStreamEvents();
    setIsStreaming(false);
    setRetryStatus(null);
    setMessages((prev) => {
      const settled = prev.map((m) => (m.isStreaming ? { ...m, isStreaming: false } : m));
      projectionRef.current = resetThreadProjectionCursor(projectionRef.current, settled);
      return settled;
    });
    setRunStartedAt(null);
    client.finishRunLocally(chatId);
    client.sendMessage(chatId, "/stop");
  }, [chatId, clearActivitySegment, client, flushPendingStreamEvents, setMessages]);

  const reconcileTurnComplete = useCallback(() => {
    clearPendingStreamWork();
    projectionRef.current = resetThreadProjectionCursor(projectionRef.current);
    setRunStartedAt(null);
    setRetryStatus(null);
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
    retryStatus,
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
