import { decodeNotification, isRecoveryState } from "../../../packages/client-events/notifications"

import type {
  FileEditEvent,
  InboundEvent,
  MediaAttachment,
  TokenUsage,
  ToolProgressEvent,
  WorkspaceScopePayload,
} from "./types"

interface FileDiff {
  format: "unified" | string
  context?: number
  truncated?: boolean
  text?: string
}

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

export function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value)
}

export function optional(value: unknown, type: "boolean" | "number" | "string"): boolean {
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

export function isTokenUsage(value: unknown): value is TokenUsage {
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

export function isWorkspaceScope(value: unknown): value is WorkspaceScopePayload {
  return isRecord(value)
    && typeof value.project_path === "string"
    && (value.access_mode === "restricted" || value.access_mode === "full")
    && optional(value.project_name, "string")
    && optional(value.restrict_to_workspace, "boolean")
}

export interface WebUIResponseEvent {
  event: "webui_response"
  request_id: string
  ok: boolean
  result?: unknown
  error?: { status: number; message: string }
}

export function decodeWebUIResponse(value: unknown): WebUIResponseEvent | null | undefined {
  if (!isRecord(value) || value.event !== "webui_response") return undefined
  if (typeof value.request_id !== "string" || typeof value.ok !== "boolean") return null
  if (value.ok) return value as unknown as WebUIResponseEvent
  return isRecord(value.error)
    && typeof value.error.status === "number"
    && typeof value.error.message === "string"
    ? value as unknown as WebUIResponseEvent
    : null
}

export function decodeInboundEvent(value: unknown): InboundEvent | null | undefined {
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
