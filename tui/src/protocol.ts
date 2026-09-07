import { decodeNotification, isCompactionPhase, isRecoveryState } from "../../packages/client-events/notifications"
import type { ContextCompaction, NotificationEvent, RecoveryState } from "../../packages/client-events/notifications"
export type { ContextCompaction, RecoveryState, RecoveryStatus, RetryStatus } from "../../packages/client-events/notifications"

export type ConnectionStatus =
  | "starting"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "unavailable"
  | "closed"
  | "error"

export interface ConnectionStatusInfo {
  endpoint: string
  attempt: number
  elapsedMs: number
  retryInMs?: number
  health?: GatewayHealthStatus
}

export type GatewayHealthStatus = "ready" | "degraded" | "unreachable"

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
  absolute_path?: string
  phase?: "start" | "end" | "error" | string
  added?: number
  deleted?: number
  approximate?: boolean
  status?: "editing" | "done" | "error" | string
  operation?: "edit" | "delete" | string
  binary?: boolean
  error?: string
  diff?: FileDiff
}

interface FileDiff {
  format: "unified" | string
  context?: number
  truncated?: boolean
  text?: string
}

export interface MediaAttachment {
  kind: "image" | "video" | "file"
  url: string
  name?: string
}

export interface OutboundMedia {
  data_url: string
  name?: string
}

export interface WorkspaceScopePayload {
  project_path: string
  project_name?: string
  access_mode: "restricted" | "full"
  restrict_to_workspace?: boolean
}

export interface RuntimeControls {
  modelPresets: Array<{ name: string; model: string }>
  canUseFullAccess: boolean
}

export type InboundEvent =
  | { event: "ready"; chat_id: string; client_id: string }
  | {
      event: "attached"
      chat_id: string
      model_preset?: string | null
      usage?: TokenUsage
      recovery_state?: RecoveryState
    }
  | {
      event: "message_accepted"
      chat_id: string
      turn_id: string
      starts_turn?: boolean
      active_turn_id?: string
      started_at?: number
    }
  | {
      event: "user_message"
      chat_id: string
      text: string
      turn_id?: string
      active_turn_id?: string
      starts_turn: boolean
      started_at?: number
      media_urls?: MediaAttachment[]
    }
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
  | {
      event: "turn_end"
      chat_id: string
      latency_ms?: number
      turn_id?: string
      usage?: TokenUsage
      context_window_tokens?: number
      goal_state?: Record<string, unknown>
      outcome?: "completed" | "failed" | "cancelled" | "interrupted"
      failure_kind?: string
      failure_error_kind?: string
      failure_attempts?: number
      failure_message?: string
    }
  | {
      event: "goal_status"
      chat_id: string
      status: "running" | "idle"
      started_at?: number
      turn_id?: string
    }
  | { event: "goal_state"; chat_id: string; goal_state: Record<string, unknown> }
  | NotificationEvent
  | {
      event: "session_updated"
      chat_id: string
      scope?: string
      workspace_scope?: WorkspaceScopePayload
    }
  | { event: "runtime_model_updated"; model_name: string; model_preset?: string | null }
  | {
      event: "turn_model_updated"
      chat_id: string
      model_name: string
      model_preset?: string | null
      context_window_tokens?: number
    }
  | { event: "error"; chat_id?: string; detail?: string; reason?: string; turn_id?: string }

type OutboundEvent =
  | { type: "new_chat"; workspace_scope?: WorkspaceScopePayload }
  | { type: "fork_chat"; source_chat_id: string; before_user_index: number; title?: string }
  | { type: "attach"; chat_id: string }
  | { type: "set_workspace_scope"; chat_id: string; workspace_scope: WorkspaceScopePayload }
  | {
      type: "webui_request"
      request_id: string
      action: string
      payload: Record<string, unknown>
    }
  | {
      type: "message"
      chat_id: string
      content: string
      turn_id: string
      webui: true
      workspace_scope?: WorkspaceScopePayload
      media?: OutboundMedia[]
      cli_apps?: Array<{ name: string }>
      mcp_presets?: Array<{ name: string }>
      session_mentions?: SessionMention[]
    }

export interface ClientOptions {
  url?: string
  resolveConnection?: () => Promise<GatewayConnection>
  checkHealth?: () => Promise<GatewayHealthStatus>
  onConnection?: (connection: GatewayConnection) => void
  targetEndpoint?: string
  startupFailureDelayMs?: number
  startupRetryMaxDelayMs?: number
  chatId?: string
  initialWorkspaceScope?: WorkspaceScopePayload
  reconnectDelayMs?: number
  onEvent: (event: InboundEvent) => void
  onStatus: (status: ConnectionStatus, detail?: string, info?: ConnectionStatusInfo) => void
}

export interface GatewayApiConnection {
  apiUrl: string
  apiToken: string
}

export interface GatewayConnection extends GatewayApiConnection {
  wsUrl: string
}

