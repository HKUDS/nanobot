import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

  it("shows the primary controls without setup prose or a save button", () => {
    render(
      <ChannelSetupPanel
        token="api-token"
        feature={weixinFeature()}
        actionKey={null}
        showBrandLogos={false}
        onAction={vi.fn()}
        onFeaturesUpdate={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Connect WeChat" })).toBeInTheDocument();
    expect(screen.getByLabelText("Allowed users")).toBeInTheDocument();
    expect(screen.queryByText("Required setup")).not.toBeInTheDocument();
    expect(screen.queryByText("WeChat channel setup and gateway")).not.toBeInTheDocument();
    expect(screen.queryByText("Next steps")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save settings" })).not.toBeInTheDocument();
    expect(api.configureChannel).not.toHaveBeenCalled();
  });

  it("auto-saves primary and collapsed advanced fields in one update", async () => {
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
    expect(api.configureChannel).toHaveBeenCalledTimes(1);
    expect(onFeaturesUpdate).toHaveBeenCalledWith(refreshedFeatures);
    expect(await screen.findByText("Saved settings.")).toBeInTheDocument();
  });

  it("does not enable an inactive channel when auto-saving connect settings", async () => {
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

    fireEvent.change(screen.getByLabelText("Allowed users"), {
      target: { value: "bob" },
    });

    await waitFor(() => expect(api.configureChannel).toHaveBeenCalledWith(
      "api-token",
      "weixin",
      {
        "channels.weixin.allowFrom": "bob",
        "channels.weixin.sendProgress": "false",
        "channels.weixin.contextMessageBudget": "8",
      },
      { enable: false },
    ));
  });

  it("keeps a failed automatic save visible without adding a manual save button", async () => {
    api.configureChannel.mockRejectedValueOnce(new Error("Gateway unavailable"));
    render(
      <ChannelSetupPanel
        token="api-token"
        feature={weixinFeature()}
        actionKey={null}
        showBrandLogos={false}
        onAction={vi.fn()}
        onFeaturesUpdate={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText("Allowed users"), {
      target: { value: "bob" },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("Gateway unavailable");
    expect(screen.queryByRole("button", { name: "Save settings" })).not.toBeInTheDocument();
  });

  it("queues the latest edit while an automatic save is in flight", async () => {
    let resolveFirstSave!: (value: {
      name: string;
      saved: boolean;
      nanobot_features: NanobotFeaturesPayload;
    }) => void;
    api.configureChannel.mockImplementationOnce(() => new Promise((resolve) => {
      resolveFirstSave = resolve;
    }));
    render(
      <ChannelSetupPanel
        token="api-token"
        feature={weixinFeature()}
        actionKey={null}
        showBrandLogos={false}
        onAction={vi.fn()}
        onFeaturesUpdate={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText("Allowed users"), {
      target: { value: "bob" },
    });
    await waitFor(() => expect(api.configureChannel).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText("Allowed users"), {
      target: { value: "carol" },
    });
    await act(async () => resolveFirstSave({
      name: "weixin",
      saved: true,
      nanobot_features: refreshedFeatures,
    }));

    await waitFor(() => expect(api.configureChannel).toHaveBeenCalledTimes(2));
    expect(api.configureChannel).toHaveBeenLastCalledWith(
      "api-token",
      "weixin",
      {
        "channels.weixin.allowFrom": "carol",
        "channels.weixin.sendProgress": "false",
        "channels.weixin.contextMessageBudget": "8",
      },
      { enable: true },
    );
  });
});
