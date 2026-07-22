import { describe, expect, it } from "vitest";

import {
  channelIsRunning,
  channelSetup,
  channelStatusLabel,
  channelToggleChecked,
} from "@/components/settings/channels/ChannelIdentity";
import type { NanobotFeatureInfo } from "@/lib/types";

function feature(overrides: Partial<NanobotFeatureInfo>): NanobotFeatureInfo {
  return {
    name: "plugin-chat",
    display_name: "Plugin Chat",
    type: "channel",
    enabled: false,
    installed: true,
    ready: false,
    status: "not_enabled",
    install_supported: true,
    requires_restart: true,
    ...overrides,
  };
}

describe("channelSetup", () => {
  it("builds editable fields for a plugin-owned backend contract", () => {
    const setup = channelSetup(feature({
      setup: {
        fields: [
          {
            key: "channels.plugin-chat.apiToken",
            field: "apiToken",
            kind: "secret",
            choices: [],
            required: true,
          },
          {
            key: "channels.plugin-chat.region",
            field: "region",
            kind: "enum",
            choices: ["us", "eu"],
            required: false,
          },
        ],
        official_url: "https://plugin.example/setup",
      },
    }));

    expect(setup.officialUrl).toBe("https://plugin.example/setup");
    expect(setup.officialLabel).toBe("Open official setup");
    expect(setup.fields).toEqual([
      expect.objectContaining({
        key: "channels.plugin-chat.apiToken",
        label: "Api Token",
        secret: true,
        optional: false,
      }),
      expect.objectContaining({
        key: "channels.plugin-chat.region",
        options: [
          { value: "us", label: "Us" },
          { value: "eu", label: "Eu" },
        ],
      }),
    ]);
  });

  it("filters catalog-only fields that the backend does not accept", () => {
    const setup = channelSetup(feature({
      name: "discord",
      display_name: "Discord",
      webui: "webui/index.ts",
      setup: {
        fields: [{
          key: "channels.discord.token",
          field: "token",
          kind: "secret",
          choices: [],
          required: true,
        }],
      },
    }));

    expect(setup.fields?.map((field) => field.key)).toEqual(["channels.discord.token"]);
    expect(setup.manualFields).toBeUndefined();
  });

  it("uses backend defaults and choices with catalog presentation labels", () => {
    const setup = channelSetup(feature({
      name: "discord",
      display_name: "Discord",
      webui: "webui/index.ts",
      setup: {
        fields: [{
          key: "channels.discord.groupPolicy",
          field: "groupPolicy",
          kind: "enum",
          choices: ["open"],
          required: false,
          default_value: "open",
        }],
      },
    }));

    expect(setup.fields).toEqual([
      expect.objectContaining({
        key: "channels.discord.groupPolicy",
        label: "Group behavior",
        defaultValue: "open",
        options: [{ value: "open", label: "All messages" }],
      }),
    ]);
  });

  it("loads setup copy from the channel-owned locale", () => {
    const setup = channelSetup(feature({
      name: "dingtalk",
      display_name: "DingTalk",
      webui: "webui/index.ts",
    }), "zh-CN");

    expect(setup.summary).toBe("钉钉需要 Stream 模式的应用凭据。");
    expect(setup.steps[0]).toBe("创建或选择一个已启用 Stream 模式的钉钉应用。");
    expect(setup.fields).toContainEqual(expect.objectContaining({
      key: "channels.dingtalk.allowFrom",
      label: "允许的用户",
    }));
  });
});

describe("channel runtime state", () => {
  const tx = (_key: string, fallback: string) => fallback;

  it("only reports a channel on when the runtime is explicitly running", () => {
    const running = feature({ enabled: true, runtime_status: "running" });
    const unknown = feature({ enabled: true });

    expect(channelIsRunning(running)).toBe(true);
    expect(channelToggleChecked(running)).toBe(true);
    expect(channelStatusLabel(running, tx)).toBe("On");
    expect(channelIsRunning(unknown)).toBe(false);
    expect(channelToggleChecked(unknown)).toBe(false);
    expect(channelStatusLabel(unknown, tx)).toBe("Not running");
  });
});