export type ApiReauthenticator = (
  rejectedApiToken: string,
) => Promise<GatewayApiConnection>

export class GatewayConnectionError extends Error {
  constructor(message: string, readonly retryable: boolean) {
    super(message)
    this.name = "GatewayConnectionError"
  }
}

export interface HistoryMessage {
  role: "user" | "assistant" | "activity"
  content: string
  turnId?: string
  media?: MediaAttachment[]
  toolEvents?: ToolProgressEvent[]
  fileEdits?: FileEditEvent[]
  compaction?: ContextCompaction
  forkIndex?: number
}

export interface HistorySnapshot {
  messages: HistoryMessage[]
  hasMoreBefore: boolean
  beforeCursor: string | null
  userMessageOffset: number
}

export interface TokenUsage {
  prompt_tokens?: number
  completion_tokens?: number
  cached_tokens?: number
  cache_write_tokens?: number
  total_tokens?: number
  context_tokens?: number
  request_count?: number
  provider_tokens?: number
  estimated_tokens?: number
  cost_usd?: number
  generation_ms?: number
  measured_completion_tokens?: number
  ttft_ms?: number
  timed_requests?: number
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
  lastUsage: TokenUsage | null
}

interface SessionMention {
  name: string
  session_key: string
  title?: string
}

export interface MentionCandidate {
  kind: "session" | "cli" | "mcp"
  name: string
  targetName?: string
  displayName: string
  description: string
  session?: SessionMention
}

export interface SkillCandidate {
  name: string
  description: string
  source: string
}

export interface MessageOptions {
  media?: OutboundMedia[]
  cliApps?: Array<{ name: string }>
  mcpPresets?: Array<{ name: string }>
  sessionMentions?: SessionMention[]
  userShell?: boolean
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
  modelPreset: string | null
  recoveryState?: RecoveryState | null
  workspaceScope?: WorkspaceScopePayload | null
  pinned: boolean
  archived: boolean
}

const SKILL_REFERENCE_NAME = /^[A-Za-z0-9_-]+$/u

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
  "user_message",
  "message",
  "file_edit",
  "delta",
  "stream_end",
  "reasoning_delta",
  "reasoning_end",
  "retry_status",
  "turn_end",
  "goal_status",
  "goal_state",
  "recovery_state",
  "context_compaction",
  "session_updated",
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
    && optional(value.absolute_path, "string")
    && optional(value.phase, "string")
    && optional(value.status, "string")
    && optional(value.added, "number")
    && optional(value.deleted, "number")
    && optional(value.approximate, "boolean")
    && optional(value.operation, "string")
    && optional(value.binary, "boolean")
    && optional(value.error, "string")
    && (value.diff === undefined || isFileDiff(value.diff))
}

function isFileDiff(value: unknown): value is FileDiff {
  if (!isRecord(value) || typeof value.format !== "string") return false
  return optional(value.context, "number")
    && optional(value.truncated, "boolean")
    && optional(value.text, "string")
}

function isTokenUsage(value: unknown): value is TokenUsage {
  if (!isRecord(value)) return false
  return [
    "prompt_tokens",
    "completion_tokens",
    "cached_tokens",
    "cache_write_tokens",
    "total_tokens",
    "context_tokens",
    "request_count",
    "provider_tokens",
    "estimated_tokens",
    "cost_usd",
    "generation_ms",
    "measured_completion_tokens",
    "ttft_ms",
    "timed_requests",
  ].every((key) => optional(value[key], "number"))
}

function isMediaAttachment(value: unknown): value is MediaAttachment {
  return isRecord(value)
    && (value.kind === "image" || value.kind === "video" || value.kind === "file")
    && typeof value.url === "string"
    && optional(value.name, "string")
}

function isWorkspaceScope(value: unknown): value is WorkspaceScopePayload {
  return isRecord(value)
    && typeof value.project_path === "string"
    && (value.access_mode === "restricted" || value.access_mode === "full")
    && optional(value.project_name, "string")
    && optional(value.restrict_to_workspace, "boolean")
}

interface WebUIResponseEvent {
  event: "webui_response"
  request_id: string
  ok: boolean
  result?: unknown
  error?: { status: number; message: string }
}

