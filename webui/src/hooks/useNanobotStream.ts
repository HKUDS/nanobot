import { useCallback, useEffect, useRef, useState } from "react";

import { useClient } from "@/providers/ClientProvider";
import type { InboundEvent, UIMessage } from "@/lib/types";

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
export function useNanobotStream(
  chatId: string | null,
  initialMessages: UIMessage[] = [],
): {
  messages: UIMessage[];
  isStreaming: boolean;
  send: (content: string) => void;
  setMessages: React.Dispatch<React.SetStateAction<UIMessage[]>>;
} {
  const { client } = useClient();
  const [messages, setMessages] = useState<UIMessage[]>(initialMessages);
  const [isStreaming, setIsStreaming] = useState(false);
  const buffer = useRef<StreamBuffer | null>(null);

  // Reset local state when switching chats.
  useEffect(() => {
    setMessages(initialMessages);
    setIsStreaming(false);
    buffer.current = null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatId]);

  useEffect(() => {
    if (!chatId) return;

    const handle = (ev: InboundEvent) => {
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
        if (!buffer.current) {
          setIsStreaming(false);
          return;
        }
        const finalId = buffer.current.messageId;
        buffer.current = null;
        setIsStreaming(false);
        setMessages((prev) =>
          prev.map((m) =>
            m.id === finalId ? { ...m, isStreaming: false } : m,
          ),
        );
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

        // A complete (non-streamed) assistant message. If a stream was in
        // flight, drop the placeholder so we don't render the text twice.
        const activeId = buffer.current?.messageId;
        buffer.current = null;
        setIsStreaming(false);
        setMessages((prev) => {
          const filtered = activeId ? prev.filter((m) => m.id !== activeId) : prev;
          return [
            ...filtered,
            {
              id: crypto.randomUUID(),
              role: "assistant",
              content: ev.text,
              createdAt: Date.now(),
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
    };
  }, [chatId, client]);

  const send = useCallback(
    (content: string) => {
      if (!chatId || !content.trim()) return;
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "user",
          content,
          createdAt: Date.now(),
        },
      ]);
      client.sendMessage(chatId, content);
    },
    [chatId, client],
  );

  return { messages, isStreaming, send, setMessages };
}
