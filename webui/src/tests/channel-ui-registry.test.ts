import { resolve } from "node:path";

import postcss from "postcss";
import tailwindcss from "tailwindcss";
import loadConfig from "tailwindcss/loadConfig";
import { describe, expect, it, vi } from "vitest";

import {
  channelUiContribution,
  channelUiOwner,
  channelUiPresentation,
  registeredChannelUiContributions,
} from "@/channel-plugins/registry";

describe("channel UI contributions", () => {
  it("selects channel-owned UI only through the backend manifest entry", () => {
    expect(channelUiContribution("feishu", "webui/index.tsx")?.Panel).toBeDefined();
    expect(channelUiContribution("linear", "webui/index.tsx")?.Panel).toBeDefined();
    expect(channelUiContribution("weixin", "webui/index.tsx")?.ConnectFlow).toBeDefined();
    expect(channelUiContribution("feishu", undefined)).toBeUndefined();
    expect(channelUiContribution("feishu", "webui/missing.tsx")).toBeUndefined();
    expect(channelUiContribution("missing", "webui/index.tsx")).toBeUndefined();

    const registrations = registeredChannelUiContributions();
    const channels = registrations.map((entry) => entry.channel);
    expect(channels).toEqual(expect.arrayContaining(["feishu", "linear", "weixin"]));
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

  it("includes channel-owned UI in Tailwind's production scan", async () => {
    vi.stubEnv("NODE_ENV", "production");
    try {
      const config = loadConfig(resolve(process.cwd(), "tailwind.config.js"));
      const result = await postcss([tailwindcss(config)]).process("@tailwind utilities;", { from: undefined });

      // Linear's connecting indicator uses a channel-only arbitrary color.
      let backgroundColor: string | undefined;
      result.root.walkRules(".bg-\\[\\#5E6AD2\\]", (rule) => {
        rule.walkDecls("background-color", (declaration) => {
          backgroundColor = declaration.value;
        });
      });
      expect(backgroundColor?.trim()).toBeTruthy();
    } finally {
      vi.unstubAllEnvs();
    }
  });
});
