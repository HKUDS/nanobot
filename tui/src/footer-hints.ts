import { RGBA, StyledText, TextAttributes, type TextChunk } from "@opentui/core"

import type { TokenUsage } from "./protocol"

export interface FooterHint {
  key: string
  label: string
  tone?: "normal" | "danger"
}

export interface FooterHintTheme {
  accent: string
  danger: string
  muted: string
  separator: string
}

export type FooterMode =
  | "mention"
  | "runtime"
  | "active"
  | "branch"
  | "command"
  | "session"
  | "context"
  | "history"
  | "ready"

export function contextualFooterHints(
  mode: FooterMode,
  width: number,
  theme: FooterHintTheme,
  _platform: string = process.platform,
  _shiftedEnter = false,
): StyledText {
  return footerHints(hintsFor(mode, width), theme)
}

/** Latest provider-measured request telemetry, never turn-aggregate accounting. */
export function footerTelemetry(
  usage: TokenUsage | null,
  width: number,
  theme: FooterHintTheme,
): StyledText {
  if (!usage || (usage.last_request_provider_tokens || 0) <= 0) {
    return new StyledText([])
  }
  const parts: string[] = []
  const duration = usage.last_request_generation_ms
  const measured = usage.last_request_measured_completion_tokens
  if (typeof duration === "number" && duration > 0 && typeof measured === "number") {
    const rate = measured * 1000 / duration
    const value = rate < 10 ? rate.toFixed(1) : String(Math.round(rate))
    parts.push(`${value} tok/s`)
  }
  const prompt = usage.last_request_prompt_tokens
  const cached = usage.last_request_cached_tokens
  const cacheHitRate = (
    typeof cached === "number"
    && typeof prompt === "number"
    && prompt > 0
  )
    ? Math.min(100, Math.max(0, Math.round(cached * 100 / prompt)))
    : null
  if (typeof prompt === "number") {
    const contextWindowTokens = usage.last_request_context_window_tokens
    const window = contextWindowTokens && contextWindowTokens > 0
      ? `/${formatTelemetryTokens(contextWindowTokens)}`
      : ""
    const cache = width >= 72 && cacheHitRate !== null
      ? ` (${cacheHitRate}% cached)`
      : ""
    parts.push(`${formatTelemetryTokens(prompt)}${window} ctx${cache}`)
  }
  const completion = usage.last_request_completion_tokens
  if (width >= 72 && typeof completion === "number") {
    parts.push(`${formatTelemetryTokens(completion)} out`)
  }
  return footerMetrics(parts, theme)
}

function formatTelemetryTokens(value: number): string {
  const count = Math.max(0, value)
  for (const [threshold, suffix] of [[1_000_000_000, "B"], [1_000_000, "M"], [1_000, "K"]] as const) {
    if (count < threshold) continue
    const scaled = count / threshold
    const compact = scaled >= 10 ? Math.round(scaled) : Math.round(scaled * 10) / 10
    return `${compact}${suffix}`
  }
  return String(Math.round(count))
}

function footerMetrics(parts: readonly string[], theme: FooterHintTheme): StyledText {
  const chunks: TextChunk[] = []
  parts.forEach((text, index) => {
    if (index) chunks.push(chunk(" · ", theme.separator))
    chunks.push(chunk(text, index === 0 ? theme.accent : theme.muted, index === 0))
  })
  return new StyledText(chunks)
}

/** Give shortcuts visual hierarchy without turning the footer into a toolbar. */
export function footerHints(hints: readonly FooterHint[], theme: FooterHintTheme): StyledText {
  const chunks: TextChunk[] = []
  hints.forEach((hint, index) => {
    if (index) chunks.push(chunk(" · ", theme.separator))
    const color = hint.tone === "danger" ? theme.danger : theme.accent
    chunks.push(chunk(hint.key, color, true))
    chunks.push(chunk(` ${hint.label}`, theme.muted))
  })
  return new StyledText(chunks)
}

function hintsFor(
  mode: FooterMode,
  width: number,
): FooterHint[] {
  if (mode === "runtime") return width >= 64
    ? [hint("↑↓/click", "choose"), hint("enter", "apply"), hint("esc", "close")]
    : [hint("enter", "apply"), hint("esc", "close")]
  if (mode === "mention") return width >= 64
    ? [hint("↑↓", "choose"), hint("tab/enter", "insert"), hint("esc", "close")]
    : [hint("enter", "insert"), hint("esc", "close")]
  if (mode === "active") return []
  if (mode === "branch") return width >= 64
    ? [hint("type", "filter"), hint("↑↓", "choose"), hint("enter", "branch"), hint("esc", "close")]
    : [hint("enter", "branch"), hint("esc", "close")]
  if (mode === "command") return width >= 72
    ? [hint("↑↓", "choose"), hint("tab", "complete"), hint("esc", "close")]
    : [hint("tab", "complete"), hint("esc", "close")]
  if (mode === "session") return width >= 64
    ? [hint("type", "filter"), hint("↑↓", "choose"), hint("enter", "open"), hint("esc", "close")]
    : [hint("enter", "open"), hint("esc", "close")]
  if (mode === "context") return [hint("esc", "close"), hint("pgup/pgdn", "scroll")]
  if (mode === "history") return width >= 72
    ? [hint("ctrl+end", "latest"), hint("pgup/pgdn", "scroll")]
    : width >= 48 ? [hint("ctrl+end", "latest")] : []
  return []
}

function hint(key: string, label: string): FooterHint {
  return { key, label }
}

function chunk(text: string, color: string, bold = false): TextChunk {
  return {
    __isChunk: true,
    text,
    fg: RGBA.fromHex(color),
    attributes: bold ? TextAttributes.BOLD : 0,
  }
}
