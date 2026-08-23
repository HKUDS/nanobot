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

interface MediaAttachment {
  kind: "image" | "video" | "file"
  url: string
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

export type RecoveryStatus = "resuming" | "awaiting_user" | "recovered" | "failed"

export interface RecoveryState {
  status: RecoveryStatus
  recovery_id: string
  reason?: string
  attempts?: number
  can_continue?: boolean
}

export interface ConfigEditorSecret {
  path: string
  configured: boolean
}

export interface ConfigEditorSection {
  id: string
  label: string
  description: string
  prefixes: string[]
}

export interface ConfigEditorPresentation {
  primary_paths: string[]
  provider_primary_fields: string[]
  sections: ConfigEditorSection[]
  deprecated_paths: string[]
}

export interface ConfigEditorSnapshot {
  version: number
  revision: string
  config: Record<string, unknown>
  schema: Record<string, unknown>
  secrets: ConfigEditorSecret[]
  presentation: ConfigEditorPresentation
  requires_restart?: boolean
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
    }
  | {
      event: "goal_status"
      chat_id: string
      status: "running" | "idle"
      started_at?: number
      turn_id?: string
    }
  | { event: "goal_state"; chat_id: string; goal_state: Record<string, unknown> }
  | ({ event: "recovery_state"; chat_id: string } & RecoveryState)
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
      cli_apps?: Array<{ name: string }>
      mcp_presets?: Array<{ name: string }>
      session_mentions?: SessionMention[]
    }
  | {
      type: "webui_request"
      request_id: string
      action: string
      payload: Record<string, unknown>
    }

