import { describe, expect, it } from "vitest";

import { channelSetup } from "@/components/settings/channels/ChannelIdentity";
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
        requirements: [[["apiToken"]]],
        multi_instance: false,
        official_url: "https://plugin.example/setup",
      },
    }));

    expect(setup.officialUrl).toBe("https://plugin.example/setup");
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
      setup: {
        fields: [{
          key: "channels.discord.token",
          field: "token",
          kind: "secret",
          choices: [],
          required: true,
        }],
        requirements: [[["token"]]],
        multi_instance: false,
      },
    }));

    expect(setup.fields?.map((field) => field.key)).toEqual(["channels.discord.token"]);
    expect(setup.manualFields).toBeUndefined();
  });
});
