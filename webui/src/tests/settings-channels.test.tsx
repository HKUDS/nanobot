import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type {
  ChannelSetupContract,
  ChannelSetupContractField,
  NanobotFeatureInfo,
} from "@/lib/types";
import { requestMutationMock, jsonResponse, settingsPayload, renderSettingsView, installSettingsViewTestHooks } from "@/tests/settings-test-utils";


function channelSetupField(
  channel: string,
  field: string,
  kind: ChannelSetupContractField["kind"] = "string",
  options: {
    required?: boolean;
    choices?: string[];
    defaultValue?: string;
  } = {},
): ChannelSetupContractField {
  return {
    key: `channels.${channel}.${field}`,
    field,
    kind,
    choices: options.choices ?? [],
    required: options.required ?? false,
    ...(options.defaultValue === undefined ? {} : { default_value: options.defaultValue }),
  };
}

function channelSetupContract(
  channel: "discord" | "email" | "feishu" | "matrix" | "qq",
): ChannelSetupContract {
  const field = (
    name: string,
    kind: ChannelSetupContractField["kind"] = "string",
    options: Parameters<typeof channelSetupField>[3] = {},
  ) => channelSetupField(channel, name, kind, options);

  switch (channel) {
    case "discord":
      return {
        official_url: "https://discord.com/developers/applications",
        fields: [
          field("token", "secret", { required: true }),
          field("allowFrom", "list"),
          field("allowChannels", "list"),
          field("groupPolicy", "enum", {
            choices: ["mention", "open"],
            defaultValue: "mention",
          }),
        ],
        requirements: [
          { alternatives: [["channels.discord.token"]] },
        ],
      };
    case "email":
      return {
        official_url: "https://support.google.com/accounts/answer/185833",
        fields: [
          field("consentGranted", "bool", { required: true, defaultValue: "false" }),
          field("imapHost", "string", { required: true }),
          field("imapPort", "int"),
          field("imapUsername", "string", { required: true }),
          field("imapPassword", "secret", { required: true }),
          field("smtpHost", "string", { required: true }),
          field("smtpPort", "int"),
          field("smtpUsername", "string", { required: true }),
          field("smtpPassword", "secret", { required: true }),
          field("fromAddress"),
          field("pollIntervalSeconds", "int"),
          field("allowFrom", "list"),
          field("verifyDkim", "bool", { defaultValue: "true" }),
          field("verifySpf", "bool", { defaultValue: "true" }),
        ],
        requirements: [
          { alternatives: [["channels.email.consentGranted"]] },
          { alternatives: [["channels.email.imapHost"]] },
          { alternatives: [["channels.email.imapUsername"]] },
          { alternatives: [["channels.email.imapPassword"]] },
          { alternatives: [["channels.email.smtpHost"]] },
          { alternatives: [["channels.email.smtpUsername"]] },
          { alternatives: [["channels.email.smtpPassword"]] },
        ],
      };
    case "feishu":
      return {
        official_url: "https://open.feishu.cn/app",
        fields: [
          field("appId", "string", { required: true }),
          field("appSecret", "secret", { required: true }),
          field("domain", "enum", {
            choices: ["feishu", "lark"],
            defaultValue: "feishu",
          }),
          field("groupPolicy", "enum", {
            choices: ["mention", "open"],
            defaultValue: "mention",
          }),
          field("allowFrom", "list"),
          field("topicIsolation", "bool"),
        ],
        requirements: [
          { alternatives: [["channels.feishu.appId"]] },
          { alternatives: [["channels.feishu.appSecret"]] },
        ],
      };
    case "matrix":
      return {
        official_url: "https://matrix.org/ecosystem/clients/",
        fields: [
          field("homeserver", "string", { required: true }),
          field("userId", "string", { required: true }),
          field("password", "secret"),
          field("accessToken", "secret"),
          field("deviceId"),
          field("groupPolicy", "enum", {
            choices: ["allowlist", "mention", "open"],
            defaultValue: "open",
          }),
        ],
        requirements: [
          { alternatives: [["channels.matrix.homeserver"]] },
          { alternatives: [["channels.matrix.userId"]] },
          {
            alternatives: [
              ["channels.matrix.password"],
              ["channels.matrix.accessToken", "channels.matrix.deviceId"],
            ],
          },
        ],
      };
    case "qq":
      return {
        official_url: "https://q.qq.com/",
        fields: [
          field("appId", "string", { required: true }),
          field("secret", "secret", { required: true }),
          field("allowFrom", "list"),
          field("msgFormat", "enum", {
            choices: ["markdown", "plain"],
            defaultValue: "plain",
          }),
        ],
        requirements: [
          { alternatives: [["channels.qq.appId"]] },
          { alternatives: [["channels.qq.secret"]] },
        ],
      };
  }
}

function uninstalledConnectFeature(
  name: "feishu" | "weixin" | "whatsapp",
): NanobotFeatureInfo {
  const displayNames = {
    feishu: "Feishu",
    weixin: "WeChat",
    whatsapp: "WhatsApp",
  };
  return {
    name,
    display_name: displayNames[name],
    webui: "webui/index.tsx",
    type: "channel",
    enabled: false,
    configured: false,
    installed: false,
    ready: false,
    runtime_status: "stopped",
    status: "not_enabled",
    install_supported: true,
    requires_restart: true,
    ...(name === "feishu"
      ? {
          instances: [{
            id: "default",
            name: "nanobot",
            enabled: false,
            runtime_status: "stopped",
            configured: false,
            config_values: {},
            configured_fields: [],
          }],
        }
      : {}),
  };
}

