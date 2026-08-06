import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import weixinUi from "../../../nanobot/channels/weixin/webui";
import { ChannelSetupPanel } from "@/components/settings/channels/ChannelSetupPanel";
import type { NanobotFeatureInfo, NanobotFeaturesPayload } from "@/lib/types";

const api = vi.hoisted(() => ({
  configureChannel: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, configureChannel: api.configureChannel };
});

const refreshedFeatures: NanobotFeaturesPayload = {
  features: [],
  enabled_count: 0,
};

function weixinFeature(
  overrides: Partial<NanobotFeatureInfo> = {},
): NanobotFeatureInfo {
  return {
    name: "weixin",
    display_name: "WeChat",
    webui: "webui/index.tsx",
    type: "channel",
    enabled: true,
    running: true,
    runtime_status: "running",
    configured: true,
    config_values: {
      "channels.weixin.allowFrom": "alice",
      "channels.weixin.sendProgress": "false",
      "channels.weixin.contextMessageBudget": "8",
    },
    configured_fields: ["channels.weixin.token"],
    setup: {
      fields: [
        {
          key: "channels.weixin.token",
          field: "token",
          kind: "secret",
          choices: [],
          required: true,
        },
        {
          key: "channels.weixin.allowFrom",
          field: "allowFrom",
          kind: "list",
          choices: [],
          required: false,
        },
        {
          key: "channels.weixin.sendProgress",
          field: "sendProgress",
          kind: "bool",
          choices: [],
          required: false,
          default_value: "false",
        },
        {
          key: "channels.weixin.contextMessageBudget",
          field: "contextMessageBudget",
          kind: "int",
          choices: [],
          required: false,
          default_value: "8",
        },
      ],
    },
    installed: true,
    ready: true,
    status: "enabled",
    install_supported: true,
    requires_restart: false,
    ...overrides,
  };
}

describe("Weixin settings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.configureChannel.mockResolvedValue({
      name: "weixin",
      saved: true,
      nanobot_features: refreshedFeatures,
    });
  });

  it("exposes every runtime setting in the primary or advanced group", () => {
    const setup = weixinUi.presentation.setup;
    const exposedFields = [
      ...(setup.fields ?? []),
      ...(setup.manualFields ?? []),
    ].map((field) => field.key);

    expect(new Set(exposedFields)).toEqual(new Set([
      "channels.weixin.token",
      "channels.weixin.allowFrom",
      "channels.weixin.baseUrl",
      "channels.weixin.cdnBaseUrl",
      "channels.weixin.routeTag",
      "channels.weixin.stateDir",
      "channels.weixin.pollTimeout",
      "channels.weixin.sendProgress",
      "channels.weixin.sendToolHints",
      "channels.weixin.replyProgressMessages",
      "channels.weixin.replyProgressMaxMessages",
      "channels.weixin.contextMessageBudget",
      "channels.weixin.streaming",
      "channels.weixin.blockStreaming",
      "channels.weixin.blockStreamingMinChars",
      "channels.weixin.blockStreamingMaxMessages",
    ]));
  });

  it("saves primary and collapsed advanced fields in connect mode", async () => {
    const onFeaturesUpdate = vi.fn();
    render(
      <ChannelSetupPanel
        token="api-token"
        feature={weixinFeature()}
        actionKey={null}
        showBrandLogos={false}
        onAction={vi.fn()}
        onFeaturesUpdate={onFeaturesUpdate}
      />,
    );

    const progress = screen.getByRole("radiogroup", { name: "Send progress" });
    fireEvent.click(within(progress).getByRole("radio", { name: "On" }));

    const advanced = screen.getByText("Advanced").closest("details");
    expect(advanced).not.toHaveAttribute("open");
    if (!(advanced instanceof HTMLDetailsElement)) {
      throw new Error("Advanced settings are not rendered in a details element");
    }
    advanced.open = true;
    expect(advanced.open).toBe(true);

    fireEvent.change(screen.getByLabelText("Context message budget"), {
      target: { value: "7" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save settings" }));

    await waitFor(() => expect(api.configureChannel).toHaveBeenCalledWith(
      "api-token",
      "weixin",
      {
        "channels.weixin.allowFrom": "alice",
        "channels.weixin.sendProgress": "true",
        "channels.weixin.contextMessageBudget": "7",
      },
      { enable: true },
    ));
    expect(onFeaturesUpdate).toHaveBeenCalledWith(refreshedFeatures);
    expect(await screen.findByText("Saved settings.")).toBeInTheDocument();
  });

  it("does not enable an inactive channel when saving connect settings", async () => {
    render(
      <ChannelSetupPanel
        token="api-token"
        feature={weixinFeature({
          enabled: false,
          running: false,
          runtime_status: "stopped",
          status: "not_enabled",
        })}
        actionKey={null}
        showBrandLogos={false}
        onAction={vi.fn()}
        onFeaturesUpdate={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Save settings" }));

    await waitFor(() => expect(api.configureChannel).toHaveBeenCalledWith(
      "api-token",
      "weixin",
      {
        "channels.weixin.allowFrom": "alice",
        "channels.weixin.sendProgress": "false",
        "channels.weixin.contextMessageBudget": "8",
      },
      { enable: false },
    ));
  });
});
