import {
  BoxRenderable,
  MarkdownRenderable,
  RGBA,
  ScrollBoxRenderable,
  SyntaxStyle,
  TextAttributes,
  TextRenderable,
  type CliRenderer,
  type TreeSitterClient,
} from "@opentui/core"

import type { FileEditEvent, HistoryMessage, ToolProgressEvent } from "./protocol"
import { renderLatexAsUnicode } from "./latex"
import { hideScrollbars } from "./scrollbox"
import { mergeToolEvent, renderToolEvent } from "./tool-renderers"

export interface TranscriptTheme {
  text: string
  muted: string
  error: string
  user: string
  userBackground: string | null
  border: string
  syntax: SyntaxStyle
}

export interface TranscriptHeader {
  model: string
  workspace: string
  version: string
  access: string
}

export interface TranscriptNavigation {
  awayFromBottom: boolean
  unseenOutput: boolean
}

interface Activity {
  text: TextRenderable
  lines: string[]
  keys: Map<string, number>
  expanded: boolean
  events: Map<string, ToolProgressEvent>
}

interface ActivityPreviewItem {
  text: string
  steps: number
  group?: string
}

const ACTIVITY_PREVIEW_LINES = 4
// OpenTUI renders at 30 FPS. Re-parsing the entire Markdown buffer for every
// provider token turns long answers into quadratic work without producing any
// additional visible frames. Paint the first token immediately, then coalesce
// subsequent deltas to the renderer cadence.
const STREAM_FLUSH_MS = 32

/** Projects gateway events into retained, reflowable conversation cells. */
export class Transcript {
  readonly root: ScrollBoxRenderable
  private live: { row: BoxRenderable; markdown: MarkdownRenderable; content: string } | null = null
  private activity: Activity | null = null
  private readonly styledText: Array<{
    renderable: TextRenderable
    tone: "text" | "muted" | "error" | "user"
  }> = []
  private readonly markdown = new Set<MarkdownRenderable>()
  private readonly activities = new Set<Activity>()
  private readonly frames = new Set<BoxRenderable>()
  private readonly userRows = new Set<BoxRenderable>()
  private readonly userTurnIds = new Set<string>()
  private wrote = false
  private nextId = 0
  private navigation: TranscriptNavigation = { awayFromBottom: false, unseenOutput: false }
  private navigationTimer: ReturnType<typeof setTimeout> | null = null
  private pendingStream = ""
  private streamTimer: ReturnType<typeof setTimeout> | null = null

  constructor(
    private readonly renderer: CliRenderer,
    private theme: TranscriptTheme,
    private readonly treeSitterClient: TreeSitterClient,
    private readonly onNavigationChange?: (state: TranscriptNavigation) => void,
    private readonly showHeader = true,
    private readonly workspace = "",
  ) {
    this.root = new ScrollBoxRenderable(renderer, {
      id: "nanobot-tui-transcript",
      width: "100%",
      minHeight: 0,
      flexGrow: 0,
      scrollX: false,
      scrollY: true,
      stickyScroll: true,
      stickyStart: "bottom",
      viewportCulling: true,
      contentOptions: {
        flexDirection: "column",
        minHeight: 0,
        paddingTop: 1,
        paddingBottom: 1,
        paddingLeft: 1,
        paddingRight: 1,
      },
      verticalScrollbarOptions: { visible: false },
      horizontalScrollbarOptions: { visible: false },
      onMouseScroll: () => this.scheduleNavigationUpdate(),
    })
    hideScrollbars(this.root)
  }

  setTheme(theme: TranscriptTheme): void {
    const previousSyntax = this.theme.syntax
    this.theme = theme
    for (const { renderable, tone } of this.styledText) renderable.fg = theme[tone]
    for (const renderable of this.markdown) renderable.syntaxStyle = theme.syntax
    for (const frame of this.frames) frame.borderColor = theme.border
    for (const row of this.userRows) {
      row.backgroundColor = theme.userBackground
        ? RGBA.fromHex(theme.userBackground)
        : RGBA.defaultBackground()
    }
    // Markdown may still be rendering this frame. Release the prior native
    // style only after the renderer reaches idle, matching OpenCode's retained
    // theme lifecycle and avoiding both leaks and use-after-free transitions.
    void this.renderer.idle().catch(() => {}).finally(() => previousSyntax.destroy())
  }

  header(options: TranscriptHeader): void {
    if (!this.showHeader) return
    const row = new BoxRenderable(this.renderer, {
      id: this.id("header-row"),
      width: "100%",
      maxWidth: 62,
      flexDirection: "column",
      border: true,
      borderStyle: "rounded",
      borderColor: this.theme.border,
      paddingLeft: 1,
      paddingRight: 1,
    })
    const title = this.createText(`>_  nanobot  v${options.version}`, "text", true)
    const context = this.createText([
      "",
      `${options.model}  ·  ${options.access}`,
      options.workspace,
    ].join("\n"), "muted")
    row.add(title)
    row.add(context)
    this.root.add(row)
    this.frames.add(row)
    this.wrote = true
  }

