import { RGBA, type BoxRenderable, type CliRenderer, type TextChunk } from "@opentui/core"

import { PickerMenu, type PickerMenuTheme } from "./picker-menu"
import type { SessionSummary } from "./protocol"

type SessionMenuRow = SessionSummary & { active: boolean; unread: boolean }

const SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

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
  private spinnerFrame = 0
  private spinnerTimer: ReturnType<typeof setInterval> | null = null
  private rows: SessionMenuRow[] = []
  private defaultModelPreset = ""
  private readonly snapshots = new Map<string, {
    preview: string
    runStartedAt: number | null
  }>()
  private readonly unreadChatIds = new Set<string>()

  constructor(
    renderer: CliRenderer,
    private theme: PickerMenuTheme,
    onSelect?: (session: SessionSummary) => void,
  ) {
    this.picker = new PickerMenu<SessionMenuRow>(renderer, theme, {
      id: "nanobot-tui-session-menu",
      key: (session) => session.chatId,
      searchText: (session) => [
        sessionLabel(session),
        session.modelPreset || "",
        session.preview,
        session.chatId,
        session.workspaceScope?.project_name || "",
        session.workspaceScope?.project_path || "",
        session.recoveryState?.status || "",
        session.recoveryState?.reason || "",
      ].join(" "),
      render: (session, selected) => {
        const age = updatedLabel(session.updatedAt)
        const detail = [
          this.showWorkspaces ? this.workspaceLabel(session) : "",
          this.modelOverride(session),
        ]
          .filter(Boolean)
          .join(" · ")
        const marker = this.marker(session)
        const foreground = this.interrupted(session)
          ? this.theme.warning || this.theme.accent || this.theme.text
          : selected ? this.theme.text : this.theme.muted
        return [
          ...(marker ? [chunk(`${marker.text} `, marker.color)] : []),
          chunk(sessionLabel(session), foreground),
          ...(detail ? [chunk(`  ${detail}`, this.theme.muted)] : []),
          ...(age ? [chunk(`  ${age}`, this.theme.muted)] : []),
        ]
      },
      emptyText: "No matching sessions",
      onSelect,
    })
    this.root = this.picker.root
  }

  get visible(): boolean {
    return this.picker.visible
  }

  open(
    sessions: SessionSummary[],
    currentChatId: string,
    limit: number,
    defaultModelPreset = "",
  ): void {
    this.defaultModelPreset = defaultModelPreset
    this.observe(sessions, currentChatId)
    this.rows = this.prepareRows(sessions, currentChatId)
    this.picker.show(this.rows, "", limit)
    this.syncSpinner()
  }

  replace(
    sessions: SessionSummary[],
    currentChatId: string,
    defaultModelPreset = this.defaultModelPreset,
  ): void {
    this.defaultModelPreset = defaultModelPreset
    this.observe(sessions, currentChatId)
    this.rows = this.prepareRows(sessions, currentChatId)
    this.picker.replace(this.rows)
    this.syncSpinner()
  }

  markRead(chatId: string): void {
    this.unreadChatIds.delete(chatId)
  }

  private prepareRows(sessions: SessionSummary[], currentChatId: string): SessionMenuRow[] {
    this.prepareWorkspaceLabels(sessions)
    return sessions
      .map((session) => ({
        ...session,
        active: session.chatId === currentChatId,
        unread: this.unreadChatIds.has(session.chatId),
      }))
      .sort((left, right) => {
        return Number(right.active) - Number(left.active)
          || sessionPriority(right) - sessionPriority(left)
          || Number(right.pinned) - Number(left.pinned)
          || Number(left.archived) - Number(right.archived)
          || timestamp(right.updatedAt) - timestamp(left.updatedAt)
          || sessionLabel(left).localeCompare(sessionLabel(right))
      })
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
    this.stopSpinner()
    this.rows = []
    this.picker.hide()
  }

  setTheme(theme: PickerMenuTheme): void {
    this.theme = theme
    this.picker.setTheme(theme)
  }

  private marker(session: SessionMenuRow): { text: string; color: string } | null {
    if (this.interrupted(session)) {
      return {
        text: "⚠",
        color: this.theme.warning || this.theme.accent || this.theme.text,
      }
    }
    if (session.runStartedAt !== null) {
      return {
        text: SPINNER_FRAMES[this.spinnerFrame % SPINNER_FRAMES.length] || SPINNER_FRAMES[0]!,
        color: this.theme.accent || this.theme.text,
      }
    }
    if (session.active) return { text: "●", color: this.theme.text }
    if (session.unread) return { text: "•", color: this.theme.accent || this.theme.text }
    if (session.pinned) return { text: "◆", color: this.theme.muted }
    if (session.archived) return { text: "◇", color: this.theme.muted }
    return null
  }

  private interrupted(session: SessionMenuRow): boolean {
    return session.recoveryState?.status === "awaiting_user"
      || session.recoveryState?.status === "failed"
  }

  private observe(sessions: SessionSummary[], currentChatId: string): void {
    const present = new Set<string>()
    for (const session of sessions) {
      present.add(session.chatId)
      const previous = this.snapshots.get(session.chatId)
      const active = session.chatId === currentChatId
      const completed = previous !== undefined
        && previous.runStartedAt !== null
        && session.runStartedAt === null
      const receivedContent = previous !== undefined && previous.preview !== session.preview
      if (active) this.unreadChatIds.delete(session.chatId)
      else if (completed || receivedContent) this.unreadChatIds.add(session.chatId)
      this.snapshots.set(session.chatId, {
        preview: session.preview,
        runStartedAt: session.runStartedAt,
      })
    }
    for (const chatId of this.snapshots.keys()) {
      if (present.has(chatId)) continue
      this.snapshots.delete(chatId)
      this.unreadChatIds.delete(chatId)
    }
  }

  private syncSpinner(): void {
    if (!this.visible || !this.rows.some((session) => session.runStartedAt !== null)) {
      this.stopSpinner()
      return
    }
    if (this.spinnerTimer) return
    this.spinnerTimer = setInterval(() => {
      this.spinnerFrame = (this.spinnerFrame + 1) % SPINNER_FRAMES.length
      this.picker.redraw()
    }, 90)
    ;(this.spinnerTimer as unknown as { unref?: () => void }).unref?.()
  }

  private stopSpinner(): void {
    if (this.spinnerTimer) clearInterval(this.spinnerTimer)
    this.spinnerTimer = null
    this.spinnerFrame = 0
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

  private modelOverride(session: SessionSummary): string {
    const preset = session.modelPreset?.trim() || ""
    return preset && preset !== this.defaultModelPreset ? preset : ""
  }
}

function chunk(text: string, color: string): TextChunk {
  return {
    __isChunk: true,
    text,
    fg: RGBA.fromHex(color),
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

function sessionPriority(session: SessionMenuRow): number {
  if (session.recoveryState?.status === "awaiting_user"
    || session.recoveryState?.status === "failed") return 3
  if (session.runStartedAt !== null) return 2
  return session.unread ? 1 : 0
}

function timestamp(value: string | null): number {
  if (!value) return 0
  const parsed = Date.parse(value)
  return Number.isNaN(parsed) ? 0 : parsed
}
