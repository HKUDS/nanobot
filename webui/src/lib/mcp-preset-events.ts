import type { McpPresetInfo, McpPresetsPayload } from "@/lib/types";

export function installedMcpPresetsFromPayload(payload: McpPresetsPayload): McpPresetInfo[] {
  return payload.presets.filter(
    (preset) => preset.source !== "agent-plugin"
      && (preset.enabled ?? (preset.installed && preset.configured)),
  );
}
