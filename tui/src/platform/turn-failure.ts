import { nonModelFailureLine } from "../../../packages/client-events/turn-failure"
import { emptyFinalResponseLine, terminalLocale } from "./locale"

export function retryFailureLabel(errorKind: string): string {
  if (errorKind === "billing") return "Model provider quota is unavailable"
  if (errorKind === "connection") return "Could not connect to the model provider"
  if (errorKind === "timeout") return "Model provider request timed out"
  if (errorKind === "rate_limit") return "Model provider rate limit reached"
  if (errorKind === "server") return "Model provider service error"
  return "Model provider request failed"
}

export function terminalModelFailureLine(errorKind?: string, attempts?: number): string {
  const emptyFinal = emptyFinalResponseLine(errorKind)
  if (emptyFinal) return emptyFinal
  if (errorKind === "unsupported_image") {
    return "Image input is off for this preset. Check the preset or select a model that supports images."
  }
  const reason = retryFailureLabel(errorKind || "unknown")
  if (errorKind === "billing") {
    return `${reason}. Add credit or check billing for the provider account, then try again.`
  }
  const retryResult = typeof attempts === "number" && Number.isInteger(attempts) && attempts > 0
    ? ` The request still failed on attempt ${attempts}, so retries stopped.`
    : ""
  return `${reason}.${retryResult} Check the provider configuration or service status, then try again.`
}

export function turnFailureLine(failure: {
  failure_kind?: string
  failure_error_kind?: string
  failure_attempts?: number
}): string {
  return failure.failure_kind === "model"
    ? terminalModelFailureLine(failure.failure_error_kind, failure.failure_attempts)
    : nonModelFailureLine(failure.failure_kind, terminalLocale())
}
