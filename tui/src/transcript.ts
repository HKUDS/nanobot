import {
  BoxRenderable,
  MarkdownRenderable,
  ScrollBoxRenderable,
  SyntaxStyle,
  TextAttributes,
  TextRenderable,
  type CliRenderer,
  type TreeSitterClient,
} from "@opentui/core"

import type { FileEditEvent, HistoryMessage, ToolProgressEvent } from "./protocol"

export interface TranscriptTheme {
  text: string
  muted: string
  error: string
  user: string
  assistant: string
  syntax: SyntaxStyle
}

export interface TranscriptHeader {
  model: string
  workspace: string
  version: string
  access: string
}

interface Activity {
  text: TextRenderable
  lines: string[]
  keys: Map<string, number>
  expanded: boolean
}

const ACTIVITY_PREVIEW_LINES = 6

/** Projects gateway events into retained, reflowable conversation cells. */
export class Transcript {
  readonly root: ScrollBoxRenderable
  private live: { row: BoxRenderable; markdown: MarkdownRenderable; content: string } | null = null
  private activity: Activity | null = null
  private readonly styledText: Array<{
    renderable: TextRenderable
    tone: "text" | "muted" | "error" | "user" | "assistant"
  }> = []
  private readonly markdown = new Set<MarkdownRenderable>()
  private readonly activities = new Set<Activity>()
  private wrote = false
  private nextId = 0

  constructor(
    private readonly renderer: CliRenderer,
    private theme: TranscriptTheme,
    private readonly treeSitterClient: TreeSitterClient,
  ) {
    this.root = new ScrollBoxRenderable(renderer, {
      id: "nanobot-tui-transcript",
      width: "100%",
      minHeight: 0,
      flexGrow: 1,
      scrollX: false,
      scrollY: true,
      stickyScroll: true,
      stickyStart: "bottom",
      viewportCulling: true,
      contentOptions: {
        flexDirection: "column",
        paddingTop: 1,
        paddingBottom: 1,
        paddingLeft: 1,
        paddingRight: 1,
      },
      verticalScrollbarOptions: { visible: false },
      horizontalScrollbarOptions: { visible: false },
    })
    this.root.verticalScrollBar.visible = false
    this.root.horizontalScrollBar.visible = false
  }

  setTheme(theme: TranscriptTheme): void {
    const previousSyntax = this.theme.syntax
    this.theme = theme
    for (const { renderable, tone } of this.styledText) renderable.fg = theme[tone]
    for (const renderable of this.markdown) renderable.syntaxStyle = theme.syntax
    // Markdown may still be rendering this frame. Release the prior native
    // style only after the renderer reaches idle, matching OpenCode's retained
    // theme lifecycle and avoiding both leaks and use-after-free transitions.
    void this.renderer.idle().catch(() => {}).finally(() => previousSyntax.destroy())
  }

  header(options: TranscriptHeader): void {
    const row = this.createRow("header")
    const title = this.createText(`>_  nanobot  v${options.version}`, "text", true)
    const context = this.createText([
      `${options.model}  ·  ${options.access}`,
      options.workspace,
    ].join("\n"), "muted")
    row.add(title)
    row.add(context)
    this.root.add(row)
    this.wrote = true
  }

  reset(header: TranscriptHeader): void {
    for (const child of [...this.root.getChildren()]) {
      this.root.remove(child)
      child.destroyRecursively()
    }
    this.live = null
    this.activity = null
    this.styledText.length = 0
    this.markdown.clear()
    this.activities.clear()
    this.wrote = false
    this.nextId = 0
    this.header(header)
  }

  history(messages: HistoryMessage[]): void {
    for (const message of messages) {
      if (message.role === "user") this.user(message.content)
      else if (message.role === "assistant") this.assistant(message.content)
      else if (message.fileEdits?.length) this.fileEdits(message.fileEdits)
      else this.progress(message.content, message.toolEvents)
    }
    this.finishActivity()
  }

  user(content: string): void {
    this.finishActivity()
    this.writeRole("›", content, "user")
  }

  assistant(content: string): void {
    if (!content.trim()) return
    this.finishActivity()
    this.writeMarkdown(content, false)
  }

  notice(content: string, error = false): void {
    this.finishActivity()
    this.writeRole(error ? "×" : "·", content, error ? "error" : "muted")
  }

  stream(delta: string): void {
    if (!delta) return
    if (!this.live) {
      this.finishActivity()
      const markdown = this.createMarkdown("", true, "assistant-stream")
      const row = this.writeAssistant(markdown)
      this.live = { row, markdown, content: "" }
    }
    this.live.content += delta
    this.live.markdown.content = this.live.content
  }

  finishStream(fallback = ""): void {
    if (this.live) {
      const content = fallback || this.live.content
      // Finalize the retained Markdown node in place. This preserves scroll
      // anchors and avoids the one-frame jump caused by replacing the row.
      this.live.markdown.content = content
      this.live.markdown.streaming = false
      this.live = null
    } else if (fallback.trim()) {
      this.assistant(fallback)
    }
  }

  reconcileStream(content: string): void {
    if (!content || !this.live) return
    this.live.content = content
    this.live.markdown.content = content
  }

