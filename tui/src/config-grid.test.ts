import { expect, test } from "bun:test"
import { configColumns } from "./config-grid"

test("configuration columns use terminal cells and reserve space for values", () => {
  for (const width of [16, 32, 56, 80]) {
    const lines = ["Short", "中文名称", "👩‍💻 coding", "Very long provider name that must truncate"]
      .map((label) => configColumns(label, "Unknown", width))
    expect(new Set(lines.map((line) => Bun.stringWidth(line.slice(0, line.indexOf("Unknown"))))).size).toBe(1)
    for (const line of lines) expect(Bun.stringWidth(line)).toBeLessThanOrEqual(width)
  }
})
