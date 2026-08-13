export type ConnectionStatus = "connecting" | "connected" | "closed" | "error"

export interface ToolProgressEvent {
  version?: number
  phase?: "start" | "end" | "error" | string
  call_id?: string
  name?: string
  arguments?: unknown
  result?: unknown
  error?: unknown
  files?: unknown[]
  embeds?: unknown[]
}

export interface FileEditEvent {
  version?: number
  call_id?: string
  tool?: string
  path?: string
  phase?: "start" | "end" | "error" | string
  added?: number
  deleted?: number
  status?: "editing" | "done" | "error" | string
  error?: string
}

export type InboundEvent =
  | { event: "ready"; chat_id: string; client_id: string }
  | { event: "attached"; chat_id: string }
  | { event: "message_accepted"; chat_id: string; turn_id: string }
  | {
      event: "message"
      chat_id: string
      text: string
      kind?: "tool_hint" | "progress" | "reasoning"
      tool_events?: ToolProgressEvent[]
      turn_id?: string
    }
  | { event: "file_edit"; chat_id: string; edits: FileEditEvent[]; turn_id?: string }
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
  | {
      event: "goal_status"
      chat_id: string
      status: "running" | "idle"
      started_at?: number
      turn_id?: string
    }
  | { event: "goal_state"; chat_id: string; goal_state: Record<string, unknown> }
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
  reconnectDelayMs?: number
  onEvent: (event: InboundEvent) => void
  onStatus: (status: ConnectionStatus, detail?: string) => void
}

export interface HistoryMessage {
  role: "user" | "assistant" | "activity"
  content: string
  toolEvents?: ToolProgressEvent[]
  fileEdits?: FileEditEvent[]
}

export interface HistorySnapshot {
  messages: HistoryMessage[]
  hasMoreBefore: boolean
  beforeCursor: string | null
}

export interface SessionContextSnapshot {
  totalMessages: number
  archivedMessages: number
  replayMessages: number
  estimatedReplayTokens: number
  estimatedSummaryTokens: number
  estimatedSessionTokens: number
  archivedSummary: string | null
  archivedSummaryAt: string | null
}

export interface SlashCommand {
  command: string
  title: string
  description: string
  argHint: string
  lifecycle: SlashCommandLifecycle
  acceptsArgs: boolean
}

export type SlashCommandLifecycle =
  | "side_channel"
  | "finalize_active_turn"
  | "stop_active_turn"
  | "agent_turn"
  | "agent_turn_with_args"

export interface SessionSummary {
  chatId: string
  title: string
  preview: string
  createdAt: string | null
  updatedAt: string | null
  runStartedAt: number | null
  pinned: boolean
  archived: boolean
}

const SLASH_COMMAND_LIFECYCLES = new Set([
  "side_channel",
  "finalize_active_turn",
  "stop_active_turn",
  "agent_turn",
  "agent_turn_with_args",
])

const CHAT_EVENTS = new Set([
  "attached",
  "message_accepted",
  "message",
  "file_edit",
  "delta",
  "stream_end",
  "reasoning_delta",
  "reasoning_end",
  "turn_end",
  "goal_status",
  "goal_state",
  "turn_model_updated",
  "error",
])

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value)
}

function optional(value: unknown, type: "boolean" | "number" | "string"): boolean {
  return value === undefined || typeof value === type
}

function isToolEvent(value: unknown): value is ToolProgressEvent {
  if (!isRecord(value)) return false
  return optional(value.version, "number")
    && optional(value.phase, "string")
    && optional(value.call_id, "string")
    && optional(value.name, "string")
    && (value.files === undefined || Array.isArray(value.files))
    && (value.embeds === undefined || Array.isArray(value.embeds))
}

function isFileEdit(value: unknown): value is FileEditEvent {
  if (!isRecord(value)) return false
  return optional(value.version, "number")
    && optional(value.call_id, "string")
    && optional(value.tool, "string")
    && optional(value.path, "string")
    && optional(value.phase, "string")
    && optional(value.status, "string")
    && optional(value.added, "number")
    && optional(value.deleted, "number")
    && optional(value.error, "string")
}

function decodeInboundEvent(value: unknown): InboundEvent | null | undefined {
  if (!isRecord(value)) return null
  const record = value
  const name = record.event
  if (typeof name !== "string") return null
  if (name === "ready") {
    return typeof record.chat_id === "string" && typeof record.client_id === "string"
      ? value as InboundEvent
      : null
  }
  if (name === "runtime_model_updated") {
    return typeof record.model_name === "string"
      && (record.model_preset === undefined
        || record.model_preset === null
        || typeof record.model_preset === "string")
      ? value as InboundEvent
      : null
  }
  if (name === "error" && (record.chat_id === undefined || typeof record.chat_id === "string")) {
    return optional(record.detail, "string") && optional(record.reason, "string")
      ? value as InboundEvent
      : null
  }
  if (!CHAT_EVENTS.has(name)) return undefined // Forward-compatible additive event.
  if (typeof record.chat_id !== "string") return null
  if (["message", "delta", "reasoning_delta"].includes(name) && typeof record.text !== "string") {
    return null
  }
  if (
    name === "message"
    && record.tool_events !== undefined
    && (!Array.isArray(record.tool_events) || !record.tool_events.every(isToolEvent))
  ) return null
  if (name === "file_edit" && (!Array.isArray(record.edits) || !record.edits.every(isFileEdit))) {
    return null
  }
  if (
    name === "stream_end"
    && (!optional(record.text, "string")
      || !optional(record.resuming, "boolean")
      || !optional(record.merge_next, "boolean"))
  ) return null
  if (name === "turn_end" && !optional(record.latency_ms, "number")) return null
  if (name === "goal_status" && record.status !== "running" && record.status !== "idle") return null
  if (name === "goal_state" && (!record.goal_state || typeof record.goal_state !== "object")) return null
  if (name === "turn_model_updated" && typeof record.model_name !== "string") return null
  return value as InboundEvent
}

