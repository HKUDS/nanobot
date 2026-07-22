import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ChannelValidationPayload,
  NanobotChannelInstanceInfo,
  NanobotFeatureInfo,
} from "@/lib/types";

import {
  isVisibleTelegramInstance,
  nextTelegramInstanceId,
  TELEGRAM_PROXY_CLEAR_VALUE,
  TelegramBotsPanel,
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

function telegramFeature(instance: NanobotChannelInstanceInfo): NanobotFeatureInfo {
  const field = (
    key: string,
    kind: string,
    required = false,
  ) => ({
    key,
    field: key.split(".").at(-1) ?? key,
    kind,
    choices: key.endsWith(".groupPolicy") ? ["mention", "open"] : [],
    required,
  });
  return {
    name: "telegram",
    display_name: "Telegram",
    webui: "webui/index.ts",
    type: "channel",
    enabled: instance.enabled,
    running: instance.runtime_status === "running",
    runtime_status: instance.runtime_status,
    configured: instance.configured,
    config_values: instance.config_values,
    configured_fields: instance.configured_fields,
    setup: {
      official_url: "https://t.me/BotFather",
      fields: [
        field("channels.telegram.name", "string"),
        field("channels.telegram.token", "secret", true),
        field("channels.telegram.allowFrom", "list"),
        field("channels.telegram.groupPolicy", "enum"),
      ],
    },
    instances: [instance],
    installed: true,
    ready: true,
    status: "enabled",
    install_supported: false,
    requires_restart: false,
  };
}

function telegramValidation(
  overrides: Partial<ChannelValidationPayload> = {},
): ChannelValidationPayload {
  return {
    name: "telegram",
    status: "connected",
    checks: [],
    missing_fields: [],
    can_enable: true,
    requires_restart: false,
    ...overrides,
  };
}

const savedConfiguration = {
  name: "telegram",
  saved: true,
  saved_keys: [],
};

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

  it("renders one token form for an incomplete bot without setup steps", async () => {
    const user = userEvent.setup();
    const customDefault = telegramInstance({
      name: "Support bot",
      config_values: {
        "channels.telegram.name": "Support bot",
        "channels.telegram.groupPolicy": "mention",
      },
    });

    expect(isVisibleTelegramInstance(customDefault)).toBe(true);
    render(
      <TelegramBotsPanel
        token="api-token"
        feature={telegramFeature(customDefault)}
        showBrandLogos={false}
        onFeaturesUpdate={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Support bot" }));

    expect(screen.getAllByLabelText("Bot token", { selector: "input" })).toHaveLength(1);
    expect(screen.getByLabelText("Bot token", { selector: "input" })).toBeVisible();
    expect(screen.queryByText("Next steps")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Add bot" }));
    expect(screen.getByRole("link", { name: "Open BotFather" })).toBeVisible();
    expect(screen.getAllByLabelText("Bot token", { selector: "input" })).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Support bot" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );

    await user.click(screen.getByRole("button", { name: "Support bot" }));
    expect(screen.queryByRole("link", { name: "Open BotFather" })).not.toBeInTheDocument();
    expect(screen.getAllByLabelText("Bot token", { selector: "input" })).toHaveLength(1);
  });

  it("keeps configured controls compact and internal metadata out of the panel", async () => {
    const user = userEvent.setup();
    const configuredFields = [
      ...defaultFields,
      "channels.telegram.token",
      "channels.telegram.proxy",
    ];
    const defaultInstance = telegramInstance({
      enabled: true,
      configured: true,
      runtime_status: "running",
      configured_fields: configuredFields,
    });
    const customInstance = telegramInstance({
      id: "bot-2",
      name: "nano_test0001bot",
      enabled: true,
      configured: true,
      runtime_status: "running",
      config_values: {
        "channels.telegram.name": "nano_test0001bot",
        "channels.telegram.groupPolicy": "mention",
      },
      configured_fields: configuredFields,
    });
    const feature = telegramFeature(defaultInstance);
    feature.instances = [defaultInstance, customInstance];
    render(
      <TelegramBotsPanel
        token="api-token"
        feature={feature}
        showBrandLogos={false}
        onFeaturesUpdate={vi.fn()}
      />,
    );

    expect(screen.getByText("Configured: 2 · Running: 2")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "nanobot" }));

    const defaultCheck = screen.getByRole("button", { name: "Check connection" });
    const defaultControls = defaultCheck.closest("section")?.firstElementChild;
    expect(defaultControls).not.toBeNull();
    expect(within(defaultControls as HTMLElement).getByText("Running")).toBeVisible();
    expect(screen.queryByText("Default bot")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "nano_test0001bot" }));

    const checkConnection = screen.getByRole("button", { name: "Check connection" });
    const customControls = checkConnection.closest("section")?.firstElementChild;
    expect(customControls).not.toBeNull();
    expect(within(customControls as HTMLElement).getByText("Running")).toBeVisible();
    expect(screen.queryByText("bot-2")).not.toBeInTheDocument();
    expect(screen.queryByText("Next steps")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open Telegram setup" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add bot" })).toBeVisible();
    expect(screen.getAllByText("Advanced")).toHaveLength(1);

    const advanced = screen.getByText("Advanced").closest("details");
    expect(advanced).not.toHaveAttribute("open");
    expect(
      screen.getByLabelText("Network proxy (optional)", { selector: "input" }),
    ).not.toBeVisible();

    const advancedSummary = advanced?.querySelector("summary");
    expect(advancedSummary).not.toBeNull();
    await user.click(advancedSummary!);
    expect(advanced).toHaveAttribute("open");
    expect(
      screen.getByLabelText("Network proxy (optional)", { selector: "input" }),
    ).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Add bot" }));
    expect(screen.getByRole("link", { name: "Open BotFather" })).toBeVisible();
    expect(screen.queryByRole("link", { name: "Open Telegram setup" })).not.toBeInTheDocument();
  });

  it("connects with only the required token and keeps optional settings collapsed", async () => {
    apiMocks.validateChannel.mockResolvedValue(telegramValidation({
      identity: { name: "token_only_bot" },
    }));
    apiMocks.configureChannel.mockResolvedValue(savedConfiguration);
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
    apiMocks.validateChannel.mockResolvedValue(telegramValidation({
      status: "configured",
    }));
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
    apiMocks.validateChannel.mockResolvedValue(telegramValidation({
      identity: { name: "proxied_bot" },
    }));
    apiMocks.configureChannel.mockResolvedValue(savedConfiguration);
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
    apiMocks.configureChannel.mockResolvedValue(savedConfiguration);
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
    apiMocks.validateChannel.mockResolvedValue(telegramValidation({
      identity: { name: "working_bot" },
    }));
    apiMocks.configureChannel.mockResolvedValue(savedConfiguration);
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
    apiMocks.validateChannel.mockResolvedValue(telegramValidation({
      status: "configured",
      checks: [{
        id: "proxy_connection",
        label: "Network proxy",
        status: "warn",
        message: "Could not reach Telegram through the network proxy.",
      }],
    }));
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
    apiMocks.validateChannel.mockResolvedValue(telegramValidation({
      status: "configured",
      checks: [{
        id: "get_me",
        label: "Bot identity",
        status: "warn",
        message: "Telegram could not verify the token: HTTP 503.",
      }],
    }));
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
    apiMocks.validateChannel.mockResolvedValue(telegramValidation({
      status: "invalid",
      checks: [{
        id: "proxy_env",
        label: "Proxy environment variable",
        status: "fail",
        message: "Set every environment variable referenced by the network proxy.",
      }],
      can_enable: false,
    }));
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
    const validation = telegramValidation({
      identity: { name: "old_bot" },
    });
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
    expect(screen.getByRole("button", { name: "Check connection" })).toBeVisible();
  });
});
