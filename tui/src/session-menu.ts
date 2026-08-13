import { type BoxRenderable, type CliRenderer } from "@opentui/core"

import { PickerMenu, type PickerMenuTheme } from "./picker-menu"
import type { SessionSummary } from "./protocol"

type SessionMenuRow = SessionSummary & { active: boolean }

function sessionLabel(session: SessionSummary): string {
  return session.title.trim() || session.preview.trim() || "Untitled chat"
}

function updatedLabel(value: string | null): string {
  if (!value) return ""
  const date = new Date(value)
  if (Number.isNaN(date.valueOf())) return ""
  const age = Math.max(0, Date.now() - date.valueOf())
  if (age < 60_000) return "now"
  if (age < 3_600_000) return `${Math.floor(age / 60_000)}m`
  if (age < 86_400_000) return `${Math.floor(age / 3_600_000)}h`
  return `${Math.floor(age / 86_400_000)}d`
}

/** Searchable session navigation over the gateway-owned session list. */
export class SessionMenu {
  readonly root: BoxRenderable
  private readonly picker: PickerMenu<SessionMenuRow>

  constructor(renderer: CliRenderer, theme: PickerMenuTheme) {
    this.picker = new PickerMenu(renderer, theme, {
      id: "nanobot-tui-session-menu",
      searchText: (session) => `${sessionLabel(session)} ${session.preview} ${session.chatId}`,
      render: (session) => {
        const age = updatedLabel(session.updatedAt)
        const preview = session.preview.trim()
        const detail = [age, preview && preview !== sessionLabel(session) ? preview : ""]
          .filter(Boolean)
          .join(" · ")
        const marker = session.active ? "● " : session.pinned ? "◆ " : session.archived ? "◇ " : ""
        return `${marker}${sessionLabel(session)}${detail ? `  ${detail}` : ""}`
      },
      emptyText: "No matching sessions",
    })
    this.root = this.picker.root
  }

  get visible(): boolean {
    return this.picker.visible
  }

  open(sessions: SessionSummary[], currentChatId: string, limit: number): void {
    const rows = sessions
      .map((session) => ({ ...session, active: session.chatId === currentChatId }))
      .sort((left, right) => {
        return Number(right.active) - Number(left.active)
          || Number(right.pinned) - Number(left.pinned)
          || Number(left.archived) - Number(right.archived)
      })
    this.picker.show(rows, "", limit)
  }

  update(query: string, limit: number): void {
    this.picker.update(query, limit)
  }

  move(direction: -1 | 1): boolean {
    return this.picker.move(direction)
  }

  choose(): SessionSummary | null {
    return this.picker.current()
  }

  hide(): void {
    this.picker.hide()
  }

  setTheme(theme: PickerMenuTheme): void {
    this.picker.setTheme(theme)
  }
}
