import { type BoxRenderable, type CliRenderer } from "@opentui/core"

import type { SlashCommand, SlashCommandLifecycle } from "./protocol"
import { PickerMenu, type PickerMenuTheme } from "./picker-menu"

export type CommandMenuTheme = PickerMenuTheme

type TuiCommandAction =
  | "sessions"
  | "new-chat"
  | "context"
  | "diff"
  | "branch"
  | "detach"
  | "exit"

export interface TuiCommand {
  command: string
  title: string
  description: string
  action: TuiCommandAction
}

export type CommandChoice =
  | { source: "gateway"; command: SlashCommand }
  | { source: "tui"; command: TuiCommand }

export type ResolvedSlashCommandLifecycle = Exclude<SlashCommandLifecycle, "agent_turn_with_args">

function descriptor(choice: CommandChoice): SlashCommand | TuiCommand {
  return choice.command
}

export function resolveSlashCommandLifecycle(
  input: string,
  command: SlashCommand,
): ResolvedSlashCommandLifecycle | null {
  const name = input.split(/\s+/u, 1)[0] || ""
  if (name.toLocaleLowerCase() !== command.command.toLocaleLowerCase()) return null
  const args = input.slice(name.length).trim()
  if (args && !command.acceptsArgs) return null
  if (command.lifecycle === "agent_turn_with_args") {
    return args ? "agent_turn" : "side_channel"
  }
  return command.lifecycle
}

/** Retained slash-command discovery with one small completion interface. */
export class CommandMenu {
  readonly root: BoxRenderable
  private readonly picker: PickerMenu<CommandChoice>
  private commands: CommandChoice[] = []
  private query = ""

  constructor(
    renderer: CliRenderer,
    theme: CommandMenuTheme,
  ) {
    this.picker = new PickerMenu(renderer, theme, {
      id: "nanobot-tui-command-menu",
      searchText: (choice) => {
        const command = descriptor(choice)
        return `${command.command} ${command.title}`
      },
      render: (choice) => {
        const command = descriptor(choice)
        const argHint = "argHint" in command ? command.argHint : ""
        const hint = argHint ? ` ${argHint}` : ""
        const detail = (command.description || command.title).replace(/\s+/gu, " ")
        return `${command.command}${hint}  ${detail}`
      },
    })
    this.root = this.picker.root
  }

  get visible(): boolean {
    return this.picker.visible
  }

  setCommands(commands: SlashCommand[], local: TuiCommand[] = []): void {
    const gatewayNames = new Set(commands.map((command) => command.command.toLocaleLowerCase()))
    this.commands = [
      ...commands.map((command): CommandChoice => ({ source: "gateway", command })),
      ...local
        .filter((command) => !gatewayNames.has(command.command.toLocaleLowerCase()))
        .map((command): CommandChoice => ({ source: "tui", command })),
    ].sort((left, right) => descriptor(left).command.localeCompare(descriptor(right).command))
    this.update(this.query)
  }

  resolve(input: string): CommandChoice | null {
    const name = input.trim().split(/\s+/u, 1)[0]?.toLocaleLowerCase()
    if (!name) return null
    return this.commands.find((choice) => {
      const command = descriptor(choice)
      if (command.command.toLocaleLowerCase() !== name) return false
      if (choice.source === "tui") return input.trim().length === command.command.length
      return resolveSlashCommandLifecycle(input.trim(), choice.command) !== null
    }) || null
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
    const choice = this.picker.current()
    if (!choice) return null
    const command = descriptor(choice)
    if (input.trim() === command.command) return null
    const acceptsArgs = choice.source === "gateway" && choice.command.acceptsArgs
    return `${command.command}${acceptsArgs ? " " : ""}`
  }

  complete(): string | null {
    if (!this.visible) return null
    const choice = this.picker.current()
    if (!choice) return null
    const command = descriptor(choice)
    this.hide()
    const acceptsArgs = choice.source === "gateway" && choice.command.acceptsArgs
    return `${command.command}${acceptsArgs ? " " : ""}`
  }

  hide(): void {
    this.picker.hide()
  }

  setTheme(theme: CommandMenuTheme): void {
    this.picker.setTheme(theme)
  }
}
