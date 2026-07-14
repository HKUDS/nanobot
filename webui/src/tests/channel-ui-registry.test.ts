import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import {
  channelUiContribution,
  registeredChannelUiContributions,
} from "@/channel-plugins/registry";

describe("channel UI contributions", () => {
  it("selects channel-owned UI only through the backend manifest entry", () => {
    expect(channelUiContribution("feishu", "webui/index.tsx")?.Panel).toBeTypeOf("function");
    expect(channelUiContribution("weixin", "webui/index.tsx")?.ConnectFlow).toBeTypeOf("function");
    expect(channelUiContribution("feishu", undefined)).toBeUndefined();
    expect(channelUiContribution("feishu", "webui/missing.tsx")).toBeUndefined();
    expect(channelUiContribution("missing", "webui/index.tsx")).toBeUndefined();

    const registrations = registeredChannelUiContributions();
    const channels = registrations.map((entry) => entry.channel);
    expect(channels).toEqual(expect.arrayContaining(["feishu", "weixin"]));
    expect(new Set(channels).size).toBe(channels.length);
    expect(registrations.every((entry) => entry.webui === "webui/index.tsx")).toBe(true);
  });

  it("keeps the core setup panel independent of concrete channel plugins", () => {
    const source = readFileSync(
      resolve(process.cwd(), "src/components/settings/channels/ChannelSetupPanel.tsx"),
      "utf8",
    );

    expect(source).not.toMatch(/feature\.name\s*===\s*["'](?:feishu|weixin)["']/);
    expect(source).not.toMatch(/channel-plugins\/(?:feishu|weixin)/);
    expect(source).not.toMatch(/(?:Feishu|Weixin)(?:AssistantsPanel|ConnectFlow)/);
  });

  it("discovers UI contributions only from channel-owned packages", () => {
    const source = readFileSync(
      resolve(process.cwd(), "src/channel-plugins/registry.ts"),
      "utf8",
    );

    expect(source).toContain("../../../nanobot/channels/*/webui/**/*.{ts,tsx}");
    expect(source).not.toContain('"./*/index.tsx"');
  });

  it("derives channel identity from the package directory", () => {
    for (const channel of ["feishu", "weixin"]) {
      const source = readFileSync(
        resolve(process.cwd(), `../nanobot/channels/${channel}/webui/index.tsx`),
        "utf8",
      );
      expect(source).not.toMatch(/\bchannel\s*:/);
    }
  });

  it("includes channel-owned UI in Tailwind's production scan", () => {
    const source = readFileSync(resolve(process.cwd(), "tailwind.config.js"), "utf8");

    expect(source).toContain("../nanobot/channels/*/webui/**/*.{ts,tsx}");
  });
});
