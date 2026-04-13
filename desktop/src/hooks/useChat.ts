import { useState, useCallback, useRef } from "react";
import { useWebSocket, type WSMessage } from "./useWebSocket";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  images?: string[];
  attachments?: string[];
  timestamp: string;
  isStreaming?: boolean;
}

interface UseChatOptions {
  gatewayUrl?: string;
  sessionKey?: string;
  modelId?: string;
}

interface LoadedSession {
  key: string;
  messages: ChatMessage[];
  modelId?: string;
}

interface SessionChatState {
  messages: ChatMessage[];
  isLoading: boolean;
  progress: string;
}

const emptySessionState = (): SessionChatState => ({
  messages: [],
  isLoading: false,
  progress: "",
});

const messageSignature = (message: ChatMessage): string =>
  JSON.stringify({
    role: message.role,
    content: message.content,
    images: message.images || [],
    attachments: message.attachments || [],
  });

const mergeLoadedMessages = (loaded: ChatMessage[], local: ChatMessage[]): ChatMessage[] => {
  if (local.length === 0) return loaded;
  const seen = new Set(loaded.map(messageSignature));
  const optimistic = local.filter((message) => !seen.has(messageSignature(message)));
  return [...loaded, ...optimistic];
};

export function useChat({
  gatewayUrl = "ws://localhost:18790",
  sessionKey = "desktop:direct",
  modelId,
}: UseChatOptions = {}) {
  const [sessionStates, setSessionStates] = useState<Record<string, SessionChatState>>({});
  const currentSessionKey = useRef(sessionKey);
  currentSessionKey.current = sessionKey;
  const currentModelId = useRef(modelId);
  currentModelId.current = modelId;

  const updateSessionState = useCallback(
    (key: string, updater: (state: SessionChatState) => SessionChatState) => {
      setSessionStates((prev) => {
        const current = prev[key] || emptySessionState();
        return {
          ...prev,
          [key]: updater(current),
        };
      });
    },
    []
  );

  const onMessage = useCallback((msg: WSMessage) => {
    const targetSessionKey = msg.session_key || currentSessionKey.current;
    switch (msg.type) {
      case "progress":
        updateSessionState(targetSessionKey, (state) => ({
          ...state,
          isLoading: true,
          progress: msg.content,
        }));
        break;

      case "tool_hint":
        updateSessionState(targetSessionKey, (state) => ({
          ...state,
          isLoading: true,
          progress: `🔧 ${msg.content}`,
        }));
        break;

      case "reply":
        updateSessionState(targetSessionKey, (state) => ({
          ...state,
          isLoading: false,
          progress: "",
          messages: [
            ...state.messages,
            {
              id: `assistant-${Date.now()}`,
              role: "assistant",
              content: msg.content,
              images: Array.isArray(msg.images) ? msg.images : [],
              attachments: Array.isArray(msg.attachments) ? msg.attachments : [],
              timestamp: new Date().toISOString(),
            },
          ],
        }));
        break;

      case "error":
        updateSessionState(targetSessionKey, (state) => ({
          ...state,
          isLoading: false,
          progress: "",
          messages: [
            ...state.messages,
            {
              id: `error-${Date.now()}`,
              role: "assistant",
              content: `⚠️ ${msg.content}`,
              timestamp: new Date().toISOString(),
            },
          ],
        }));
        break;
    }
  }, [updateSessionState]);

  const { connected, sendMessage } = useWebSocket({
    url: `${gatewayUrl}/api/chat`,
    onMessage,
  });

  const send = useCallback(
    (content: string, media: string[] = [], images: string[] = [], attachments: string[] = []) => {
      if (!content.trim() && media.length === 0) return;

      const userMsg: ChatMessage = {
        id: `user-${Date.now()}`,
        role: "user",
        content: content.trim(),
        images,
        attachments,
        timestamp: new Date().toISOString(),
      };

      const targetSessionKey = currentSessionKey.current;
      updateSessionState(targetSessionKey, (state) => ({
        ...state,
        messages: [...state.messages, userMsg],
        isLoading: true,
        progress: "",
      }));
      sendMessage(content.trim(), targetSessionKey, media, currentModelId.current);
    },
    [sendMessage, updateSessionState]
  );

  const clearMessages = useCallback(() => {
    updateSessionState(currentSessionKey.current, () => emptySessionState());
  }, [updateSessionState]);

  const loadSession = useCallback(
    async (key: string): Promise<LoadedSession | null> => {
      currentSessionKey.current = key;
      try {
        const safeKey = key.replace(":", "__");
        const res = await fetch(
          `${gatewayUrl.replace("ws://", "http://").replace("wss://", "https://")}/api/sessions/${safeKey}`
        );
        if (res.ok) {
          const data = await res.json();
          const messages = (data.messages || []).map((m: any, i: number) => ({
            id: `${m.role}-${i}`,
            role: m.role,
            content: typeof m.content === "string" ? m.content : "",
            images: Array.isArray(m.images) ? m.images : [],
            attachments: Array.isArray(m.attachments) ? m.attachments : [],
            timestamp: m.timestamp || "",
          })).filter(
            (message: ChatMessage) =>
              message.content || (message.images?.length || 0) > 0 || (message.attachments?.length || 0) > 0
          );
          updateSessionState(key, (state) => ({
            ...state,
            messages: mergeLoadedMessages(messages, state.messages),
          }));
          return {
            key,
            messages,
            modelId: typeof data.modelId === "string" ? data.modelId : undefined,
          };
        }
      } catch {
        // Failed to load session; start fresh
        updateSessionState(key, (state) => ({
          ...state,
          messages: [],
        }));
      }
      return null;
    },
    [gatewayUrl, updateSessionState]
  );

  const activeState = sessionStates[currentSessionKey.current] || emptySessionState();

  return {
    messages: activeState.messages,
    isLoading: activeState.isLoading,
    progress: activeState.progress,
    connected,
    send,
    clearMessages,
    loadSession,
    sessionKey: currentSessionKey,
  };
}
