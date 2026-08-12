export type ConnectionStatus = "connecting" | "connected" | "closed" | "error"

export type InboundEvent =
  | { event: "ready"; chat_id: string; client_id: string }
  | { event: "attached"; chat_id: string }
  | { event: "message_accepted"; chat_id: string; turn_id: string }
  | {
      event: "message"
      chat_id: string
      text: string
      kind?: "tool_hint" | "progress" | "reasoning"
      turn_id?: string
    }
  | { event: "delta"; chat_id: string; text: string; stream_id?: string; turn_id?: string }
  | {
      event: "stream_end"
      chat_id: string
      text?: string
      stream_id?: string
      resuming?: boolean
      merge_next?: boolean
      turn_id?: string
    }
  | { event: "reasoning_delta"; chat_id: string; text: string; turn_id?: string }
  | { event: "reasoning_end"; chat_id: string; turn_id?: string }
  | { event: "turn_end"; chat_id: string; latency_ms?: number; turn_id?: string }
  | { event: "runtime_model_updated"; model_name: string; model_preset?: string | null }
  | { event: "turn_model_updated"; chat_id: string; model_name: string }
  | { event: "error"; chat_id?: string; detail?: string; reason?: string; turn_id?: string }

type OutboundEvent =
  | { type: "new_chat" }
  | { type: "attach"; chat_id: string }
  | { type: "message"; chat_id: string; content: string; turn_id: string; webui: true }

export interface ClientOptions {
  url: string
  chatId?: string
  onEvent: (event: InboundEvent) => void
  onStatus: (status: ConnectionStatus, detail?: string) => void
}

export interface HistoryMessage {
  role: "user" | "assistant"
  content: string
}

export async function fetchHistory(
  apiUrl: string,
  apiToken: string,
  chatId: string,
): Promise<HistoryMessage[]> {
  if (!apiUrl || !apiToken) return []
  const key = encodeURIComponent(`websocket:${chatId}`)
  const response = await fetch(`${apiUrl}/api/sessions/${key}/webui-thread?limit=120&direction=latest`, {
    headers: { Authorization: `Bearer ${apiToken}` },
  })
  if (response.status === 404) return []
  if (!response.ok) throw new Error(`history request failed: HTTP ${response.status}`)
  const payload = (await response.json()) as { messages?: Array<Record<string, unknown>> }
  return (payload.messages || []).flatMap((message) => {
    const role = message.role
    const content = message.content
    if ((role !== "user" && role !== "assistant") || typeof content !== "string" || !content.trim()) {
      return []
    }
    return [{ role, content }]
  })
}

export class NanobotClient {
  private socket: WebSocket | null = null
  private chatId = ""

  constructor(private readonly options: ClientOptions) {}

  get activeChatId(): string {
    return this.chatId
  }

  connect(): void {
    this.options.onStatus("connecting")
    const socket = new WebSocket(this.options.url)
    this.socket = socket
    socket.addEventListener("open", () => this.options.onStatus("connected"))
    socket.addEventListener("message", (message) => this.handleMessage(String(message.data)))
    socket.addEventListener("error", () => this.options.onStatus("error", "connection failed"))
    socket.addEventListener("close", () => this.options.onStatus("closed"))
  }

  close(): void {
    this.socket?.close()
    this.socket = null
  }

  send(content: string): string {
    if (!this.chatId) throw new Error("chat is not ready")
    const turnId = crypto.randomUUID()
    this.write({
      type: "message",
      chat_id: this.chatId,
      content,
      turn_id: turnId,
      webui: true,
    })
    return turnId
  }

  private handleMessage(raw: string): void {
    let value: unknown
    try {
      value = JSON.parse(raw) as unknown
    } catch {
      this.options.onStatus("error", "gateway sent invalid JSON")
      return
    }
    if (!value || typeof value !== "object" || !("event" in value)) {
      this.options.onStatus("error", "gateway sent an invalid event")
      return
    }
    const event = value as InboundEvent

    if (event.event === "ready") {
      if (this.options.chatId) {
        this.chatId = this.options.chatId
        this.write({ type: "attach", chat_id: this.chatId })
      } else {
        this.write({ type: "new_chat" })
      }
    } else if (event.event === "attached") {
      this.chatId = event.chat_id
    }
    this.options.onEvent(event)
  }

  private write(event: OutboundEvent): void {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      throw new Error("gateway connection is not open")
    }
    this.socket.send(JSON.stringify(event))
  }
}
