import { describe, expect, it } from "vitest";

import computerUseIcon from "@/assets/apps/computer-use.webp";
import { mcpPresetBrand } from "@/lib/mcp-preset-brand";
import type { CuaDriverSetup } from "@/lib/types";

describe("managed Computer Use branding", () => {
  const preset = { name: "cua-driver", display_name: "Cua Driver", logo_url: null, source: "preset" };

  it("uses the local product identity for the built-in preset, including older hosts without setup metadata", () => {
    expect(mcpPresetBrand(preset)).toEqual({ display_name: "Computer Use", logo_url: computerUseIcon });
  });

  it("preserves a manually configured Cua server's own branding", () => {
    const driver_setup: CuaDriverSetup = {
      schema: 1, version: "0.33.4", platform: "Darwin", machine: "mac", supported: true,
      installed: true, managed: false, mode: "custom",
    };
    expect(mcpPresetBrand({ ...preset, driver_setup })).toEqual({ display_name: "Cua Driver", logo_url: null });
  });

  it("does not rebrand a custom server or a persisted attachment based on its identifier alone", () => {
    for (const source of ["custom", undefined]) {
      expect(mcpPresetBrand({ ...preset, source })).toEqual({ display_name: "Cua Driver", logo_url: null });
    }
  });
});