function decodeWebUIResponse(value: unknown): WebUIResponseEvent | null | undefined {
  if (!isRecord(value) || value.event !== "webui_response") return undefined
  if (typeof value.request_id !== "string" || typeof value.ok !== "boolean") return null
  if (value.ok) return value as unknown as WebUIResponseEvent
  return isRecord(value.error)
    && typeof value.error.status === "number"
    && typeof value.error.message === "string"
    ? value as unknown as WebUIResponseEvent
    : null
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
  if (
    name === "attached"
    && ((record.model_preset !== undefined
      && record.model_preset !== null
      && typeof record.model_preset !== "string")
      || (record.usage !== undefined && !isTokenUsage(record.usage))
      || (record.recovery_state !== undefined && !isRecoveryState(record.recovery_state)))
  ) return null
  if (
    ["user_message", "message", "delta", "reasoning_delta"].includes(name)
    && typeof record.text !== "string"
  ) {
    return null
  }
  if (
    ["message_accepted", "user_message"].includes(name)
    && (
      (name === "user_message" && typeof record.starts_turn !== "boolean")
      || !optional(record.starts_turn, "boolean")
      || !optional(record.active_turn_id, "string")
      || !optional(record.started_at, "number")
    )
  ) return null
  if (
    name === "user_message"
    && record.media_urls !== undefined
    && (!Array.isArray(record.media_urls) || !record.media_urls.every(isMediaAttachment))
  ) return null
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
  if (
    name === "turn_end"
    && (!optional(record.latency_ms, "number")
      || !optional(record.context_window_tokens, "number")
      || (record.usage !== undefined && !isTokenUsage(record.usage))
      || (record.goal_state !== undefined && !isRecord(record.goal_state))
      || (record.outcome !== undefined
        && !["completed", "failed", "cancelled", "interrupted"].includes(String(record.outcome)))
      || !optional(record.failure_kind, "string")
      || !optional(record.failure_error_kind, "string")
      || (record.failure_attempts !== undefined
        && (typeof record.failure_attempts !== "number"
          || !Number.isInteger(record.failure_attempts)
          || record.failure_attempts < 1))
      || !optional(record.failure_message, "string"))
  ) return null
  if (name === "goal_status" && record.status !== "running" && record.status !== "idle") return null
  if (name === "goal_state" && !isRecord(record.goal_state)) return null
  if (decodeNotification(record) === null) return null
  if (
    name === "session_updated"
    && (!optional(record.scope, "string")
      || (record.workspace_scope !== undefined && !isWorkspaceScope(record.workspace_scope)))
  ) return null
  if (
    name === "turn_model_updated"
    && (typeof record.model_name !== "string"
      || (record.model_preset !== undefined
        && record.model_preset !== null
        && typeof record.model_preset !== "string")
      || !optional(record.context_window_tokens, "number"))
  ) return null
  return value as InboundEvent
}

async function fetchApi(
  apiUrl: string,
  apiToken: string,
  path: string,
  reauthenticate?: ApiReauthenticator,
): Promise<Response> {
  const request = (connection: GatewayApiConnection) => fetch(`${connection.apiUrl}${path}`, {
    headers: { Authorization: `Bearer ${connection.apiToken}` },
  })
  const response = await request({ apiUrl, apiToken })
  if (response.status !== 401 || !reauthenticate) return response
  return request(await reauthenticate(apiToken))
}

export async function fetchHistory(
  apiUrl: string,
  apiToken: string,
  chatId: string,
  beforeCursor?: string | null,
  reauthenticate?: ApiReauthenticator,
): Promise<HistorySnapshot> {
  if (!apiUrl || !apiToken) {
    return { messages: [], hasMoreBefore: false, beforeCursor: null, userMessageOffset: 0 }
  }
  const key = encodeURIComponent(`websocket:${chatId}`)
  const params = new URLSearchParams({ limit: "120", direction: "latest" })
  if (beforeCursor) params.set("before", beforeCursor)
  const response = await fetchApi(
    apiUrl,
    apiToken,
    `/api/sessions/${key}/webui-thread?${params}`,
    reauthenticate,
  )
  if (response.status === 404) {
    return { messages: [], hasMoreBefore: false, beforeCursor: null, userMessageOffset: 0 }
  }
  if (!response.ok) throw new Error(`history request failed: HTTP ${response.status}`)
  const payload = (await response.json()) as {
    messages?: Array<Record<string, unknown>>
    page?: { has_more_before?: boolean; before_cursor?: string; user_message_offset?: number }
  }
  let userIndex = typeof payload.page?.user_message_offset === "number"
    ? Math.max(0, payload.page.user_message_offset)
    : 0
  const messages: HistoryMessage[] = []
  for (const message of payload.messages || []) {
    const role = message.role
    const content = message.content
    if (message.kind === "compaction") {
      const compaction = message.compaction
      if (isRecord(compaction)
        && typeof compaction.id === "string"
        && compaction.id
        && isCompactionPhase(compaction.phase)) {
        messages.push({
          role: "activity",
          content: "",
          compaction: { id: compaction.id, phase: compaction.phase },
        })
      }
      continue
    }
    if (role === "tool" && message.kind === "trace") {
      const traces = Array.isArray(message.traces)
        ? message.traces.filter((value): value is string => typeof value === "string")
        : []
      const toolEvents = Array.isArray(message.toolEvents)
        ? message.toolEvents.filter(isToolEvent)
        : undefined
      const fileEdits = Array.isArray(message.fileEdits)
        ? message.fileEdits.filter(isFileEdit)
        : undefined
      const activity = traces.join("\n") || (typeof content === "string" ? content : "")
      messages.push({
        role: "activity",
        content: activity,
        ...(toolEvents?.length ? { toolEvents } : {}),
        ...(fileEdits?.length ? { fileEdits } : {}),
      })
      continue
    }
    if (
      (role !== "user" && role !== "assistant")
      || message.kind === "reasoning"
      || typeof content !== "string"
    ) {
      continue
    }
    const media = Array.isArray(message.media) ? message.media.filter(isMediaAttachment) : []
    if (role === "user") {
      if (!content.trim() && !media.length) continue
      userIndex += 1
      messages.push({
        role: "user",
        content,
        ...(media.length ? { media } : {}),
        ...(typeof message.turnId === "string" ? { turnId: message.turnId } : {}),
      })
    } else if (content.trim()) {
      messages.push({ role: "assistant", content, forkIndex: userIndex })
    }
  }
  return {
    messages,
    hasMoreBefore: payload.page?.has_more_before === true,
    beforeCursor: typeof payload.page?.before_cursor === "string"
      ? payload.page.before_cursor
      : null,
    userMessageOffset: typeof payload.page?.user_message_offset === "number"
      ? Math.max(0, payload.page.user_message_offset)
      : 0,
  }
}

