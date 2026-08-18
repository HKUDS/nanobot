import { type BoxRenderable, type CliRenderer } from "@opentui/core"

import { PickerMenu, type PickerMenuTheme } from "./picker-menu"
import type { SessionSummary } from "./protocol"

type SessionMenuRow = SessionSummary & { active: boolean }

export function sessionLabel(session: SessionSummary): string {
  const label = session.title.trim() || session.preview.trim() || "Untitled chat"
  return label.replace(/\s+/gu, " ")
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
  private readonly workspaceLabels = new Map<string, string>()
  private showWorkspaces = false

  constructor(
    renderer: CliRenderer,
    theme: PickerMenuTheme,
    onSelect?: (session: SessionSummary) => void,
  ) {
    this.picker = new PickerMenu<SessionMenuRow>(renderer, theme, {
      id: "nanobot-tui-session-menu",
      searchText: (session) => [
        sessionLabel(session),
        session.modelPreset || "",
        session.preview,
        session.chatId,
        session.workspaceScope?.project_name || "",
        session.workspaceScope?.project_path || "",
      ].join(" "),
      render: (session) => {
        const age = updatedLabel(session.updatedAt)
        const preview = session.preview.trim()
        const detail = [
          this.showWorkspaces ? this.workspaceLabel(session) : "",
          session.modelPreset,
          age,
          preview && preview !== sessionLabel(session) ? preview : "",
        ]
          .filter(Boolean)
          .join(" · ")
        const marker = session.active ? "● " : session.pinned ? "◆ " : session.archived ? "◇ " : ""
        return `${marker}${sessionLabel(session)}${detail ? `  ${detail}` : ""}`
      },
      emptyText: "No matching sessions",
      onSelect,
    })
    this.root = this.picker.root
  }

  get visible(): boolean {
    return this.picker.visible
  }

  open(sessions: SessionSummary[], currentChatId: string, limit: number): void {
    this.prepareWorkspaceLabels(sessions)
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

  private prepareWorkspaceLabels(sessions: SessionSummary[]): void {
    this.workspaceLabels.clear()
    const scopes = sessions.flatMap((session) => {
      const path = normalizeWorkspacePath(session.workspaceScope?.project_path)
      return path ? [{ path, name: session.workspaceScope?.project_name?.trim() || pathName(path) }] : []
    })
    const paths = new Set(scopes.map(({ path }) => path))
    this.showWorkspaces = paths.size > 1
    if (!this.showWorkspaces) return
    const namePaths = new Map<string, Set<string>>()
    for (const { path, name } of scopes) {
      const pathsForName = namePaths.get(name) || new Set<string>()
      pathsForName.add(path)
      namePaths.set(name, pathsForName)
    }
    for (const { path, name } of scopes) {
      this.workspaceLabels.set(path, namePaths.get(name)?.size === 1 ? name : shortPath(path))
    }
  }

  private workspaceLabel(session: SessionSummary): string {
    return this.workspaceLabels.get(normalizeWorkspacePath(session.workspaceScope?.project_path)) || ""
  }
}

function normalizeWorkspacePath(value: string | undefined): string {
  return (value || "").trim().replace(/\\/gu, "/").replace(/\/+$/u, "")
}

function pathName(path: string): string {
  return path.split("/").filter(Boolean).at(-1) || path
}

function shortPath(path: string): string {
  const parts = path.split("/").filter(Boolean)
  return parts.slice(-2).join("/") || path
}
