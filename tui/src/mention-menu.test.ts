import { describe, expect, test } from "bun:test"

import { insertMention, mentionOptions, mentionQuery } from "./mention-menu"
import type { MentionCandidate } from "./protocol"

const candidates: MentionCandidate[] = [
  { kind: "cli", name: "github", displayName: "GitHub", description: "CLI" },
  { kind: "mcp", name: "linear", displayName: "Linear", description: "MCP" },
  {
    kind: "session",
    name: "release-plan",
    displayName: "Release plan",
    description: "Session",
    session: { name: "release-plan", session_key: "websocket:release", title: "Release plan" },
  },
]

describe("mention projection", () => {
  test("finds and replaces only the mention under the cursor", () => {
    const value = "ask @rel about this"
    const query = mentionQuery(value, 8)
    expect(query).toEqual({ query: "rel", start: 4, end: 8 })
    expect(insertMention(value, candidates[2]!, query!).value).toBe("ask @release-plan about this")
  })

  test("keeps namespaced completion aliases separate from gateway capability ids", () => {
    const options = mentionOptions("use @github-2", [{
      kind: "mcp",
      name: "github-2",
      targetName: "github",
      displayName: "GitHub MCP",
      description: "MCP server",
    }])

    expect(options.mcpPresets).toEqual([{ name: "github" }])
  })

  test("maps visible mentions onto the gateway metadata lanes", () => {
    expect(mentionOptions("Use @github with @linear and @release-plan", candidates)).toEqual({
      cliApps: [{ name: "github" }],
      mcpPresets: [{ name: "linear" }],
      sessionMentions: [{
        name: "release-plan",
        session_key: "websocket:release",
        title: "Release plan",
      }],
    })
  })
})