export async function fetchHistory(
  apiUrl: string,
  apiToken: string,
  chatId: string,
  beforeCursor?: string | null,
): Promise<HistorySnapshot> {
  if (!apiUrl || !apiToken) {
    return { messages: [], hasMoreBefore: false, beforeCursor: null }
  }
  const key = encodeURIComponent(`websocket:${chatId}`)
  const params = new URLSearchParams({ limit: "120", direction: "latest" })
  if (beforeCursor) params.set("before", beforeCursor)
  const response = await fetch(`${apiUrl}/api/sessions/${key}/webui-thread?${params}`, {
    headers: { Authorization: `Bearer ${apiToken}` },
  })
  if (response.status === 404) {
    return { messages: [], hasMoreBefore: false, beforeCursor: null }
  }
  if (!response.ok) throw new Error(`history request failed: HTTP ${response.status}`)
  const payload = (await response.json()) as {
    messages?: Array<Record<string, unknown>>
    page?: { has_more_before?: boolean; before_cursor?: string }
  }
  const messages: HistoryMessage[] = (payload.messages || []).flatMap((message) => {
    const role = message.role
    const content = message.content
    if (role === "tool" && message.kind === "trace") {
      const traces = Array.isArray(message.traces)
        ? message.traces.filter((value): value is string => typeof value === "string")
        : []
      const toolEvents = Array.isArray(message.toolEvents)
        ? message.toolEvents as ToolProgressEvent[]
        : undefined
      const fileEdits = Array.isArray(message.fileEdits)
        ? message.fileEdits as FileEditEvent[]
        : undefined
      const activity = traces.join("\n") || (typeof content === "string" ? content : "")
      return [{ role: "activity", content: activity, toolEvents, fileEdits }]
    }
    if (
      (role !== "user" && role !== "assistant")
      || message.kind === "reasoning"
      || typeof content !== "string"
      || !content.trim()
    ) {
      return []
    }
    return [{ role: role as HistoryMessage["role"], content }]
  })
  return {
    messages,
    hasMoreBefore: payload.page?.has_more_before === true,
    beforeCursor: typeof payload.page?.before_cursor === "string"
      ? payload.page.before_cursor
      : null,
  }
}

export async function fetchSessionContext(
  apiUrl: string,
  apiToken: string,
  chatId: string,
): Promise<SessionContextSnapshot | null> {
  if (!apiUrl || !apiToken) return null
  const key = encodeURIComponent(`websocket:${chatId}`)
  const response = await fetch(`${apiUrl}/api/sessions/${key}/context`, {
    headers: { Authorization: `Bearer ${apiToken}` },
  })
  if (response.status === 404) return null
  if (!response.ok) throw new Error(`context request failed: HTTP ${response.status}`)
  const value = await response.json() as Record<string, unknown>
  const number = (key: string) => typeof value[key] === "number" ? value[key] as number : 0
  return {
    totalMessages: number("total_messages"),
    archivedMessages: number("archived_messages"),
    replayMessages: number("replay_messages"),
    estimatedReplayTokens: number("estimated_replay_tokens"),
    estimatedSummaryTokens: number("estimated_summary_tokens"),
    estimatedSessionTokens: number("estimated_session_tokens"),
    archivedSummary: typeof value.archived_summary === "string" ? value.archived_summary : null,
    archivedSummaryAt: typeof value.archived_summary_at === "string"
      ? value.archived_summary_at
      : null,
  }
}

export async function fetchSlashCommands(
  apiUrl: string,
  apiToken: string,
): Promise<SlashCommand[]> {
  if (!apiUrl || !apiToken) return []
  const response = await fetch(`${apiUrl}/api/commands`, {
    headers: { Authorization: `Bearer ${apiToken}` },
  })
  if (!response.ok) throw new Error(`command request failed: HTTP ${response.status}`)
  const payload = await response.json() as { commands?: unknown[] }
  return (payload.commands || []).flatMap((value) => {
    if (
      !isRecord(value)
      || typeof value.command !== "string"
      || typeof value.lifecycle !== "string"
      || !SLASH_COMMAND_LIFECYCLES.has(value.lifecycle)
    ) return []
    return [{
      command: value.command,
      title: typeof value.title === "string" ? value.title : value.command,
      description: typeof value.description === "string" ? value.description : "",
      argHint: typeof value.arg_hint === "string" ? value.arg_hint : "",
      lifecycle: value.lifecycle as SlashCommandLifecycle,
      acceptsArgs: value.accepts_args === true,
    }]
  })
}

