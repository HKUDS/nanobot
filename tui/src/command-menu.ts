import { type BoxRenderable, type CliRenderer } from "@opentui/core"

import type { SlashCommand } from "./protocol"
import { PickerMenu, type PickerMenuTheme } from "./picker-menu"

export type CommandMenuTheme = PickerMenuTheme

/** Retained slash-command discovery with one small completion interface. */
export class CommandMenu {
  readonly root: BoxRenderable
  private readonly picker: PickerMenu<SlashCommand>
  private commands: SlashCommand[] = []
  private query = ""

  constructor(
    renderer: CliRenderer,
    theme: CommandMenuTheme,
  ) {
    this.picker = new PickerMenu(renderer, theme, {
      id: "nanobot-tui-command-menu",
      searchText: (command) => `${command.command} ${command.title}`,
      render: (command) => {
        const hint = command.argHint ? ` ${command.argHint}` : ""
        const detail = (command.description || command.title).replace(/\s+/gu, " ")
        return `${command.command}${hint}  ${detail}`
      },
    })
    this.root = this.picker.root
  }

  get visible(): boolean {
    return this.picker.visible
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
    if (changed || !this.picker.visible) this.picker.show(this.commands, token.slice(1), limit)
    else this.picker.update(token.slice(1), limit)
  }

  move(direction: -1 | 1): boolean {
    return this.picker.move(direction)
  }

  completion(input: string): string | null {
    if (!this.visible) return null
    const command = this.picker.current()
    if (!command || input.trim() === command.command) return null
    return `${command.command}${command.acceptsArgs ? " " : ""}`
  }

  complete(): string | null {
    if (!this.visible) return null
    const command = this.picker.current()
    if (!command) return null
    this.hide()
    return `${command.command}${command.acceptsArgs ? " " : ""}`
  }

  hide(): void {
    this.picker.hide()
  }

  setTheme(theme: CommandMenuTheme): void {
    this.picker.setTheme(theme)
  }
}
