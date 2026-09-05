/** Transport notifications shared by the browser and terminal clients. */
export type RecoveryStatus = "resuming" | "awaiting_user" | "recovered" | "failed"

export interface RecoveryState {
  status: RecoveryStatus
  recovery_id: string
  reason?: string
  attempts?: number
  can_continue?: boolean
}

export interface ContextCompaction {
  id: string
  phase: "started" | "succeeded" | "failed" | "cancelled"
}

export type NotificationEvent =
  | ({ event: "recovery_state"; chat_id: string; turn_id?: string } & RecoveryState)
  | {
      event: "context_compaction"
      chat_id: string
      turn_id?: string
      compaction_id: string
      phase: ContextCompaction["phase"]
    }

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
}

function optional(value: unknown, type: "boolean" | "number" | "string"): boolean {
  return value === undefined || typeof value === type
}

export function isCompactionPhase(value: unknown): value is ContextCompaction["phase"] {
  return value === "started" || value === "succeeded" || value === "failed" || value === "cancelled"
}

export function isRecoveryState(value: unknown): value is RecoveryState {
  return isRecord(value)
    && typeof value.status === "string"
    && ["resuming", "awaiting_user", "recovered", "failed"].includes(value.status)
    && typeof value.recovery_id === "string"
    && optional(value.reason, "string")
    && optional(value.attempts, "number")
    && optional(value.can_continue, "boolean")
}

/** Undefined means another protocol family; null means a malformed notification. */
export function decodeNotification(value: unknown): NotificationEvent | null | undefined {
  if (!isRecord(value)) return undefined
  if (value.event !== "recovery_state" && value.event !== "context_compaction") return undefined
  if (typeof value.chat_id !== "string" || !optional(value.turn_id, "string")) return null
  if (value.event === "recovery_state") {
    return isRecoveryState(value) ? value as unknown as NotificationEvent : null
  }
  return typeof value.compaction_id === "string" && value.compaction_id.length > 0
    && isCompactionPhase(value.phase) ? value as unknown as NotificationEvent : null
}

/** A terminal history row must not regress when an older live event arrives. */
export function acceptsCompactionPhase(
  current: ContextCompaction["phase"] | undefined,
  incoming: ContextCompaction["phase"],
): boolean {
  return current === undefined || (current === "started" && incoming !== "started")
}
