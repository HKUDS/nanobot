import { describe, expect, test } from "bun:test"

import { ComposerDraft, MAX_DRAFT_IMAGES } from "./composer-draft"

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

  test("keeps image bytes outside the editor and drops attachments with deleted placeholders", () => {
    const draft = new ComposerDraft()
    const first = draft.image({ mimeType: "image/png", dataUrl: "data:image/png;base64,AAAA" })
    const second = draft.image({ mimeType: "image/jpeg", dataUrl: "data:image/jpeg;base64,BBBB" })

    expect(first?.text).toBe("[Image #1] ")
    expect(second?.text).toBe("[Image #2] ")
    const visible = `compare ${second?.text}${first?.text}`
    expect(draft.expand(visible)).toBe("compare   ")
    expect(draft.display(visible)).toBe(visible)
    expect(draft.media(visible)).toEqual([
      { data_url: "data:image/jpeg;base64,BBBB", name: "clipboard-image-2.jpg" },
      { data_url: "data:image/png;base64,AAAA", name: "clipboard-image-1.png" },
    ])

    draft.prune(first?.text || "")
    expect(draft.imageCount).toBe(1)
    expect(draft.media(second?.text || "")).toEqual([])
  })

  test("removes a partially edited image placeholder as one atomic unit", () => {
    const draft = new ComposerDraft()
    const image = draft.image({ mimeType: "image/png", dataUrl: "data:image/png;base64,AAAA" })
    const previous = `before ${image?.text}after`
    const value = previous.replace("[Image #1]", "Image #1]")

    expect(draft.reconcileImageEdit(previous, value, 7)).toEqual({
      value: "before  after",
      cursor: 7,
      removedImages: ["Image #1"],
    })
    expect(draft.imageCount).toBe(0)
    expect(draft.media(value)).toEqual([])
  })

  test("removes an edited duplicate occurrence without leaving a placeholder fragment", () => {
    const draft = new ComposerDraft()
    const image = draft.image({ mimeType: "image/png", dataUrl: "data:image/png;base64,AAAA" })
    const label = image?.text.trim() || ""
    const previous = `${label} ${label}`

    expect(draft.reconcileImageEdit(previous, previous.slice(1), 0)).toEqual({
      value: ` ${label}`,
      cursor: 0,
      removedImages: [],
    })
    expect(draft.imageCount).toBe(1)
  })

  test("snaps cursor movement across complete image placeholders", () => {
    const draft = new ComposerDraft()
    const image = draft.image({ mimeType: "image/png", dataUrl: "data:image/png;base64,AAAA" })
    const visible = `a ${image?.text}b`

    expect(draft.snapImageCursor(visible, 3, 2)).toBe(12)
    expect(draft.snapImageCursor(visible, 11, 12)).toBe(2)
    expect(draft.snapImageCursor(visible, 2, 0)).toBe(2)
    expect(draft.snapImageCursor(visible, 12, 13)).toBe(12)
    expect(draft.moveImageCursor(visible, 2, 1)).toBe(12)
    expect(draft.moveImageCursor(visible, 12, -1)).toBe(2)
  })

  test("allocates image labels around literal composer text", () => {
    const draft = new ComposerDraft()
    const content = "Explain [Image #1]"
    const insertion = draft.image(
      { mimeType: "image/png", dataUrl: "data:image/png;base64,AAAA" },
      content,
    )

    expect(insertion?.text).toBe("[Image #2] ")
    expect(draft.expand(`${content} ${insertion?.text}`.trim())).toBe(`${content} `)
  })

  test("detects image labels duplicated after insertion without deleting text", () => {
    const draft = new ComposerDraft()
    const image = draft.image({ mimeType: "image/png", dataUrl: "data:image/png;base64,AAAA" })
    const visible = `${image?.text}Explain [Image #1]`

    expect(draft.hasImageLabelConflict(visible)).toBeTrue()
    expect(draft.expand(visible)).toBe(visible)
  })

  test("detects image labels inside compacted paste text added afterward", () => {
    const draft = new ComposerDraft()
    const image = draft.image({ mimeType: "image/png", dataUrl: "data:image/png;base64,AAAA" })
    const content = ["Explain [Image #1]", ...Array.from({ length: 11 }, () => "detail")].join("\n")
    const paste = draft.paste(content)
    const visible = `${image?.text}${paste.text}`

    expect(draft.hasImageLabelConflict(visible)).toBeTrue()
    expect(draft.expand(visible)).toContain("Explain [Image #1]")
  })

  test("allocates image labels around hidden compacted paste text", () => {
    const draft = new ComposerDraft()
    const content = ["Explain [Image #1]", ...Array.from({ length: 11 }, () => "detail")].join("\n")
    const paste = draft.paste(content)
    const image = draft.image(
      { mimeType: "image/png", dataUrl: "data:image/png;base64,AAAA" },
      paste.text,
    )

    expect(image?.text).toBe("[Image #2] ")
    expect(draft.expand(`${paste.text}${image?.text}`)).toContain("Explain [Image #1]")
  })

  test("matches the gateway image count before accepting another placeholder", () => {
    const draft = new ComposerDraft()
    for (let index = 0; index < MAX_DRAFT_IMAGES; index += 1) {
      expect(draft.image({
        mimeType: "image/png",
        dataUrl: `data:image/png;base64,${index}`,
      })).not.toBeNull()
    }

    expect(draft.image({
      mimeType: "image/png",
      dataUrl: "data:image/png;base64,overflow",
    })).toBeNull()
    expect(draft.imageCount).toBe(MAX_DRAFT_IMAGES)
  })
})
