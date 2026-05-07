import { useCallback, useEffect, useRef, useState } from "react";

import { useClient } from "@/providers/ClientProvider";
import { toMediaAttachment } from "@/lib/media";
import type { StreamError } from "@/lib/nanobot-client";
import type {
  InboundEvent,
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

export function useNanobotStream(
  chatId: string | null,
  initialMessages: UIMessage[] = [],
  hasPendingToolCalls = false,
  onTurnEnd?: () => void,
): {
  messages: UIMessage[];
  isStreaming: boolean;
  send: (content: string, images?: SendImage[]) => void;
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

  // Reset local state when switching chats. ``streamError`` is scoped to the
     // send that triggered it, so a chat swap should wipe it out: a stale
     // "Message too large" banner on a freshly-opened chat-B would confuse the
     // user about which send actually failed (and in which chat).
     useEffect(() => {
       setMessages(initialMessages);
       // Check if the new chat's last message is a trace row — if so, the
       // model may still be processing.
       setIsStreaming(
         initialMessages.length > 0
           ? initialMessages[initialMessages.length - 1].kind === "trace"
           : false,
       );
       // Also consider hasPendingToolCalls from session history.
       if (hasPendingToolCalls) {
         setIsStreaming(true);
       }
       setStreamError(null);
       buffer.current = null;
       if (streamEndTimerRef.current !== null) {
         clearTimeout(streamEndTimerRef.current);
         streamEndTimerRef.current = null;
       }
       // eslint-disable-next-line react-hooks/exhaustive-deps
     }, [chatId, initialMessages, hasPendingToolCalls]);

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
        const id = buffer.current?.messageId ?? crypto.randomUUID();
        if (!buffer.current) {
          buffer.current = { messageId: id, parts: [] };
          setMessages((prev) => [
            ...prev,
            {
              id,
              role: "assistant",
              content: "",
              isStreaming: true,
              createdAt: Date.now(),
            },
          ]);
          setIsStreaming(true);
        }
        buffer.current.parts.push(ev.text);
        const combined = buffer.current.parts.join("");
        const targetId = buffer.current.messageId;
        setMessages((prev) =>
          prev.map((m) => (m.id === targetId ? { ...m, content: combined } : m)),
        );
        return;
      }

      if (ev.event === "stream_end") {
        // stream_end only means the text segment finished — the model may
        // still be executing tools.  Do NOT reset isStreaming here; the
        // definitive "turn is complete" signal is ``turn_end``.
        if (!buffer.current) return;
        buffer.current = null;
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
        setMessages((prev) =>
          prev.map((m) => (m.isStreaming ? { ...m, isStreaming: false } : m)),
        );
        onTurnEnd?.();
        return;
      }

      if (ev.event === "session_updated") {
        onTurnEnd?.();
        return;
      }

      if (ev.event === "message") {
        // Intermediate agent breadcrumbs (tool-call hints, raw progress).
        // Attach them to the last trace row if it was the last emitted item
        // so a sequence of calls collapses into one compact trace group.
        if (ev.kind === "tool_hint" || ev.kind === "progress") {
          const line = ev.text;
          setMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last && last.kind === "trace" && !last.isStreaming) {
              const merged: UIMessage = {
                ...last,
                traces: [...(last.traces ?? [last.content]), line],
                content: line,
              };
              return [...prev.slice(0, -1), merged];
            }
            return [
              ...prev,
              {
                id: crypto.randomUUID(),
                role: "tool",
                kind: "trace",
                content: line,
                traces: [line],
                createdAt: Date.now(),
              },
            ];
          });
          return;
        }

        const media = ev.media_urls?.length
          ? ev.media_urls.map((m) => toMediaAttachment(m))
          : ev.media?.map((url) => toMediaAttachment({ url }));

        // A complete (non-streamed) assistant message. If a stream was in
        // flight, drop the placeholder so we don't render the text twice.
        const activeId = buffer.current?.messageId;
        buffer.current = null;
        // Do NOT reset isStreaming here — only ``turn_end`` signals that
        // the full turn (all tool calls + final text) is complete.
        setMessages((prev) => {
          const filtered = activeId ? prev.filter((m) => m.id !== activeId) : prev;
          const content = ev.buttons?.length ? (ev.button_prompt ?? ev.text) : ev.text;
          return [
            ...filtered,
            {
              id: crypto.randomUUID(),
              role: "assistant",
              content,
              createdAt: Date.now(),
              ...(ev.buttons && ev.buttons.length > 0 ? { buttons: ev.buttons } : {}),
              ...(media && media.length > 0 ? { media } : {}),
            },
          ];
        });
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
    (content: string, images?: SendImage[]) => {
      if (!chatId) return;
      const hasImages = !!images && images.length > 0;
      // Text is optional when images are attached — the agent will still see
      // the image blocks via ``media`` paths.
      if (!hasImages && !content.trim()) return;

      const previews = hasImages ? images!.map((i) => i.preview) : undefined;
      setMessages((prev) => [
        ...prev,
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
      client.sendMessage(chatId, content, wireMedia);
    },
    [chatId, client],
  );

  return {
    messages,
    isStreaming,
    send,
    setMessages,
    streamError,
    dismissStreamError,
  };
}