describe("Settings channels", () => {
  installSettingsViewTestHooks();

  it("installs WhatsApp support before exposing the connect flow", async () => {
    const whatsappFeature = {
      name: "whatsapp",
      display_name: "WhatsApp",
      webui: "webui/index.tsx",
      type: "channel",
      enabled: false,
      configured: false,
      installed: false,
      ready: false,
      status: "not_enabled",
      install_supported: true,
      requires_restart: false,
    } as const;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/settings") return jsonResponse(settingsPayload());
        if (url === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
        if (url === "/api/settings/mcp-presets") return jsonResponse({ presets: [], installed_count: 0 });
        if (url === "/api/settings/nanobot-features") {
          return jsonResponse({ features: [whatsappFeature], enabled_count: 0 });
        }
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }),
    );
    requestMutationMock.mockResolvedValueOnce({
      features: [{ ...whatsappFeature, installed: true }],
      enabled_count: 0,
      requires_restart: false,
      last_action: {
        ok: true,
        message: "Installed support for channel 'whatsapp'",
        enabled: false,
      },
    });

    renderSettingsView({ initialSection: "channels" });

    expect(await screen.findByRole("button", { name: "View WhatsApp settings" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Connect WhatsApp" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Install support" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(
      "nanobot will install what WhatsApp needs. You can connect it after installation.",
    )).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Install support" }));

    await waitFor(() =>
      expect(requestMutationMock).toHaveBeenCalledWith(
        "settings.feature.enable",
        { name: "whatsapp", install_only: true },
        150_000,
      ),
    );
    expect(await screen.findByRole("button", { name: "Connect WhatsApp" })).toBeInTheDocument();
    expect(requestMutationMock.mock.calls.some(([action]) => (
      action.startsWith("settings.channel.connect")
    ))).toBe(false);
  });

  it.each([
    ["feishu", "Feishu", "Create assistant"],
    ["weixin", "WeChat", "Connect WeChat"],
  ] as const)(
    "installs %s support before mounting its custom connect panel",
    async (name, displayName, connectActionLabel) => {
      const feature = uninstalledConnectFeature(name);
      vi.stubGlobal(
        "fetch",
        vi.fn(async (input: RequestInfo | URL) => {
          const url = String(input);
          if (url === "/api/settings") return jsonResponse(settingsPayload());
          if (url === "/api/settings/cli-apps") {
            return jsonResponse({ apps: [], installed_count: 0 });
          }
          if (url === "/api/settings/mcp-presets") {
            return jsonResponse({ presets: [], installed_count: 0 });
          }
          if (url === "/api/settings/nanobot-features") {
            return jsonResponse({ features: [feature], enabled_count: 0 });
          }
          return { ok: false, status: 404, json: async () => ({}) } as Response;
        }),
      );
      requestMutationMock.mockResolvedValueOnce({
        features: [{ ...feature, installed: true }],
        enabled_count: 0,
        requires_restart: false,
        last_action: {
          ok: true,
          message: `Installed support for channel '${name}'`,
          enabled: false,
        },
      });

      renderSettingsView({ initialSection: "channels" });

      expect(
        await screen.findByRole("button", { name: `View ${displayName} settings` }),
      ).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Install support" })).toBeEnabled();
      expect(screen.queryByRole("button", { name: connectActionLabel })).not.toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: "Install support" }));
      const dialog = screen.getByRole("dialog");
      fireEvent.click(within(dialog).getByRole("button", { name: "Install support" }));

      await waitFor(() =>
        expect(requestMutationMock).toHaveBeenCalledWith(
          "settings.feature.enable",
          { name, install_only: true },
          150_000,
        ),
      );
      expect(
        await screen.findByRole("button", { name: connectActionLabel }, { timeout: 3_000 }),
      ).toBeInTheDocument();
      expect(requestMutationMock.mock.calls.some(([action]) => (
        action.startsWith("settings.channel.connect")
      ))).toBe(false);
    },
  );

  it("announces an install-only failure and logs action context", async () => {
    const feature = uninstalledConnectFeature("whatsapp");
    const installError = new Error("Package install failed");
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      vi.stubGlobal(
        "fetch",
        vi.fn(async (input: RequestInfo | URL) => {
          const url = String(input);
          if (url === "/api/settings") return jsonResponse(settingsPayload());
          if (url === "/api/settings/cli-apps") {
            return jsonResponse({ apps: [], installed_count: 0 });
          }
          if (url === "/api/settings/mcp-presets") {
            return jsonResponse({ presets: [], installed_count: 0 });
          }
          if (url === "/api/settings/nanobot-features") {
            return jsonResponse({ features: [feature], enabled_count: 0 });
          }
          return { ok: false, status: 404, json: async () => ({}) } as Response;
        }),
      );
      requestMutationMock.mockRejectedValueOnce(installError);

      renderSettingsView({ initialSection: "channels" });

      expect(
        await screen.findByRole("button", { name: "View WhatsApp settings" }),
      ).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Install support" }));
      fireEvent.click(
        within(screen.getByRole("dialog")).getByRole("button", { name: "Install support" }),
      );

      expect(await screen.findByRole("alert")).toHaveTextContent("Package install failed");
      expect(consoleError).toHaveBeenCalledWith(
        "nanobot feature action failed",
        expect.objectContaining({
          action: "enable",
          name: "whatsapp",
          installOnly: true,
          error: installError,
        }),
      );
    } finally {
      consoleError.mockRestore();
    }
  });

  it("shows an enabled channel with missing support as failed", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(settingsPayload());
      if (url === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
      if (url === "/api/settings/mcp-presets") return jsonResponse({ presets: [], installed_count: 0 });
      if (url === "/api/settings/nanobot-features") {
        return jsonResponse({
          features: [{
            name: "matrix",
            display_name: "Matrix",
            type: "channel",
            enabled: true,
            running: false,
            runtime_status: "failed",
            runtime_error: "Channel dependencies could not be installed. Check gateway logs.",
            installed: false,
            ready: false,
            status: "missing_dependency",
            install_supported: true,
            requires_restart: true,
          }],
          enabled_count: 1,
        });
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    requestMutationMock.mockResolvedValueOnce({
      features: [{
        name: "matrix",
        display_name: "Matrix",
        type: "channel",
        enabled: true,
        installed: true,
        ready: true,
        status: "enabled",
        install_supported: true,
        requires_restart: true,
      }],
      enabled_count: 1,
      last_action: { ok: true, message: "Enabled channel 'matrix'", enabled: true },
    });

    renderSettingsView({ initialSection: "channels" });

    expect(await screen.findByRole("button", { name: "View Matrix settings" })).toBeInTheDocument();
    expect(screen.queryByText("0 running · 1 channels")).not.toBeInTheDocument();
    expect(screen.getAllByText("Failed").length).toBeGreaterThan(0);
    expect(screen.queryByText("Enabled, support needs install")).not.toBeInTheDocument();

    expect(screen.getByRole("switch", { name: "Matrix channel" })).toHaveAttribute("aria-checked", "false");
    fireEvent.click(screen.getByRole("button", { name: "Install support" }));
    fireEvent.click(screen.getByRole("button", { name: "Install and enable" }));

    await waitFor(() =>
      expect(requestMutationMock).toHaveBeenCalledWith(
        "settings.feature.enable",
        { name: "matrix" },
        150_000,
      ),
    );
  });

  it("shows a configured channel as failed when its runtime did not start", async () => {
    const runtimeError = "Channel failed to start. Check gateway logs.";
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/settings") return jsonResponse(settingsPayload());
        if (url === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
        if (url === "/api/settings/mcp-presets") return jsonResponse({ presets: [], installed_count: 0 });
        if (url === "/api/settings/nanobot-features") {
          return jsonResponse({
            features: [{
              name: "matrix",
              display_name: "Matrix",
              type: "channel",
              enabled: true,
              configured: true,
              installed: true,
              ready: false,
              running: false,
              runtime_status: "failed",
              runtime_error: runtimeError,
              status: "failed",
              install_supported: true,
              requires_restart: false,
            }],
            enabled_count: 0,
          });
        }
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }),
    );

    renderSettingsView({ initialSection: "channels" });

    expect(await screen.findByRole("button", { name: "View Matrix settings" })).toBeInTheDocument();
    expect(screen.queryByText("0 running · 1 channels")).not.toBeInTheDocument();
    expect(screen.getAllByText("Failed").length).toBeGreaterThan(0);
    expect(screen.getByText(runtimeError)).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Matrix channel" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });

  it("starts Feishu connect in WebUI instead of showing a CLI command", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(settingsPayload());
      if (url === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
      if (url === "/api/settings/mcp-presets") return jsonResponse({ presets: [], installed_count: 0 });
      if (url === "/api/settings/nanobot-features") {
        return jsonResponse({
          features: [{
            name: "feishu",
            display_name: "Feishu",
            webui: "webui/index.tsx",
            type: "channel",
            enabled: false,
            configured: false,
            installed: true,
            ready: false,
            status: "not_enabled",
            install_supported: true,
            requires_restart: true,
          }],
          enabled_count: 0,
        });
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    requestMutationMock.mockResolvedValueOnce({
      session_id: "feishu-session",
      status: "pending",
      qr_url: "https://accounts.feishu.cn/login?device_code=device",
      domain: "feishu",
      interval_ms: 5000,
      expires_at_ms: Date.now() + 600_000,
      message: "Scan with Feishu or Lark to connect.",
    });

    renderSettingsView({ initialSection: "channels" });

    expect(await screen.findByRole("button", { name: "View Feishu settings" })).toBeInTheDocument();
    expect(screen.queryByText("nanobot channels login feishu")).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole(
      "button",
      { name: "nanobot" },
      { timeout: 3_000 },
    ));
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    await waitFor(() =>
      expect(requestMutationMock).toHaveBeenCalledWith(
        "settings.channel.connect.start",
        { channel: "feishu", domain: "feishu", instance_id: "default", mode: "replace" },
        150_000,
      ),
    );
    expect(await screen.findByText("Scan with Feishu")).toBeInTheDocument();
    expect(screen.getByText("Waiting for authorization...")).toBeInTheDocument();
  });

  it("starts Feishu connect from the default assistant action", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(settingsPayload());
      if (url === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
      if (url === "/api/settings/mcp-presets") return jsonResponse({ presets: [], installed_count: 0 });
      if (url === "/api/settings/nanobot-features") {
        return jsonResponse({
          features: [{
            name: "feishu",
            display_name: "Feishu",
            webui: "webui/index.tsx",
            type: "channel",
            enabled: false,
            configured: false,
            installed: true,
            ready: false,
            status: "not_enabled",
            install_supported: true,
            requires_restart: true,
          }],
          enabled_count: 0,
        });
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    requestMutationMock.mockResolvedValueOnce({
      session_id: "feishu-switch-session",
      status: "pending",
      qr_url: "https://accounts.feishu.cn/login?device_code=switch-device",
      domain: "feishu",
      interval_ms: 5000,
      expires_at_ms: Date.now() + 600_000,
      message: "Scan with Feishu or Lark to connect.",
    });

    renderSettingsView({ initialSection: "channels" });

    expect(await screen.findByRole("button", { name: "View Feishu settings" })).toBeInTheDocument();
    fireEvent.click(await screen.findByRole(
      "button",
      { name: "nanobot" },
      { timeout: 3_000 },
    ));
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    await waitFor(() =>
      expect(requestMutationMock).toHaveBeenCalledWith(
        "settings.channel.connect.start",
        { channel: "feishu", domain: "feishu", instance_id: "default", mode: "replace" },
        150_000,
      ),
    );
    expect(await screen.findByText("Scan with Feishu")).toBeInTheDocument();
  });

  it("enables configured Feishu assistant without starting a new connect flow", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(settingsPayload());
      if (url === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
      if (url === "/api/settings/mcp-presets") return jsonResponse({ presets: [], installed_count: 0 });
      if (url === "/api/settings/nanobot-features") {
        return jsonResponse({
          features: [{
            name: "feishu",
            display_name: "Feishu",
            webui: "webui/index.tsx",
            type: "channel",
            enabled: false,
            configured: true,
            installed: true,
            ready: false,
            status: "not_enabled",
            install_supported: true,
            requires_restart: true,
          }],
          enabled_count: 0,
        });
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    requestMutationMock.mockImplementation(async (action: string) => {
      if (action === "settings.feature.enable") {
        return {
          features: [{
            name: "feishu",
            display_name: "Feishu",
            webui: "webui/index.tsx",
            type: "channel",
            enabled: true,
            running: true,
            runtime_status: "running",
            configured: true,
            instances: [{
              id: "default",
              name: "nanobot",
              enabled: true,
              running: true,
              runtime_status: "running",
              configured: true,
              config_values: { "channels.feishu.appId": "cli_test" },
              configured_fields: [
                "channels.feishu.appId",
                "channels.feishu.appSecret",
              ],
            }],
            installed: true,
            ready: true,
            status: "enabled",
            install_supported: true,
            requires_restart: true,
          }],
          enabled_count: 1,
          requires_restart: false,
          last_action: { ok: true, message: "Enabled channel 'feishu'", enabled: true },
        };
      }
      if (action === "settings.channel.connect.start") {
        throw new Error("Feishu connect should not start when credentials are already configured");
      }
      return settingsPayload();
    });

    renderSettingsView({ initialSection: "channels" });

    fireEvent.click(await screen.findByRole("button", { name: "nanobot" }));
    fireEvent.click(await screen.findByRole("switch", { name: "nanobot assistant" }));

    await waitFor(() =>
      expect(requestMutationMock).toHaveBeenCalledWith(
        "settings.feature.enable",
        { name: "feishu", instance_id: "default" },
        150_000,
      ),
    );
    expect(requestMutationMock.mock.calls.some(([action]) => (
      action === "settings.channel.connect.start"
    ))).toBe(false);
    expect(screen.getByRole("switch", { name: "nanobot assistant" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("shows Feishu assistant instances in the channel details", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/settings") return jsonResponse(settingsPayload());
        if (url === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
        if (url === "/api/settings/mcp-presets") return jsonResponse({ presets: [], installed_count: 0 });
        if (url === "/api/settings/nanobot-features") {
          return jsonResponse({
            features: [{
              name: "feishu",
              display_name: "Feishu",
              webui: "webui/index.tsx",
              type: "channel",
              enabled: true,
              configured: true,
              installed: true,
              ready: true,
              status: "enabled",
              install_supported: true,
              requires_restart: true,
              setup: channelSetupContract("feishu"),
              instances: [
                {
                  id: "default",
                  name: "nanobot",
                  display_name: "Support Bot",
                  avatar_url: "https://example.com/support.png",
                  enabled: true,
                  configured: true,
                  config_values: {
                    "channels.feishu.appId": "cli_default",
                    "channels.feishu.domain": "feishu",
                    "channels.feishu.groupPolicy": "mention",
                    "channels.feishu.allowFrom": "",
                    "channels.feishu.topicIsolation": "true",
                  },
                  configured_fields: [
                    "channels.feishu.appId",
                    "channels.feishu.appSecret",
                    "channels.feishu.domain",
                    "channels.feishu.groupPolicy",
                    "channels.feishu.topicIsolation",
                  ],
                },
                {
                  id: "product",
                  name: "Product bot",
                  display_name: "Product Helper",
                  avatar_url: "https://example.com/product.png",
                  enabled: false,
                  configured: true,
                  config_values: { "channels.feishu.appId": "cli_product" },
                  configured_fields: [
                    "channels.feishu.appId",
                    "channels.feishu.appSecret",
                  ],
                },
              ],
            }],
            enabled_count: 1,
          });
        }
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }),
    );

    renderSettingsView({ initialSection: "channels" });

    expect(await screen.findByText("Product Helper")).toBeInTheDocument();
    expect(screen.getAllByText("Support Bot")).toHaveLength(1);
    expect(document.querySelector('img[src="https://example.com/support.png"]')).toBeTruthy();

    expect(screen.getByRole("button", { name: /Support Bot/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.getByRole("button", { name: /Product Helper/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );

    expect(screen.queryByText("cli_def...ault")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Support Bot/ }));
    expect(screen.getByRole("button", { name: /Support Bot/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getAllByText("cli_def...ault").length).toBeGreaterThan(0);
    expect(screen.getByText("Advanced")).toBeInTheDocument();
    expect(screen.getByText("Topic isolation")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Product Helper/ }));
    expect(screen.getByRole("button", { name: /Support Bot/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.getByRole("button", { name: /Product Helper/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("renders external multi-instance channels from the shared contract", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(settingsPayload());
      if (url === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
      if (url === "/api/settings/mcp-presets") return jsonResponse({ presets: [], installed_count: 0 });
      if (url === "/api/settings/nanobot-features") {
        return jsonResponse({
          features: [{
            name: "multiplugin",
            display_name: "Multi Plugin",
            type: "channel",
            enabled: true,
            running: true,
            runtime_status: "running",
            configured: true,
            installed: true,
            ready: true,
            status: "enabled",
            install_supported: true,
            requires_restart: false,
            setup: {
              fields: [
                channelSetupField("multiplugin", "token", "secret", { required: true }),
                channelSetupField("multiplugin", "region", "enum", {
                  choices: ["eu", "us"],
                  defaultValue: "us",
                }),
              ],
            },
            instances: [
              {
                id: "default",
                name: "Default worker",
                enabled: true,
                running: true,
                runtime_status: "running",
                configured: true,
                config_values: { "channels.multiplugin.region": "us" },
                configured_fields: ["channels.multiplugin.token"],
              },
              {
                id: "product",
                name: "Product worker",
                enabled: true,
                running: true,
                runtime_status: "running",
                configured: true,
                config_values: { "channels.multiplugin.region": "eu" },
                configured_fields: ["channels.multiplugin.token"],
              },
            ],
          }],
          enabled_count: 1,
        });
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSettingsView({ initialSection: "channels" });

    expect(await screen.findByText("Default worker")).toBeInTheDocument();
    expect(screen.queryByRole("switch", { name: "Multi Plugin channel" })).not.toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Default worker instance" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByRole("switch", { name: "Product worker instance" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    fireEvent.click(screen.getByRole("button", { name: "Product worker" }));
    expect(screen.getByRole("radio", { name: "Eu" })).toBeChecked();
    expect(screen.getByText("Saved")).toBeInTheDocument();
  });

  it("shows a single Feishu assistant without a duplicate assistant list", async () => {
    const feishuPayload = {
      features: [{
        name: "feishu",
        display_name: "Feishu",
        webui: "webui/index.tsx",
        type: "channel",
        enabled: true,
        configured: true,
        installed: true,
        ready: true,
        status: "enabled",
        running: true,
        runtime_status: "running",
        install_supported: true,
        requires_restart: true,
        instances: [{
          id: "default",
          name: "nanobot",
          display_name: "Support Bot",
          avatar_url: "https://example.com/support.png",
          enabled: true,
          running: true,
          runtime_status: "running",
          configured: true,
          config_values: { "channels.feishu.appId": "cli_support" },
          configured_fields: [
            "channels.feishu.appId",
            "channels.feishu.appSecret",
          ],
        }],
      }],
      enabled_count: 1,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/settings") return jsonResponse(settingsPayload());
        if (url === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
        if (url === "/api/settings/mcp-presets") return jsonResponse({ presets: [], installed_count: 0 });
        if (url === "/api/settings/nanobot-features") return jsonResponse(feishuPayload);
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }),
    );
    requestMutationMock.mockResolvedValueOnce(feishuPayload);

    renderSettingsView({ initialSection: "channels" });

    await screen.findByText("Support Bot");
    expect(screen.getAllByText("Support Bot")).toHaveLength(1);
    expect(screen.getByText("1 assistant connected")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Support Bot assistant" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.queryByText("cli_sup...port")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Support Bot" }));
    expect(screen.getByText("cli_sup...port")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Replace assistant" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reconnect" }));
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.feature.enable",
      { name: "feishu", instance_id: "default" },
      150_000,
    ));
    expect(document.querySelector('img[src="https://example.com/support.png"]')).toBeTruthy();
  });

  it("does not call a configured Feishu assistant connected after runtime failure", async () => {
    const runtimeError = "Channel failed to start. Check gateway logs.";
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/settings") return jsonResponse(settingsPayload());
        if (url === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
        if (url === "/api/settings/mcp-presets") return jsonResponse({ presets: [], installed_count: 0 });
        if (url === "/api/settings/nanobot-features") {
          return jsonResponse({
            features: [{
              name: "feishu",
              display_name: "Feishu",
              webui: "webui/index.tsx",
              type: "channel",
              enabled: true,
              configured: true,
              installed: true,
              ready: false,
              running: false,
              runtime_status: "failed",
              runtime_error: runtimeError,
              status: "failed",
              install_supported: true,
              requires_restart: false,
              instances: [{
                id: "default",
                name: "test",
                enabled: true,
                configured: true,
                running: false,
                runtime_status: "failed",
                runtime_error: runtimeError,
                config_values: { "channels.feishu.appId": "cli_test" },
                configured_fields: [
                  "channels.feishu.appId",
                  "channels.feishu.appSecret",
                ],
              }],
            }],
            enabled_count: 0,
          });
        }
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }),
    );

    renderSettingsView({ initialSection: "channels" });

    await screen.findByText("No assistant connected");
    expect(screen.queryByText("0 running · 1 channels")).not.toBeInTheDocument();
    expect(screen.getAllByText("Failed").length).toBeGreaterThan(0);
    expect(screen.getByText(runtimeError)).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "test assistant" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
    expect(screen.queryByText("Connected")).not.toBeInTheDocument();
  });

  it("shows group behavior fields as options", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/settings") return jsonResponse(settingsPayload());
        if (url === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
        if (url === "/api/settings/mcp-presets") return jsonResponse({ presets: [], installed_count: 0 });
        if (url === "/api/settings/nanobot-features") {
          return jsonResponse({
            features: [{
              name: "discord",
              display_name: "Discord",
              webui: "webui/index.ts",
              type: "channel",
              enabled: true,
              installed: true,
              ready: true,
              status: "enabled",
              install_supported: true,
              requires_restart: true,
              setup: channelSetupContract("discord"),
            }],
            enabled_count: 1,
          });
        }
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }),
    );

    renderSettingsView({ initialSection: "channels" });

    expect(await screen.findByRole("button", { name: "View Discord settings" })).toBeInTheDocument();

    const behavior = screen.getByRole("group", { name: "Group behavior" });
    expect(within(behavior).getByRole("radio", { name: "Mention only" })).toBeChecked();
    expect(within(behavior).getByRole("radio", { name: "All messages" })).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("mention")).not.toBeInTheDocument();

    fireEvent.click(within(behavior).getByRole("radio", { name: "All messages" }));

    expect(within(behavior).getByRole("radio", { name: "All messages" })).toBeChecked();
  });

  it("uses a list-to-detail navigation stack on compact screens", async () => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn((query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    );
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/settings") return jsonResponse(settingsPayload());
        if (url === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
        if (url === "/api/settings/mcp-presets") return jsonResponse({ presets: [], installed_count: 0 });
        if (url === "/api/settings/nanobot-features") {
          return jsonResponse({
            features: [{
              name: "email",
              display_name: "Email",
              type: "channel",
              enabled: false,
              installed: true,
              ready: false,
              status: "not_enabled",
              install_supported: true,
              requires_restart: true,
            }],
            enabled_count: 0,
          });
        }
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }),
    );

    renderSettingsView({ initialSection: "channels" });

    const emailRow = await screen.findByRole("button", { name: "View Email settings" });
    expect(screen.getByPlaceholderText("Search channels")).toHaveClass(
      "focus-visible:ring-2",
      "focus-visible:ring-inset",
      "focus-visible:ring-ring/50",
    );
    expect(screen.queryByRole("switch", { name: "Email channel" })).not.toBeInTheDocument();

    fireEvent.click(emailRow);

    expect(screen.getByRole("button", { name: "All channels" })).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Email channel" })).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Search channels")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "All channels" }));

    expect(screen.getByPlaceholderText("Search channels")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "View Email settings" })).toBeInTheDocument();
  });

  it("saves Discord credentials from the channel setup panel", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(settingsPayload());
      if (url === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
      if (url === "/api/settings/mcp-presets") return jsonResponse({ presets: [], installed_count: 0 });
      if (url === "/api/settings/nanobot-features") {
        return jsonResponse({
          features: [{
            name: "discord",
            display_name: "Discord",
            webui: "webui/index.ts",
            type: "channel",
            enabled: false,
            configured: false,
            installed: true,
            ready: false,
            status: "not_enabled",
            install_supported: true,
            requires_restart: true,
            setup: channelSetupContract("discord"),
          }],
          enabled_count: 0,
        });
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    requestMutationMock
      .mockResolvedValueOnce({
        name: "discord",
        status: "ready",
        checks: [],
        missing_fields: [],
        can_enable: true,
        requires_restart: false,
      })
      .mockResolvedValueOnce({
          name: "discord",
          saved: true,
          saved_keys: [
            "channels.discord.token",
            "channels.discord.allowChannels",
            "channels.discord.groupPolicy",
          ],
          nanobot_features: {
            features: [{
              name: "discord",
              display_name: "Discord",
              webui: "webui/index.ts",
              type: "channel",
              enabled: true,
              running: true,
              runtime_status: "running",
              configured: true,
              installed: true,
              ready: true,
              status: "enabled",
              install_supported: true,
              requires_restart: true,
              setup: channelSetupContract("discord"),
            }],
            enabled_count: 1,
            requires_restart: false,
          },
      });

    renderSettingsView({ initialSection: "channels" });

    expect(await screen.findByRole("button", { name: "View Discord settings" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Discord setup" })).toHaveAttribute(
      "href",
      "https://nanobot.wiki/docs/0.2.2/getting-started/chat-apps#discord",
    );
    expect(screen.getByRole("switch", { name: "Discord channel" })).toBeEnabled();
    fireEvent.change(screen.getByPlaceholderText("Discord bot token"), {
      target: { value: "discord-token" },
    });
    fireEvent.change(screen.getByLabelText("Allowed channels"), {
      target: { value: "123, 456" },
    });
    fireEvent.click(within(screen.getByRole("group", { name: "Group behavior" })).getByRole(
      "radio",
      { name: "All messages" },
    ));
    fireEvent.click(screen.getByRole("button", { name: "Check and enable" }));

    await waitFor(() =>
      expect(
        requestMutationMock.mock.calls.some(([action]) => (
          action === "settings.channel.configure"
        )),
      ).toBe(true),
    );
    expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.channel.configure",
      {
        name: "discord",
        enable: true,
        values: {
          "channels.discord.token": "discord-token",
          "channels.discord.allowChannels": "123, 456",
          "channels.discord.groupPolicy": "open",
        },
      },
      150_000,
    );
    expect(await screen.findByText("Checked and enabled.")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Discord channel" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("requires Email consent to be granted before validating or enabling", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/settings") return jsonResponse(settingsPayload());
        if (url === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
        if (url === "/api/settings/mcp-presets") return jsonResponse({ presets: [], installed_count: 0 });
        if (url === "/api/settings/nanobot-features") {
          return jsonResponse({
            features: [{
              name: "email",
              display_name: "Email",
              webui: "webui/index.ts",
              type: "channel",
              enabled: false,
              configured: false,
              installed: true,
              ready: false,
              status: "not_enabled",
              install_supported: true,
              requires_restart: false,
              setup: channelSetupContract("email"),
            }],
            enabled_count: 0,
          });
        }
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }),
    );
    requestMutationMock.mockImplementation(async (action: string) => {
      if (action === "settings.channel.validate") {
        return {
          name: "email",
          status: "ready",
          checks: [],
          missing_fields: [],
          can_enable: true,
          requires_restart: false,
        };
      }
      if (action === "settings.channel.configure") {
        return {
          name: "email",
          saved: true,
          saved_keys: [
            "channels.email.consentGranted",
            "channels.email.imapHost",
            "channels.email.imapUsername",
            "channels.email.imapPassword",
            "channels.email.smtpHost",
            "channels.email.smtpUsername",
            "channels.email.smtpPassword",
          ],
        };
      }
      return settingsPayload();
    });

    renderSettingsView({ initialSection: "channels" });

    expect(await screen.findByRole("button", { name: "View Email settings" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("IMAP host"), { target: { value: "imap.example.com" } });
    fireEvent.change(screen.getByLabelText("IMAP username"), { target: { value: "bot@example.com" } });
    fireEvent.change(screen.getByLabelText("IMAP password"), { target: { value: "imap-secret" } });
    fireEvent.change(screen.getByLabelText("SMTP host"), { target: { value: "smtp.example.com" } });
    fireEvent.change(screen.getByLabelText("SMTP username"), { target: { value: "bot@example.com" } });
    fireEvent.change(screen.getByLabelText("SMTP password"), { target: { value: "smtp-secret" } });

    const consentGroup = screen.getByRole("group", { name: "Consent granted" });
    const notGranted = within(consentGroup).getByRole("radio", { name: "Not granted" });
    const granted = within(consentGroup).getByRole("radio", { name: "Granted" });
    expect(notGranted).toBeChecked();

    fireEvent.click(screen.getByRole("button", { name: "Check and enable" }));

    await waitFor(() => expect(granted).toHaveFocus());
    expect(consentGroup).toHaveAttribute("aria-invalid", "true");
    expect(notGranted).toHaveAttribute("aria-invalid", "true");
    expect(granted).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("Required to complete setup.")).toBeInTheDocument();
    expect(requestMutationMock.mock.calls.some(([action]) => (
      action === "settings.channel.validate" || action === "settings.channel.configure"
    ))).toBe(false);

    fireEvent.click(granted);

    expect(consentGroup).toHaveAttribute("aria-invalid", "false");
    expect(notGranted).toHaveAttribute("aria-invalid", "false");
    expect(granted).toHaveAttribute("aria-invalid", "false");
    expect(screen.queryByText("Required to complete setup.")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Check and enable" }));

    await waitFor(() =>
      expect(requestMutationMock).toHaveBeenCalledWith(
        "settings.channel.validate",
        expect.objectContaining({
          name: "email",
          values: expect.objectContaining({
            "channels.email.consentGranted": "true",
          }),
        }),
        20_000,
      ),
    );
    await waitFor(() =>
      expect(requestMutationMock).toHaveBeenCalledWith(
        "settings.channel.configure",
        expect.objectContaining({ name: "email", enable: true }),
        150_000,
      ),
    );
  });

  it("prefills saved channel config without exposing secrets", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(settingsPayload());
      if (url === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
      if (url === "/api/settings/mcp-presets") return jsonResponse({ presets: [], installed_count: 0 });
      if (url === "/api/settings/nanobot-features") {
        return jsonResponse({
          features: [{
            name: "discord",
            display_name: "Discord",
            webui: "webui/index.ts",
            type: "channel",
            enabled: false,
            configured: true,
            installed: true,
            ready: false,
            status: "not_enabled",
            install_supported: true,
            requires_restart: true,
            config_values: {
              "channels.discord.allowChannels": "123, 456",
              "channels.discord.groupPolicy": "open",
            },
            configured_fields: [
              "channels.discord.token",
              "channels.discord.allowChannels",
              "channels.discord.groupPolicy",
            ],
            setup: channelSetupContract("discord"),
          }],
          enabled_count: 0,
        });
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    requestMutationMock.mockResolvedValueOnce({
      features: [{
        name: "discord",
        display_name: "Discord",
        webui: "webui/index.ts",
        type: "channel",
        enabled: true,
        configured: true,
        installed: true,
        ready: true,
        status: "enabled",
        install_supported: true,
        requires_restart: true,
        setup: channelSetupContract("discord"),
      }],
      enabled_count: 1,
      requires_restart: false,
    });

    renderSettingsView({ initialSection: "channels" });

    expect(await screen.findByRole("button", { name: "View Discord settings" })).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Discord channel" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
    expect(screen.getByRole("switch", { name: "Discord channel" })).toBeEnabled();
    expect(screen.getByText("Configured manually")).toBeInTheDocument();
    expect(screen.getByText("Saved")).toBeInTheDocument();
    const savedSecret = screen.getByPlaceholderText("Saved secret");
    expect(savedSecret).toHaveValue("");
    expect(savedSecret).toHaveAttribute("autocomplete", "off");
    expect(savedSecret.closest("form")).not.toBeNull();
    expect(screen.queryByDisplayValue("discord-secret-token")).not.toBeInTheDocument();

    expect(screen.getByLabelText("Allowed channels")).toHaveValue("123, 456");
    expect(within(screen.getByRole("group", { name: "Group behavior" })).getByRole(
      "radio",
      { name: "All messages" },
    )).toBeChecked();

    fireEvent.click(screen.getByRole("switch", { name: "Discord channel" }));
    await waitFor(() =>
      expect(requestMutationMock).toHaveBeenCalledWith(
        "settings.feature.enable",
        { name: "discord" },
        150_000,
      ),
    );
  });

  it("shows an actionable credential guide for Telegram", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/settings") return jsonResponse(settingsPayload());
        if (url === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
        if (url === "/api/settings/mcp-presets") return jsonResponse({ presets: [], installed_count: 0 });
        if (url === "/api/settings/nanobot-features") {
          return jsonResponse({
            features: [{
              name: "telegram",
              display_name: "Telegram",
              webui: "webui/index.ts",
              type: "channel",
              enabled: false,
              installed: true,
              ready: false,
              status: "not_enabled",
              install_supported: true,
              requires_restart: true,
            }],
            enabled_count: 0,
          });
        }
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }),
    );

    renderSettingsView({ initialSection: "channels" });

    expect(await screen.findByRole("button", { name: "View Telegram settings" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Telegram setup" })).toHaveAttribute(
      "href",
      "https://nanobot.wiki/docs/0.2.2/getting-started/chat-apps#telegram",
    );
  });

  it("shows setup guide links with local channel identity", async () => {
    const channels = [
      ["websocket", "WebSocket", "Open WebSocket setup"],
      ["telegram", "Telegram", "Open Telegram setup"],
      ["feishu", "Feishu", "Open Feishu setup"],
      ["slack", "Slack", "Open Slack setup"],
      ["discord", "Discord", "Open Discord setup"],
      ["email", "Email", "Open Email setup"],
      ["matrix", "Matrix", "Open Matrix setup"],
      ["whatsapp", "WhatsApp", "Open WhatsApp setup"],
      ["dingtalk", "DingTalk", "Open DingTalk setup"],
      ["wecom", "WeCom", "Open WeCom setup"],
      ["weixin", "WeChat", "Open WeChat setup"],
      ["qq", "QQ", "Open QQ setup"],
      ["signal", "Signal", "Open Signal setup"],
      ["msteams", "Microsoft Teams", "Open Teams setup"],
      ["napcat", "NapCat", "Open NapCat setup"],
    ] as const;
    const hiddenChannels = [["mochat", "MoChat"]] as const;

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/settings") return jsonResponse(settingsPayload());
        if (url === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
        if (url === "/api/settings/mcp-presets") return jsonResponse({ presets: [], installed_count: 0 });
        if (url === "/api/settings/nanobot-features") {
          return jsonResponse({
            features: channels.map(([name, displayName]) => ({
              name,
              display_name: displayName,
              webui: ["feishu", "weixin", "whatsapp"].includes(name) ? "webui/index.tsx" : "webui/index.ts",
              type: "channel",
              enabled: name === "websocket",
              installed: true,
              ready: name === "websocket",
              status: name === "websocket" ? "enabled" : "not_enabled",
              install_supported: true,
              requires_restart: true,
            })).concat(hiddenChannels.map(([name, displayName]) => ({
              name,
              display_name: displayName,
              settings_visible: false,
              type: "channel",
              enabled: false,
              installed: true,
              ready: false,
              status: "not_enabled",
              install_supported: true,
              requires_restart: true,
            }))),
            enabled_count: 1,
          });
        }
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }),
    );

    renderSettingsView({ initialSection: "channels" });

    for (const [, displayName, guideLabel] of channels) {
      fireEvent.click(await screen.findByRole("button", { name: `View ${displayName} settings` }));
      if (displayName === "Feishu") {
        fireEvent.click(await screen.findByRole(
          "button",
          { name: "nanobot" },
          { timeout: 3_000 },
        ));
      }
      const guide = await screen.findByRole("link", { name: guideLabel });
      expect(guide).toHaveAttribute("href", expect.stringMatching(/^https:\/\//));
      expect(guide.querySelector("span[aria-hidden]")).not.toBeNull();
      expect(guide.querySelector('img[src^="http"]')).toBeNull();
    }
    expect(screen.queryByRole("button", { name: "View MoChat settings" })).not.toBeInTheDocument();
  });

  it("uses choices for channel enum and boolean fields", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/settings") return jsonResponse(settingsPayload());
        if (url === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
        if (url === "/api/settings/mcp-presets") return jsonResponse({ presets: [], installed_count: 0 });
        if (url === "/api/settings/nanobot-features") {
          return jsonResponse({
            features: ["email", "feishu", "matrix", "qq"].map((name) => ({
              name,
              display_name: name === "qq" ? "QQ" : name[0].toUpperCase() + name.slice(1),
              webui: name === "feishu" ? "webui/index.tsx" : "webui/index.ts",
              type: "channel",
              enabled: true,
              installed: true,
              ready: true,
              status: "enabled",
              install_supported: true,
              requires_restart: true,
              setup: channelSetupContract(name as "email" | "feishu" | "matrix" | "qq"),
            })),
            enabled_count: 4,
          });
        }
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }),
    );

    renderSettingsView({ initialSection: "channels" });

    fireEvent.click(await screen.findByRole("button", { name: "View Email settings" }));
    const consent = screen.getByRole("group", { name: "Consent granted" });
    expect(within(consent).getByRole("radio", { name: "Not granted" })).toBeChecked();
    expect(within(consent).getByRole("radio", { name: "Granted" })).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("true")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "View Feishu settings" }));
    fireEvent.click(screen.getByRole("button", { name: "nanobot" }));
    fireEvent.click(screen.getByText("Advanced"));
    const region = screen.getByRole("group", { name: "Region" });
    expect(within(region).getByRole("radio", { name: "Feishu" })).toBeChecked();
    expect(within(region).getByRole("radio", { name: "Lark" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "View Matrix settings" }));
    expect(screen.getByText("Choose one credential method")).toBeInTheDocument();
    const matrixBehavior = screen.getByRole("group", { name: "Group behavior" });
    expect(within(matrixBehavior).getByRole("radio", { name: "All messages" })).toBeChecked();
    expect(within(matrixBehavior).getByRole("radio", { name: "Allowlist" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "View QQ settings" }));
    const format = screen.getByRole("group", { name: "Message format" });
    expect(within(format).getByRole("radio", { name: "Plain text" })).toBeChecked();
    expect(within(format).getByRole("radio", { name: "Markdown" })).toBeInTheDocument();
  });

  it("does not offer to disable the websocket channel", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(settingsPayload());
      if (url === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
      if (url === "/api/settings/mcp-presets") return jsonResponse({ presets: [], installed_count: 0 });
      if (url === "/api/settings/nanobot-features") {
        return jsonResponse({
          features: [{
            name: "websocket",
            display_name: "Websocket",
            capabilities: ["always_enabled"],
            webui: "webui/index.ts",
            type: "channel",
            enabled: true,
            installed: true,
            ready: true,
            status: "enabled",
            install_supported: true,
            requires_restart: true,
          }],
          enabled_count: 1,
        });
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSettingsView({ initialSection: "channels" });

    expect(await screen.findByRole("button", { name: "View WebSocket settings" })).toBeInTheDocument();
    expect(screen.getAllByText("WebSocket")).toHaveLength(2);
    expect(screen.queryByText("Required for WebUI")).not.toBeInTheDocument();
    expect(screen.getAllByText("On").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Managed by WebUI")).toBeInTheDocument();
    expect(screen.queryByText("Configured manually")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Disable channel" })).not.toBeInTheDocument();
    const websocketSwitch = screen.getByRole("switch", { name: "WebSocket channel" });
    expect(websocketSwitch).toBeDisabled();
    expect(websocketSwitch).toHaveAttribute("aria-checked", "true");
    expect(requestMutationMock).not.toHaveBeenCalled();
  });
});
