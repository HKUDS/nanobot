import {
  BoxRenderable,
  RGBA,
  TextAttributes,
  TextRenderable,
  type CliRenderer,
} from "@opentui/core"

import type { SlashCommand } from "./protocol"

export interface CommandMenuTheme {
  text: string
  muted: string
  border: string
}

/** Retained slash-command discovery with one small completion interface. */
export class CommandMenu {
  readonly root: BoxRenderable
  private commands: SlashCommand[] = []
  private matches: SlashCommand[] = []
  private selected = 0
  private query = ""

  constructor(
    private readonly renderer: CliRenderer,
    private theme: CommandMenuTheme,
  ) {
    this.root = new BoxRenderable(renderer, {
      id: "nanobot-tui-command-menu",
      width: "100%",
      flexShrink: 0,
      flexDirection: "column",
      border: true,
      borderStyle: "rounded",
      borderColor: theme.border,
      paddingLeft: 1,
      paddingRight: 1,
      backgroundColor: RGBA.defaultBackground(),
      visible: false,
    })
  }

  get visible(): boolean {
    return this.root.visible
  }

  setCommands(commands: SlashCommand[]): void {
    this.commands = [...commands].sort((left, right) => left.command.localeCompare(right.command))
    this.update(this.query)
  }

  update(input: string, limit = 6): void {
    const changed = input !== this.query
    this.query = input
    const token = /^\/[^\s]*$/u.test(input) ? input.toLocaleLowerCase() : ""
    if (!token) {
      this.hide()
      return
    }
    const words = token.slice(1)
    this.matches = this.commands
      .filter((command) => (
        command.command.toLocaleLowerCase().startsWith(token)
        || command.title.toLocaleLowerCase().includes(words)
      ))
      .slice(0, Math.max(1, limit))
    this.selected = changed ? 0 : Math.min(this.selected, Math.max(0, this.matches.length - 1))
    this.render()
  }

  move(direction: -1 | 1): boolean {
    if (!this.visible || this.matches.length < 2) return false
    this.selected = (this.selected + direction + this.matches.length) % this.matches.length
    this.render()
    return true
  }

  completion(input: string): string | null {
    if (!this.visible) return null
    const command = this.matches[this.selected]
    if (!command || input.trim() === command.command) return null
    return `${command.command}${command.acceptsArgs ? " " : ""}`
  }

  complete(): string | null {
    if (!this.visible) return null
    const command = this.matches[this.selected]
    if (!command) return null
    this.hide()
    return `${command.command}${command.acceptsArgs ? " " : ""}`
  }

  hide(): void {
    this.matches = []
    this.selected = 0
    this.root.visible = false
    this.clear()
  }

  setTheme(theme: CommandMenuTheme): void {
    this.theme = theme
    this.root.borderColor = theme.border
    if (this.visible) this.render()
  }

  private render(): void {
    this.clear()
    this.root.visible = this.matches.length > 0
    for (const [index, command] of this.matches.entries()) {
      const selected = index === this.selected
      const hint = command.argHint ? ` ${command.argHint}` : ""
      const detail = (command.description || command.title).replace(/\s+/gu, " ")
      const line = new TextRenderable(this.renderer, {
        id: `nanobot-tui-command-${index}`,
        content: `${selected ? "›" : " "} ${command.command}${hint}  ${detail}`,
        width: "100%",
        height: 1,
        wrapMode: "none",
        fg: selected ? this.theme.text : this.theme.muted,
        attributes: selected ? TextAttributes.BOLD : 0,
      })
      this.root.add(line)
    }
  }

  private clear(): void {
    for (const child of [...this.root.getChildren()]) {
      this.root.remove(child)
      child.destroyRecursively()
    }
  }
}
