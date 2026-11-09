import { describe, expect, test } from "bun:test"

import { insertMention, mentionOptions, mentionQuery } from "./mention-menu"
import type { MentionCandidate } from "../client"

const candidates: MentionCandidate[] = [
  { kind: "cli", name: "github", displayName: "GitHub", description: "CLI" },
  { kind: "mcp", name: "linear", displayName: "Linear", description: "MCP" },
  {
    kind: "session",
    name: "luma",
    displayName: "Release plan",
    description: "Session",
    session: { id: "handle_release", name: "luma", session_key: "websocket:release", title: "Release plan" },
  },
]

describe("mention projection", () => {
  test("finds and replaces only the mention under the cursor", () => {
    const value = "ask @lu about this"
    const query = mentionQuery(value, 7)
    expect(query).toEqual({ query: "lu", start: 4, end: 7 })
    const completed = insertMention(value, candidates[2]!, query!).value
    expect(completed).toBe("ask @luma about this")
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

  test("does not mix a canonical session with colliding tool completion aliases", () => {
    const colliding: MentionCandidate[] = [
      candidates[2]!,
      { kind: "cli", name: "luma-2", targetName: "luma", displayName: "Luma CLI", description: "CLI" },
      { kind: "mcp", name: "luma-3", targetName: "luma", displayName: "Luma MCP", description: "MCP" },
    ]
    expect(mentionOptions("ask @LUMA", colliding)).toEqual({
      cliApps: [],
      mcpPresets: [],
      sessionMentions: [candidates[2]!.session!],
    })
    expect(mentionOptions("use @luma-2 and @luma-3", colliding)).toEqual({
      cliApps: [{ name: "luma" }],
      mcpPresets: [{ name: "luma" }],
      sessionMentions: [],
    })
  })

  test("maps visible mentions onto the gateway metadata lanes", () => {
    expect(mentionOptions("Use @github with @linear and @luma", candidates)).toEqual({
      cliApps: [{ name: "github" }],
      mcpPresets: [{ name: "linear" }],
      sessionMentions: [{
        id: "handle_release",
        name: "luma",
        session_key: "websocket:release",
        title: "Release plan",
      }],
    })
  })
})