export async function fetchSessionContext(
  apiUrl: string,
  apiToken: string,
  chatId: string,
  reauthenticate?: ApiReauthenticator,
): Promise<SessionContextSnapshot | null> {
  if (!apiUrl || !apiToken) return null
  const key = encodeURIComponent(`websocket:${chatId}`)
  const response = await fetchApi(
    apiUrl,
    apiToken,
    `/api/sessions/${key}/context`,
    reauthenticate,
  )
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
    lastUsage: isTokenUsage(value.last_usage) ? value.last_usage : null,
  }
}

export async function fetchSlashCommands(
  apiUrl: string,
  apiToken: string,
  reauthenticate?: ApiReauthenticator,
): Promise<SlashCommand[]> {
  if (!apiUrl || !apiToken) return []
  const response = await fetchApi(apiUrl, apiToken, "/api/commands", reauthenticate)
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

export async function fetchAvailableSkills(
  apiUrl: string,
  apiToken: string,
  reauthenticate?: ApiReauthenticator,
): Promise<SkillCandidate[]> {
  if (!apiUrl || !apiToken) return []
  const response = await fetchApi(apiUrl, apiToken, "/api/webui/skills", reauthenticate)
  if (!response.ok) throw new Error(`skill request failed: HTTP ${response.status}`)
  const payload = await response.json() as { skills?: unknown[] }
  return (payload.skills || []).flatMap((value) => {
    if (
      !isRecord(value)
      || typeof value.name !== "string"
      || !SKILL_REFERENCE_NAME.test(value.name)
      || value.enabled !== true
      || value.available !== true
    ) return []
    return [{
      name: value.name,
      description: typeof value.description === "string" ? value.description : value.name,
      source: typeof value.source === "string" ? value.source : "unknown",
    }]
  })
}

export async function fetchRuntimeControls(
  apiUrl: string,
  apiToken: string,
  reauthenticate?: ApiReauthenticator,
): Promise<RuntimeControls> {
  if (!apiUrl || !apiToken) return { modelPresets: [], canUseFullAccess: false }
  const [settingsResponse, workspacesResponse] = await Promise.all([
    fetchApi(apiUrl, apiToken, "/api/settings", reauthenticate),
    fetchApi(apiUrl, apiToken, "/api/workspaces", reauthenticate).catch(() => null),
  ])
  if (!settingsResponse.ok) {
    throw new Error(`settings request failed: HTTP ${settingsResponse.status}`)
  }
  const settings = await settingsResponse.json() as { model_presets?: unknown[] }
  const workspaces = workspacesResponse?.ok
    ? await workspacesResponse.json() as { controls?: unknown }
    : {}
  const modelPresets = (settings.model_presets || []).flatMap((value) => {
    if (!isRecord(value) || typeof value.name !== "string" || typeof value.model !== "string") {
      return []
    }
    const name = value.name.trim()
    return name ? [{ name, model: value.model.trim() }] : []
  })
  const controls = isRecord(workspaces.controls) ? workspaces.controls : {}
  return {
    modelPresets,
    canUseFullAccess: controls.can_use_full_access === true,
  }
}

export async function fetchSessions(
  apiUrl: string,
  apiToken: string,
  reauthenticate?: ApiReauthenticator,
): Promise<SessionSummary[]> {
  if (!apiUrl || !apiToken) return []
  const [response, sidebarResponse] = await Promise.all([
    fetchApi(apiUrl, apiToken, "/api/sessions", reauthenticate),
    fetchApi(apiUrl, apiToken, "/api/webui/sidebar-state", reauthenticate).catch(() => null),
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
      modelPreset: typeof value.model_preset === "string" && value.model_preset.trim()
        ? value.model_preset.trim()
        : null,
      ...(isRecoveryState(value.recovery_state)
        ? { recoveryState: value.recovery_state }
        : {}),
      ...(isWorkspaceScope(value.workspace_scope) ? { workspaceScope: value.workspace_scope } : {}),
      pinned: pinned.has(value.key),
      archived: archived.has(value.key),
    }]
  })
}

