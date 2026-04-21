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
import type { ChatSummary, UIMessage } from "@/lib/types";

const EMPTY_MESSAGES: UIMessage[] = [];

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
} {
  const { token } = useClient();
  const [state, setState] = useState<{
    key: string | null;
    messages: UIMessage[];
    loading: boolean;
    error: string | null;
  }>({
    key: null,
    messages: [],
    loading: false,
    error: null,
  });

  useEffect(() => {
    if (!key) {
      setState({
        key: null,
        messages: [],
        loading: false,
        error: null,
      });
      return;
    }
    let cancelled = false;
    // Mark the new key as loading immediately so callers never see stale
    // messages from the previous session during the render right after a switch.
    setState({
      key,
      messages: [],
      loading: true,
      error: null,
    });
    (async () => {
      try {
        const body = await fetchSessionMessages(token, key);
        if (cancelled) return;
        const ui: UIMessage[] = body.messages.flatMap((m, idx) => {
          if (m.role !== "user" && m.role !== "assistant") return [];
          if (typeof m.content !== "string") return [];
          // Hydrate signed media URLs into the bubble's ``images`` slot so
          // historical user turns render real previews (the live-send path
          // uses data URLs; both shapes converge on the same ``UIImage``).
          const images =
            m.role === "user" &&
            Array.isArray(m.media_urls) &&
            m.media_urls.length > 0
              ? m.media_urls.map((mu) => ({
                  url: mu.url,
                  name: mu.name,
                }))
              : undefined;
          return [
            {
              id: `hist-${idx}`,
              role: m.role,
              content: m.content,
              createdAt: m.timestamp ? Date.parse(m.timestamp) : Date.now(),
              ...(images ? { images } : {}),
            },
          ];
        });
        setState({
          key,
          messages: ui,
          loading: false,
          error: null,
        });
      } catch (e) {
        if (cancelled) return;
        // A 404 just means the session hasn't been persisted yet (brand-new
        // chat, first message not sent). That's a normal state, not an error.
        if (e instanceof ApiError && e.status === 404) {
          setState({
            key,
            messages: [],
            loading: false,
            error: null,
          });
        } else {
          setState({
            key,
            messages: [],
            loading: false,
            error: (e as Error).message,
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [key, token]);

  if (!key) {
    return { messages: EMPTY_MESSAGES, loading: false, error: null };
  }

  // Even before the effect above commits its loading state, never surface the
  // previous session's payload for a brand-new key.
  if (state.key !== key) {
    return { messages: EMPTY_MESSAGES, loading: true, error: null };
  }

  return {
    messages: state.messages,
    loading: state.loading,
    error: state.error,
  };
}

/** Produce a compact display title for a session. */
export function sessionTitle(
  session: ChatSummary,
  firstUserMessage?: string,
): string {
  return deriveTitle(
    firstUserMessage || session.preview,
    i18n.t("chat.newChat"),
  );
}
