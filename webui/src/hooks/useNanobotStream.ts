import { useCallback, useEffect, useRef, useState } from "react";

import { useClient } from "@/providers/ClientProvider";
import { toMediaAttachment } from "@/lib/media";
import { toolTraceLinesFromEvents } from "@/lib/tool-traces";
import type { StreamError } from "@/lib/nanobot-client";
import type {
  InboundEvent,
  OutboundImageGeneration,
  OutboundMedia,
  UIImage,
  UIMessage,
} from "@/lib/types";

interface StreamBuffer {
  /** ID of the assistant message currently receiving deltas. */
  messageId: string;
  /** Sequence of deltas accumulated in order. */
  parts: string[];
}

/**
 * Append a reasoning chunk to the last open reasoning stream in ``prev``.
 *
 * Lookup rule: prefer the most recent assistant turn in the active UI tail.
 * Most providers emit reasoning before answer text, but some only expose
 * ``reasoning_content`` after the answer stream completes. In that post-hoc
 * case the reasoning still belongs to the same assistant turn and must render
 * above the answer, not as a new row below it.
 */
function attachReasoningChunk(prev: UIMessage[], chunk: string): UIMessage[] {
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
    const hasAnswer = candidate.content.length > 0;
    if (
      candidate.reasoningStreaming
      || candidate.reasoning !== undefined
      || hasAnswer
      || candidate.isStreaming
    ) {
      const merged: UIMessage = {
        ...candidate,
        reasoning: (candidate.reasoning ?? "") + chunk,
        reasoningStreaming: true,
      };
      return [...prev.slice(0, i), merged, ...prev.slice(i + 1)];
    }
    if (!hasAnswer && candidate.isStreaming) {
      const merged: UIMessage = {
        ...candidate,
        reasoning: chunk,
        reasoningStreaming: true,
      };
      return [...prev.slice(0, i), merged, ...prev.slice(i + 1)];
    }
    break;
  }
  return [
    ...prev,
    {
      id: crypto.randomUUID(),
      role: "assistant",
      content: "",
      isStreaming: true,
      reasoning: chunk,
      reasoningStreaming: true,
      createdAt: Date.now(),
    },
  ];
}

/**
 * Find the most recent assistant placeholder that an incoming answer
 * delta should adopt instead of spawning a parallel row. We look for an
 * empty-content assistant turn that is still marked ``isStreaming`` —
 * typically created earlier by ``reasoning_delta``. Anything else means
 * the model already produced an answer in a previous turn, so the new
 * delta belongs in a fresh row.
 */
function findActiveAssistantPlaceholder(prev: UIMessage[]): string | null {
  const last = prev[prev.length - 1];
  if (!last) return null;
  if (last.role !== "assistant" || last.kind === "trace") return null;
  if (last.content.length > 0) return null;
  if (!last.isStreaming) return null;
  return last.id;
}

/**
 * Close the active reasoning stream segment, if any. Idempotent: a
 * ``reasoning_end`` with no preceding deltas is a harmless no-op.
 */
function closeReasoningStream(prev: UIMessage[]): UIMessage[] {
  for (let i = prev.length - 1; i >= 0; i -= 1) {
    const candidate = prev[i];
    if (!candidate.reasoningStreaming) continue;
    const merged: UIMessage = { ...candidate, reasoningStreaming: false };
    return [...prev.slice(0, i), merged, ...prev.slice(i + 1)];
  }
  return prev;
}

function isReasoningOnlyPlaceholder(message: UIMessage): boolean {
  return (
    message.role === "assistant"
    && message.kind !== "trace"
    && message.content.trim().length === 0
    && !!message.reasoning
    && !message.reasoningStreaming
    && !message.media?.length
  );
}

function isToolTrace(message: UIMessage | undefined): boolean {
  return message?.kind === "trace";
}

function pruneReasoningOnlyPlaceholders(prev: UIMessage[]): UIMessage[] {
  return prev.filter((message, index) => {
    if (!isReasoningOnlyPlaceholder(message)) return true;
    // A reasoning-only assistant row immediately followed by tool traces is
    // the live equivalent of a persisted assistant tool-call message with
    // empty content, reasoning_content, and tool_calls. Keep it so live render
    // and history replay stay isomorphic.
    return isToolTrace(prev[index + 1]);
  });
}

