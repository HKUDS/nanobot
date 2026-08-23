import { describe, expect, test } from "bun:test"

import { configSnapshot } from "./config-editor-fixture"
import {
  buildConfigFields,
  displayConfigValue,
  editorInitialValue,
  parseConfigValue,
  primaryConfigPaths,
  readConfigValue,
  writeConfigValue,
} from "./config-editor-model"

describe("complete config editor model", () => {
  test("keeps the first screen small while resolving the active provider credentials", () => {
    const snapshot = configSnapshot()
    expect(primaryConfigPaths(snapshot)).toEqual([
      "/agents/defaults/workspace",
      "/agents/defaults/modelPreset",
      "/agents/defaults/model",
      "/agents/defaults/provider",
      "/providers/anthropic/apiKey",
      "/providers/anthropic/apiBase",
    ])

    const fields = buildConfigFields(snapshot)
    expect(fields.find((field) => field.path === "/providers/anthropic/apiKey")).toMatchObject({
      secret: true,
      configured: true,
      advanced: false,
    })
    expect(fields.find((field) => field.path === "/agents/defaults/maxTokens")?.advanced).toBe(true)
  })

  test("represents dynamic channel and MCP maps as editable JSON leaves", () => {
    const fields = buildConfigFields(configSnapshot())

    expect(fields.find((field) => field.path === "/channels/telegram")).toMatchObject({
      type: "json",
      advanced: true,
      raw: true,
    })
    expect(fields.find((field) => field.path === "/channels/telegram/token")).toMatchObject({
      secret: true,
      advanced: false,
    })
    expect(fields.find((field) => field.path === "/tools/mcpServers")).toMatchObject({
      type: "json",
    })
    expect(fields.find((field) => field.path === "/providers/anthropic/extraBody")).toMatchObject({
      type: "json",
      nullable: true,
    })
  })

  test("edits nested values without losing sibling configuration", () => {
    const snapshot = configSnapshot()
    const field = buildConfigFields(snapshot).find(
      (candidate) => candidate.path === "/agents/defaults/maxTokens",
    )
    if (!field) throw new Error("missing fixture field")

    writeConfigValue(snapshot.config, field.path, parseConfigValue(field, "4096"))

    expect(readConfigValue(snapshot.config, field.path)).toBe(4096)
    expect(readConfigValue(snapshot.config, "/agents/defaults/model")).toBe(
      "anthropic/claude-test",
    )
  })

  test("never projects configured secret values", () => {
    const snapshot = configSnapshot()
    const field = buildConfigFields(snapshot).find(
      (candidate) => candidate.path === "/providers/anthropic/apiKey",
    )
    if (!field) throw new Error("missing fixture field")

    expect(displayConfigValue(field)).toBe("••••••••")
    expect(parseConfigValue(field, "")).toBeUndefined()

    const channels = snapshot.config.channels as { telegram: { token: string | null } }
    channels.telegram.token = "staged-secret"
    const rawChannel = buildConfigFields(snapshot).find(
      (candidate) => candidate.path === "/channels/telegram" && candidate.raw,
    )
    if (!rawChannel) throw new Error("missing raw channel field")
    expect(editorInitialValue(rawChannel)).not.toContain("staged-secret")
  })
})
