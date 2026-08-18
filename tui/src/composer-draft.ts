const LARGE_PASTE_CHARS = 1_000
const LARGE_PASTE_LINES = 10

export interface PasteInsertion {
  text: string
  compacted: boolean
  description: string
}

/** Keeps large pasted text out of the editor without changing what is sent. */
export class ComposerDraft {
  private readonly pastes = new Map<string, string>()

  paste(value: string): PasteInsertion {
    const text = value.replace(/\r\n/gu, "\n").replace(/\r/gu, "\n")
    const lines = text.split("\n").length
    if (text.length < LARGE_PASTE_CHARS && lines < LARGE_PASTE_LINES) {
      return { text, compacted: false, description: "" }
    }

    const description = lines > 1 ? `${lines} lines` : `${text.length} characters`
    const base = `[Pasted ${description}]`
    let label = base
    for (let index = 2; this.pastes.has(label); index += 1) label = `${base.slice(0, -1)} #${index}]`
    this.pastes.set(label, text)
    return { text: `${label} `, compacted: true, description }
  }

  expand(visible: string): string {
    let expanded = visible
    for (const [label, content] of this.pastes) expanded = expanded.split(label).join(content)
    return expanded
  }

  prune(visible: string): void {
    for (const label of this.pastes.keys()) {
      if (!visible.includes(label)) this.pastes.delete(label)
    }
  }

  clear(): void {
    this.pastes.clear()
  }
}
