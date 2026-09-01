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
  | "skill"
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

/** Last-turn model telemetry. Passive chrome reports the system, not its manual. */
export function footerTelemetry(
  usage: TokenUsage | null,
  width: number,
  theme: FooterHintTheme,
): StyledText {
  if (!usage) return new StyledText([])
  const parts: string[] = []
  const duration = usage.generation_ms
  const measured = usage.measured_completion_tokens
  if (typeof duration === "number" && duration > 0 && typeof measured === "number") {
    const rate = measured * 1000 / duration
    const value = rate < 10 ? rate.toFixed(1) : String(Math.round(rate))
    const estimated = (usage.estimated_tokens || 0) > 0 ? "~" : ""
    parts.push(`${estimated}${value} tok/s`)
  }
  const cacheHitRate = (
    typeof usage.cached_tokens === "number"
    && typeof usage.prompt_tokens === "number"
    && usage.prompt_tokens > 0
  )
    ? Math.min(100, Math.max(0, Math.round(
        usage.cached_tokens * 100 / usage.prompt_tokens,
      )))
    : null
  if (width >= 72) {
    const prompt = usage.prompt_tokens
    const completion = usage.completion_tokens
    if (typeof prompt === "number" || typeof completion === "number") {
      const cache = cacheHitRate === null ? "" : ` (${cacheHitRate}% cached)`
      parts.push(`${formatTelemetryTokens(prompt || 0)} in${cache}`)
      parts.push(`${formatTelemetryTokens(completion || 0)} out`)
    }
  } else if (cacheHitRate !== null) {
    parts.push(`${cacheHitRate}% cached`)
  }
  if (width >= 128 && typeof usage.cost_usd === "number" && usage.cost_usd > 0) {
    parts.push(`$${usage.cost_usd < 0.01 ? usage.cost_usd.toFixed(4) : usage.cost_usd.toFixed(2)}`)
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
  if (mode === "mention" || mode === "skill") return width >= 64
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
