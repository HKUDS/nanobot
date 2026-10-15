import type {
  ContextCompaction,
  NotificationEvent,
  RecoveryState,
} from "../../../packages/client-events/notifications"

export type {
  ContextCompaction,
  RecoveryState,
  RetryStatus,
} from "../../../packages/client-events/notifications"

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

export type OutboundEvent =
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
      media?: import("../../../packages/client-events/attachments").AttachmentReference[]
      cli_apps?: Array<{ name: string }>
      mcp_presets?: Array<{ name: string }>
      session_mentions?: SessionMention[]
    }

export interface ClientOptions {
  expectedGatewayId?: string
  reconnect?: boolean
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

export interface SessionUsageSnapshot {
  context: { tokens: number; windowTokens?: number } | null
  rounds: TokenUsage[]
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