function absorbCompleteAssistantMessage(
  prev: UIMessage[],
  message: Omit<UIMessage, "id" | "role" | "createdAt">,
): UIMessage[] {
  const last = prev[prev.length - 1];
  if (!last || !isReasoningOnlyPlaceholder(last)) {
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
 * separately (e.g. via ``fetchSessionMessages``) since the server only replays
 * live events.
 */
/** Payload passed to ``send`` when the user attaches one or more images.
 *
 * ``media`` is handed to the wire client verbatim; ``preview`` powers the
 * optimistic user bubble (blob URLs so the preview appears before the server
 * acks the frame). Keeping the two separate lets the bubble re-use the local
 * blob URL even after the server persists the file under a different name. */
export interface SendImage {
  media: OutboundMedia;
  preview: UIImage;
}

export interface SendOptions {
  imageGeneration?: OutboundImageGeneration;
}

export function useNanobotStream(
  chatId: string | null,
  initialMessages: UIMessage[] = [],
  hasPendingToolCalls = false,
  onTurnEnd?: () => void,
): {
  messages: UIMessage[];
  isStreaming: boolean;
  send: (content: string, images?: SendImage[], options?: SendOptions) => void;
  stop: () => void;
  setMessages: React.Dispatch<React.SetStateAction<UIMessage[]>>;
  /** Latest transport-level fault raised since the last ``dismissStreamError``.
   * ``null`` when there is nothing to show. */
  streamError: StreamError | null;
  /** Clear the current ``streamError`` (e.g. after the user dismisses the
   * notification or starts a fresh action). */
  dismissStreamError: () => void;
} {
  const { client } = useClient();
  const [messages, setMessages] = useState<UIMessage[]>(initialMessages);
  /** If the last loaded message is a trace row (e.g. "Using 2 tools"),
   * the model was still processing when the page loaded — keep the
   * loading spinner alive so the user sees the model is active. */
  const initialStreaming = initialMessages.length > 0
    ? initialMessages[initialMessages.length - 1].kind === "trace"
    : false;
  const [isStreaming, setIsStreaming] = useState(initialStreaming || hasPendingToolCalls);
  const [streamError, setStreamError] = useState<StreamError | null>(null);
  const buffer = useRef<StreamBuffer | null>(null);
  const suppressStreamUntilTurnEndRef = useRef(false);
  /** Timer that defers ``isStreaming = false`` after ``stream_end``.
   *
   * When the model finishes a text segment and calls a tool, the server
   * sends ``stream_end`` but the agent is still "thinking" while the tool
   * executes.  By deferring the flag reset by a short window (1 s) we keep
   * the loading spinner alive across tool-call boundaries without needing
   * backend changes. */
  const streamEndTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return client.onError((err) => setStreamError(err));
  }, [client]);

  const dismissStreamError = useCallback(() => setStreamError(null), []);

  // Reset local state when switching chats. Do not reset on every
  // ``initialMessages`` update: a brand-new chat can receive an empty/404
  // history response after the optimistic first message has already rendered.
  useEffect(() => {
    setMessages(initialMessages);
    setIsStreaming(
      (initialMessages.length > 0
        ? initialMessages[initialMessages.length - 1].kind === "trace"
        : false) || hasPendingToolCalls,
    );
    setStreamError(null);
    buffer.current = null;
    suppressStreamUntilTurnEndRef.current = false;
    if (streamEndTimerRef.current !== null) {
      clearTimeout(streamEndTimerRef.current);
      streamEndTimerRef.current = null;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatId]);

  useEffect(() => {
    if (hasPendingToolCalls) setIsStreaming(true);
  }, [hasPendingToolCalls]);

  useEffect(() => {
    if (!chatId) return;

    const handle = (ev: InboundEvent) => {
      // Any incoming event while the debounce timer is alive means the model
      // is still working (e.g. tool result arrived, more text to stream).
      // Cancel the pending "stream ended" timer so we don't hide the spinner.
      if (streamEndTimerRef.current !== null) {
        clearTimeout(streamEndTimerRef.current);
        streamEndTimerRef.current = null;
      }

      if (ev.event === "delta") {
        if (suppressStreamUntilTurnEndRef.current) return;
        const chunk = ev.text;
        setIsStreaming(true);
        setMessages((prev) => {
          // Reuse an in-flight assistant placeholder (typically created by
          // ``reasoning_delta``) so the answer renders below its own
          // thinking trace instead of in a parallel row.
          const adopted = !buffer.current ? findActiveAssistantPlaceholder(prev) : null;
          let targetId: string;
          let next: UIMessage[];
          if (buffer.current) {
            targetId = buffer.current.messageId;
            next = prev;
          } else if (adopted) {
            targetId = adopted;
            buffer.current = { messageId: targetId, parts: [] };
            next = prev;
          } else {
            targetId = crypto.randomUUID();
            buffer.current = { messageId: targetId, parts: [] };
            next = [
              ...prev,
              {
                id: targetId,
                role: "assistant",
                content: "",
                isStreaming: true,
                createdAt: Date.now(),
              },
            ];
          }
          buffer.current.parts.push(chunk);
          const combined = buffer.current.parts.join("");
          return next.map((m) =>
            m.id === targetId ? { ...m, content: combined, isStreaming: true } : m,
          );
        });
        return;
      }

      if (ev.event === "stream_end") {
        if (suppressStreamUntilTurnEndRef.current) {
          buffer.current = null;
          return;
        }
        // stream_end only means the text segment finished — the model may
        // still be executing tools.  Do NOT reset isStreaming here; the
        // definitive "turn is complete" signal is ``turn_end``.
        if (!buffer.current) return;
        buffer.current = null;
        return;
      }

      if (ev.event === "reasoning_delta") {
        if (suppressStreamUntilTurnEndRef.current) return;
        const chunk = ev.text;
        if (!chunk) return;
        setMessages((prev) => attachReasoningChunk(prev, chunk));
        setIsStreaming(true);
        return;
      }

      if (ev.event === "reasoning_end") {
        if (suppressStreamUntilTurnEndRef.current) return;
        setMessages((prev) => closeReasoningStream(prev));
        return;
      }

      if (ev.event === "turn_end") {
        // Definitive signal that the turn is fully complete.  Cancel any
        // pending debounce timer and stop the loading indicator immediately.
        if (streamEndTimerRef.current !== null) {
          clearTimeout(streamEndTimerRef.current);
          streamEndTimerRef.current = null;
        }
        setIsStreaming(false);
        setMessages((prev) => {
          const finalized = prev.map((m) => (m.isStreaming ? { ...m, isStreaming: false } : m));
          return pruneReasoningOnlyPlaceholders(finalized);
        });
        suppressStreamUntilTurnEndRef.current = false;
        onTurnEnd?.();
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
          setMessages((prev) => closeReasoningStream(attachReasoningChunk(prev, line)));
          return;
        }
        // Intermediate agent breadcrumbs (tool-call hints, raw progress).
        // Attach them to the last trace row if it was the last emitted item
        // so a sequence of calls collapses into one compact trace group.
        if (ev.kind === "tool_hint" || ev.kind === "progress") {
          const structuredLines = toolTraceLinesFromEvents(ev.tool_events);
          const lines = structuredLines.length > 0
            ? structuredLines
            : ev.text
              ? [ev.text]
              : [];
          if (lines.length === 0) return;
          setMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last && last.kind === "trace" && !last.isStreaming) {
              const merged: UIMessage = {
                ...last,
                traces: [...(last.traces ?? [last.content]), ...lines],
                content: lines[lines.length - 1],
              };
              return [...prev.slice(0, -1), merged];
            }
            return [
              ...prev,
              {
                id: crypto.randomUUID(),
                role: "tool",
                kind: "trace",
                content: lines[lines.length - 1],
                traces: lines,
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

        // A complete (non-streamed) assistant message. If a stream was in
        // flight, drop the placeholder so we don't render the text twice.
        const activeId = buffer.current?.messageId;
        buffer.current = null;
        // Do NOT reset isStreaming here — only ``turn_end`` signals that
        // the full turn (all tool calls + final text) is complete.
        setMessages((prev) => {
          const filtered = activeId ? prev.filter((m) => m.id !== activeId) : prev;
          const content = ev.text;
          return absorbCompleteAssistantMessage(filtered, {
            content,
            ...(hasMedia ? { media } : {}),
          });
        });
        if (hasMedia) {
          suppressStreamUntilTurnEndRef.current = true;
        }
        return;
      }
      // ``attached`` / ``error`` frames aren't actionable here; the client
      // shell handles them separately.
    };

    const unsub = client.onChat(chatId, handle);
    return () => {
      unsub();
      buffer.current = null;
      if (streamEndTimerRef.current !== null) {
        clearTimeout(streamEndTimerRef.current);
        streamEndTimerRef.current = null;
      }
    };
  }, [chatId, client, onTurnEnd]);

  const send = useCallback(
    (content: string, images?: SendImage[], options?: SendOptions) => {
      if (!chatId) return;
      const hasImages = !!images && images.length > 0;
      // Text is optional when images are attached — the agent will still see
      // the image blocks via ``media`` paths.
      if (!hasImages && !content.trim()) return;

      const previews = hasImages ? images!.map((i) => i.preview) : undefined;
      setMessages((prev) => [
        ...pruneReasoningOnlyPlaceholders(prev),
        {
          id: crypto.randomUUID(),
          role: "user",
          content,
          createdAt: Date.now(),
          ...(previews ? { images: previews } : {}),
        },
      ]);
      // Mark streaming immediately so the UI shows the loading indicator
      // right away, before the first delta arrives from the server.
      setIsStreaming(true);
      const wireMedia = hasImages ? images!.map((i) => i.media) : undefined;
      if (options) {
        client.sendMessage(chatId, content, wireMedia, options);
      } else {
        client.sendMessage(chatId, content, wireMedia);
      }
    },
    [chatId, client],
  );

  const stop = useCallback(() => {
    if (!chatId) return;
    setIsStreaming(false);
    setMessages((prev) =>
      prev.map((m) => (m.isStreaming ? { ...m, isStreaming: false } : m)),
    );
    suppressStreamUntilTurnEndRef.current = false;
    client.sendMessage(chatId, "/stop");
  }, [chatId, client]);

  return {
    messages,
    isStreaming,
    send,
    stop,
    setMessages,
    streamError,
    dismissStreamError,
  };
}
