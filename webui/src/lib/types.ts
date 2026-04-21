export type Role = "user" | "assistant" | "tool" | "system";

/** "trace" rows are intermediate agent breadcrumbs (tool-call hints,
 * progress pings) that should not be rendered as conversational replies. */
export type MessageKind = "message" | "trace";

export interface UIMessage {
  id: string;
  role: Role;
  content: string;
  kind?: MessageKind;
  isStreaming?: boolean;
  createdAt: number;
  /** For trace rows: each individual hint line, so consecutive hints can
   * render as a single collapsible group. */
  traces?: string[];
}

export interface ChatSummary {
  /** Server-side session key, e.g. ``websocket:abcd-...``. */
  key: string;
  /** Local channel + chat_id parts derived from ``key`` for convenience. */
  channel: string;
  chatId: string;
  createdAt: string | null;
  updatedAt: string | null;
  preview: string;
}

export interface BootstrapResponse {
  token: string;
  ws_path: string;
  expires_in: number;
  model_name?: string | null;
}

export type ConnectionStatus =
  | "idle"
  | "connecting"
  | "open"
  | "reconnecting"
  | "closed"
  | "error";

export type InboundEvent =
  | { event: "ready"; chat_id: string; client_id: string }
  | { event: "attached"; chat_id: string }
  | {
      event: "message";
      chat_id: string;
      text: string;
      reply_to?: string;
      media?: string[];
      /** Present when the frame is an agent breadcrumb (e.g. tool hint,
       * generic progress line) rather than a conversational reply. */
      kind?: "tool_hint" | "progress";
    }
  | {
      event: "delta";
      chat_id: string;
      text: string;
      stream_id?: string;
    }
  | {
      event: "stream_end";
      chat_id: string;
      stream_id?: string;
    }
  | { event: "error"; chat_id?: string; detail?: string };

export type Outbound =
  | { type: "new_chat" }
  | { type: "attach"; chat_id: string }
  | { type: "message"; chat_id: string; content: string };
