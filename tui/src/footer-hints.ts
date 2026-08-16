import { RGBA, StyledText, TextAttributes, type TextChunk } from "@opentui/core"

import { optionArrowUp } from "./platform-keys"

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
  platform: string = process.platform,
  shiftedEnter = false,
): StyledText {
  return footerHints(hintsFor(mode, width, platform, shiftedEnter), theme)
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
  platform: string,
  shiftedEnter: boolean,
): FooterHint[] {
  if (mode === "mention") return width >= 64
    ? [hint("↑↓", "choose"), hint("tab/enter", "insert"), hint("esc", "close")]
    : [hint("enter", "insert"), hint("esc", "close")]
  if (mode === "active") return width >= 96
    ? [hint("enter", "steer"), hint("tab", "queue"), hint(optionArrowUp(platform), "edit"), stopHint()]
    : width >= 64 ? [hint("enter", "steer"), hint("tab", "queue"), stopHint()] : []
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
  const newline = shiftedEnter ? "shift+enter" : "ctrl+j"
  if (width >= 112) return [
    hint("enter", "send"),
    hint(newline, "newline"),
    hint("pgup/pgdn", "scroll"),
    hint("ctrl+o", "tools"),
    stopHint(),
  ]
  if (width >= 72) return [hint("enter", "send"), hint(newline, "newline"), stopHint()]
  return width >= 48 ? [hint("enter", "send"), hint(newline, "newline")] : []
}

function hint(key: string, label: string): FooterHint {
  return { key, label }
}

function stopHint(): FooterHint {
  return { key: "ctrl+c", label: "stop", tone: "danger" }
}

function chunk(text: string, color: string, bold = false): TextChunk {
  return {
    __isChunk: true,
    text,
    fg: RGBA.fromHex(color),
    attributes: bold ? TextAttributes.BOLD : 0,
  }
}
