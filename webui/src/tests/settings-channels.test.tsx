import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import type {
  ChannelSetupContract,
  ChannelSetupContractField,
  NanobotFeatureInfo,
  NanobotFeaturesPayload,
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
    requires_dependencies: true,
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

function catalogFeature(
  name: string,
  enabled: boolean,
  requiresDependencies = false,
): NanobotFeatureInfo {
  return {
    name,
    display_name: name,
    type: "channel",
    enabled,
    configured: enabled,
    installed: true,
    requires_dependencies: requiresDependencies,
    ready: enabled,
    status: enabled ? "enabled" : "not_enabled",
    install_supported: true,
    requires_restart: false,
  };
}

describe("Settings channels", () => {
  installSettingsViewTestHooks();

  it("shows enabled channels by default when any are enabled", async () => {
    const enabled = catalogFeature("Enabled channel", true);
    const enabledWithDependencies = catalogFeature("Enabled dependency channel", true, true);
    const disabled = catalogFeature("Disabled channel", false);
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(settingsPayload());
      if (url === "/api/settings/nanobot-features") {
        return jsonResponse({ features: [enabled, enabledWithDependencies, disabled], enabled_count: 2 });
      }
      return jsonResponse({});
    }));

    renderSettingsView({ initialSection: "channels" });

    expect(await screen.findByRole("button", { name: "View Enabled channel settings" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "View Enabled dependency channel settings" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "View Disabled channel settings" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Enabled" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByText("No installation needed")).not.toBeInTheDocument();
    expect(screen.queryByText("Requires dependencies")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "All" }));
    expect(screen.getByRole("button", { name: "View Disabled channel settings" })).toBeInTheDocument();
  });

  it("shows all channels by default when none are enabled", async () => {
    const first = catalogFeature("First channel", false);
    const second = catalogFeature("Second channel", false);
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(settingsPayload());
      if (url === "/api/settings/nanobot-features") {
        return jsonResponse({ features: [first, second], enabled_count: 0 });
      }
      return jsonResponse({});
    }));

    renderSettingsView({ initialSection: "channels" });

    expect(await screen.findByRole("button", { name: "View First channel settings" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "View Second channel settings" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "true");
  });

  it("requires a restart before enabling newly installed channel support", async () => {
    const whatsappFeature = {
      name: "whatsapp",
      display_name: "WhatsApp",
      webui: "webui/index.tsx",
      type: "channel",
      enabled: false,
      configured: false,
      installed: false,
      requires_dependencies: true,
      ready: false,
      status: "not_enabled",
      install_supported: true,
      requires_restart: false,
    } as const;
    const weixinFeature = uninstalledConnectFeature("weixin");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/settings") return jsonResponse(settingsPayload());
        if (url === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
        if (url === "/api/settings/mcp-presets") return jsonResponse({ presets: [], installed_count: 0 });
        if (url === "/api/settings/nanobot-features") {
          return jsonResponse({ features: [whatsappFeature, weixinFeature], enabled_count: 0 });
        }
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }),
    );
    let finishInstall: (payload: NanobotFeaturesPayload) => void = () => {};
    requestMutationMock.mockImplementationOnce(() => new Promise((resolve) => {
      finishInstall = resolve;
    }));
    const installedPayload = {
      features: [{ ...whatsappFeature, installed: true }, weixinFeature],
      enabled_count: 0,
      requires_restart: true,
      last_action: {
        ok: true,
        message: "Installed support for channel 'whatsapp'",
        enabled: false,
      },
    };

    renderSettingsView({ initialSection: "channels" });

    requestMutationMock.mockResolvedValueOnce({ status: "pending", session_id: "test-link" });
    expect(screen.queryByRole("switch", { name: "WhatsApp channel" })).not.toBeInTheDocument();
    const installationGroup = await screen.findByRole("region", { name: "Requires dependencies" });
    fireEvent.click(within(installationGroup).getByRole("button", { name: "Install WhatsApp" }));
    const secondInstall = within(installationGroup).getByRole("button", { name: "Install WeChat" });
    expect(secondInstall).toBeDisabled();
    fireEvent.click(secondInstall);
    expect(requestMutationMock).toHaveBeenCalledTimes(1);

    await waitFor(() =>
      expect(requestMutationMock).toHaveBeenCalledWith(
        "settings.feature.enable",
        { name: "whatsapp", install_only: true },
        150_000,
      ),
    );
    finishInstall(installedPayload);
    expect(requestMutationMock).not.toHaveBeenCalledWith("settings.channel.connect.start", expect.anything(), expect.anything());
    expect(await screen.findByText("Restart nanobot to apply updated channel support.")).toBeInTheDocument();
    const installedGroup = await screen.findByRole("region", { name: "Requires dependencies" });
    expect(within(installedGroup).getByRole("switch", { name: "WhatsApp channel" })).toBeDisabled();
    expect(requestMutationMock.mock.calls.map(([action]) => action)).toEqual([
      "settings.feature.enable",
    ]);

  });

  it.each([
    ["feishu", "Feishu"],
    ["weixin", "WeChat"],
  ] as const)(
    "installs %s support before mounting its custom connect panel",
    async (name, displayName) => {
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

      if (name === "weixin") {
        requestMutationMock.mockResolvedValueOnce({ status: "pending", session_id: "weixin-auto", qr_url: "https://example.com/weixin-login" });
      }
      renderSettingsView({ initialSection: "channels" });

      fireEvent.click(await screen.findByRole("button", { name: `View ${displayName} settings` }));
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      const installButton = screen.getByRole("button", { name: `Install ${displayName}` });
      expect(installButton).toHaveFocus();
      expect(installButton).toBeEnabled();

      fireEvent.click(installButton);

      await waitFor(() =>
        expect(requestMutationMock).toHaveBeenCalledWith(
          "settings.feature.enable",
          { name, install_only: true },
          150_000,
        ),
      );
      await screen.findByRole("switch", { name: `${displayName} channel` });
      fireEvent.click(screen.getByRole("button", { name: `View ${displayName} settings` }));
      if (name === "weixin") {
        await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
          "settings.channel.connect.start", { channel: "weixin" }, 150_000,
        ));
        expect(await screen.findByRole("img", { name: "WeChat login QR code" })).toBeInTheDocument();
        expect(requestMutationMock.mock.calls.filter(([action]) => action === "settings.channel.connect.start")).toHaveLength(1);
      } else {
        expect(await screen.findByRole("button", { name: "Connect" })).toBeInTheDocument();
        expect(screen.queryByRole("button", { name: "Create assistant" })).not.toBeInTheDocument();
        expect(requestMutationMock.mock.calls.some(([action]) => action.startsWith("settings.channel.connect"))).toBe(false);
      }
    },
  );

  it("keeps WeChat login recovery visible across transient channel refreshes", async () => {
    const expiredFeature: NanobotFeatureInfo = {
      name: "weixin",
      display_name: "WeChat",
      webui: "webui/index.tsx",
      type: "channel",
      enabled: true,
      configured: true,
      installed: true,
      requires_dependencies: true,
      ready: false,
      running: false,
      runtime_status: "failed",
      runtime_error: "WeChat login expired. Scan again to reconnect.",
      status: "failed",
      install_supported: true,
      requires_restart: false,
    };
    let currentFeature = expiredFeature;
    let featureFetches = 0;
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
          featureFetches += 1;
          return jsonResponse({ features: [currentFeature], enabled_count: 0 });
        }
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }),
    );
    requestMutationMock.mockImplementation(async (action: string) => {
      if (action === "settings.channel.connect.start") {
        return {
          status: "pending",
          session_id: "weixin-recovery",
          qr_url: "https://example.com/weixin-recovery",
        };
      }
      return settingsPayload();
    });

    renderSettingsView({ initialSection: "channels" });

    fireEvent.click(await screen.findByRole("button", { name: "View WeChat settings" }));
    expect(await screen.findByRole("img", { name: "WeChat login QR code" })).toBeInTheDocument();
    const fetchesBeforeRefresh = featureFetches;
    currentFeature = {
      ...expiredFeature,
      runtime_status: "stopped",
      runtime_error: undefined,
      status: "enabled",
    };
    window.dispatchEvent(new Event("focus"));

    await waitFor(() => expect(featureFetches).toBeGreaterThan(fetchesBeforeRefresh));
    expect(screen.getByRole("img", { name: "WeChat login QR code" })).toBeInTheDocument();
    expect(screen.getByText("WeChat login expired. Scan again to reconnect.")).toBeInTheDocument();
    expect(requestMutationMock.mock.calls.filter(([action]) => (
      action === "settings.channel.connect.start"
    ))).toHaveLength(1);
  });

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

      fireEvent.click(await screen.findByRole("button", { name: "Install WhatsApp" }));

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
            requires_dependencies: true,
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
        requires_dependencies: true,
        ready: true,
        status: "enabled",
        install_supported: true,
        requires_restart: true,
      }],
      enabled_count: 1,
      last_action: { ok: true, message: "Enabled channel 'matrix'", enabled: true },
    });

    renderSettingsView({ initialSection: "channels" });

    expect((await screen.findAllByText("Failed")).length).toBeGreaterThan(0);
    expect(screen.queryByRole("switch", { name: "Matrix channel" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Install Matrix" }));

    await waitFor(() =>
      expect(requestMutationMock).toHaveBeenCalledWith(
        "settings.feature.enable",
        { name: "matrix", install_only: true },
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

    fireEvent.click(await screen.findByRole("button", { name: "View Matrix settings" }));
    expect(screen.getAllByText("Failed").length).toBeGreaterThan(0);
    expect(screen.getByText(runtimeError)).toBeInTheDocument();
    expect(screen.getByLabelText("Matrix channel")).toHaveAttribute(
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

    fireEvent.click(await screen.findByRole("button", { name: "View Feishu settings" }));
    fireEvent.click(await screen.findByRole("button", { name: "Connect" }));

    await waitFor(() =>
      expect(requestMutationMock).toHaveBeenCalledWith(
        "settings.channel.connect.start",
        { channel: "feishu", domain: "feishu", instance_id: "default", mode: "replace" },
        150_000,
      ),
    );
    expect(await screen.findByText("Scan with Feishu")).toBeInTheDocument();
    expect(await screen.findByText("Waiting for authorization...")).toBeInTheDocument();
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

    fireEvent.click(await screen.findByRole("button", { name: "View Feishu settings" }));
    fireEvent.click(await screen.findByRole("button", { name: "Connect" }));

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

    fireEvent.click((await screen.findAllByRole("button", { name: /^View .+ settings$/ }))[0]);
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

  it("opens and saves each Feishu assistant's settings directly from Advanced", async () => {
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

    fireEvent.click((await screen.findAllByRole("button", { name: /^View .+ settings$/ }))[0]);
    expect(await screen.findByText("Product Helper")).toBeInTheDocument();
    expect(screen.getAllByText("Support Bot")).toHaveLength(1);
    expect(document.querySelector('img[src="https://example.com/support.png"]')).toBeTruthy();

    const support = within(screen.getByText("Support Bot").closest("article")!);
    const product = within(screen.getByText("Product Helper").closest("article")!);
    const supportAdvanced = support.getByRole("button", { name: "Advanced" });
    const productAdvanced = product.getByRole("button", { name: "Advanced" });
    expect(supportAdvanced).toBeVisible();
    expect(productAdvanced).toBeVisible();

    supportAdvanced.focus();
    await userEvent.setup().keyboard("[Enter]");
    expect(supportAdvanced).toHaveAttribute("aria-expanded", "true");
    expect(support.getByLabelText("App ID")).toBeVisible();
    expect(support.getByLabelText("App ID")).toHaveValue("cli_default");
    expect(support.getByRole("group", { name: "Topic isolation" })).toBeVisible();

    fireEvent.click(productAdvanced);
    expect(supportAdvanced).toHaveAttribute("aria-expanded", "false");
    expect(productAdvanced).toHaveAttribute("aria-expanded", "true");
    expect(product.getByLabelText("App ID")).toHaveValue("cli_product");
    fireEvent.change(product.getByLabelText("App ID"), { target: { value: "cli_updated" } });
    const featureRequests = () => vi.mocked(fetch).mock.calls
      .filter(([input]) => String(input) === "/api/settings/nanobot-features").length;
    const beforeRefresh = featureRequests();
    await act(async () => { fireEvent(window, new Event("focus")); });
    await waitFor(() => expect(featureRequests()).toBeGreaterThan(beforeRefresh));
    expect(product.getByLabelText("App ID")).toHaveValue("cli_updated");
    fireEvent.click(productAdvanced);
    expect(productAdvanced).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(productAdvanced);
    expect(product.getByLabelText("App ID")).toHaveValue("cli_updated");
    fireEvent.click(product.getByRole("button", { name: "Save settings" }));
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.channel.configure",
      expect.objectContaining({
        name: "feishu",
        instance_id: "product",
        enable: false,
        values: expect.objectContaining({ "channels.feishu.appId": "cli_updated" }),
      }),
      150_000,
    ));
    expect(await screen.findByText("Settings saved.")).toBeVisible();

    productAdvanced.focus();
    await userEvent.setup().keyboard("[Space]");
    expect(productAdvanced).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(supportAdvanced);
    expect(support.getByLabelText("App ID")).toHaveValue("cli_default");
  });

  it("opens WeChat advanced settings from the header and preserves autosave", async () => {
    const feature: NanobotFeatureInfo = {
      name: "weixin",
      display_name: "WeChat",
      webui: "webui/index.tsx",
      type: "channel",
      installed: true,
      enabled: false,
      configured: true,
      ready: true,
      status: "not_enabled",
      install_supported: true,
      requires_restart: false,
      setup: { fields: [
        channelSetupField("weixin", "sendProgress", "bool"),
        channelSetupField("weixin", "baseUrl"),
        channelSetupField("weixin", "token", "secret"),
      ] },
      config_values: {
        "channels.weixin.sendProgress": "true",
        "channels.weixin.baseUrl": "https://api.example.com",
      },
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/api/settings") return jsonResponse(settingsPayload());
      if (String(input) === "/api/settings/nanobot-features") {
        return jsonResponse({ features: [feature], enabled_count: 0 });
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    }));
    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View WeChat settings" }));

    const advanced = await screen.findByRole("button", { name: "Advanced" });
    advanced.focus();
    await userEvent.setup().keyboard("[Enter]");
    const apiUrl = screen.getByRole("textbox", { name: "API URL" });
    expect(apiUrl).toBeVisible();
    expect(screen.queryByLabelText("Token")).not.toBeInTheDocument();
    fireEvent.change(apiUrl, { target: { value: "https://updated.example.com" } });
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.channel.configure",
      expect.objectContaining({
        name: "weixin",
        enable: false,
        values: expect.objectContaining({ "channels.weixin.baseUrl": "https://updated.example.com" }),
      }),
      150_000,
    ));

    fireEvent.click(advanced);
    fireEvent.click(advanced);
    expect(screen.getByRole("textbox", { name: "API URL" })).toHaveValue("https://updated.example.com");
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

    fireEvent.click((await screen.findAllByRole("button", { name: /^View .+ settings$/ }))[0]);
    expect(await screen.findByText("Default worker")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Default worker instance" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByRole("switch", { name: "Product worker instance" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    fireEvent.click(within(screen.getByText("Product worker").closest("article")!)
      .getByRole("button", { name: "Advanced" }));
    expect(screen.getByRole("radio", { name: "Eu" })).toBeChecked();
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

    fireEvent.click((await screen.findAllByRole("button", { name: /^View .+ settings$/ }))[0]);
    await screen.findByText("Support Bot");
    expect(screen.getAllByText("Support Bot")).toHaveLength(1);
    expect(screen.getByRole("switch", { name: "Support Bot assistant" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    fireEvent.click(screen.getByRole("button", { name: "Advanced" }));
    expect(screen.getByLabelText("App ID")).toBeInTheDocument();
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

    fireEvent.click((await screen.findAllByRole("button", { name: /^View .+ settings$/ }))[0]);
    expect(screen.getAllByText("Failed").length).toBeGreaterThan(0);
    expect(screen.getByText(runtimeError)).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "test assistant" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });

  it("preserves advanced field edits when collapsed and reopened with the keyboard", async () => {
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

    fireEvent.click(await screen.findByRole("button", { name: "View Discord settings" }));

    const advanced = screen.getByRole("button", { name: "Advanced" });
    advanced.focus();
    await userEvent.setup().keyboard("[Enter]");
    expect(advanced).toHaveAttribute("aria-expanded", "true");
    const behavior = screen.getByRole("group", { name: "Group behavior" });
    expect(behavior).toBeVisible();
    expect(within(behavior).getByRole("radio", { name: "Mention only" })).toBeChecked();
    expect(within(behavior).getByRole("radio", { name: "All messages" })).toBeInTheDocument();

    fireEvent.click(within(behavior).getByRole("radio", { name: "All messages" }));

    expect(within(behavior).getByRole("radio", { name: "All messages" })).toBeChecked();

    fireEvent.click(advanced);
    expect(advanced).toHaveAttribute("aria-expanded", "false");
    expect(behavior).not.toBeVisible();
    advanced.focus();
    await userEvent.setup().keyboard("[Space]");
    expect(advanced).toHaveAttribute("aria-expanded", "true");
    expect(behavior).toBeVisible();
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
    expect(emailRow).toBeVisible();
    expect(screen.getByRole("switch", { name: "Email channel" })).toBeInTheDocument();

    fireEvent.click(emailRow);

    expect(screen.getByRole("dialog")).toHaveFocus();
    expect(within(screen.getByRole("dialog")).getByRole("heading", { name: "Email" })).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Close", exact: true }));

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

    fireEvent.click(await screen.findByRole("button", { name: "View Discord settings" }));
    fireEvent.pointerDown(screen.getByRole("button", { name: "Help", exact: true }), { button: 0, ctrlKey: false });
    expect(await screen.findByRole("menuitem", { name: "Open Discord setup" })).toHaveAttribute(
      "href",
      "https://nanobot.wiki/docs/0.2.2/getting-started/chat-apps#discord",
    );
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    expect(screen.getByLabelText("Discord channel")).toBeEnabled();
    fireEvent.change(screen.getByPlaceholderText("Discord bot token"), {
      target: { value: "discord-token" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Advanced" }));
    fireEvent.change(screen.getByLabelText("Allowed channels"), {
      target: { value: "123, 456" },
    });
    fireEvent.click(within(screen.getByRole("group", { name: "Group behavior" })).getByRole(
      "radio",
      { name: "All messages" },
    ));
    fireEvent.click(screen.getByRole("switch", { name: "Enable channel", exact: true }));

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
    expect(screen.getByLabelText("Discord channel")).toHaveAttribute(
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

    fireEvent.click(await screen.findByRole("button", { name: "View Email settings" }));
    expect(screen.getByText("Receiving mail")).toBeInTheDocument();
    expect(screen.getByText("Sending mail")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("IMAP host"), { target: { value: "imap.example.com" } });
    fireEvent.change(screen.getByLabelText("IMAP username"), { target: { value: "bot@example.com" } });
    fireEvent.change(screen.getByLabelText("IMAP password"), { target: { value: "imap-secret" } });
    fireEvent.change(screen.getByLabelText("SMTP host"), { target: { value: "smtp.example.com" } });
    fireEvent.change(screen.getByLabelText("SMTP username"), { target: { value: "bot@example.com" } });
    fireEvent.change(screen.getByLabelText("SMTP password"), { target: { value: "smtp-secret" } });

    const consentGroup = screen.getByRole("group", { name: "Allow nanobot to read and send email" });
    const notGranted = within(consentGroup).getByRole("radio", { name: "Not granted" });
    const granted = within(consentGroup).getByRole("radio", { name: "Granted" });
    expect(notGranted).toBeChecked();

    fireEvent.click(screen.getByRole("switch", { name: "Enable channel", exact: true }));

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
    fireEvent.click(screen.getByRole("switch", { name: "Enable channel", exact: true }));

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

    fireEvent.click(await screen.findByRole("button", { name: "View Discord settings" }));
    expect(screen.getByLabelText("Discord channel")).toHaveAttribute(
      "aria-checked",
      "false",
    );
    expect(screen.getByLabelText("Discord channel")).toBeEnabled();
    const savedSecret = screen.getByPlaceholderText("Saved secret");
    expect(savedSecret).toHaveValue("");
    expect(savedSecret).toHaveAttribute("autocomplete", "off");
    expect(savedSecret.closest("form")).not.toBeNull();
    expect(screen.queryByDisplayValue("discord-secret-token")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Advanced" }));
    expect(screen.getByLabelText("Allowed channels")).toHaveValue("123, 456");
    expect(within(screen.getByRole("group", { name: "Group behavior" })).getByRole(
      "radio",
      { name: "All messages" },
    )).toBeChecked();

    fireEvent.click(screen.getByRole("button", { name: "Close", exact: true }));
    fireEvent.click(screen.getByLabelText("Discord channel"));
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

    fireEvent.click(await screen.findByRole("button", { name: "View Telegram settings" }));
    fireEvent.pointerDown(screen.getByRole("button", { name: "Help", exact: true }), { button: 0, ctrlKey: false });
    expect(await screen.findByRole("menuitem", { name: "Open Telegram setup" })).toHaveAttribute(
      "href",
      "https://nanobot.wiki/docs/0.2.2/getting-started/chat-apps#telegram",
    );
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
  });

  it("opens channel setup guides from the help menu", async () => {
    const channels = [
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
      ["mochat", "MoChat", "Open MoChat setup guide"],
    ] as const;

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
            })),
            enabled_count: 1,
          });
        }
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }),
    );

    renderSettingsView({ initialSection: "channels" });

    for (const [, displayName, guideLabel] of channels) {
      fireEvent.click(await screen.findByRole("button", { name: `View ${displayName} settings` }));
      fireEvent.pointerDown(screen.getByRole("button", { name: "Help", exact: true }), { button: 0, ctrlKey: false });
      const guide = await screen.findByRole("menuitem", { name: guideLabel });
      expect(guide).toHaveAttribute("href", expect.stringMatching(/^https:\/\//));
      fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
      fireEvent.click(screen.getByRole("button", { name: "Close", exact: true }));
    }
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
    const consent = screen.getByRole("group", { name: "Allow nanobot to read and send email" });
    expect(within(consent).getByRole("radio", { name: "Not granted" })).toBeChecked();
    expect(within(consent).getByRole("radio", { name: "Granted" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Close", exact: true }));
    fireEvent.click(screen.getByRole("button", { name: "View Feishu settings" }));
    fireEvent.click(screen.getByRole("button", { name: "Advanced" }));
    const region = screen.getByRole("group", { name: "Region" });
    expect(within(region).getByRole("radio", { name: "Feishu" })).toBeChecked();
    expect(within(region).getByRole("radio", { name: "Lark" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Close", exact: true }));
    fireEvent.click(screen.getByRole("button", { name: "View Matrix settings" }));
    expect(screen.getByText("Choose one credential method")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Advanced" }));
    const matrixBehavior = screen.getByRole("group", { name: "Group behavior" });
    expect(within(matrixBehavior).getByRole("radio", { name: "All messages" })).toBeChecked();
    expect(within(matrixBehavior).getByRole("radio", { name: "Allowlist" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Close", exact: true }));
    fireEvent.click(screen.getByRole("button", { name: "View QQ settings" }));
    fireEvent.click(screen.getByRole("button", { name: "Advanced" }));
    const format = screen.getByRole("group", { name: "Message format" });
    expect(within(format).getByRole("radio", { name: "Plain text" })).toBeChecked();
    expect(within(format).getByRole("radio", { name: "Markdown" })).toBeInTheDocument();
  });

  it("keeps the WebUI websocket channel enabled without opening a setup dialog", async () => {
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

    const websocketName = await screen.findByText("nanobot WebUI");
    fireEvent.click(websocketName);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    const websocketSwitch = screen.getByRole("switch", { name: "nanobot WebUI channel" });
    expect(websocketSwitch).toBeDisabled();
    expect(websocketSwitch).toHaveAttribute("aria-checked", "true");
    expect(requestMutationMock).not.toHaveBeenCalled();
  });
});
