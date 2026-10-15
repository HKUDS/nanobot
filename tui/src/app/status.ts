import type { ConnectionStatus, ConnectionStatusInfo, RetryStatus } from "../client"

export function formatElapsed(milliseconds: number): string {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000))
  if (seconds < 60) return `${seconds}s`
  return `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, "0")}s`
}

export function connectionStatusText(
  status: ConnectionStatus,
  info?: ConnectionStatusInfo,
): string {
  if (["starting", "connecting", "connected"].includes(status)) return "Getting ready…"
  if (status === "reconnecting") return "Resuming…"
  if (status === "unavailable") {
    return info?.health === "degraded"
      ? "Still getting ready…"
      : "Nanobot is taking longer to respond…"
  }
  if (status === "error") return "Nanobot unavailable. Restart nanobot."
  return "Session ended"
}

function retryFailureLabel(errorKind: string): string {
  if (errorKind === "billing") return "Model provider quota is unavailable"
  if (errorKind === "connection") return "Could not connect to the model provider"
  if (errorKind === "timeout") return "Model provider request timed out"
  if (errorKind === "rate_limit") return "Model provider rate limit reached"
  if (errorKind === "server") return "Model provider service error"
  return "Model provider request failed"
}

export function terminalModelFailureLine(errorKind?: string, attempts?: number): string {
  const reason = retryFailureLabel(errorKind || "unknown")
  if (errorKind === "billing") {
    return `${reason}. Add credit or check billing for the provider account, then try again.`
  }
  const retryResult = typeof attempts === "number" && Number.isInteger(attempts) && attempts > 0
    ? ` The request still failed on attempt ${attempts}, so retries stopped.`
    : ""
  return `${reason}.${retryResult} Check the provider configuration or service status, then try again.`
}

export interface RenderedRetryStatus extends RetryStatus {
  nextRetryAtMs?: number
}

export function retryStatusLine(status: RenderedRetryStatus, nowMs = Date.now()): string {
  const label = retryFailureLabel(status.error_kind)
  if (status.state === "exhausted") return `${label}. Ending turn.`
  if (status.state === "recovered") return "Connection restored"
  if (status.state === "cleared") return "Retry status cleared"
  const remaining = Math.max(
    0,
    Math.ceil(((status.nextRetryAtMs ?? nowMs) - nowMs) / 1000),
  )
  const attempt = status.max_attempts
    ? `${status.attempt}/${status.max_attempts}`
    : String(status.attempt)
  return `${label}. Retrying in ${remaining}s (attempt ${attempt}).`
}

export function sessionExitMessage(chatId: string): string {
  const sessionId = `websocket:${chatId}`
  return `Resume with: nanobot agent --session ${sessionId}\n`
}
