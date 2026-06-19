import type { McpPresetInfo, McpPresetsPayload } from "@/lib/types";

export const MCP_PRESETS_CHANGED_EVENT = "nanobot:mcp-presets-changed";

export function isMcpPresetsPayload(value: unknown): value is McpPresetsPayload {
  return !!value
    && typeof value === "object"
    && Array.isArray((value as { presets?: unknown }).presets);
}

export function installedMcpPresetsFromPayload(payload: McpPresetsPayload): McpPresetInfo[] {
  return payload.presets.filter((preset) => preset.installed && preset.configured);
}

export function notifyMcpPresetsChanged(payload: McpPresetsPayload): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<McpPresetsPayload>(MCP_PRESETS_CHANGED_EVENT, {
    detail: payload,
  }));
}
