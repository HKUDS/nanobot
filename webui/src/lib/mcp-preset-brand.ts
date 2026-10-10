import computerUseIcon from "@/assets/apps/computer-use.webp";
import type { McpPresetInfo } from "@/lib/types";

type McpBrandSource = Pick<McpPresetInfo, "name" | "display_name" | "logo_url" | "source" | "driver_setup">;

export function isManagedCuaDriver(preset: Pick<McpPresetInfo, "name" | "source" | "driver_setup">): boolean {
  return preset.name === "cua-driver" && preset.source === "preset" && preset.driver_setup?.managed !== false;
}

/** Product branding is local presentation; server identifiers and custom branding stay untouched. */
export function mcpPresetBrand(preset: McpBrandSource) {
  return isManagedCuaDriver(preset)
    ? { display_name: "Computer Use", logo_url: computerUseIcon }
    : { display_name: preset.display_name, logo_url: preset.logo_url };
}