function sessionMentionName(session: SessionSummary): string {
  const label = (session.title || session.preview || "session")
    .normalize("NFKC")
    .replace(/\s+/gu, "-")
    .replace(/[^\p{L}\p{N}_-]+/gu, "")
    .replace(/-+/gu, "-")
    .replace(/^-|-$/gu, "")
  return Array.from(label || "session").slice(0, 40).join("")
}

/** Installed capabilities and saved chats share one mention namespace. */
export async function fetchMentionCandidates(
  apiUrl: string,
  apiToken: string,
  reauthenticate?: ApiReauthenticator,
): Promise<MentionCandidate[]> {
  if (!apiUrl || !apiToken) return []
  const [sessions, appsResponse, mcpResponse] = await Promise.all([
    fetchSessions(apiUrl, apiToken, reauthenticate),
    fetchApi(
      apiUrl,
      apiToken,
      "/api/settings/cli-apps?installed_only=1",
      reauthenticate,
    ).catch(() => null),
    fetchApi(apiUrl, apiToken, "/api/settings/mcp-presets", reauthenticate).catch(() => null),
  ])
  const used = new Set<string>()
  const uniqueName = (raw: string) => {
    const base = raw || "session"
    let name = base
    let suffix = 2
    while (used.has(name.toLocaleLowerCase())) name = `${base}-${suffix++}`
    used.add(name.toLocaleLowerCase())
    return name
  }
  const candidates: MentionCandidate[] = []
  if (appsResponse?.ok) {
    const payload = await appsResponse.json() as { apps?: unknown[] }
    for (const value of payload.apps || []) {
      if (!isRecord(value) || value.installed !== true || typeof value.name !== "string") continue
      const name = uniqueName(value.name)
      candidates.push({
        kind: "cli",
        name,
        ...(name === value.name ? {} : { targetName: value.name }),
        displayName: typeof value.display_name === "string" ? value.display_name : name,
        description: typeof value.description === "string" ? value.description : "CLI app",
      })
    }
  }
  if (mcpResponse?.ok) {
    const payload = await mcpResponse.json() as { presets?: unknown[] }
    for (const value of payload.presets || []) {
      if (
        !isRecord(value)
        || value.installed !== true
        || value.configured !== true
        || typeof value.name !== "string"
      ) continue
      const name = uniqueName(value.name)
      candidates.push({
        kind: "mcp",
        name,
        ...(name === value.name ? {} : { targetName: value.name }),
        displayName: typeof value.display_name === "string" ? value.display_name : name,
        description: typeof value.description === "string" ? value.description : "MCP server",
      })
    }
  }
  for (const session of sessions) {
    const name = uniqueName(sessionMentionName(session))
    candidates.push({
      kind: "session",
      name,
      displayName: sessionLabelForMention(session),
      description: session.preview || "Saved session",
      session: {
        name,
        session_key: `websocket:${session.chatId}`,
        title: session.title || undefined,
      },
    })
  }
  return candidates
}

function sessionLabelForMention(session: SessionSummary): string {
  return (session.title || session.preview || "Untitled chat").replace(/\s+/gu, " ").trim()
}

/** Resolve fresh short-lived credentials once the local gateway is reachable. */
export async function fetchGatewayConnection(
  bootstrapUrl: string,
  bootstrapSecret: string,
  apiUrl: string,
  clientId: string,
): Promise<GatewayConnection> {
  const response = await fetch(bootstrapUrl, {
    headers: bootstrapSecret ? { "X-Nanobot-Auth": bootstrapSecret } : {},
  })
  if (!response.ok) {
    const retryable = response.status === 408 || response.status === 429 || response.status >= 500
    throw new GatewayConnectionError(
      `gateway bootstrap failed: HTTP ${response.status}`,
      retryable,
    )
  }
  let payload: unknown
  try {
    payload = await response.json()
  } catch {
    throw new GatewayConnectionError("gateway bootstrap response is invalid", false)
  }
  if (!isRecord(payload)) {
    throw new GatewayConnectionError("gateway bootstrap response is invalid", false)
  }
  if (typeof payload.ws_url !== "string" || !payload.ws_url.trim()) {
    throw new GatewayConnectionError("gateway bootstrap response is missing ws_url", false)
  }
  let wsUrl: URL
  try {
    wsUrl = new URL(payload.ws_url)
  } catch {
    throw new GatewayConnectionError("gateway bootstrap response has an invalid ws_url", false)
  }
  if (wsUrl.protocol !== "ws:" && wsUrl.protocol !== "wss:") {
    throw new GatewayConnectionError("gateway bootstrap response has an invalid ws_url", false)
  }
  if (typeof payload.token === "string" && payload.token) {
    wsUrl.searchParams.append("token", payload.token)
  }
  wsUrl.searchParams.append("client_id", clientId)
  return {
    wsUrl: wsUrl.toString(),
    apiUrl,
    apiToken: typeof payload.api_token === "string" ? payload.api_token : "",
  }
}

