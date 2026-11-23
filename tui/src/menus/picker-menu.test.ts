import { afterEach, describe, expect, test } from "bun:test"
import { TextRenderable } from "@opentui/core"
import { createTestRenderer, type TestRendererSetup } from "@opentui/core/testing"

import { PickerMenu } from "./picker-menu"

interface Choice {
  id: string
  label: string
}

const theme = {
  text: "#FFFFFF",
  muted: "#999999",
  border: "#555555",
}

function choices(...ids: string[]): Choice[] {
  return ids.map((id) => ({ id, label: `Choice ${id}` }))
}

describe("PickerMenu", () => {
  let setup: TestRendererSetup | undefined

  afterEach(() => {
    if (setup && !setup.renderer.isDestroyed) setup.renderer.destroy()
    setup = undefined
  })

  test("keeps overflow choices reachable inside a bounded visible window", async () => {
    setup = await createTestRenderer({ width: 60, height: 14, screenMode: "alternate-screen" })
    let picked = ""
    const menu = new PickerMenu<Choice>(setup.renderer, theme, {
      id: "test-picker",
      key: (choice) => choice.id,
      searchText: (choice) => choice.label,
      render: (choice) => choice.label,
      onSelect: (choice) => { picked = choice.id },
    })
    setup.renderer.root.add(menu.root)
    menu.show(choices("0", "1", "2", "3", "4"), "", 3)
    await setup.renderOnce()

    expect(menu.root.getChildren().filter((child) => child.id !== "test-picker-overflow")).toHaveLength(3)
    expect(setup.captureCharFrame()).toContain("1–3 of 5 ↓")
    expect(setup.captureCharFrame()).not.toContain("Choice 3")

    menu.move(1)
    menu.move(1)
    menu.move(1)
    await setup.flush()
    expect(menu.current()?.id).toBe("3")
    expect(setup.captureCharFrame()).toContain("2–4 of 5 ↑↓")
    expect(setup.captureCharFrame()).toContain("› Choice 3")
    expect(setup.captureCharFrame()).not.toContain("Choice 0")

    menu.move(1)
    menu.move(1)
    expect(menu.current()?.id).toBe("0")
    menu.move(-1)
    await setup.flush()
    expect(menu.current()?.id).toBe("4")
    expect(setup.captureCharFrame()).toContain("3–5 of 5 ↑")

    const firstVisible = menu.root.getChildren()[0] as TextRenderable | undefined
    if (!firstVisible) throw new Error("picker row was not rendered")
    await setup.mockMouse.click(firstVisible.x + 2, firstVisible.y)
    expect(picked).toBe("2")
    expect(menu.current()?.id).toBe("2")
  })

  test("keeps preserved and filtered selections inside the visible window", async () => {
    setup = await createTestRenderer({ width: 60, height: 14, screenMode: "alternate-screen" })
    const menu = new PickerMenu<Choice>(setup.renderer, theme, {
      id: "test-picker",
      key: (choice) => choice.id,
      searchText: (choice) => choice.id,
      render: (choice) => choice.label,
    })
    setup.renderer.root.add(menu.root)
    menu.show(choices("a", "b", "c", "d", "e"), "", 2)
    menu.move(1)
    menu.move(1)
    menu.move(1)
    expect(menu.current()?.id).toBe("d")

    menu.replace(choices("e", "d", "a"))
    await setup.renderOnce()
    expect(menu.current()?.id).toBe("d")
    expect(setup.captureCharFrame()).toContain("› Choice d")
    expect(setup.captureCharFrame()).toContain("2–3 of 3 ↑")

    menu.update("e", 2)
    await setup.flush()
    expect(menu.current()?.id).toBe("e")
    expect(setup.captureCharFrame()).toContain("› Choice e")
    expect(menu.root.getChildren()).toHaveLength(1)
  })
})
