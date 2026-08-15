import {
  BoxRenderable,
  DiffRenderable,
  RGBA,
  ScrollBoxRenderable,
  SyntaxStyle,
  TextAttributes,
  TextRenderable,
  type CliRenderer,
  type KeyEvent,
  type TreeSitterClient,
} from "@opentui/core"

import type { FileEditEvent, HistoryMessage } from "./protocol"
import { hideScrollbars } from "./scrollbox"

export interface DiffViewerTheme {
  text: string
  muted: string
  border: string
  accent: string
  success: string
  error: string
  addedBackground: string | null
  removedBackground: string | null
  syntax: SyntaxStyle
}

interface DiffItem {
  key: string
  edit: FileEditEvent
}

function editKey(edit: FileEditEvent): string {
  return [edit.call_id, edit.tool, edit.path].filter(Boolean).join("|") || "unknown"
}

/** Merge start/end frames without discarding the final patch payload. */
export function mergeFileEdits(
  previous: FileEditEvent[],
  incoming: FileEditEvent[],
): FileEditEvent[] {
  const edits = new Map(previous.map((edit) => [editKey(edit), edit]))
  for (const edit of incoming) {
    const key = editKey(edit)
    edits.set(key, { ...edits.get(key), ...edit })
  }
  return [...edits.values()]
}

/** File edits from the newest user turn only; never leak an older turn into /diff. */
export function latestTurnFileEdits(messages: HistoryMessage[]): FileEditEvent[] {
  let edits: FileEditEvent[] = []
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index]
    if (!message) continue
    if (message.role === "user") break
    if (message.fileEdits?.length) edits = mergeFileEdits(edits, message.fileEdits)
  }
  return edits
}

function filetype(path: string): string | undefined {
  const extension = path.split(".").at(-1)?.toLocaleLowerCase()
  return ({
    c: "c",
    cc: "cpp",
    cpp: "cpp",
    css: "css",
    go: "go",
    html: "html",
    java: "java",
    js: "javascript",
    json: "json",
    jsx: "javascript",
    md: "markdown",
    py: "python",
    rb: "ruby",
    rs: "rust",
    sh: "bash",
    sql: "sql",
    toml: "toml",
    ts: "typescript",
    tsx: "typescript",
    yaml: "yaml",
    yml: "yaml",
  } as Record<string, string | undefined>)[extension || ""]
}

function stat(edit: FileEditEvent): string {
  const added = Math.max(0, edit.added || 0)
  const deleted = Math.max(0, edit.deleted || 0)
  return `+${added} -${deleted}`
}

/** Full-screen, read-only projection of file-edit events owned by the session. */
export class DiffViewer {
  readonly root: BoxRenderable
  private readonly header: TextRenderable
  private readonly fileHeader: TextRenderable
  private readonly scroll: ScrollBoxRenderable
  private readonly footer: TextRenderable
  private items: DiffItem[] = []
  private selected = 0

  constructor(
    private readonly renderer: CliRenderer,
    private theme: DiffViewerTheme,
    private readonly treeSitterClient: TreeSitterClient,
  ) {
    this.root = new BoxRenderable(renderer, {
      id: "nanobot-tui-diff-viewer",
      position: "absolute",
      top: 0,
      left: 0,
      width: "100%",
      height: "100%",
      zIndex: 100,
      flexDirection: "column",
      padding: 1,
      backgroundColor: RGBA.defaultBackground(),
      visible: false,
    })
    this.header = new TextRenderable(renderer, {
      id: "nanobot-tui-diff-header",
      content: "Diff · Last turn",
      width: "100%",
      height: 1,
      flexShrink: 0,
      fg: theme.text,
      attributes: TextAttributes.BOLD,
    })
    this.fileHeader = new TextRenderable(renderer, {
      id: "nanobot-tui-diff-file",
      content: "",
      width: "100%",
      minHeight: 1,
      maxHeight: 2,
      flexShrink: 0,
      fg: theme.muted,
      wrapMode: "word",
    })
    this.scroll = new ScrollBoxRenderable(renderer, {
      id: "nanobot-tui-diff-scroll",
      width: "100%",
      minHeight: 0,
      flexGrow: 1,
      scrollX: false,
      scrollY: true,
      viewportCulling: true,
      contentOptions: {
        flexDirection: "column",
        paddingTop: 1,
        paddingBottom: 1,
      },
      verticalScrollbarOptions: { visible: false },
      horizontalScrollbarOptions: { visible: false },
    })
    hideScrollbars(this.scroll)
    this.footer = new TextRenderable(renderer, {
      id: "nanobot-tui-diff-footer",
      content: "←/→ file · pgup/pgdn scroll · esc close",
      width: "100%",
      height: 1,
      flexShrink: 0,
      fg: theme.muted,
    })
    this.root.add(this.header)
    this.root.add(this.fileHeader)
    this.root.add(this.scroll)
    this.root.add(this.footer)
  }

  get visible(): boolean {
    return this.root.visible
  }

  show(edits: FileEditEvent[]): void {
    this.update(edits)
    this.root.visible = true
  }

  update(edits: FileEditEvent[]): void {
    const selectedKey = this.items[this.selected]?.key
    this.items = edits.map((edit) => ({ key: editKey(edit), edit }))
    this.selected = Math.max(0, selectedKey
      ? this.items.findIndex((item) => item.key === selectedKey)
      : Math.min(this.selected, this.items.length - 1))
    if (this.selected < 0) this.selected = 0
    this.render()
  }

