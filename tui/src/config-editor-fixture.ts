import type { ConfigEditorSnapshot } from "./protocol"

export function configSnapshot(): ConfigEditorSnapshot {
  return {
    version: 1,
    revision: "revision-1",
    config: {
      agents: {
        defaults: {
          workspace: "/work",
          modelPreset: null,
          model: "anthropic/claude-test",
          provider: "auto",
          maxTokens: 8192,
        },
      },
      providers: { anthropic: { apiKey: null, apiBase: null, extraBody: null } },
      channels: { sendProgress: true, telegram: { enabled: false, token: null } },
      tools: { exec: { enable: true, timeout: 60 }, mcpServers: {} },
    },
    schema: {
      type: "object",
      properties: {
        agents: {
          type: "object",
          properties: {
            defaults: {
              type: "object",
              properties: {
                workspace: { type: "string" },
                modelPreset: { anyOf: [{ type: "string" }, { type: "null" }] },
                model: { type: "string" },
                provider: { type: "string" },
                maxTokens: { type: "integer" },
              },
            },
          },
        },
        providers: {
          type: "object",
          properties: {
            anthropic: {
              type: "object",
              properties: {
                apiKey: { anyOf: [{ type: "string" }, { type: "null" }] },
                apiBase: { anyOf: [{ type: "string" }, { type: "null" }] },
                extraBody: { anyOf: [{ type: "object" }, { type: "null" }] },
              },
            },
          },
        },
        channels: {
          type: "object",
          properties: {
            sendProgress: { type: "boolean" },
            telegram: {
              type: "object",
              properties: {
                enabled: { type: "boolean" },
                token: { type: "string" },
              },
              additionalProperties: true,
            },
          },
          additionalProperties: true,
        },
        tools: {
          type: "object",
          properties: {
            exec: {
              type: "object",
              properties: {
                enable: { type: "boolean" },
                timeout: { type: "integer" },
              },
            },
            mcpServers: { type: "object", additionalProperties: { type: "object" } },
          },
        },
      },
    },
    secrets: [
      { path: "/providers/anthropic/apiKey", configured: true },
      { path: "/channels/telegram/token", configured: false },
    ],
    presentation: {
      primary_paths: [
        "/agents/defaults/workspace",
        "/agents/defaults/modelPreset",
        "/agents/defaults/model",
        "/agents/defaults/provider",
      ],
      provider_primary_fields: ["apiKey", "apiBase"],
      sections: [
        {
          id: "models",
          label: "Models and providers",
          description: "Models",
          prefixes: ["/agents/defaults/model", "/agents/defaults/provider", "/providers"],
        },
        { id: "agent", label: "Agent", description: "Agent", prefixes: ["/agents"] },
        { id: "channels", label: "Channels", description: "Channels", prefixes: ["/channels"] },
        { id: "tools", label: "Tools", description: "Tools", prefixes: ["/tools"] },
      ],
      deprecated_paths: [],
    },
  }
}