/** Read gateway readiness without sending bootstrap or API credentials. */
export async function fetchGatewayHealth(
  healthUrl: string,
  timeoutMs = 400,
): Promise<GatewayHealthStatus> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetch(healthUrl, { signal: controller.signal })
    if (response.status !== 200 && response.status !== 503) return "unreachable"
    const payload: unknown = await response.json()
    if (!isRecord(payload)) return "unreachable"
    if (
      response.status === 503
      && payload.status === "degraded"
      && payload.ready === false
      && payload.process === "alive"
    ) return "degraded"
    if (response.status === 200 && payload.status === "ok" && payload.ready !== false) {
      return "ready"
    }
    return "unreachable"
  } catch {
    return "unreachable"
  } finally {
    clearTimeout(timer)
  }
}

/** Return only the authority users can act on, never credentials or an authenticated path. */
export function connectionEndpoint(value: string | undefined): string {
  if (!value) return "local gateway"
  try {
    return new URL(value).host || "local gateway"
  } catch {
    return "local gateway"
  }
}

/** Reduce arbitrary fetch/WebSocket errors to a small set of credential-safe reasons. */
export function sanitizeConnectionFailure(error: unknown): string {
  const signals: string[] = []
  const seen = new Set<unknown>()
  const collect = (value: unknown): void => {
    if (value === null || value === undefined || seen.has(value)) return
    if (typeof value === "object") seen.add(value)
    if (typeof value === "string") {
      signals.push(value)
      return
    }
    if (value instanceof Error) {
      signals.push(value.name, value.message)
      collect(value.cause)
      if (value instanceof AggregateError) {
        for (const nested of value.errors) collect(nested)
      }
      return
    }
    if (!isRecord(value)) return
    if (typeof value.code === "string") signals.push(value.code)
    collect(value.cause)
    if (Array.isArray(value.errors)) {
      for (const nested of value.errors) collect(nested)
    }
  }
  collect(error)
  const signal = signals.join(" ")
  if (/ECONNREFUSED|connection refused/iu.test(signal)) return "connection refused"
  if (/ETIMEDOUT|timed? out|timeout/iu.test(signal)) return "connection timed out"
  if (/ENOTFOUND|EAI_AGAIN|name not resolved|host not found/iu.test(signal)) {
    return "host not found"
  }
  if (/certificate|TLS|SSL/iu.test(signal)) return "secure connection failed"
  const bootstrapStatus = signal.match(/gateway bootstrap failed:\s*HTTP\s*(\d{3})/iu)
  if (bootstrapStatus?.[1]) return `gateway bootstrap failed: HTTP ${bootstrapStatus[1]}`
  if (/bootstrap response is missing ws_url/iu.test(signal)) {
    return "gateway bootstrap response is missing ws_url"
  }
  if (/bootstrap response (?:has an invalid ws_url|is invalid)/iu.test(signal)) {
    return "gateway bootstrap response is invalid"
  }
  if (/gateway is still starting/iu.test(signal)) return "gateway is still starting"
  if (/fetch failed|failed to fetch|network error/iu.test(signal)) return "network request failed"
  return "connection failed"
}

export class NanobotClient {
  private socket: WebSocket | null = null
  private chatId = ""
  private workspaceScope?: WorkspaceScopePayload
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private reconnectAttempt = 0
  private closedByClient = false
  private opening = false
  private connectedOnce = false
  private connectionAttempt = 0
  private retryStartedAt = 0
  private nextRetryAt = 0
  private lastFailure = ""
  private healthStatus: GatewayHealthStatus | undefined
  private failureEscalationTimer: ReturnType<typeof setTimeout> | null = null
  private readonly endpoint: string
  private readonly pendingMutations = new Map<string, {
    resolve: (value: unknown) => void
    reject: (error: Error) => void
    timer: ReturnType<typeof setTimeout>
  }>()

  constructor(private readonly options: ClientOptions) {
    this.endpoint = options.targetEndpoint || connectionEndpoint(options.url)
  }

  get activeChatId(): string {
    return this.chatId
  }

  connect(): void {
    this.closedByClient = false
    this.connectionAttempt = 0
    this.reconnectAttempt = 0
    this.retryStartedAt = Date.now()
    this.nextRetryAt = 0
    this.lastFailure = ""
    this.healthStatus = undefined
    void this.open()
  }

