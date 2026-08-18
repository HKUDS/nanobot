import { type BoxRenderable, type CliRenderer } from "@opentui/core"

import { PickerMenu, type PickerMenuTheme } from "./picker-menu"
import type { MentionCandidate, MessageOptions } from "./protocol"

export interface MentionQuery {
  query: string
  start: number
  end: number
}

export function mentionQuery(value: string, cursor: number): MentionQuery | null {
  const end = Math.min(Math.max(cursor, 0), value.length)
  const match = /(?:^|[\s([{])@([\p{L}\p{N}_-]*)$/u.exec(value.slice(0, end))
  if (!match) return null
  const valueQuery = match[1] ?? ""
  const start = end - valueQuery.length - 1
  return { query: valueQuery.toLocaleLowerCase(), start, end }
}

export function insertMention(
  value: string,
  candidate: MentionCandidate,
  query: MentionQuery,
): { value: string; cursor: number } {
  const suffix = value.slice(query.end)
  const tail = /^\s/u.test(suffix) ? "" : " "
  const inserted = `@${candidate.name}${tail}`
  return {
    value: `${value.slice(0, query.start)}${inserted}${suffix}`,
    cursor: query.start + inserted.length,
  }
}

export function mentionOptions(value: string, candidates: MentionCandidate[]): MessageOptions {
  const names = new Set(
    [...value.matchAll(/(?:^|[\s([{])@([\p{L}\p{N}_-]+)/gu)]
      .flatMap((match) => match[1] ? [match[1].toLocaleLowerCase()] : []),
  )
  const selected = candidates.filter((candidate) => names.has(candidate.name.toLocaleLowerCase()))
  return {
    cliApps: selected
      .filter((item) => item.kind === "cli")
      .map((item) => ({ name: item.targetName || item.name })),
    mcpPresets: selected
      .filter((item) => item.kind === "mcp")
      .map((item) => ({ name: item.targetName || item.name })),
    sessionMentions: selected.flatMap((item) => item.session ? [item.session] : []),
  }
}

export class MentionMenu {
  readonly root: BoxRenderable
  private readonly picker: PickerMenu<MentionCandidate>

  constructor(renderer: CliRenderer, theme: PickerMenuTheme) {
    this.picker = new PickerMenu(renderer, theme, {
      id: "nanobot-tui-mention-menu",
      searchText: (item) => `${item.name} ${item.displayName} ${item.description}`,
      render: (item) => `${item.displayName}  @${item.name} · ${item.kind}`,
      emptyText: "No matching sessions or tools",
    })
    this.root = this.picker.root
  }

  get visible(): boolean { return this.picker.visible }
  show(items: MentionCandidate[], query: string, limit: number): void {
    this.picker.show(items, query, limit)
  }
  update(query: string, limit: number): void { this.picker.update(query, limit) }
  move(direction: -1 | 1): boolean { return this.picker.move(direction) }
  choose(): MentionCandidate | null { return this.picker.current() }
  hide(): void { this.picker.hide() }
  setTheme(theme: PickerMenuTheme): void { this.picker.setTheme(theme) }
}
