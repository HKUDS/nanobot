import { useState, useEffect, useRef, useCallback } from "react";

export interface WSMessage {
  type: "reply" | "progress" | "tool_hint" | "error" | "pong";
  content: string;
  session_key?: string;
  images?: string[];
  attachments?: string[];
}

interface UseWebSocketOptions {
  url: string;
  onMessage?: (msg: WSMessage) => void;
  reconnectInterval?: number;
}

export function useWebSocket({ url, onMessage, reconnectInterval = 3000 }: UseWebSocketOptions) {
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout>>();
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as WSMessage;
        onMessageRef.current?.(data);
      } catch {
        // Ignore parsing errors
      }
    };

    ws.onclose = () => {
      setConnected(false);
      wsRef.current = null;
      // Auto-reconnect
      reconnectRef.current = setTimeout(connect, reconnectInterval);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [url, reconnectInterval]);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  const send = useCallback((data: object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    }
  }, []);

  const sendMessage = useCallback(
    (content: string, sessionKey?: string, media: string[] = [], modelId?: string) => {
      send({
        type: "message",
        content,
        media,
        session_key: sessionKey || "desktop:direct",
        model_id: modelId || null,
      });
    },
    [send]
  );

  return { connected, send, sendMessage };
}
