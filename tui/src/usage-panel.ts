import {
  BoxRenderable,
  RGBA,
  StyledText,
  TextAttributes,
  TextRenderable,
  type CliRenderer,
  type TextChunk,
} from "@opentui/core"

import { formatTokenCount } from "./context-panel"
import type { SessionUsageSnapshot } from "./protocol"

export interface UsagePanelTheme {
  text: string
  muted: string
  border: string
  accent: string
  cached: string
  warning: string
  error: string
}

function known(value: number | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
}

function chunk(text: string, color: string, bold = false): TextChunk {
  return {
    __isChunk: true,
    text,
    fg: RGBA.fromHex(color),
    attributes: bold ? TextAttributes.BOLD : 0,
  }
}

/** A bounded, read-only view of persisted model-call usage. */
export class UsagePanel {
  readonly root: BoxRenderable
  private readonly body: TextRenderable
  private snapshot: SessionUsageSnapshot = { context: null, rounds: [] }
  private selected = 0
  private message = ""
  private width = 68
  private height = 24

  constructor(renderer: CliRenderer, private theme: UsagePanelTheme) {
    this.root = new BoxRenderable(renderer, {
      id: "nanobot-tui-usage-panel",
      width: "100%",
      maxWidth: 72,
      flexShrink: 0,
      flexDirection: "column",
      border: true,
      borderStyle: "rounded",
      borderColor: theme.border,
      paddingLeft: 1,
      paddingRight: 1,
      visible: false,
    })
    this.body = new TextRenderable(renderer, {
      id: "nanobot-tui-usage-body",
      width: "100%",
      content: "",
      wrapMode: "none",
    })
    this.root.add(this.body)
  }

  get visible(): boolean {
    return this.root.visible
  }

  showMessage(message: string): void {
    this.message = message
    this.root.visible = true
    this.render()
  }

  show(snapshot: SessionUsageSnapshot): void {
    this.snapshot = snapshot
    this.selected = Math.max(0, snapshot.rounds.length - 1)
    this.message = ""
    this.root.visible = true
    this.render()
  }

  hide(): void {
    this.root.visible = false
  }

  move(direction: -1 | 1): void {
    this.selected = Math.max(0, Math.min(this.snapshot.rounds.length - 1, this.selected + direction))
    this.render()
  }

  resize(terminalWidth: number, terminalHeight: number): void {
    // The shell has one column of padding on each side; the panel adds four.
    this.width = Math.max(1, Math.min(72, terminalWidth - 2) - 4)
    this.height = terminalHeight
    this.render()
  }

  setTheme(theme: UsagePanelTheme): void {
    this.theme = theme
    this.root.borderColor = theme.border
    this.render()
  }

