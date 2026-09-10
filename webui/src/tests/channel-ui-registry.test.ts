import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import {
  channelUiContribution,
  channelUiOwner,
  channelUiPresentation,
  registeredChannelUiContributions,
} from "@/channel-plugins/registry";

describe("channel UI contributions", () => {
  it("selects channel-owned UI only through the backend manifest entry", () => {
    expect(channelUiContribution("feishu", "webui/index.tsx")?.Panel).toBeDefined();
    expect(channelUiContribution("weixin", "webui/index.tsx")?.ConnectFlow).toBeDefined();
    expect(channelUiContribution("feishu", undefined)).toBeUndefined();
    expect(channelUiContribution("feishu", "webui/missing.tsx")).toBeUndefined();
    expect(channelUiContribution("missing", "webui/index.tsx")).toBeUndefined();

    const registrations = registeredChannelUiContributions();
    const channels = registrations.map((entry) => entry.channel);
    expect(channels).toEqual(expect.arrayContaining(["feishu", "weixin"]));
    expect(new Set(channels).size).toBe(channels.length);
    expect(registrations.every((entry) => /^webui\/index\.tsx?$/.test(entry.webui))).toBe(true);
    expect(channelUiContribution("slack", "webui/index.ts")?.presentation.displayName).toBe("Slack");
  });

  it("keeps aliases inside the owning channel contribution", () => {
    expect(channelUiPresentation("lark")?.displayName).toBe("Lark");
    expect(channelUiPresentation("wechat")?.displayName).toBe("WeChat");
    expect(channelUiOwner("lark")).toBe("feishu");
    expect(channelUiOwner("wechat")).toBe("weixin");
  });

  it("includes channel-owned UI in Tailwind's production scan", () => {
    const source = readFileSync(resolve(process.cwd(), "tailwind.config.js"), "utf8");

    expect(source).toContain("../nanobot/channels/*/webui/**/*.{ts,tsx}");
  });
});