export async function fetchSessions(
  apiUrl: string,
  apiToken: string,
): Promise<SessionSummary[]> {
  if (!apiUrl || !apiToken) return []
  const headers = { Authorization: `Bearer ${apiToken}` }
  const [response, sidebarResponse] = await Promise.all([
    fetch(`${apiUrl}/api/sessions`, { headers }),
    fetch(`${apiUrl}/api/webui/sidebar-state`, { headers }).catch(() => null),
  ])
  if (!response.ok) throw new Error(`session request failed: HTTP ${response.status}`)
  const payload = await response.json() as { sessions?: unknown[] }
  let sidebar: Record<string, unknown> = {}
  if (sidebarResponse?.ok) {
    try {
      const value: unknown = await sidebarResponse.json()
      if (isRecord(value)) sidebar = value
    } catch {
      // Session navigation remains available against older or damaged sidebar state.
    }
  }
  const pinned = new Set(Array.isArray(sidebar.pinned_keys) ? sidebar.pinned_keys : [])
  const archived = new Set(Array.isArray(sidebar.archived_keys) ? sidebar.archived_keys : [])
  const titles = isRecord(sidebar.title_overrides) ? sidebar.title_overrides : {}
  return (payload.sessions || []).flatMap((value) => {
    if (!isRecord(value) || typeof value.key !== "string" || !value.key.startsWith("websocket:")) {
      return []
    }
    const chatId = value.key.slice("websocket:".length)
    if (!chatId) return []
    const titleOverride = titles[value.key]
    return [{
      chatId,
      title: typeof titleOverride === "string"
        ? titleOverride
        : typeof value.title === "string" ? value.title : "",
      preview: typeof value.preview === "string" ? value.preview : "",
      createdAt: typeof value.created_at === "string" ? value.created_at : null,
      updatedAt: typeof value.updated_at === "string" ? value.updated_at : null,
      runStartedAt: typeof value.run_started_at === "number" ? value.run_started_at : null,
      pinned: pinned.has(value.key),
      archived: archived.has(value.key),
    }]
  })
}

export class NanobotClient {
  private socket: WebSocket | null = null
  private chatId = ""
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private reconnectAttempt = 0
  private closedByClient = false

  constructor(private readonly options: ClientOptions) {}

  get activeChatId(): string {
    return this.chatId
  }

  connect(): void {
    this.closedByClient = false
    this.open()
  }

  private open(): void {
    if (this.socket) return
    this.options.onStatus("connecting")
    const socket = new WebSocket(this.options.url)
    this.socket = socket
    socket.addEventListener("open", () => {
      if (this.socket !== socket) return
      this.reconnectAttempt = 0
      this.options.onStatus("connected")
    })
    socket.addEventListener("message", (message) => {
      if (this.socket === socket) this.handleMessage(String(message.data))
    })
    socket.addEventListener("error", () => {
      if (this.socket === socket) this.options.onStatus("error", "connection failed")
    })
    socket.addEventListener("close", () => {
      if (this.socket !== socket) return
      this.socket = null
      if (this.closedByClient) {
        this.options.onStatus("closed")
        return
      }
      this.scheduleReconnect()
    })
  }

  close(): void {
    this.closedByClient = true
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.reconnectTimer = null
    const socket = this.socket
    this.socket = null
    socket?.close()
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

  attach(chatId: string): void {
    if (!chatId) throw new Error("chat id is required")
    this.write({ type: "attach", chat_id: chatId })
  }

  newChat(): void {
    this.write({ type: "new_chat" })
  }

  private handleMessage(raw: string): void {
    let value: unknown
    try {
      value = JSON.parse(raw) as unknown
    } catch {
      this.options.onStatus("error", "gateway sent invalid JSON")
      return
    }
    const event = decodeInboundEvent(value)
    if (event === undefined) return
    if (event === null) {
      this.options.onStatus("error", "gateway sent an invalid event")
      return
    }

    if (event.event === "ready") {
      const requestedChatId = this.chatId || this.options.chatId
      if (requestedChatId) {
        this.chatId = requestedChatId
        this.write({ type: "attach", chat_id: this.chatId })
      } else {
        this.write({ type: "new_chat" })
      }
    } else if (event.event === "attached") {
      this.chatId = event.chat_id
    }
    this.options.onEvent(event)
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer || this.closedByClient) return
    const base = this.options.reconnectDelayMs ?? 500
    const delay = Math.min(8_000, base * 2 ** Math.min(this.reconnectAttempt++, 4))
    this.options.onStatus("connecting", `reconnecting in ${delay}ms`)
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      this.open()
    }, delay)
  }

  private write(event: OutboundEvent): void {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      throw new Error("gateway connection is not open")
    }
    this.socket.send(JSON.stringify(event))
  }
}
