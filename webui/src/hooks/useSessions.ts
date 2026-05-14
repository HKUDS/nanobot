import { useCallback, useEffect, useRef, useState } from "react";

import { useClient } from "@/providers/ClientProvider";
import i18n from "@/i18n";
import {
  ApiError,
  deleteSession as apiDeleteSession,
  fetchSessionMessages,
  listSessions,
} from "@/lib/api";
import { deriveTitle } from "@/lib/format";
import { toMediaAttachment } from "@/lib/media";
import { formatToolCallTrace } from "@/lib/tool-traces";
import type { ChatSummary, UIMessage } from "@/lib/types";

const EMPTY_MESSAGES: UIMessage[] = [];

type HistoryMessage = Awaited<ReturnType<typeof fetchSessionMessages>>["messages"][number];

function reasoningFromHistory(message: HistoryMessage): string | undefined {
  if (typeof message.reasoning_content === "string" && message.reasoning_content.trim()) {
    return message.reasoning_content;
  }
  if (!Array.isArray(message.thinking_blocks)) return undefined;
  const parts = message.thinking_blocks
    .map((block) => {
      if (!block || typeof block !== "object") return "";
      const thinking = (block as { thinking?: unknown }).thinking;
      return typeof thinking === "string" ? thinking.trim() : "";
    })
    .filter(Boolean);
  return parts.length > 0 ? parts.join("\n\n") : undefined;
}

function toolTracesFromHistory(message: HistoryMessage): string[] {
  if (!Array.isArray(message.tool_calls)) return [];
  return message.tool_calls
    .map(formatToolCallTrace)
    .filter((trace): trace is string => !!trace);
}

/** Sidebar state: fetches the full session list and exposes create / delete actions. */
export function useSessions(): {
  sessions: ChatSummary[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  createChat: () => Promise<string>;
  deleteChat: (key: string) => Promise<void>;
} {
  const { client, token } = useClient();
  const [sessions, setSessions] = useState<ChatSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const tokenRef = useRef(token);
  tokenRef.current = token;

  const refresh = useCallback(async () => {
    try {
      setLoading(true);
      const rows = await listSessions(tokenRef.current);
      setSessions(rows);
      setError(null);
    } catch (e) {
      const msg =
        e instanceof ApiError ? `HTTP ${e.status}` : (e as Error).message;
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    return client.onSessionUpdate(() => {
      void refresh();
    });
  }, [client, refresh]);

  const createChat = useCallback(async (): Promise<string> => {
    const chatId = await client.newChat();
    const key = `websocket:${chatId}`;
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
      },
      ...prev.filter((s) => s.key !== key),
    ]);
    return chatId;
  }, [client]);

  const deleteChat = useCallback(
    async (key: string) => {
      await apiDeleteSession(tokenRef.current, key);
      setSessions((prev) => prev.filter((s) => s.key !== key));
    },
    [],
  );

  return { sessions, loading, error, refresh, createChat, deleteChat };
}