  progress(content: string, events: ToolProgressEvent[] = []): string {
    const lines = events.length > 0
      ? events.map(formatToolEvent).filter(Boolean)
      : content.split("\n").map(cleanProgress).filter(Boolean)
    if (lines.length === 0) return ""
    if (!this.activity) this.activity = this.createActivity()
    for (const [index, line] of lines.entries()) {
      const key = events[index]?.call_id ? `tool:${events[index]?.call_id}` : undefined
      const existing = key ? this.activity.keys.get(key) : undefined
      if (existing !== undefined) {
        this.activity.lines[existing] = line
      } else if (line !== this.activity.lines.at(-1)) {
        if (key) this.activity.keys.set(key, this.activity.lines.length)
        this.activity.lines.push(line)
      }
    }
    this.renderActivity(this.activity)
    return lines.at(-1) || ""
  }

  fileEdits(edits: FileEditEvent[]): string {
    return this.progress("", edits.map((edit) => ({
      call_id: `file:${edit.call_id || edit.path || "unknown"}`,
      phase: edit.status === "error" ? "error" : edit.phase,
      name: edit.path ? `${edit.tool || "edit"} ${edit.path}` : "edit file",
      arguments: edit.error || formatDiffStat(edit),
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
  }

  scrollToEdge(edge: "top" | "bottom"): void {
    this.root.scrollTo(edge === "top" ? 0 : this.root.scrollHeight)
  }

  destroy(): void {
    this.live = null
    this.activity = null
    this.theme.syntax.destroy()
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

  private createActivity(): Activity {
    const row = this.createRow("activity")
    const text = new TextRenderable(this.renderer, {
      id: this.id("agent-activity"),
      content: "",
      width: "100%",
      wrapMode: "word",
      fg: this.theme.muted,
    })
    row.add(text)
    this.root.add(row)
    this.styledText.push({ renderable: text, tone: "muted" })
    this.wrote = true
    const activity = { text, lines: [], keys: new Map(), expanded: false }
    this.activities.add(activity)
    return activity
  }

  private renderActivity(activity: Activity): void {
    if (activity.expanded || activity.lines.length <= ACTIVITY_PREVIEW_LINES) {
      activity.text.content = activity.lines.join("\n")
      return
    }
    const visible = activity.lines.slice(-(ACTIVITY_PREVIEW_LINES - 1))
    const hidden = activity.lines.length - visible.length
    activity.text.content = [`  … ${hidden} earlier steps · Ctrl+O expand`, ...visible].join("\n")
  }

  private createText(
    content: string,
    tone: "text" | "muted" | "error" | "user" | "assistant",
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
  ): void {
    const row = this.createRow(tone === "user" ? "user" : "notice", "row")
    const prefix = this.createText(marker, tone, true, "role-marker")
    prefix.width = 2
    prefix.flexShrink = 0
    const text = this.createText(content, tone === "user" ? "text" : tone, false, "role-content")
    text.width = "auto"
    text.minWidth = 0
    text.flexGrow = 1
    row.add(prefix)
    row.add(text)
    this.root.add(row)
    this.wrote = true
  }

  private createMarkdown(content: string, streaming: boolean, id = "markdown"): MarkdownRenderable {
    const markdown = new MarkdownRenderable(this.renderer, {
      id: this.id(id),
      content,
      width: "auto",
      minWidth: 0,
      flexGrow: 1,
      syntaxStyle: this.theme.syntax,
      streaming,
      internalBlockMode: "top-level",
      treeSitterClient: this.treeSitterClient,
    })
    this.markdown.add(markdown)
    return markdown
  }

  private writeMarkdown(content: string, streaming: boolean): void {
    this.writeAssistant(this.createMarkdown(content, streaming))
  }

  private writeAssistant(markdown: MarkdownRenderable): BoxRenderable {
    const row = this.createRow("assistant", "row")
    const prefix = this.createText("•", "assistant", false, "role-marker")
    prefix.width = 2
    prefix.flexShrink = 0
    row.add(prefix)
    row.add(markdown)
    this.root.add(row)
    this.wrote = true
    return row
  }
}

function cleanProgress(value: string): string {
  const text = value.trim().replace(/^\*\*(.*?)\*\*$/u, "$1").replace(/\s+/gu, " ")
  return text ? `  · ${text}` : ""
}

function formatToolEvent(event: ToolProgressEvent): string {
  const phase = event.phase || "start"
  const marker = phase === "error" ? "×" : phase === "end" ? "✓" : "›"
  const name = event.name?.trim() || "tool"
  const detail = phase === "error"
    ? compactValue(event.error)
    : phase === "start"
      ? compactValue(event.arguments)
      : ""
  return `  ${marker} ${name}${detail ? ` ${detail}` : ""}`
}

function compactValue(value: unknown): string {
  if (value == null || value === "") return ""
  const text = typeof value === "string" ? value : JSON.stringify(value)
  return text.length > 72 ? `${text.slice(0, 69)}…` : text
}

function formatDiffStat(edit: FileEditEvent): string {
  const added = typeof edit.added === "number" ? `+${edit.added}` : ""
  const deleted = typeof edit.deleted === "number" ? `-${edit.deleted}` : ""
  return [added, deleted].filter(Boolean).join(" ")
}