  private async open(): Promise<void> {
    if (this.socket || this.opening || this.closedByClient) return
    this.opening = true
    this.nextRetryAt = 0
    this.connectionAttempt += 1
    this.reportConnectionProgress()
    let url = this.options.url
    try {
      if (this.options.resolveConnection) {
        const connection = await this.options.resolveConnection()
        if (this.closedByClient) return
        this.options.onConnection?.(connection)
        url = connection.wsUrl
      }
    } catch (error) {
      if (!this.closedByClient) {
        this.lastFailure = sanitizeConnectionFailure(error)
        if (error instanceof GatewayConnectionError && !error.retryable) {
          this.clearFailureEscalation()
          this.options.onStatus("error", this.lastFailure, this.connectionInfo())
          return
        }
        await this.checkHealthAndScheduleReconnect()
      }
      return
    } finally {
      this.opening = false
    }
    if (!url) {
      this.options.onStatus("error", "gateway URL is not configured", this.connectionInfo())
      return
    }
    let socket: WebSocket
    try {
      socket = new WebSocket(url)
    } catch (error) {
      this.lastFailure = sanitizeConnectionFailure(error)
      await this.checkHealthAndScheduleReconnect()
      return
    }
    let opened = false
    this.socket = socket
    socket.addEventListener("open", () => {
      if (this.socket !== socket) return
      opened = true
      this.connectedOnce = true
      this.connectionAttempt = 0
      this.reconnectAttempt = 0
      this.retryStartedAt = 0
      this.nextRetryAt = 0
      this.lastFailure = ""
      this.healthStatus = "ready"
      this.clearFailureEscalation()
      this.options.onStatus("connected", undefined, this.connectionInfo())
    })
    socket.addEventListener("message", (message) => {
      if (this.socket === socket) this.handleMessage(String(message.data))
    })
    socket.addEventListener("error", () => {
      if (this.socket !== socket) return
      this.lastFailure = "connection failed"
      this.reportRetryState()
    })
    socket.addEventListener("close", () => {
      if (this.socket !== socket) return
      this.socket = null
      this.rejectPendingMutations("gateway connection closed")
      if (this.closedByClient) {
        this.options.onStatus("closed")
        return
      }
      if (opened) {
        this.connectionAttempt = 0
        this.reconnectAttempt = 0
        this.retryStartedAt = Date.now()
      }
      if (!this.lastFailure) this.lastFailure = "connection closed"
      this.reportRetryState()
      void this.checkHealthAndScheduleReconnect()
    })
  }

  close(): void {
    this.closedByClient = true
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.reconnectTimer = null
    this.clearFailureEscalation()
    const socket = this.socket
    this.socket = null
    socket?.close()
    this.rejectPendingMutations("gateway connection closed")
  }

  send(content: string, options: MessageOptions = {}): string {
    if (!this.chatId) throw new Error("chat is not ready")
    const turnId = crypto.randomUUID()
    this.write({
      type: "message",
      chat_id: this.chatId,
      content,
      turn_id: turnId,
      webui: true,
      ...(this.workspaceScope ? { workspace_scope: this.workspaceScope } : {}),
      ...(options.userShell ? { user_shell: true } : {}),
      ...(options.media?.length ? { media: options.media } : {}),
      ...(options.cliApps?.length ? { cli_apps: options.cliApps } : {}),
      ...(options.mcpPresets?.length ? { mcp_presets: options.mcpPresets } : {}),
      ...(options.sessionMentions?.length
        ? { session_mentions: options.sessionMentions }
        : {}),
    })
    return turnId
  }

  attach(chatId: string): void {
    if (!chatId) throw new Error("chat id is required")
    this.workspaceScope = undefined
    this.write({ type: "attach", chat_id: chatId })
  }

  newChat(scope?: WorkspaceScopePayload): void {
    this.workspaceScope = scope
    this.write({ type: "new_chat", ...(scope ? { workspace_scope: scope } : {}) })
  }

  forkChat(sourceChatId: string, beforeUserIndex: number, title?: string): void {
    this.write({
      type: "fork_chat",
      source_chat_id: sourceChatId,
      before_user_index: beforeUserIndex,
      ...(title?.trim() ? { title: title.trim() } : {}),
    })
  }

  setWorkspaceScope(scope: WorkspaceScopePayload): void {
    if (!this.chatId) throw new Error("chat is not ready")
    this.workspaceScope = scope
    this.write({ type: "set_workspace_scope", chat_id: this.chatId, workspace_scope: scope })
  }

  updateRecovery(
    action: "continue" | "dismiss",
    chatId: string,
    recoveryId: string,
  ): Promise<RecoveryState> {
    return this.requestMutation<unknown>(`recovery.${action}`, {
      chat_id: chatId,
      recovery_id: recoveryId,
    }).then((result) => {
      if (!isRecoveryState(result)) throw new Error("gateway returned an invalid recovery state")
      return result
    })
  }

