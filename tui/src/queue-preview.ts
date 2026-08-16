import {
  BoxRenderable,
  RGBA,
  StyledText,
  TextAttributes,
  TextRenderable,
  type CliRenderer,
  type TextChunk,
} from "@opentui/core"

import { optionArrowUp } from "./platform-keys"

export interface QueuePreviewTheme {
  accent: string
  muted: string
  faint: string
}

const MAX_VISIBLE = 3

/** A compact, retained projection of follow-ups waiting behind the active turn. */
export class QueuePreview {
  readonly root: BoxRenderable
  private readonly header: TextRenderable
  private readonly rows: TextRenderable[]
  private readonly editKey: string
  private theme: QueuePreviewTheme
  private messages: readonly string[] = []

  constructor(renderer: CliRenderer, theme: QueuePreviewTheme, platform: string = process.platform) {
    this.theme = theme
    this.editKey = optionArrowUp(platform)
    this.root = new BoxRenderable(renderer, {
      id: "nanobot-tui-queue-preview",
      width: "100%",
      height: 1,
      flexShrink: 0,
      flexDirection: "column",
      paddingLeft: 1,
      paddingRight: 1,
      visible: false,
      backgroundColor: RGBA.defaultBackground(),
    })
    this.header = new TextRenderable(renderer, {
      id: "nanobot-tui-queue-header",
      width: "100%",
      height: 1,
      flexShrink: 0,
      truncate: true,
    })
    this.rows = Array.from({ length: MAX_VISIBLE }, (_, index) => new TextRenderable(renderer, {
      id: `nanobot-tui-queue-row-${index}`,
      width: "100%",
      height: 1,
      flexShrink: 0,
      truncate: true,
      visible: false,
    }))
    this.root.add(this.header)
    for (const row of this.rows) this.root.add(row)
  }

  update(messages: readonly string[]): void {
    this.messages = [...messages]
    const visible = messages.slice(-MAX_VISIBLE)
    this.root.visible = messages.length > 0
    this.root.height = messages.length ? visible.length + 1 : 1
    this.header.content = new StyledText([
      chunk("Queued next", this.theme.accent, true),
      chunk(`  ${messages.length}`, this.theme.faint),
      chunk(`  ·  ${this.editKey} edit last`, this.theme.faint),
    ])
    this.rows.forEach((row, index) => {
      const message = visible[index]
      row.visible = Boolean(message)
      row.content = message ? `  ↳ ${oneLine(message)}` : ""
      row.fg = this.theme.muted
    })
  }

  setTheme(theme: QueuePreviewTheme): void {
    this.theme = theme
    this.update(this.messages)
  }
}

function oneLine(value: string): string {
  const preview = value.slice(0, 240).replace(/\s+/gu, " ").trim()
  return value.length > 240 ? `${preview}…` : preview
}

function chunk(text: string, color: string, bold = false): TextChunk {
  return {
    __isChunk: true,
    text,
    fg: RGBA.fromHex(color),
    attributes: bold ? TextAttributes.BOLD : 0,
  }
}
