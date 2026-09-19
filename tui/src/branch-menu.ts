import { type BoxRenderable, type CliRenderer } from "@opentui/core"

import { PickerMenu, type PickerMenuTheme } from "./picker-menu"
import type { HistoryMessage } from "./protocol"

export interface BranchPoint {
  beforeUserIndex: number
  preview: string
}

export function branchPoints(messages: HistoryMessage[]): BranchPoint[] {
  return messages.flatMap((message) => (
    message.role === "assistant" && typeof message.forkIndex === "number"
      ? [{ beforeUserIndex: message.forkIndex, preview: message.content.replace(/\s+/gu, " ").trim() }]
      : []
  ))
}

export class BranchMenu {
  readonly root: BoxRenderable
  private readonly picker: PickerMenu<BranchPoint>

  constructor(renderer: CliRenderer, theme: PickerMenuTheme) {
    this.picker = new PickerMenu(renderer, theme, {
      id: "nanobot-tui-branch-menu",
      searchText: (point) => point.preview,
      render: (point) => `After turn ${point.beforeUserIndex}  ${point.preview}`,
      emptyText: "No completed replies to branch from",
    })
    this.root = this.picker.root
  }

  get visible(): boolean { return this.picker.visible }
  open(points: BranchPoint[], limit: number): void { this.picker.show(points, "", limit) }
  update(query: string, limit: number): void { this.picker.update(query, limit) }
  move(direction: -1 | 1): boolean { return this.picker.move(direction) }
  choose(): BranchPoint | null { return this.picker.current() }
  hide(): void { this.picker.hide() }
  setTheme(theme: PickerMenuTheme): void { this.picker.setTheme(theme) }
}