  private requestMutation<T>(
    action: string,
    payload: Record<string, unknown> = {},
    timeoutMs = 20_000,
  ): Promise<T> {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      return Promise.reject(new Error("gateway connection is not open"))
    }
    const requestId = crypto.randomUUID()
    const frame = JSON.stringify({
      type: "webui_request",
      request_id: requestId,
      action,
      payload,
    } satisfies OutboundEvent)
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pendingMutations.delete(requestId)
        reject(new Error(`gateway request timed out after ${timeoutMs}ms`))
      }, timeoutMs)
      this.pendingMutations.set(requestId, {
        resolve: (value) => resolve(value as T),
        reject,
        timer,
      })
      try {
        this.socket?.send(frame)
      } catch {
        clearTimeout(timer)
        this.pendingMutations.delete(requestId)
        reject(new Error("could not send gateway request"))
      }
    })
  }

  private rejectPendingMutations(message: string): void {
    for (const pending of this.pendingMutations.values()) {
      clearTimeout(pending.timer)
      pending.reject(new Error(message))
    }
    this.pendingMutations.clear()
  }

  private handleMessage(raw: string): void {
    let value: unknown
    try {
      value = JSON.parse(raw) as unknown
    } catch {
      this.options.onStatus("error", "gateway sent invalid JSON")
      return
    }
    const response = decodeWebUIResponse(value)
    if (response === null) {
      this.options.onStatus("error", "gateway sent an invalid event")
      return
    }
    if (response) {
      const pending = this.pendingMutations.get(response.request_id)
      if (!pending) return
      clearTimeout(pending.timer)
      this.pendingMutations.delete(response.request_id)
      if (response.ok) pending.resolve(response.result)
      else pending.reject(new Error(response.error?.message || "gateway request failed"))
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
        this.newChat(this.options.initialWorkspaceScope)
      }
    } else if (event.event === "attached") {
      this.chatId = event.chat_id
    } else if (event.event === "session_updated" && event.workspace_scope) {
      this.workspaceScope = event.workspace_scope
    }
    this.options.onEvent(event)
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer || this.closedByClient) return
    if (!this.retryStartedAt) this.retryStartedAt = Date.now()
    const base = this.options.reconnectDelayMs ?? 500
    const maxDelay = this.connectedOnce
      ? 8_000
      : this.options.startupRetryMaxDelayMs ?? 8_000
    const delay = Math.min(maxDelay, base * 2 ** Math.min(this.reconnectAttempt++, 4))
    this.nextRetryAt = Date.now() + delay
    this.reportRetryState()
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      void this.open()
    }, delay)
  }

  private async checkHealthAndScheduleReconnect(): Promise<void> {
    if (this.options.checkHealth) {
      try {
        this.healthStatus = await this.options.checkHealth()
      } catch {
        this.healthStatus = "unreachable"
      }
    }
    if (!this.closedByClient) this.scheduleReconnect()
  }

  private connectionInfo(): ConnectionStatusInfo {
    return {
      endpoint: this.endpoint,
      attempt: Math.max(1, this.connectionAttempt),
      elapsedMs: this.retryStartedAt ? Math.max(0, Date.now() - this.retryStartedAt) : 0,
      ...(this.nextRetryAt
        ? { retryInMs: Math.max(0, this.nextRetryAt - Date.now()) }
        : {}),
      ...(this.healthStatus ? { health: this.healthStatus } : {}),
    }
  }

  private reportConnectionProgress(): void {
    if (this.connectedOnce) {
      this.options.onStatus("reconnecting", this.lastFailure || undefined, this.connectionInfo())
      return
    }
    const phase = this.options.resolveConnection ? "starting" : "connecting"
    this.options.onStatus(phase, undefined, this.connectionInfo())
  }

  private reportRetryState(): void {
    const info = this.connectionInfo()
    if (this.connectedOnce) {
      this.options.onStatus("reconnecting", this.lastFailure, info)
      return
    }
    const failureDelay = this.options.startupFailureDelayMs ?? 3_000
    if (info.elapsedMs >= failureDelay) {
      this.clearFailureEscalation()
      this.options.onStatus("unavailable", this.lastFailure, info)
      return
    }
    this.reportConnectionProgress()
    if (this.failureEscalationTimer) return
    this.failureEscalationTimer = setTimeout(() => {
      this.failureEscalationTimer = null
      if (this.closedByClient || this.connectedOnce || !this.lastFailure) return
      this.options.onStatus("unavailable", this.lastFailure, this.connectionInfo())
    }, Math.max(0, failureDelay - info.elapsedMs))
  }

  private clearFailureEscalation(): void {
    if (this.failureEscalationTimer) clearTimeout(this.failureEscalationTimer)
    this.failureEscalationTimer = null
  }

  private write(event: OutboundEvent): void {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      throw new Error("gateway connection is not open")
    }
    this.socket.send(JSON.stringify(event))
  }
}
