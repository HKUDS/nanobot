import {
  BoxRenderable,
  RGBA,
  StyledText,
  TextAttributes,
  TextRenderable,
  type CliRenderer,
  type TextChunk,
} from "@opentui/core"

export interface PickerMenuTheme {
  text: string
  muted: string
  border: string
  accent?: string
  warning?: string
  selectedBackground?: string
}

interface PickerMenuOptions<T> {
  id: string
  key?: (item: T) => string
  searchText: (item: T) => string
  render: (item: T, selected: boolean) => string | TextChunk[]
  emptyText?: string
  maxWidth?: number
  onSelect?: (item: T) => void
}

/** Shared retained picker for command discovery and session navigation. */
export class PickerMenu<T> {
  readonly root: BoxRenderable
  private items: T[] = []
  private matches: T[] = []
  private selected = 0
  private query = ""
  private limit = 6

  constructor(
    private readonly renderer: CliRenderer,
    private theme: PickerMenuTheme,
    private readonly options: PickerMenuOptions<T>,
  ) {
    this.root = new BoxRenderable(renderer, {
      id: options.id,
      width: "100%",
      ...(options.maxWidth ? { maxWidth: options.maxWidth } : {}),
      flexShrink: 0,
      flexDirection: "column",
      border: true,
      borderStyle: "rounded",
      borderColor: theme.border,
      paddingLeft: 1,
      paddingRight: 1,
      backgroundColor: RGBA.defaultBackground(),
      visible: false,
      onMouseDown: (event) => {
        if (event.button !== 0) return
        event.preventDefault()
        event.stopPropagation()
        this.renderer.clearSelection()
      },
    })
  }

  get visible(): boolean {
    return this.root.visible
  }

  show(items: T[], query = "", limit = 6): void {
    this.items = items
    this.root.visible = true
    this.update(query, limit)
  }

  replace(items: T[]): void {
    if (!this.visible) return
    this.items = items
    this.update(this.query, this.limit)
  }

  redraw(): void {
    if (this.visible) this.render()
  }

  update(query: string, limit = this.limit): void {
    if (!this.visible) return
    const changed = query !== this.query
    const previous = this.matches[this.selected]
    const previousKey = previous === undefined ? null : this.options.key?.(previous)
    this.query = query
    this.limit = Math.max(1, limit)
    const words = query.trim().toLocaleLowerCase().split(/\s+/u).filter(Boolean)
    this.matches = this.items
      .filter((item) => {
        const haystack = this.options.searchText(item).toLocaleLowerCase()
        return words.every((word) => haystack.includes(word))
      })
      .slice(0, this.limit)
    if (changed) {
      this.selected = 0
    } else {
      const preserved = previous === undefined
        ? -1
        : previousKey === null || previousKey === undefined
          ? this.matches.indexOf(previous)
          : this.matches.findIndex((item) => this.options.key?.(item) === previousKey)
      this.selected = preserved >= 0
        ? preserved
        : Math.min(this.selected, Math.max(0, this.matches.length - 1))
    }
    this.render()
  }

  move(direction: -1 | 1): boolean {
    if (!this.visible || this.matches.length < 2) return false
    this.selected = (this.selected + direction + this.matches.length) % this.matches.length
    this.render()
    return true
  }

  current(): T | null {
    return this.visible ? this.matches[this.selected] ?? null : null
  }

  hide(): void {
    this.items = []
    this.matches = []
    this.selected = 0
    this.query = ""
    this.root.visible = false
    this.clear()
  }

  setTheme(theme: PickerMenuTheme): void {
    this.theme = theme
    this.root.borderColor = theme.border
    if (this.visible) this.render()
  }

  private render(): void {
    this.clear()
    if (this.matches.length === 0) {
      this.root.add(new TextRenderable(this.renderer, {
        id: `${this.options.id}-empty`,
        content: this.options.emptyText || "No matches",
        width: "100%",
        height: 1,
        fg: this.theme.muted,
        selectable: false,
      }))
      return
    }
    for (const [index, item] of this.matches.entries()) {
      const selected = index === this.selected
      const rendered = this.options.render(item, selected)
      const content = typeof rendered === "string"
        ? `${selected ? "›" : " "} ${rendered}`
        : new StyledText([
            chunk(`${selected ? "›" : " "} `, selected ? this.theme.text : this.theme.muted),
            ...rendered,
          ])
      this.root.add(new TextRenderable(this.renderer, {
        id: `${this.options.id}-${index}`,
        content,
        width: "100%",
        height: 1,
        wrapMode: "none",
        fg: selected ? this.theme.text : this.theme.muted,
        selectable: false,
        ...(selected && this.theme.selectedBackground
          ? { backgroundColor: RGBA.fromHex(this.theme.selectedBackground) }
          : {}),
        attributes: selected ? TextAttributes.BOLD : 0,
        onMouseMove: () => {
          if (this.selected === index) return
          this.selected = index
          this.render()
        },
        onMouseDown: (event) => {
          if (event.button !== 0) return
          event.preventDefault()
          event.stopPropagation()
          this.renderer.clearSelection()
          this.selected = index
          this.options.onSelect?.(item)
        },
      }))
    }
  }

  private clear(): void {
    for (const child of [...this.root.getChildren()]) {
      this.root.remove(child)
      child.destroyRecursively()
    }
  }
}

function chunk(text: string, color: string): TextChunk {
  return {
    __isChunk: true,
    text,
    fg: RGBA.fromHex(color),
  }
}
