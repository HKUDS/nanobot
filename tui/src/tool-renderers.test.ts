import { describe, expect, test } from "bun:test"

import { mergeToolEvent, renderToolEvent } from "./tool-renderers"

describe("tool renderers", () => {
  test("retains start arguments when an end frame only carries output", () => {
    const event = mergeToolEvent(
      { call_id: "exec-1", phase: "start", name: "exec", arguments: { cmd: "git status" } },
      { call_id: "exec-1", phase: "end", name: "exec", result: { output: "clean" } },
    )
    expect(renderToolEvent(event)).toBe("  ✓ Ran  git status")
  })

  test("uses stable task language for common file and web tools", () => {
    expect(renderToolEvent({ phase: "end", name: "read_file", arguments: { path: "README.md" } }))
      .toBe("  ✓ Read  README.md")
    expect(renderToolEvent({ phase: "start", name: "web_search", arguments: { query: "nanobot" } }))
      .toBe("  › Search web  nanobot")
    expect(renderToolEvent({ phase: "error", name: "web_fetch", error: "timeout" }))
      .toBe("  × Fetch  timeout")
  })

  test("compresses verification and edits into outcome language", () => {
    expect(renderToolEvent({ phase: "end", name: "exec", arguments: { cmd: "bun test" } }))
      .toBe("  ✓ Testing  bun test")
    expect(renderToolEvent({ phase: "end", name: "apply_patch", arguments: { path: "app.ts" } }))
      .toBe("  ✓ Edited  app.ts")
  })

  test("shortens file paths relative to the workspace while preserving the useful tail", () => {
    const workspace = String.raw`C:\workspace\nanobot`
    expect(renderToolEvent({
      phase: "end",
      name: "read_file",
      arguments: { path: String.raw`C:\workspace\nanobot\tui\src\app.ts` },
    }, { workspace })).toBe("  ✓ Read  tui/src/app.ts")
    expect(renderToolEvent({
      phase: "end",
      name: "read_file",
      arguments: {
        path: String.raw`C:\workspace\nanobot\.worktrees\feature\nanobot\providers\fallback_provider.py`,
      },
    }, { workspace })).toBe("  ✓ Read  …/feature/nanobot/providers/fallback_provider.py")
  })

  test("summarizes subagent delegation without exposing raw argument JSON", () => {
    expect(renderToolEvent({
      phase: "end",
      name: "spawn",
      arguments: { task: "Simplify the fallback provider implementation" },
    })).toBe("  ✓ Delegated  Simplify the fallback provider implementation")
  })
})