  private render(): void {
    if (!this.visible) return
    const { theme, width } = this
    const compact = this.height < 20
    const tiny = this.height < 14
    const chunks: TextChunk[] = []
    const line = (text: string, color = theme.text, bold = false) => {
      chunks.push(chunk(`${text}\n`, color, bold))
    }
    const heading = (left: string, right: string) => {
      line(`${left}${" ".repeat(Math.max(1, width - left.length - right.length))}${right}`)
    }
    if (this.message) {
      line("Usage", theme.accent, true)
      line(this.message, theme.muted)
    } else {
      const context = this.snapshot.context
      if (context && known(context.tokens)) {
        const window = context.windowTokens
        const percent = known(window) && window > 0
          ? Math.min(100, Math.round(context.tokens / window * 100)) : null
        heading(
          `Context ${formatTokenCount(context.tokens)} / ${known(window) && window > 0 ? formatTokenCount(window) : "?"}`,
          percent === null ? "" : `${percent}%`,
        )
        if (percent !== null && !compact) {
          const filled = Math.round(percent / 100 * width)
          const color = percent >= 90 ? theme.error : percent >= 75 ? theme.warning : theme.muted
          chunks.push(chunk("━".repeat(filled), color), chunk(`${"─".repeat(width - filled)}\n`, theme.border))
        }
      } else {
        line("Context unavailable", theme.muted)
      }
      const rounds = this.snapshot.rounds
      if (!rounds.length) {
        line("No model-call usage available yet", theme.muted)
      } else {
        if (!compact) line("")
        const inputs = rounds.map((round) => round.prompt_tokens ?? 0)
        const max = Math.max(1, ...inputs)
        if (!tiny) heading(width < 48 ? "Rounds" : "Recent rounds", `Input tokens · max ${formatTokenCount(max)}`)
        const chartHeight = Math.max(1, Math.min(6, this.height - 18))
        const slot = Math.max(1, Math.floor(width / rounds.length))
        const barWidth = Math.min(3, Math.max(1, slot - 1))
        const blocks = " ▁▂▃▄▅▆▇█"
        const bars = rounds.map((round, index) => {
          const input = inputs[index] ?? 0
          const units = Math.max(1, Math.round(input / max * chartHeight * 8))
          // Quantize both boundaries from token counts, not the rounded bar height.
          const cachedUnits = known(round.cached_tokens)
            ? Math.min(units, Math.round(Math.min(input, round.cached_tokens) / max * chartHeight * 8))
            : null
          return { units, cachedUnits }
        })
        for (let row = chartHeight - 1; row >= 0; row -= 1) {
          bars.forEach(({ units, cachedUnits }) => {
            const fill = Math.max(0, Math.min(8, units - row * 8))
            const cachedFill = cachedUnits === null ? null
              : Math.max(0, Math.min(fill, cachedUnits - row * 8))
            if (fill === 8 && cachedFill !== null && cachedFill > 0 && cachedFill < 8) {
              const cell = chunk((blocks[cachedFill] ?? " ").repeat(barWidth), theme.cached)
              cell.bg = RGBA.fromHex(theme.accent)
              chunks.push(cell)
            } else {
              // A partial top can contain three regions, but a cell has only two
              // colors. Preserve the empty space and use the larger filled segment.
              const color = cachedFill === null ? theme.muted
                : cachedFill > 0 && cachedFill * 2 >= fill ? theme.cached : theme.accent
              chunks.push(chunk((blocks[fill] ?? " ").repeat(barWidth), color))
            }
            chunks.push(chunk(" ".repeat(slot - barWidth), theme.muted))
          })
          line("")
        }
        const round = rounds[this.selected]
        if (round && !tiny) {
          const input = round.prompt_tokens ?? 0
          const count = (value: number | undefined) => known(value) ? value.toLocaleString("en-US") : "?"
          line(`${width < 48 ? "" : "Round "}${this.selected + 1}/${rounds.length} · In ${count(input)} · Out ${count(round.completion_tokens)}`)
          const cache = known(round.cached_tokens)
            ? `${Math.round(Math.min(input, round.cached_tokens) / input * 100)}%` : "?"
          const time = known(round.generation_ms) ? ` · ${(round.generation_ms / 1000).toFixed(1)}s` : ""
          if (!compact) {
            const estimated = known(round.estimated_tokens) && round.estimated_tokens > 0
            line(`Cache ${cache}${time}${estimated && width >= 48 ? " · includes estimated usage" : ""}`, theme.muted)
            if (estimated && width < 48) line("Includes estimated usage", theme.muted)
          }
        }
        if (!compact) {
          chunks.push(
            chunk("■ ", theme.accent), chunk("Uncached  ", theme.muted),
            chunk("■ ", theme.cached), chunk("Cached  ", theme.muted),
            chunk(width < 48 ? "■ Unknown\n" : "■ Unknown cache\n", theme.muted),
          )
        }
      }
    }
    // Keep the final newline from reserving an empty row in the retained layout.
    const last = chunks.at(-1)
    if (last) last.text = last.text.replace(/\n$/u, "")
    this.body.content = new StyledText(chunks)
  }
}
