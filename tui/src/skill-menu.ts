import { type BoxRenderable, type CliRenderer } from "@opentui/core"

import { PickerMenu, type PickerMenuTheme } from "./picker-menu"
import type { SkillCandidate } from "./protocol"

export interface SkillQuery {
  query: string
  start: number
  end: number
}

export function skillQuery(value: string, cursor: number): SkillQuery | null {
  const cursorAt = Math.min(Math.max(cursor, 0), value.length)
  const match = /(?:^|[^\p{L}\p{N}\p{M}\p{Pc}$])\$([A-Za-z0-9_-]*)$/u.exec(
    value.slice(0, cursorAt),
  )
  if (!match) return null
  const valueQuery = match[1] ?? ""
  const start = cursorAt - valueQuery.length - 1
  const remainder = /^[A-Za-z0-9_-]*/u.exec(value.slice(cursorAt))?.[0] || ""
  return {
    query: valueQuery.toLocaleLowerCase(),
    start,
    end: cursorAt + remainder.length,
  }
}

export function insertSkill(
  value: string,
  candidate: SkillCandidate,
  query: SkillQuery,
): { value: string; cursor: number } {
  const suffix = value.slice(query.end)
  const tail = /^\s/u.test(suffix) ? "" : " "
  const inserted = `$${candidate.name}${tail}`
  return {
    value: `${value.slice(0, query.start)}${inserted}${suffix}`,
    cursor: query.start + inserted.length,
  }
}

export class SkillMenu {
  readonly root: BoxRenderable
  private readonly picker: PickerMenu<SkillCandidate>
  private items: SkillCandidate[] = []

  constructor(renderer: CliRenderer, theme: PickerMenuTheme) {
    this.picker = new PickerMenu(renderer, theme, {
      id: "nanobot-tui-skill-menu",
      key: (item) => item.name,
      searchText: (item) => `${item.name} ${item.description}`,
      render: (item) => `$${item.name}  ${item.description.replace(/\s+/gu, " ")}`,
      emptyText: "No matching skills",
    })
    this.root = this.picker.root
  }

  get visible(): boolean { return this.picker.visible }
  show(items: SkillCandidate[], query: string, limit: number): void {
    this.items = items
    this.picker.show(this.ranked(query), query, limit)
  }
  update(query: string, limit: number): void {
    this.picker.show(this.ranked(query), query, limit)
  }
  move(direction: -1 | 1): boolean { return this.picker.move(direction) }
  choose(): SkillCandidate | null { return this.picker.current() }
  hide(): void { this.picker.hide() }
  setTheme(theme: PickerMenuTheme): void { this.picker.setTheme(theme) }

  private ranked(query: string): SkillCandidate[] {
    const needle = query.toLocaleLowerCase()
    if (!needle) return this.items
    const score = (item: SkillCandidate): number => {
      const name = item.name.toLocaleLowerCase()
      if (name === needle) return 0
      if (name.startsWith(needle)) return 1
      if (name.includes(needle)) return 2
      return 3
    }
    return this.items
      .map((item, index) => ({ item, index, score: score(item) }))
      .sort((left, right) => left.score - right.score || left.index - right.index)
      .map(({ item }) => item)
  }
}