  reset(header: TranscriptHeader): void {
    if (this.navigationTimer) clearTimeout(this.navigationTimer)
    this.navigationTimer = null
    this.clearStreamTimer()
    this.pendingStream = ""
    for (const child of [...this.root.getChildren()]) {
      this.root.remove(child)
      child.destroyRecursively()
    }
    this.live = null
    this.activity = null
    this.styledText.length = 0
    this.markdown.clear()
    this.activities.clear()
    this.frames.clear()
    this.userRows.clear()
    this.userTurnIds.clear()
    this.wrote = false
    this.nextId = 0
    this.navigation = { awayFromBottom: false, unseenOutput: false }
    hideScrollbars(this.root)
    this.header(header)
    this.emitNavigation()
  }

  history(messages: HistoryMessage[]): void {
    for (const message of messages) {
      if (message.role === "user") this.user(message.content, message.turnId)
      else if (message.role === "assistant") this.assistant(message.content)
      else if (message.fileEdits?.length) this.fileEdits(message.fileEdits)
      else this.progress(message.content, message.toolEvents)
    }
    this.finishActivity()
  }

  async prependHistory(messages: HistoryMessage[]): Promise<void> {
    if (messages.length === 0) return
    const previousTop = this.root.scrollTop
    const previousHeight = this.root.scrollHeight
    let index = this.showHeader ? 1 : 0
    for (const message of messages) {
      if (message.role === "user") {
        if (message.turnId && this.userTurnIds.has(message.turnId)) continue
        this.writeRole("›", message.content, "user", index++)
        if (message.turnId) this.userTurnIds.add(message.turnId)
      } else if (message.role === "assistant") {
        this.writeMarkdown(message.content, false, index++)
      } else {
        const activity = this.createActivity(index++)
        const events: ToolProgressEvent[] = message.fileEdits?.length
          ? message.fileEdits.map((edit) => ({
              call_id: `file:${edit.call_id || edit.path || "unknown"}`,
              phase: edit.status === "error" ? "error" : edit.phase,
              name: edit.tool || "edit_file",
              arguments: { path: edit.path, stat: edit.error || formatDiffStat(edit) },
            }))
          : message.toolEvents || []
        this.updateActivity(activity, message.content, events)
      }
    }
    this.renderer.requestRender()
    await this.renderer.idle()
    this.root.scrollTop = previousTop + Math.max(0, this.root.scrollHeight - previousHeight)
  }

  get atTop(): boolean {
    return this.root.scrollTop <= 0
  }

  user(content: string, turnId?: string): boolean {
    if (turnId && this.userTurnIds.has(turnId)) return false
    this.noteOutput()
    this.finishActivity()
    this.writeRole("›", content, "user")
    if (turnId) this.userTurnIds.add(turnId)
    return true
  }

  assistant(content: string): void {
    if (!content.trim()) return
    this.noteOutput()
    this.finishActivity()
    this.writeMarkdown(content, false)
  }

  notice(content: string, error = false): void {
    this.noteOutput()
    this.finishActivity()
    this.writeRole(error ? "×" : "·", content, error ? "error" : "muted")
  }

  stream(delta: string): void {
    if (!delta) return
    this.noteOutput()
    if (!this.live) {
      this.finishActivity()
      const markdown = this.createMarkdown("", true, "assistant-stream")
      const row = this.writeAssistant(markdown)
      this.live = { row, markdown, content: "" }
    }
    if (!this.live.content && !this.pendingStream) {
      this.live.content = delta
      this.live.markdown.content = renderLatexAsUnicode(delta)
      return
    }
    this.pendingStream += delta
    if (this.streamTimer) return
    this.streamTimer = setTimeout(() => this.flushStream(), STREAM_FLUSH_MS)
  }

  finishStream(fallback = ""): void {
    this.flushStream()
    if (this.live) {
      const content = fallback || this.live.content
      // Finalize the retained Markdown node in place. This preserves scroll
      // anchors and avoids the one-frame jump caused by replacing the row.
      this.live.markdown.content = renderLatexAsUnicode(content)
      this.live.markdown.streaming = false
      this.live = null
    } else if (fallback.trim()) {
      this.assistant(fallback)
    }
  }

  reconcileStream(content: string): void {
    if (!content || !this.live) return
    this.clearStreamTimer()
    this.pendingStream = ""
    this.live.content = content
    this.live.markdown.content = renderLatexAsUnicode(content)
  }

