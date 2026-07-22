import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ChannelValidationPayload,
  NanobotChannelInstanceInfo,
} from "@/lib/types";

import {
  isVisibleTelegramInstance,
  nextTelegramInstanceId,
  TELEGRAM_PROXY_CLEAR_VALUE,
  TelegramConnectionCheck,
  TelegramCredentialsForm,
  TelegramProxySettings,
} from "../../webui/TelegramBotsPanel";

const apiMocks = vi.hoisted(() => ({
  configureChannel: vi.fn(),
  validateChannel: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    configureChannel: apiMocks.configureChannel,
    validateChannel: apiMocks.validateChannel,
  };
});

const defaultFields = [
  "channels.telegram.name",
  "channels.telegram.groupPolicy",
];

function telegramInstance(
  overrides: Partial<NanobotChannelInstanceInfo> = {},
): NanobotChannelInstanceInfo {
  return {
    id: "default",
    name: "nanobot",
    enabled: false,
    configured: false,
    config_values: {
      "channels.telegram.name": "nanobot",
      "channels.telegram.groupPolicy": "mention",
    },
    configured_fields: defaultFields,
    ...overrides,
  };
}

describe("TelegramBotsPanel", () => {
  beforeEach(() => {
    apiMocks.configureChannel.mockReset();
    apiMocks.validateChannel.mockReset();
  });

  it("reuses the virtual default instance for the first bot", () => {
    const virtualDefault = telegramInstance();

    expect(isVisibleTelegramInstance(virtualDefault)).toBe(false);
    expect(nextTelegramInstanceId([virtualDefault])).toBe("default");
  });

  it("keeps a customized incomplete instance visible", () => {
    const customDefault = telegramInstance({
      name: "Support bot",
      config_values: {
        "channels.telegram.name": "Support bot",
        "channels.telegram.groupPolicy": "mention",
      },
    });

    expect(isVisibleTelegramInstance(customDefault)).toBe(true);
  });

  it("connects with only the required token and keeps optional settings collapsed", async () => {
    apiMocks.validateChannel.mockResolvedValue({
      name: "telegram",
      status: "connected",
      checks: [],
      identity: { name: "token_only_bot" },
      missing_fields: [],
      can_enable: true,
      requires_restart: false,
    } satisfies ChannelValidationPayload);
    apiMocks.configureChannel.mockResolvedValue({
      name: "telegram",
      saved: true,
      saved_keys: [],
    });
    const user = userEvent.setup();
    render(
      <TelegramCredentialsForm
        token="api-token"
        instanceId="default"
        submitLabel="Check and connect"
        tx={(_key, fallback) => fallback}
        onFeaturesUpdate={vi.fn()}
      />,
    );

    const tokenInput = screen.getByLabelText("Bot token", { selector: "input" });
    const advanced = screen.getByText("Advanced options").closest("details");
    expect(tokenInput).toBeRequired();
    expect(advanced).not.toHaveAttribute("open");
    expect(screen.getByLabelText("Bot name", { selector: "input" })).not.toBeVisible();
    expect(
      screen.getByLabelText("Network proxy (optional)", { selector: "input" }),
    ).not.toBeVisible();

    const botToken = "123456:abcdefghijklmnopqrstuvwxyz";
    await user.type(tokenInput, botToken);
    await user.click(screen.getByRole("button", { name: "Check and connect" }));

    await waitFor(() => {
      expect(apiMocks.configureChannel).toHaveBeenCalled();
    });
    expect(apiMocks.validateChannel).toHaveBeenCalledWith(
      "api-token",
      "telegram",
      { "channels.telegram.token": botToken },
      { instanceId: "default" },
    );
    expect(apiMocks.configureChannel).toHaveBeenCalledWith(
      "api-token",
      "telegram",
      {
        "channels.telegram.name": "@token_only_bot",
        "channels.telegram.token": botToken,
      },
      { enable: true, instanceId: "default" },
    );
  });

  it("does not save a new token when Telegram verification is unavailable", async () => {
    apiMocks.validateChannel.mockResolvedValue({
      name: "telegram",
      status: "configured",
      checks: [],
      missing_fields: [],
      can_enable: true,
      requires_restart: false,
    } satisfies ChannelValidationPayload);
    const user = userEvent.setup();
    render(
      <TelegramCredentialsForm
        token="api-token"
        instanceId="default"
        submitLabel="Check and connect"
        tx={(_key, fallback) => fallback}
        onFeaturesUpdate={vi.fn()}
      />,
    );

    await user.type(
      screen.getByLabelText("Bot token", { selector: "input" }),
      "123456:abcdefghijklmnopqrstuvwxyz",
    );
    await user.click(screen.getByRole("button", { name: "Check and connect" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Telegram could not verify this token right now. Try again before connecting.",
    );
    expect(apiMocks.configureChannel).not.toHaveBeenCalled();
  });

  it("uses the entered proxy to verify and save a new bot", async () => {
    apiMocks.validateChannel.mockResolvedValue({
      name: "telegram",
      status: "connected",
      checks: [],
      identity: { name: "proxied_bot" },
      missing_fields: [],
      can_enable: true,
      requires_restart: false,
    } satisfies ChannelValidationPayload);
    apiMocks.configureChannel.mockResolvedValue({
      name: "telegram",
      saved: true,
      saved_keys: [],
    });
    const user = userEvent.setup();
    render(
      <TelegramCredentialsForm
        token="api-token"
        instanceId="default"
        submitLabel="Check and connect"
        tx={(_key, fallback) => fallback}
        onFeaturesUpdate={vi.fn()}
      />,
    );

    const botToken = "123456:abcdefghijklmnopqrstuvwxyz";
    const proxy = "socks5://127.0.0.1:1080";
    await user.type(screen.getByLabelText("Bot token", { selector: "input" }), botToken);
    await user.click(screen.getByText("Advanced options"));
    await user.type(
      screen.getByLabelText("Network proxy (optional)", { selector: "input" }),
      proxy,
    );
    await user.click(screen.getByRole("button", { name: "Check and connect" }));

    await waitFor(() => {
      expect(apiMocks.configureChannel).toHaveBeenCalled();
    });
    expect(apiMocks.validateChannel).toHaveBeenCalledWith(
      "api-token",
      "telegram",
      {
        "channels.telegram.token": botToken,
        "channels.telegram.proxy": proxy,
      },
      { instanceId: "default" },
    );
    expect(apiMocks.configureChannel).toHaveBeenCalledWith(
      "api-token",
      "telegram",
      {
        "channels.telegram.name": "@proxied_bot",
        "channels.telegram.token": botToken,
        "channels.telegram.proxy": proxy,
      },
      { enable: true, instanceId: "default" },
    );
  });

  it("lets an incomplete bot remove a saved proxy before entering a token", async () => {
    apiMocks.configureChannel.mockResolvedValue({
      name: "telegram",
      saved: true,
      saved_keys: [],
    });
    const user = userEvent.setup();
    render(
      <TelegramCredentialsForm
        token="api-token"
        instanceId="support"
        proxyConfigured
        instanceEnabled={false}
        submitLabel="Check and connect"
        tx={(_key, fallback) => fallback}
        onFeaturesUpdate={vi.fn()}
      />,
    );

    await user.click(screen.getByText("Advanced options"));
    await user.click(screen.getByRole("button", { name: "Remove saved proxy" }));

    expect(apiMocks.configureChannel).toHaveBeenCalledWith(
      "api-token",
      "telegram",
      { "channels.telegram.proxy": TELEGRAM_PROXY_CLEAR_VALUE },
      { enable: false, instanceId: "support" },
    );
    expect(apiMocks.validateChannel).not.toHaveBeenCalled();
    expect(await screen.findByText("Saved proxy removed.")).toBeInTheDocument();
  });

  it("lets an existing bot replace and remove its masked proxy", async () => {
    apiMocks.validateChannel.mockResolvedValue({
      name: "telegram",
      status: "connected",
      checks: [],
      identity: { name: "working_bot" },
      missing_fields: [],
      can_enable: true,
      requires_restart: false,
    } satisfies ChannelValidationPayload);
    apiMocks.configureChannel.mockResolvedValue({
      name: "telegram",
      saved: true,
      saved_keys: [],
    });
    const user = userEvent.setup();
    const instance = telegramInstance({
      id: "support",
      name: "Support bot",
      enabled: true,
      configured: true,
      configured_fields: [...defaultFields, "channels.telegram.token", "channels.telegram.proxy"],
    });
    render(
      <TelegramProxySettings
        token="api-token"
        instance={instance}
        onFeaturesUpdate={vi.fn()}
      />,
    );

    expect(screen.getByText("Configured")).toBeInTheDocument();
    await user.click(screen.getByText("Network proxy (optional)"));
    const proxy = "http://127.0.0.1:7890";
    await user.type(
      screen.getByLabelText("Network proxy (optional)", { selector: "input" }),
      proxy,
    );
    await user.click(screen.getByRole("button", { name: "Check and save" }));

    await waitFor(() => {
      expect(apiMocks.configureChannel).toHaveBeenCalledWith(
        "api-token",
        "telegram",
        { "channels.telegram.proxy": proxy },
        { enable: true, instanceId: "support" },
      );
    });

    await user.click(screen.getByRole("button", { name: "Remove saved proxy" }));
    expect(apiMocks.configureChannel).toHaveBeenLastCalledWith(
      "api-token",
      "telegram",
      { "channels.telegram.proxy": TELEGRAM_PROXY_CLEAR_VALUE },
      { enable: true, instanceId: "support" },
    );
  });

  it("points a failed saved-bot proxy transport check to its configured proxy", async () => {
    apiMocks.validateChannel.mockResolvedValue({
      name: "telegram",
      status: "configured",
      checks: [{
        id: "proxy_connection",
        label: "Network proxy",
        status: "warn",
        message: "Could not reach Telegram through the network proxy.",
      }],
      missing_fields: [],
      can_enable: true,
      requires_restart: false,
    } satisfies ChannelValidationPayload);
    const user = userEvent.setup();
    const instance = telegramInstance({
      configured: true,
      configured_fields: [...defaultFields, "channels.telegram.token", "channels.telegram.proxy"],
    });
    render(<TelegramConnectionCheck token="api-token" instance={instance} />);

    await user.click(screen.getByRole("button", { name: "Check connection" }));

    expect(await screen.findByText(
      "Telegram could not be reached through this proxy. Check the address and credentials.",
    )).toBeInTheDocument();
  });

  it("does not blame a saved proxy for a Telegram HTTP failure", async () => {
    apiMocks.validateChannel.mockResolvedValue({
      name: "telegram",
      status: "configured",
      checks: [{
        id: "get_me",
        label: "Bot identity",
        status: "warn",
        message: "Telegram could not verify the token: HTTP 503.",
      }],
      missing_fields: [],
      can_enable: true,
      requires_restart: false,
    } satisfies ChannelValidationPayload);
    const user = userEvent.setup();
    const instance = telegramInstance({
      configured: true,
      configured_fields: [...defaultFields, "channels.telegram.token", "channels.telegram.proxy"],
    });
    render(<TelegramConnectionCheck token="api-token" instance={instance} />);

    await user.click(screen.getByRole("button", { name: "Check connection" }));

    expect(await screen.findByText(
      "A saved token was found, but Telegram could not verify it right now.",
    )).toBeInTheDocument();
    expect(screen.queryByText(/address and credentials/)).not.toBeInTheDocument();
  });

  it("explains when a saved proxy environment variable is not set", async () => {
    apiMocks.validateChannel.mockResolvedValue({
      name: "telegram",
      status: "invalid",
      checks: [{
        id: "proxy_env",
        label: "Proxy environment variable",
        status: "fail",
        message: "Set every environment variable referenced by the network proxy.",
      }],
      missing_fields: [],
      can_enable: false,
      requires_restart: false,
    } satisfies ChannelValidationPayload);
    const user = userEvent.setup();
    const instance = telegramInstance({
      configured: true,
      configured_fields: [...defaultFields, "channels.telegram.token", "channels.telegram.proxy"],
    });
    render(<TelegramConnectionCheck token="api-token" instance={instance} />);

    await user.click(screen.getByRole("button", { name: "Check connection" }));

    expect(await screen.findByText(
      "The saved proxy uses an environment variable that is not set.",
    )).toBeInTheDocument();
  });

  it("clears a checked identity when refreshed instance data arrives", async () => {
    const validation: ChannelValidationPayload = {
      name: "telegram",
      status: "connected",
      checks: [],
      identity: { name: "old_bot" },
      missing_fields: [],
      can_enable: true,
      requires_restart: false,
    };
    apiMocks.validateChannel.mockResolvedValue(validation);
    const user = userEvent.setup();
    const instance = telegramInstance({ configured: true });
    const { rerender } = render(
      <TelegramConnectionCheck token="api-token" instance={instance} />,
    );

    await user.click(screen.getByRole("button", { name: "Check connection" }));
    expect(await screen.findByText("Connected as @old_bot.")).toBeInTheDocument();

    rerender(
      <TelegramConnectionCheck
        token="api-token"
        instance={{ ...instance }}
      />,
    );

    await waitFor(() => {
      expect(screen.queryByText("Connected as @old_bot.")).not.toBeInTheDocument();
    });
    expect(screen.getByText("Verify the saved token with Telegram.")).toBeInTheDocument();
  });
});