/** Lazy-load a session's on-disk messages the first time the UI displays it. */
export function useSessionHistory(key: string | null): {
  messages: UIMessage[];
  loading: boolean;
  error: string | null;
  refresh: () => void;
  version: number;
  /** ``true`` when the last persisted assistant turn has ``tool_calls`` but no
   *  final text yet — the model was still processing when the page loaded. */
  hasPendingToolCalls: boolean;
} {
  const { token } = useClient();
  const [refreshSeq, setRefreshSeq] = useState(0);
  const refresh = useCallback(() => {
    setRefreshSeq((value) => value + 1);
  }, []);
  const [state, setState] = useState<{
    key: string | null;
    messages: UIMessage[];
    loading: boolean;
    error: string | null;
    hasPendingToolCalls: boolean;
    version: number;
  }>({
    key: null,
    messages: [],
    loading: false,
    error: null,
    hasPendingToolCalls: false,
    version: 0,
  });

  useEffect(() => {
    if (!key) {
      setState({
        key: null,
        messages: [],
        loading: false,
        error: null,
        hasPendingToolCalls: false,
        version: 0,
      });
      return;
    }
    let cancelled = false;
    // Mark the new key as loading immediately so callers never see stale
    // messages from the previous session during the render right after a switch.
    setState((prev) => prev.key === key
      ? { ...prev, loading: true, error: null }
      : {
          key,
          messages: [],
          loading: true,
          error: null,
          hasPendingToolCalls: false,
          version: 0,
        });
    (async () => {
      try {
        const body = await fetchSessionMessages(token, key);
        if (cancelled) return;
        const ui: UIMessage[] = body.messages.flatMap((m, idx) => {
          if (m.role !== "user" && m.role !== "assistant") return [];
          if (typeof m.content !== "string") return [];
          // Hydrate signed media URLs into generic UI attachments. Image-only
          // user turns still populate the legacy ``images`` slot so the
          // existing optimistic-send and lightbox paths remain unchanged.
          const media =
            Array.isArray(m.media_urls) && m.media_urls.length > 0
              ? m.media_urls.map((mu) => toMediaAttachment(mu))
              : undefined;
          const images =
            m.role === "user" && media?.every((item) => item.kind === "image")
              ? media.map((item) => ({ url: item.url, name: item.name }))
              : undefined;
          const row: UIMessage = {
            id: `hist-${idx}`,
            role: m.role,
            content: m.content,
            createdAt: m.timestamp ? Date.parse(m.timestamp) : Date.now(),
            ...(images ? { images } : {}),
            ...(media ? { media } : {}),
            ...(m.role === "assistant" && reasoningFromHistory(m)
              ? { reasoning: reasoningFromHistory(m), reasoningStreaming: false }
              : {}),
          };
          const traces = m.role === "assistant" ? toolTracesFromHistory(m) : [];
          if (traces.length === 0) {
            return row.content.trim() || row.media?.length ? [row] : [];
          }
          return [
            ...(row.content.trim() || row.reasoning || row.media?.length ? [row] : []),
            {
              id: `hist-${idx}-tools`,
              role: "tool" as const,
              kind: "trace" as const,
              content: traces[traces.length - 1],
              traces,
              createdAt: m.timestamp ? Date.parse(m.timestamp) : Date.now(),
            },
          ];
        });
        // Tool result rows can trail the assistant tool-call row while the turn
        // is still running, so check the last conversational row.
        const lastRaw = [...body.messages]
          .reverse()
          .find((m) => m.role === "user" || m.role === "assistant");
        const hasPending =
          lastRaw?.role === "assistant" &&
          Array.isArray(lastRaw.tool_calls) &&
          lastRaw.tool_calls.length > 0;
        setState((prev) => ({
          key,
          messages: ui,
          loading: false,
          error: null,
          hasPendingToolCalls: hasPending,
          version: prev.key === key ? prev.version + 1 : 1,
        }));
      } catch (e) {
        if (cancelled) return;
        // A 404 just means the session hasn't been persisted yet (brand-new
        // chat, first message not sent). That's a normal state, not an error.
        if (e instanceof ApiError && e.status === 404) {
          setState((prev) => ({
            key,
            messages: [],
            loading: false,
            error: null,
            hasPendingToolCalls: false,
            version: prev.key === key ? prev.version + 1 : 1,
          }));
        } else {
          setState((prev) => ({
            key,
            messages: [],
            loading: false,
            error: (e as Error).message,
            hasPendingToolCalls: false,
            version: prev.key === key ? prev.version : 0,
          }));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [key, token, refreshSeq]);

  if (!key) {
    return {
      messages: EMPTY_MESSAGES,
      loading: false,
      error: null,
      refresh,
      version: 0,
      hasPendingToolCalls: false,
    };
  }

  // Even before the effect above commits its loading state, never surface the
  // previous session's payload for a brand-new key.
  if (state.key !== key) {
    return {
      messages: EMPTY_MESSAGES,
      loading: true,
      error: null,
      refresh,
      version: 0,
      hasPendingToolCalls: false,
    };
  }

  return {
    messages: state.messages,
    loading: state.loading,
    error: state.error,
    refresh,
    version: state.version,
    hasPendingToolCalls: state.hasPendingToolCalls,
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
