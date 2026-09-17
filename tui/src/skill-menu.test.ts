import { afterEach, describe, expect, test } from "bun:test"
import { createTestRenderer, type TestRendererSetup } from "@opentui/core/testing"

import { insertSkill, SkillMenu, skillQuery } from "./skill-menu"
import type { SkillCandidate } from "./protocol"

const skills: SkillCandidate[] = [
  { name: "simplify", description: "Simplify code", source: "workspace" },
  { name: "verify", description: "Verify public behavior", source: "builtin" },
]

describe("skill completion", () => {
  let setup: TestRendererSetup | undefined

  afterEach(() => {
    if (setup && !setup.renderer.isDestroyed) setup.renderer.destroy()
    setup = undefined
  })

  test("finds and replaces only the skill reference under the cursor", () => {
    const value = "use $ver before release"
    const query = skillQuery(value, 8)

    expect(query).toEqual({ query: "ver", start: 4, end: 8 })
    expect(insertSkill(value, skills[1]!, query!)).toEqual({
      value: "use $verify before release",
      cursor: 11,
    })
  })

  test("matches backend token boundaries and replaces a whole token", () => {
    expect(skillQuery("$", 1)).toEqual({ query: "", start: 0, end: 1 })
    expect(skillQuery("run ($SIM", 9)).toEqual({ query: "sim", start: 5, end: 9 })
    expect(skillQuery("price$ver", 9)).toBeNull()
    expect(skillQuery("文$ver", 5)).toBeNull()
    expect(skillQuery("$verify done", 12)).toBeNull()

    const midToken = skillQuery("use $verify before release", 8)
    expect(midToken).toEqual({ query: "ver", start: 4, end: 11 })
    expect(insertSkill("use $verify before release", skills[1]!, midToken!).value)
      .toBe("use $verify before release")
  })

  test("filters, navigates, and chooses available skills", async () => {
    setup = await createTestRenderer({ width: 72, height: 16, screenMode: "alternate-screen" })
    const menu = new SkillMenu(setup.renderer, {
      text: "#FFFFFF",
      muted: "#999999",
      border: "#555555",
    })
    setup.renderer.root.add(menu.root)
    menu.show(skills, "", 6)
    await setup.renderOnce()

    expect(setup.captureCharFrame()).toContain("› $simplify")
    expect(setup.captureCharFrame()).toContain("$verify")
    expect(menu.move(1)).toBe(true)
    expect(menu.choose()).toEqual(skills[1]!)

    menu.update("simp", 6)
    expect(menu.choose()).toEqual(skills[0]!)

    menu.show([
      { name: "alpha", description: "Verify workflow", source: "workspace" },
      skills[1]!,
    ], "verify", 6)
    expect(menu.choose()).toEqual(skills[1]!)

    menu.show([skills[0]!], "verify", 6)
    expect(menu.choose()).toBeNull()
  })
})
