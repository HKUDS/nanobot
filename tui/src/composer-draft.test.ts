import { describe, expect, test } from "bun:test"

import { ComposerDraft } from "./composer-draft"

describe("ComposerDraft", () => {
  test("keeps ordinary pastes editable as ordinary text", () => {
    const draft = new ComposerDraft()
    const insertion = draft.paste("first\r\nsecond")

    expect(insertion).toEqual({ text: "first\nsecond", compacted: false, description: "" })
    expect(draft.expand(`before ${insertion.text} after`)).toBe("before first\nsecond after")
  })

  test("compacts large pastes and expands only placeholders that remain", () => {
    const draft = new ComposerDraft()
    const content = Array.from({ length: 12 }, (_, index) => `line ${index}`).join("\n")
    const first = draft.paste(content)
    const second = draft.paste(content)

    expect(first.text).toBe("[Pasted 12 lines] ")
    expect(second.text).toBe("[Pasted 12 lines #2] ")
    expect(draft.expand(`review ${first.text.trim()}`)).toBe(`review ${content}`)

    draft.prune(second.text)
    expect(draft.expand(first.text.trim())).toBe(first.text.trim())
    expect(draft.expand(second.text.trim())).toBe(content)
  })
})
