import {
  BoxRenderable,
  TextRenderable,
  type CliRenderer,
} from "@opentui/core"

import type { SessionContextSnapshot } from "./protocol"

export interface ContextPanelTheme {
  text: string
  border: string
  accent: string
}

export function formatTokenCount(value: number): string {
  if (value < 1_000) return String(value)
  const compact = value >= 10_000 ? Math.round(value / 1_000) : Math.round(value / 100) / 10
  return `${compact}k`
}

/** Read-only explanation of the session-owned context replayed to the agent. */
export class ContextPanel {
  readonly root: BoxRenderable
  private readonly stats: TextRenderable
  private readonly summary: TextRenderable

  constructor(renderer: CliRenderer, theme: ContextPanelTheme) {
    this.root = new BoxRenderable(renderer, {
      id: "nanobot-tui-context-panel",
      width: "100%",
      maxHeight: 9,
      flexShrink: 0,
      flexDirection: "column",
      border: true,
      borderStyle: "rounded",
      borderColor: theme.border,
      paddingLeft: 1,
      paddingRight: 1,
      visible: false,
    })
    this.stats = new TextRenderable(renderer, {
      id: "nanobot-tui-context-stats",
      content: "",
      width: "100%",
      fg: theme.accent,
      wrapMode: "word",
    })
    this.summary = new TextRenderable(renderer, {
      id: "nanobot-tui-context-summary",
      content: "",
      width: "100%",
      maxHeight: 6,
      fg: theme.text,
      wrapMode: "word",
    })
    this.root.add(this.stats)
    this.root.add(this.summary)
  }

  get visible(): boolean {
    return this.root.visible
  }

  show(context: SessionContextSnapshot): void {
    this.stats.content = `~${formatTokenCount(context.estimatedSessionTokens)} tokens · ${context.replayMessages} replay · ${context.archivedMessages} archived`
    this.summary.content = context.archivedSummary ?? ""
    this.root.visible = true
  }

  hide(): void {
    this.root.visible = false
  }

  resize(terminalHeight: number): void {
    const compact = terminalHeight < 14
    const medium = terminalHeight < 20
    this.summary.visible = !compact
    this.summary.maxHeight = medium ? 2 : 6
    this.root.maxHeight = compact ? 3 : medium ? 5 : 9
  }

  setTheme(theme: ContextPanelTheme): void {
    this.root.borderColor = theme.border
    this.stats.fg = theme.accent
    this.summary.fg = theme.text
  }
}