  progress(content: string, events: ToolProgressEvent[] = []): string {
    if (events.length === 0 && !content.split("\n").some((line) => cleanProgress(line))) return ""
    this.noteOutput()
    if (!this.activity) this.activity = this.createActivity()
    return this.updateActivity(this.activity, content, events)
  }

  fileEdits(edits: FileEditEvent[]): string {
    return this.progress("", edits.map((edit) => ({
      call_id: `file:${edit.call_id || edit.path || "unknown"}`,
      phase: edit.status === "error" ? "error" : edit.phase,
      name: edit.tool || "edit_file",
      arguments: { path: edit.path, stat: edit.error || formatDiffStat(edit) },
    })))
  }

  finishActivity(): void {
    this.activity = null
  }

  toggleActivityDetails(): boolean | null {
    const activity = [...this.activities]
      .filter((item) => item.lines.length > ACTIVITY_PREVIEW_LINES)
      .at(-1)
    if (!activity) return null
    activity.expanded = !activity.expanded
    this.renderActivity(activity)
    return activity.expanded
  }

  scrollByPage(direction: -1 | 1): void {
    this.root.scrollBy(direction * Math.max(3, Math.floor(this.root.height * 0.7)))
    this.scheduleNavigationUpdate()
  }

  scrollToEdge(edge: "top" | "bottom"): void {
    this.root.scrollTo(edge === "top" ? 0 : this.root.scrollHeight)
    if (edge === "bottom") this.updateNavigation(false, true)
    else this.scheduleNavigationUpdate()
  }

  destroy(): void {
    if (this.navigationTimer) clearTimeout(this.navigationTimer)
    this.clearStreamTimer()
    this.pendingStream = ""
    this.live = null
    this.activity = null
    this.frames.clear()
    this.userRows.clear()
    this.theme.syntax.destroy()
  }

  private flushStream(): void {
    this.clearStreamTimer()
    if (!this.live || !this.pendingStream) return
    this.live.content += this.pendingStream
    this.pendingStream = ""
    this.live.markdown.content = renderLatexAsUnicode(this.live.content)
  }

  private clearStreamTimer(): void {
    if (this.streamTimer) clearTimeout(this.streamTimer)
    this.streamTimer = null
  }

  private noteOutput(): void {
    this.updateNavigation(true)
  }

  private scheduleNavigationUpdate(): void {
    if (this.navigationTimer) clearTimeout(this.navigationTimer)
    this.navigationTimer = setTimeout(() => {
      this.navigationTimer = null
      this.updateNavigation(false)
    }, 0)
  }

  private updateNavigation(output: boolean, forceBottom = false): void {
    const awayFromBottom = forceBottom ? false : !this.isAtBottom()
    const unseenOutput = awayFromBottom
      ? this.navigation.unseenOutput || output
      : false
    if (
      awayFromBottom === this.navigation.awayFromBottom
      && unseenOutput === this.navigation.unseenOutput
    ) return
    this.navigation = { awayFromBottom, unseenOutput }
    this.emitNavigation()
  }

  private isAtBottom(): boolean {
    const bottom = Math.max(0, this.root.scrollHeight - this.root.height)
    return this.root.scrollTop >= bottom - 1
  }

  private emitNavigation(): void {
    this.onNavigationChange?.({ ...this.navigation })
  }

  private id(prefix: string): string {
    this.nextId += 1
    return `${prefix}-${this.nextId}`
  }

  private createRow(kind = "row", direction: "column" | "row" = "column"): BoxRenderable {
    return new BoxRenderable(this.renderer, {
      id: this.id(`${kind}-row`),
      width: "100%",
      marginTop: this.wrote ? 1 : 0,
      flexDirection: direction,
    })
  }

  private createActivity(index?: number): Activity {
    const row = this.createRow("activity")
    const text = new TextRenderable(this.renderer, {
      id: this.id("agent-activity"),
      content: "",
      width: "100%",
      wrapMode: "word",
      fg: this.theme.muted,
    })
    row.add(text)
    this.root.add(row, index)
    this.styledText.push({ renderable: text, tone: "muted" })
    this.wrote = true
    const activity = {
      text,
      lines: [],
      keys: new Map<string, number>(),
      expanded: false,
      events: new Map<string, ToolProgressEvent>(),
    }
    this.activities.add(activity)
    return activity
  }

  private updateActivity(
    activity: Activity,
    content: string,
    events: ToolProgressEvent[] = [],
  ): string {
    const projected = events.map((event) => {
      const key = event.call_id ? `tool:${event.call_id}` : ""
      const merged = key ? mergeToolEvent(activity.events.get(key), event) : event
      if (key) activity.events.set(key, merged)
      return { key, line: renderToolEvent(merged, { workspace: this.workspace }) }
    })
    const lines = events.length > 0
      ? projected.map(({ line }) => line).filter(Boolean)
      : content.split("\n").map(cleanProgress).filter(Boolean)
    for (const [index, line] of lines.entries()) {
      const key = projected[index]?.key || undefined
      const existing = key ? activity.keys.get(key) : undefined
      if (existing !== undefined) {
        activity.lines[existing] = line
      } else if (line !== activity.lines.at(-1)) {
        if (key) activity.keys.set(key, activity.lines.length)
        activity.lines.push(line)
      }
    }
    this.renderActivity(activity)
    return lines.at(-1) || ""
  }