export interface ClientOptions {
  url?: string
  resolveConnection?: () => Promise<GatewayConnection>
  onConnection?: (connection: GatewayConnection) => void
  connectionRetryLabel?: string
  startupRetryMaxDelayMs?: number
  chatId?: string
  initialWorkspaceScope?: WorkspaceScopePayload
  reconnectDelayMs?: number
  onEvent: (event: InboundEvent) => void
  onStatus: (status: ConnectionStatus, detail?: string) => void
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
  toolEvents?: ToolProgressEvent[]
  fileEdits?: FileEditEvent[]
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
  total_tokens?: number
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

export interface MessageOptions {
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
  "turn_end",
  "goal_status",
  "goal_state",
  "recovery_state",
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
    "total_tokens",
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

function isRecoveryState(value: unknown): value is RecoveryState {
  return isRecord(value)
    && ["resuming", "awaiting_user", "recovered", "failed"].includes(String(value.status))
    && typeof value.recovery_id === "string"
    && optional(value.reason, "string")
    && optional(value.attempts, "number")
    && optional(value.can_continue, "boolean")
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
      || (record.goal_state !== undefined && !isRecord(record.goal_state)))
  ) return null
  if (name === "goal_status" && record.status !== "running" && record.status !== "idle") return null
  if (name === "goal_state" && !isRecord(record.goal_state)) return null
  if (name === "recovery_state" && !isRecoveryState(record)) return null
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
      || !content.trim()
    ) {
      continue
    }
    if (role === "user") {
      userIndex += 1
      messages.push({
        role: "user",
        content,
        ...(typeof message.turnId === "string" ? { turnId: message.turnId } : {}),
      })
    } else {
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

interface PendingMutation {
  event: Extract<OutboundEvent, { type: "webui_request" }>
  resolve: (value: unknown) => void
  reject: (reason: Error) => void
  timer: ReturnType<typeof setTimeout>
}

export async function fetchConfigEditor(
  apiUrl: string,
  apiToken: string,
  reauthenticate?: ApiReauthenticator,
): Promise<ConfigEditorSnapshot> {
  if (!apiUrl || !apiToken) throw new Error("configuration connection is not ready")
  const response = await fetchApi(
    apiUrl,
    apiToken,
    "/api/settings/config-editor",
    reauthenticate,
  )
  if (!response.ok) throw new Error(`configuration request failed: HTTP ${response.status}`)
  return decodeConfigEditorSnapshot(await response.json() as unknown)
}

export function decodeConfigEditorSnapshot(payload: unknown): ConfigEditorSnapshot {
  if (!isRecord(payload)
    || typeof payload.version !== "number"
    || typeof payload.revision !== "string"
    || !isRecord(payload.config)
    || !isRecord(payload.schema)
    || !Array.isArray(payload.secrets)
    || !isRecord(payload.presentation)
    || !Array.isArray(payload.presentation.primary_paths)
    || !Array.isArray(payload.presentation.provider_primary_fields)
    || !Array.isArray(payload.presentation.sections)
    || !Array.isArray(payload.presentation.deprecated_paths)
  ) throw new Error("gateway returned an invalid configuration contract")

  const secrets = payload.secrets.flatMap((value): ConfigEditorSecret[] => (
    isRecord(value) && typeof value.path === "string" && typeof value.configured === "boolean"
      ? [{ path: value.path, configured: value.configured }]
      : []
  ))
  const sections = payload.presentation.sections.flatMap((value): ConfigEditorSection[] => (
    isRecord(value)
      && typeof value.id === "string"
      && typeof value.label === "string"
      && typeof value.description === "string"
      && Array.isArray(value.prefixes)
      && value.prefixes.every((prefix) => typeof prefix === "string")
      ? [{
          id: value.id,
          label: value.label,
          description: value.description,
          prefixes: value.prefixes as string[],
        }]
      : []
  ))
  const strings = (value: unknown[]): string[] => value.filter(
    (item): item is string => typeof item === "string",
  )
  return {
    version: payload.version,
    revision: payload.revision,
    config: payload.config,
    schema: payload.schema,
    secrets,
    presentation: {
      primary_paths: strings(payload.presentation.primary_paths),
      provider_primary_fields: strings(payload.presentation.provider_primary_fields),
      sections,
      deprecated_paths: strings(payload.presentation.deprecated_paths),
    },
    ...(payload.requires_restart === true ? { requires_restart: true } : {}),
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

export class NanobotClient {
  private socket: WebSocket | null = null
  private chatId = ""
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private reconnectAttempt = 0
  private closedByClient = false
  private opening = false
  private connectedOnce = false
  private readonly pendingMutations = new Map<string, PendingMutation>()

  constructor(private readonly options: ClientOptions) {}

  get activeChatId(): string {
    return this.chatId
  }

  connect(): void {
    this.closedByClient = false
    void this.open()
  }

  private async open(): Promise<void> {
    if (this.socket || this.opening || this.closedByClient) return
    this.opening = true
    this.options.onStatus("connecting")
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
        if (error instanceof GatewayConnectionError && !error.retryable) {
          this.options.onStatus("error", error.message)
          return
        }
        this.options.onStatus(
          "connecting",
          this.options.connectionRetryLabel || "gateway unavailable",
        )
        this.scheduleReconnect(false)
      }
      return
    } finally {
      this.opening = false
    }
    if (!url) {
      this.options.onStatus("error", "gateway URL is not configured")
      return
    }
    const socket = new WebSocket(url)
    this.socket = socket
    socket.addEventListener("open", () => {
      if (this.socket !== socket) return
      this.connectedOnce = true
      this.reconnectAttempt = 0
      this.options.onStatus("connected")
      for (const pending of this.pendingMutations.values()) this.write(pending.event)
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
      this.rejectPendingMutations("gateway connection closed")
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
      ...(options.userShell ? { user_shell: true } : {}),
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
    this.write({ type: "attach", chat_id: chatId })
  }

  newChat(scope?: WorkspaceScopePayload): void {
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

  requestMutation<T = unknown>(
    action: string,
    payload: Record<string, unknown> = {},
    timeoutMs = 20_000,
  ): Promise<T> {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      return Promise.reject(new Error("gateway connection is not open"))
    }
    const requestId = `tui-${crypto.randomUUID()}`
    const event = {
      type: "webui_request",
      request_id: requestId,
      action,
      payload,
    } satisfies OutboundEvent
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pendingMutations.delete(requestId)
        reject(new Error(`gateway request timed out after ${timeoutMs}ms`))
      }, timeoutMs)
      this.pendingMutations.set(requestId, {
        event,
        resolve: (value) => resolve(value as T),
        reject,
        timer,
      })
      try {
        this.write(event)
      } catch (error) {
        clearTimeout(timer)
        this.pendingMutations.delete(requestId)
        reject(error instanceof Error ? error : new Error(String(error)))
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
      if (response.ok) {
        pending.resolve(response.result)
      } else {
        const status = response.error?.status ? `HTTP ${response.error.status}: ` : ""
        let message = response.error?.message || "gateway request failed"
        try {
          const detail = JSON.parse(message) as unknown
          if (isRecord(detail) && typeof detail.error === "string") message = detail.error
        } catch {
          // Plain-text gateway errors are already suitable for the settings surface.
        }
        pending.reject(new Error(`${status}${message}`))
      }
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
    }
    this.options.onEvent(event)
  }

  private scheduleReconnect(announce = true): void {
    if (this.reconnectTimer || this.closedByClient) return
    const base = this.options.reconnectDelayMs ?? 500
    const maxDelay = this.connectedOnce
      ? 8_000
      : this.options.startupRetryMaxDelayMs ?? 8_000
    const delay = Math.min(maxDelay, base * 2 ** Math.min(this.reconnectAttempt++, 4))
    if (announce) this.options.onStatus("connecting", `reconnecting in ${delay}ms`)
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      void this.open()
    }, delay)
  }

  private write(event: OutboundEvent): void {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      throw new Error("gateway connection is not open")
    }
    this.socket.send(JSON.stringify(event))
  }
}
