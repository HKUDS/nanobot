import {
  BoxRenderable,
  RGBA,
  StyledText,
  TextAttributes,
  TextRenderable,
  type CliRenderer,
  type TextChunk,
} from "@opentui/core"

import type { RecoveryState } from "./protocol"

export interface RecoveryNoticeTheme {
  text: string
  muted: string
  border: string
  accent: string
  warning: string
  error: string
}

interface RecoveryNoticeOptions {
  onContinue: () => void
  onDismiss: () => void
}

/** A quiet action surface for a gateway-owned interrupted turn. */
export class RecoveryNotice {
  readonly root: BoxRenderable
  private readonly title: TextRenderable
  private readonly detail: TextRenderable
  private readonly dismiss: TextRenderable
  private readonly resume: TextRenderable
  private state: RecoveryState | null = null
  private busy = false

  constructor(
    renderer: CliRenderer,
    private theme: RecoveryNoticeTheme,
    options: RecoveryNoticeOptions,
  ) {
    this.root = new BoxRenderable(renderer, {
      id: "nanobot-tui-recovery-notice",
      width: "100%",
      height: 4,
      flexShrink: 0,
      flexDirection: "column",
      border: true,
      borderStyle: "rounded",
      borderColor: theme.border,
      paddingLeft: 1,
      paddingRight: 1,
      visible: false,
      backgroundColor: RGBA.defaultBackground(),
    })
    const header = new BoxRenderable(renderer, {
      id: "nanobot-tui-recovery-header",
      width: "100%",
      height: 1,
      flexDirection: "row",
      alignItems: "center",
      gap: 2,
    })
    this.title = new TextRenderable(renderer, {
      id: "nanobot-tui-recovery-title",
      width: "auto",
      minWidth: 0,
      flexGrow: 1,
      height: 1,
      truncate: true,
      selectable: false,
    })
    this.detail = new TextRenderable(renderer, {
      id: "nanobot-tui-recovery-detail",
      width: "100%",
      height: 1,
      truncate: true,
      selectable: false,
    })
    this.dismiss = this.action(renderer, "dismiss", "Dismiss", options.onDismiss)
    this.resume = this.action(renderer, "continue", "Continue", options.onContinue, true)
    header.add(this.title)
    header.add(this.dismiss)
    header.add(this.resume)
    this.root.add(header)
    this.root.add(this.detail)
  }

  get visible(): boolean {
    return this.root.visible
  }

  show(state: RecoveryState): void {
    this.state = state
    this.busy = false
    this.root.visible = true
    this.render()
  }

  hide(): void {
    this.state = null
    this.busy = false
    this.root.visible = false
  }

  setBusy(busy: boolean): void {
    this.busy = busy
    if (this.visible) this.render()
  }

  setTheme(theme: RecoveryNoticeTheme): void {
    this.theme = theme
    this.root.borderColor = theme.border
    if (this.visible) this.render()
  }

  private action(
    renderer: CliRenderer,
    id: string,
    label: string,
    callback: () => void,
    primary = false,
  ): TextRenderable {
    return new TextRenderable(renderer, {
      id: `nanobot-tui-recovery-${id}`,
      content: label,
      width: label.length,
      height: 1,
      flexShrink: 0,
      selectable: false,
      onMouseOver: () => {
        if (this.busy) return
        const target = primary ? this.resume : this.dismiss
        target.attributes = TextAttributes.BOLD | TextAttributes.UNDERLINE
      },
      onMouseOut: () => this.render(),
      onMouseDown: (event) => {
        if (event.button !== 0 || this.busy) return
        event.preventDefault()
        event.stopPropagation()
        renderer.clearSelection()
        callback()
      },
    })
  }

  private render(): void {
    if (!this.state) return
    const failed = this.state.status === "failed"
    const contextUnavailable = this.state.can_continue === false
    const title = failed ? "Recovery failed" : "Task interrupted"
    const detail = failed
      ? "Review the saved task before continuing."
      : contextUnavailable
        ? "This task can’t be resumed safely. Dismiss to start a new message."
        : "Review the saved context. Tools will not replay automatically."
    this.title.content = new StyledText([
      chunk("⚠ ", failed ? this.theme.error : this.theme.warning),
      chunk(title, this.theme.text, true),
    ])
    this.detail.content = new StyledText([chunk(`  ${detail}`, this.theme.muted)])
    this.dismiss.fg = RGBA.fromHex(this.busy ? this.theme.muted : this.theme.text)
    this.resume.visible = !contextUnavailable
    this.resume.fg = RGBA.fromHex(this.busy ? this.theme.muted : this.theme.accent)
    this.dismiss.attributes = 0
    this.resume.attributes = TextAttributes.BOLD
  }
}

function chunk(text: string, color: string, bold = false): TextChunk {
  return {
    __isChunk: true,
    text,
    fg: RGBA.fromHex(color),
    attributes: bold ? TextAttributes.BOLD : 0,
  }
}