  private renderActivity(activity: Activity): void {
    if (activity.expanded || activity.lines.length <= ACTIVITY_PREVIEW_LINES) {
      activity.text.content = activity.lines.join("\n")
      return
    }
    const visible = activityPreview(activity.lines).slice(-(ACTIVITY_PREVIEW_LINES - 1))
    const visibleSteps = visible.reduce((total, item) => total + item.steps, 0)
    const hidden = activity.lines.length - visibleSteps
    const disclosure = hidden > 0 ? `${hidden} earlier steps` : `${activity.lines.length} steps`
    activity.text.content = [
      `  … ${disclosure} · Ctrl+O expand`,
      ...visible.map((item) => item.text),
    ].join("\n")
  }

  private createText(
    content: string,
    tone: "text" | "muted" | "error" | "user",
    bold = false,
    id = "text",
  ): TextRenderable {
    const text = new TextRenderable(this.renderer, {
      id: this.id(id),
      content,
      width: "100%",
      wrapMode: "word",
      fg: this.theme[tone],
      attributes: bold ? TextAttributes.BOLD : 0,
    })
    this.styledText.push({ renderable: text, tone })
    return text
  }

  private writeRole(
    marker: string,
    content: string,
    tone: "muted" | "error" | "user",
    index?: number,
  ): void {
    const row = this.createRow(tone === "user" ? "user" : "notice", "row")
    if (tone === "user") {
      row.backgroundColor = this.theme.userBackground
        ? RGBA.fromHex(this.theme.userBackground)
        : RGBA.defaultBackground()
      this.userRows.add(row)
    }
    const prefix = this.createText(marker, tone, true, "role-marker")
    prefix.width = 2
    prefix.flexShrink = 0
    const text = this.createText(content, tone === "user" ? "text" : tone, false, "role-content")
    text.width = "auto"
    text.minWidth = 0
    text.flexGrow = 1
    row.add(prefix)
    row.add(text)
    this.root.add(row, index)
    this.wrote = true
  }

  private createMarkdown(content: string, streaming: boolean, id = "markdown"): MarkdownRenderable {
    const markdown = new MarkdownRenderable(this.renderer, {
      id: this.id(id),
      content: renderLatexAsUnicode(content),
      width: "auto",
      minWidth: 0,
      flexGrow: 1,
      flexShrink: 1,
      syntaxStyle: this.theme.syntax,
      streaming,
      internalBlockMode: "top-level",
      tableOptions: {
        style: "columns",
        widthMode: "full",
        columnFitter: "balanced",
        wrapMode: "word",
      },
      treeSitterClient: this.treeSitterClient,
    })
    this.markdown.add(markdown)
    return markdown
  }

  private writeMarkdown(content: string, streaming: boolean, index?: number): void {
    this.writeAssistant(this.createMarkdown(content, streaming), index)
  }

  private writeAssistant(markdown: MarkdownRenderable, index?: number): BoxRenderable {
    const row = this.createRow("assistant", "row")
    const prefix = this.createText("•", "muted", false, "role-marker")
    prefix.width = 2
    prefix.flexShrink = 0
    row.add(prefix)
    row.add(markdown)
    this.root.add(row, index)
    this.wrote = true
    return row
  }
}

function cleanProgress(value: string): string {
  const text = value.trim().replace(/^\*\*(.*?)\*\*$/u, "$1").replace(/\s+/gu, " ")
  return text ? `  · ${text}` : ""
}

function activityPreview(lines: readonly string[]): ActivityPreviewItem[] {
  const preview: ActivityPreviewItem[] = []
  for (const line of lines) {
    const match = line.match(/^  ([›✓]) (Read|Edited|Editing)  /u)
    const group = match ? `${match[1]}:${match[2]}` : undefined
    const previous = preview.at(-1)
    if (match && group && previous?.group === group) {
      previous.steps += 1
      previous.text = `  ${match[1]} ${match[2]} ${previous.steps} files`
      continue
    }
    preview.push({ text: line, steps: 1, ...(group ? { group } : {}) })
  }
  return preview
}

function formatDiffStat(edit: FileEditEvent): string {
  const added = typeof edit.added === "number" ? `+${edit.added}` : ""
  const deleted = typeof edit.deleted === "number" ? `-${edit.deleted}` : ""
  return [added, deleted].filter(Boolean).join(" ")
}
