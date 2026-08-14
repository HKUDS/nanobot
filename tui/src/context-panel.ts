import {
  BoxRenderable,
  TextAttributes,
  TextRenderable,
  type CliRenderer,
} from "@opentui/core"

import type { SessionContextSnapshot } from "./protocol"

export interface ContextPanelTheme {
  text: string
  muted: string
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
  private readonly title: TextRenderable
  private readonly stats: TextRenderable
  private readonly summary: TextRenderable
  private readonly note: TextRenderable

  constructor(renderer: CliRenderer, theme: ContextPanelTheme) {
    this.root = new BoxRenderable(renderer, {
      id: "nanobot-tui-context-panel",
      width: "100%",
      maxHeight: 12,
      flexShrink: 0,
      flexDirection: "column",
      border: true,
      borderStyle: "rounded",
      borderColor: theme.border,
      paddingLeft: 1,
      paddingRight: 1,
      visible: false,
    })
    this.title = new TextRenderable(renderer, {
      id: "nanobot-tui-context-title",
      content: "Agent context",
      width: "100%",
      height: 1,
      fg: theme.text,
      attributes: TextAttributes.BOLD,
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
    this.note = new TextRenderable(renderer, {
      id: "nanobot-tui-context-note",
      content: "Session view only · memory, instructions, and skills are added separately · Esc close",
      width: "100%",
      fg: theme.muted,
      wrapMode: "word",
    })
    this.root.add(this.title)
    this.root.add(this.stats)
    this.root.add(this.summary)
    this.root.add(this.note)
  }

  get visible(): boolean {
    return this.root.visible
  }

  show(context: SessionContextSnapshot): void {
    const archived = context.archivedMessages > 0
      ? `${context.archivedMessages} archived · summary ${context.archivedSummary ? "active" : "unavailable"}`
      : "No archived messages"
    this.stats.content = `~${formatTokenCount(context.estimatedSessionTokens)} session tokens · ${context.replayMessages} replay messages · ${archived}`
    this.summary.content = context.archivedSummary
      ? `Summary\n${context.archivedSummary}`
      : "The agent is currently replaying raw session messages; no compacted summary exists yet."
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
    this.note.visible = !medium
    this.root.maxHeight = compact ? 4 : medium ? 6 : 12
  }

  setTheme(theme: ContextPanelTheme): void {
    this.root.borderColor = theme.border
    this.title.fg = theme.text
    this.stats.fg = theme.accent
    this.summary.fg = theme.text
    this.note.fg = theme.muted
  }
}
