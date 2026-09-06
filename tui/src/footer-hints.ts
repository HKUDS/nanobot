import { RGBA, StyledText, TextAttributes, type TextChunk } from "@opentui/core"

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

/** Latest measured request's context-window occupancy. */
export function footerTelemetry(
  contextTokens: number | null,
  contextWindowTokens: number | null,
  theme: FooterHintTheme,
): StyledText {
  if (
    typeof contextTokens !== "number"
    || !Number.isFinite(contextTokens)
    || contextTokens < 0
    || typeof contextWindowTokens !== "number"
    || !Number.isFinite(contextWindowTokens)
    || contextWindowTokens <= 0
  ) return new StyledText([])
  const percentage = Math.min(100, Math.round(
    contextTokens * 100 / contextWindowTokens,
  ))
  return new StyledText([chunk(`${percentage}% context`, theme.accent, true)])
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