  hide(): void {
    this.root.visible = false
  }

  handleKey(key: KeyEvent): boolean {
    if (!this.visible) return false
    if (key.name === "escape") {
      this.hide()
      return true
    }
    if (key.name === "pageup" || key.name === "pagedown") {
      const direction = key.name === "pageup" ? -1 : 1
      this.scroll.scrollBy(direction * Math.max(3, Math.floor(this.scroll.height * 0.75)))
      return true
    }
    if (key.name === "home") {
      this.scroll.scrollTo(0)
      return true
    }
    if (key.name === "end") {
      this.scroll.scrollTo(this.scroll.scrollHeight)
      return true
    }
    if (["[", "]", "left", "right"].includes(key.name)) {
      this.select(key.name === "[" || key.name === "left" ? -1 : 1)
      return true
    }
    return false
  }

  resize(width: number): void {
    this.footer.content = width >= 58
      ? "←/→ file · pgup/pgdn scroll · home/end · esc close"
      : "←/→ file · pgup/pgdn · esc"
  }

  setTheme(theme: DiffViewerTheme): void {
    const previousSyntax = this.theme.syntax
    this.theme = theme
    this.header.fg = theme.text
    this.fileHeader.fg = theme.muted
    this.footer.fg = theme.muted
    this.render()
    void this.renderer.idle().catch(() => {}).finally(() => previousSyntax.destroy())
  }

  destroy(): void {
    this.theme.syntax.destroy()
  }

  private select(direction: -1 | 1): void {
    if (this.items.length < 2) return
    this.selected = (this.selected + direction + this.items.length) % this.items.length
    this.render()
  }

  private render(): void {
    for (const child of [...this.scroll.getChildren()]) {
      this.scroll.remove(child)
      child.destroyRecursively()
    }
    const totalAdded = this.items.reduce((sum, item) => sum + Math.max(0, item.edit.added || 0), 0)
    const totalDeleted = this.items.reduce((sum, item) => sum + Math.max(0, item.edit.deleted || 0), 0)
    const count = this.items.length
    this.header.content = count
      ? `Diff · Last turn · ${count} ${count === 1 ? "change" : "changes"} · +${totalAdded} -${totalDeleted}`
      : "Diff · Last turn"
    const item = this.items[this.selected]
    if (!item) {
      this.fileHeader.content = "No file changes in the last turn."
      this.scroll.add(this.text("Run an editing task, then use /diff to inspect its patch.", "muted"))
      return
    }
    const edit = item.edit
    const index = this.items.length > 1 ? `${this.selected + 1}/${this.items.length} · ` : ""
    const state = edit.status === "editing" ? " · editing" : edit.status === "error" ? " · failed" : ""
    this.fileHeader.content = `${index}${edit.path || "Unknown file"} · ${stat(edit)}${state}`
    const text = edit.diff?.format === "unified" ? edit.diff.text?.trimEnd() : ""
    if (text) {
      this.scroll.add(new DiffRenderable(this.renderer, {
        id: `nanobot-tui-diff-${this.selected}`,
        diff: text,
        width: "100%",
        height: "auto",
        flexShrink: 0,
        view: "unified",
        wrapMode: "char",
        showLineNumbers: true,
        fg: this.theme.text,
        filetype: filetype(edit.path || ""),
        syntaxStyle: this.theme.syntax,
        treeSitterClient: this.treeSitterClient,
        lineNumberFg: this.theme.muted,
        lineNumberBg: RGBA.defaultBackground(),
        contextBg: RGBA.defaultBackground(),
        contextContentBg: RGBA.defaultBackground(),
        addedBg: this.theme.addedBackground || RGBA.defaultBackground(),
        addedContentBg: this.theme.addedBackground || RGBA.defaultBackground(),
        addedLineNumberBg: this.theme.addedBackground || RGBA.defaultBackground(),
        removedBg: this.theme.removedBackground || RGBA.defaultBackground(),
        removedContentBg: this.theme.removedBackground || RGBA.defaultBackground(),
        removedLineNumberBg: this.theme.removedBackground || RGBA.defaultBackground(),
        addedSignColor: this.theme.success,
        removedSignColor: this.theme.error,
        selectionBg: this.theme.border,
        selectionFg: this.theme.text,
      }))
      if (edit.diff?.truncated) {
        this.scroll.add(this.text("… Diff truncated by the gateway; line counts may be larger.", "accent"))
      }
      return
    }
    const message = edit.status === "editing"
      ? "The file is still being edited; its patch will appear when the tool finishes."
      : edit.status === "error"
        ? edit.error || "The edit failed before a patch was produced."
        : edit.binary
          ? "Binary file changed; an inline text diff is unavailable."
          : "This edit has no renderable patch."
    this.scroll.add(this.text(message, edit.status === "error" ? "error" : "muted"))
  }

  private text(content: string, tone: "muted" | "error" | "accent"): TextRenderable {
    return new TextRenderable(this.renderer, {
      id: `nanobot-tui-diff-note-${this.selected}-${tone}`,
      content,
      width: "100%",
      minHeight: 1,
      fg: this.theme[tone],
      wrapMode: "word",
    })
  }
}
