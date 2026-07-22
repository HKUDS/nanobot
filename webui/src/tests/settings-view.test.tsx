import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SettingsView } from "@/components/settings/SettingsView";
import { ClientProvider } from "@/providers/ClientProvider";
import type {
  ChannelSetupContract,
  ChannelSetupContractField,
  SettingsPayload,
} from "@/lib/types";

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
  } as Response;
}

function settingsPayload(): SettingsPayload {
  return {
    agent: {
      model: "openai/gpt-4o",
      provider: "auto",
      resolved_provider: "openai",
      has_api_key: true,
      model_preset: "default",
      max_tokens: 8192,
      context_window_tokens: 200000,
      temperature: 0.1,
      reasoning_effort: null,
      timezone: "UTC",
      bot_name: "nanobot",
      bot_icon: "nb",
      tool_hint_max_length: 40,
    },
    model_presets: [{
      name: "default",
      label: "Default",
      active: true,
      is_default: true,
      model: "openai/gpt-4o",
      provider: "auto",
      max_tokens: 8192,
      context_window_tokens: 200000,
      temperature: 0.1,
      reasoning_effort: null,
    }],
    providers: [],
    web_search: {
      provider: "duckduckgo",
      api_key_hint: null,
      base_url: null,
      max_results: 5,
      timeout: 30,
      providers: [{ name: "duckduckgo", label: "DuckDuckGo", credential: "none" }],
    },
    web: {
      enable: true,
      proxy: null,
      user_agent: null,
      search: { max_results: 5, timeout: 30 },
      fetch: { use_jina_reader: true },
    },
    api: {
      host: "127.0.0.1",
      port: 8900,
      timeout: 120,
      api_key_hint: null,
    },
    observability: {
      provider: "langfuse",
      configured: false,
      base_url: "https://cloud.langfuse.com",
    },
    image_generation: {
      enabled: false,
      provider: "openrouter",
      provider_configured: false,
      model: "openai/gpt-5.4-image-2",
      default_aspect_ratio: "1:1",
      default_image_size: "1K",
      max_images_per_turn: 4,
      save_dir: "generated",
      providers: [],
    },
    runtime: {
      config_path: "/tmp/config.json",
      workspace_path: "/tmp/workspace",
      gateway_host: "127.0.0.1",
      gateway_port: 18790,
      heartbeat: {
        enabled: true,
        interval_s: 1800,
        keep_recent_messages: 8,
      },
      dream: {
        schedule: "every 2h",
      },
      unified_session: false,
    },
    advanced: {
      restrict_to_workspace: false,
      webui_allow_local_service_access: true,
      webui_default_access_mode: "default",
      private_service_protection_enabled: true,
      ssrf_whitelist_count: 0,
      mcp_server_count: 0,
      exec_enabled: true,
      exec_sandbox: null,
      exec_path_prepend_set: false,
      exec_path_append_set: false,
    },
    requires_restart: false,
    version: {
      current: "0.2.2",
    },
    docs: {
      version: "0.2.2",
      base_url: "https://nanobot.wiki/docs/0.2.2",
      chat_apps_url: "https://nanobot.wiki/docs/0.2.2/getting-started/chat-apps",
      latest_url: "https://nanobot.wiki/docs/latest",
    },
  };
}

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
  channel: "discord" | "email" | "feishu" | "matrix" | "qq" | "telegram",
): ChannelSetupContract {
  const field = (
    name: string,
    kind: ChannelSetupContractField["kind"] = "string",
    options: Parameters<typeof channelSetupField>[3] = {},
  ) => channelSetupField(channel, name, kind, options);

  switch (channel) {
    case "telegram":
      return {
        official_url: "https://t.me/BotFather",
        fields: [
          field("name"),
          field("token", "secret", { required: true }),
          field("proxy", "secret"),
          field("allowFrom", "list"),
          field("groupPolicy", "enum", {
            choices: ["mention", "open"],
            defaultValue: "mention",
          }),
        ],
      };
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
      };
  }
}

function autoDynamicProviderPayload(
  options: {
    configured: boolean;
    hasApiKey: boolean;
    apiBase: string | null;
    apiKeyHint: string | null;
  },
): SettingsPayload {
  const base = settingsPayload();
  return {
    ...base,
    agent: {
      ...base.agent,
      model: "companyProxy/gpt-4o",
      provider: "companyProxy",
      resolved_provider: "companyProxy",
      has_api_key: options.hasApiKey,
    },
    model_presets: [
      {
        ...base.model_presets[0],
        model: "companyProxy/gpt-4o",
        provider: "auto",
      },
    ],
    providers: [
      {
        name: "companyProxy",
        label: "Company Proxy",
        configured: options.configured,
        auth_type: "api_key",
        api_key_required: false,
        api_key_hint: options.apiKeyHint,
        api_base: options.apiBase,
        default_api_base: null,
      },
    ],
  };
}

const installedAnyGen = {
  name: "anygen",
  display_name: "AnyGen",
  category: "generation",
  description: "Generate docs, slides, websites and more via AnyGen cloud API",
  requires: "ANYGEN_API_KEY",
  source: "harness",
  entry_point: "cli-anything-anygen",
  install_supported: true,
  installed: true,
  available: true,
  status: "installed",
  logo_url: "https://www.google.com/s2/favicons?domain=anygen.io&sz=64",
  brand_color: "#111827",
  skill_installed: true,
};

function renderSettingsView(
  options: {
    initialSection?:
      | "overview"
      | "appearance"
      | "apps"
      | "channels"
      | "automations"
      | "advanced"
      | "models"
      | "image"
      | "browser"
      | "runtime";
    initialSettings?: SettingsPayload;
    showSidebar?: boolean;
    onSettingsChange?: (payload: SettingsPayload) => void;
    onNativeEngineRestart?: () => Promise<string>;
  } = {},
) {
  render(
    <ClientProvider client={{} as never} token="tok">
      <SettingsView
        theme="light"
        initialSection={options.initialSection ?? "apps"}
        initialSettings={options.initialSettings}
        showSidebar={options.showSidebar}
        onToggleTheme={() => {}}
        onBackToChat={() => {}}
        onModelNameChange={() => {}}
        onSettingsChange={options.onSettingsChange}
        onNativeEngineRestart={options.onNativeEngineRestart}
      />
    </ClientProvider>,
  );
}

describe("SettingsView Apps catalog", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn((query: string) => ({
        matches: query === "(min-width: 1280px)",
        media: query,
        onchange: null,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    );
  });

  afterEach(() => {
    localStorage.removeItem("nanobot-webui.settings-preferences");
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("persists the file edit display local preference", async () => {
    renderSettingsView({
      initialSection: "appearance",
      initialSettings: settingsPayload(),
      showSidebar: true,
    });

    expect(screen.getByText("File edit display")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Diff" }));

    await waitFor(() => {
      const saved = JSON.parse(localStorage.getItem("nanobot-webui.settings-preferences") || "{}");
      expect(saved.fileEditDisplayMode).toBe("diff");
    });
  });

  it("does not show the Settings kicker on the standalone Automations surface", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(settingsPayload());
      if (url === "/api/webui/automations") return jsonResponse({ jobs: [] });
      return jsonResponse({});
    }));

    renderSettingsView({
      initialSection: "automations",
      initialSettings: settingsPayload(),
      showSidebar: false,
    });

    expect(screen.getByRole("heading", { name: "Automations" })).toBeInTheDocument();
    expect(await screen.findByText("No automations yet.")).toBeInTheDocument();
    expect(screen.queryByText("Settings")).not.toBeInTheDocument();
  });

  it("starts the managed API server from System", async () => {
    const base = settingsPayload();
    const stopped = {
      installed: false,
      running: false,
      managed: false,
      host: "127.0.0.1",
      port: 8900,
      timeout: 120,
      api_key_hint: null,
      endpoint: "http://127.0.0.1:8900/v1",
      command: "nanobot serve",
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(base);
      if (url === "/api/settings/api-service") return jsonResponse(stopped);
      if (url === "/api/settings/nanobot-features") {
        return jsonResponse({ features: [], enabled_count: 0 });
      }
      if (url === "/api/settings/api-service/start?host=127.0.0.1&port=8900&timeout=120") {
        return jsonResponse({ ...stopped, installed: true, running: true, managed: true });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSettingsView({ initialSection: "runtime", initialSettings: base, showSidebar: true });

    fireEvent.click(await screen.findByRole("button", { name: "Start API server" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/settings/api-service/start?host=127.0.0.1&port=8900&timeout=120",
        expect.any(Object),
      );
    });
  });

  it("shows a visible uninstall button for installed CLI apps and calls uninstall", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") {
        return jsonResponse(settingsPayload());
      }
      if (url === "/api/settings/cli-apps") {
        return jsonResponse({
          apps: [installedAnyGen],
          installed_count: 1,
          catalog_updated_at: "2026-04-18",
        });
      }
      if (url === "/api/settings/mcp-presets") {
        return jsonResponse({ presets: [], installed_count: 0 });
      }
      if (url === "/api/settings/cli-apps/uninstall?name=anygen") {
        return jsonResponse({
          apps: [{ ...installedAnyGen, installed: false, status: "available" }],
          installed_count: 0,
          catalog_updated_at: "2026-04-18",
          last_action: {
            ok: true,
            message: "Uninstalled CLI for AnyGen.",
            still_available: false,
          },
        });
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSettingsView();

    expect(await screen.findByRole("heading", { name: "Apps" })).toBeInTheDocument();
    expect(await screen.findByText("AnyGen")).toBeInTheDocument();
    const uninstall = screen.getByRole("button", { name: "Uninstall app" });

    fireEvent.click(uninstall);

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/settings/cli-apps/uninstall?name=anygen",
        expect.objectContaining({
          headers: { Authorization: "Bearer tok" },
        }),
      ),
    );
    expect(await screen.findByText("Uninstalled CLI for AnyGen.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));

    expect(screen.queryByText("Uninstalled CLI for AnyGen.")).not.toBeInTheDocument();
  });

  it("keeps runtime dependencies out of Apps and explains chat mentions", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(settingsPayload());
      if (url === "/api/settings/cli-apps") {
        return jsonResponse({
          apps: [{ ...installedAnyGen, installed: false, status: "available" }],
          installed_count: 0,
        });
      }
      if (url === "/api/settings/mcp-presets") {
        return jsonResponse({ presets: [], installed_count: 0 });
      }
      if (url === "/api/settings/nanobot-features") {
        return jsonResponse({
          features: [
            {
              name: "api",
              display_name: "Api",
              type: "feature",
              enabled: true,
              installed: true,
              ready: true,
              status: "enabled",
              install_supported: true,
              requires_restart: true,
            },
          ],
          enabled_count: 1,
        });
      }
      return jsonResponse({});
    }));

    renderSettingsView({ initialSection: "apps" });

    expect(await screen.findByText("Add tools to nanobot, then @ them in chat.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ready" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Apps" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Integrations" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Plugins" })).not.toBeInTheDocument();
    expect(screen.queryByText("Api")).not.toBeInTheDocument();
    expect(screen.getByText("AnyGen")).toBeInTheDocument();
    expect(screen.getByText("0 ready")).toBeInTheDocument();
  });

  it("shows nanobot optional features and enables one", async () => {
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
            webui: "webui/index.ts",
            type: "channel",
            enabled: false,
            installed: false,
            ready: false,
            status: "missing_dependency",
            install_supported: true,
            requires_restart: true,
          }],
          enabled_count: 0,
        });
      }
      if (url === "/api/settings/nanobot-features/enable?name=matrix") {
        return jsonResponse({
          features: [{
            name: "matrix",
            display_name: "Matrix",
            webui: "webui/index.ts",
            type: "channel",
            enabled: true,
            running: true,
            runtime_status: "running",
            installed: true,
            ready: true,
            status: "enabled",
            install_supported: true,
            requires_restart: true,
          }],
          enabled_count: 1,
          last_action: { ok: true, message: "Enabled channel 'matrix'", enabled: true },
        });
      }
      if (url === "/api/settings/nanobot-features/disable?name=matrix") {
        return jsonResponse({
          features: [{
            name: "matrix",
            display_name: "Matrix",
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
          requires_restart: true,
          last_action: { ok: true, message: "Disabled channel 'matrix'", enabled: false },
        });
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSettingsView({ initialSection: "channels" });

    const matrixRow = await screen.findByRole("button", { name: "View Matrix settings" });
    expect(matrixRow).toHaveAttribute("aria-pressed", "true");
    expect(screen.getAllByText("Matrix")).toHaveLength(2);
    expect(screen.getAllByText("Use nanobot from Matrix rooms.")).toHaveLength(2);
    expect(screen.queryByText(/Enabling Nanobot features may install Python packages/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("switch", { name: "Matrix channel" }));
    expect(screen.getByRole("dialog", { name: "Install support for Matrix?" })).toBeInTheDocument();
    expect(screen.getByText("nanobot will add what Matrix needs, then turn it on. Continue?")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalledWith(
      "/api/settings/nanobot-features/enable?name=matrix",
      expect.anything(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Install and enable" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/settings/nanobot-features/enable?name=matrix",
        expect.objectContaining({
          headers: { Authorization: "Bearer tok" },
        }),
      ),
    );
    await waitFor(() =>
      expect(screen.getByRole("switch", { name: "Matrix channel" })).toHaveAttribute("aria-checked", "true"),
    );
    expect(screen.queryByText("Enabled channel 'matrix'")).not.toBeInTheDocument();
    expect(screen.queryByText("Restart nanobot to apply updated channel support.")).not.toBeInTheDocument();
    expect(screen.getAllByText("On").length).toBeGreaterThan(0);

    expect(screen.getByLabelText("Homeserver")).toBeInTheDocument();
    expect(screen.getByLabelText("User ID")).toBeInTheDocument();
    expect(screen.getByLabelText("Device ID")).toBeInTheDocument();
    expect(screen.queryByText("channels.matrix.homeserver")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("switch", { name: "Matrix channel" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/settings/nanobot-features/disable?name=matrix",
        expect.objectContaining({
          headers: { Authorization: "Bearer tok" },
        }),
      ),
    );
    await waitFor(() =>
      expect(screen.getByRole("switch", { name: "Matrix channel" })).toHaveAttribute("aria-checked", "false"),
    );
    expect(screen.queryByText("Disabled channel 'matrix'")).not.toBeInTheDocument();
  });

  it("installs Telegram support from the channel switch before showing bot setup", async () => {
    const telegramInstance = {
      id: "default",
      name: "nanobot",
      enabled: false,
      configured: false,
      config_values: {
        "channels.telegram.name": "nanobot",
        "channels.telegram.groupPolicy": "mention",
      },
      configured_fields: [
        "channels.telegram.name",
        "channels.telegram.groupPolicy",
      ],
    };
    const telegramFeature = (installed: boolean) => ({
      name: "telegram",
      display_name: "Telegram",
      webui: "webui/index.ts",
      type: "channel",
      enabled: installed,
      configured: false,
      installed,
      ready: false,
      status: installed ? "not_enabled" : "missing_dependency",
      install_supported: true,
      requires_restart: true,
      setup: channelSetupContract("telegram"),
      instances: [{ ...telegramInstance, enabled: installed }],
    });
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(settingsPayload());
      if (url === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
      if (url === "/api/settings/mcp-presets") return jsonResponse({ presets: [], installed_count: 0 });
      if (url === "/api/settings/nanobot-features") {
        return jsonResponse({
          features: [telegramFeature(false)],
          enabled_count: 0,
        });
      }
      if (url === "/api/settings/nanobot-features/enable?name=telegram") {
        return jsonResponse({
          features: [telegramFeature(true)],
          enabled_count: 1,
          requires_restart: true,
          last_action: { ok: true, message: "Enabled channel 'telegram'", enabled: true },
        });
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSettingsView({ initialSection: "channels" });

    const telegramSwitch = await screen.findByRole("switch", { name: "Telegram channel" });
    expect(telegramSwitch).toBeEnabled();
    expect(screen.queryByLabelText("Bot token", { selector: "input" })).not.toBeInTheDocument();

    fireEvent.click(telegramSwitch);
    expect(screen.getByRole("dialog", { name: "Install support for Telegram?" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Install and enable" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/settings/nanobot-features/enable?name=telegram",
        expect.objectContaining({ headers: { Authorization: "Bearer tok" } }),
      ),
    );
    fireEvent.click(await screen.findByRole("button", { name: "nanobot" }));
    expect(screen.getByLabelText("Bot token", { selector: "input" })).toBeVisible();
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
      if (url === "/api/settings/nanobot-features/enable?name=matrix") {
        return jsonResponse({
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
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSettingsView({ initialSection: "channels" });

    expect(await screen.findByRole("button", { name: "View Matrix settings" })).toBeInTheDocument();
    expect(screen.getByText("0 running · 1 channels")).toBeInTheDocument();
    expect(screen.getAllByText("Failed").length).toBeGreaterThan(0);
    expect(screen.queryByText("Enabled, support needs install")).not.toBeInTheDocument();

    expect(screen.getByRole("switch", { name: "Matrix channel" })).toHaveAttribute("aria-checked", "false");
    fireEvent.click(screen.getByRole("button", { name: "Install support" }));
    fireEvent.click(screen.getByRole("button", { name: "Install and enable" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/settings/nanobot-features/enable?name=matrix",
        expect.objectContaining({
          headers: { Authorization: "Bearer tok" },
        }),
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
    expect(screen.getByText("0 running · 1 channels")).toBeInTheDocument();
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
      if (url === "/api/settings/channels/feishu/connect/start?domain=feishu&instance_id=default&mode=replace") {
        return jsonResponse({
          session_id: "feishu-session",
          status: "pending",
          qr_url: "https://accounts.feishu.cn/login?device_code=device",
          domain: "feishu",
          interval_ms: 5000,
          expires_at_ms: Date.now() + 600_000,
          message: "Scan with Feishu or Lark to connect.",
        });
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSettingsView({ initialSection: "channels" });

    expect(await screen.findByRole("button", { name: "View Feishu settings" })).toBeInTheDocument();
    expect(screen.queryByText("nanobot channels login feishu")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "nanobot" }));
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/settings/channels/feishu/connect/start?domain=feishu&instance_id=default&mode=replace",
        expect.objectContaining({
          headers: { Authorization: "Bearer tok" },
        }),
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
      if (url === "/api/settings/channels/feishu/connect/start?domain=feishu&instance_id=default&mode=replace") {
        return jsonResponse({
          session_id: "feishu-switch-session",
          status: "pending",
          qr_url: "https://accounts.feishu.cn/login?device_code=switch-device",
          domain: "feishu",
          interval_ms: 5000,
          expires_at_ms: Date.now() + 600_000,
          message: "Scan with Feishu or Lark to connect.",
        });
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSettingsView({ initialSection: "channels" });

    expect(await screen.findByRole("button", { name: "View Feishu settings" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "nanobot" }));
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/settings/channels/feishu/connect/start?domain=feishu&instance_id=default&mode=replace",
        expect.objectContaining({
          headers: { Authorization: "Bearer tok" },
        }),
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
      if (url === "/api/settings/nanobot-features/enable?name=feishu&instance_id=default") {
        return jsonResponse({
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
        });
      }
      if (url === "/api/settings/channels/feishu/connect/start?domain=feishu&instance_id=default&mode=replace") {
        throw new Error("Feishu connect should not start when credentials are already configured");
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSettingsView({ initialSection: "channels" });

    fireEvent.click(await screen.findByRole("button", { name: "nanobot" }));
    fireEvent.click(await screen.findByRole("switch", { name: "nanobot assistant" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/settings/nanobot-features/enable?name=feishu&instance_id=default",
        expect.objectContaining({
          headers: { Authorization: "Bearer tok" },
        }),
      ),
    );
    expect(fetchMock.mock.calls.some(([input]) =>
      String(input) === "/api/settings/channels/feishu/connect/start?domain=feishu&instance_id=default&mode=replace",
    )).toBe(false);
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
    expect(screen.getByRole("radio", { name: "Eu" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText("Saved")).toBeInTheDocument();
  });

  it("shows a single Feishu assistant without a duplicate assistant list", async () => {
    const reconnectUrls: string[] = [];
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
        if (url === "/api/settings/nanobot-features/enable?name=feishu&instance_id=default") {
          reconnectUrls.push(url);
          return jsonResponse(feishuPayload);
        }
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }),
    );

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
    await waitFor(() => expect(reconnectUrls).toHaveLength(1));
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
    expect(screen.getByText("0 running · 1 channels")).toBeInTheDocument();
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
    fireEvent.click(screen.getByText("Advanced"));

    const behavior = screen.getByRole("radiogroup", { name: "Group behavior" });
    expect(within(behavior).getByRole("radio", { name: "Mention only" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(within(behavior).getByRole("radio", { name: "All messages" })).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("mention")).not.toBeInTheDocument();

    fireEvent.click(within(behavior).getByRole("radio", { name: "All messages" }));

    expect(within(behavior).getByRole("radio", { name: "All messages" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
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
    expect(screen.getByPlaceholderText("Search channels")).toBeInTheDocument();
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
      if (url === "/api/settings/channels/configure?name=discord&enable=true") {
        return jsonResponse({
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
      }
      if (url === "/api/settings/channels/validate?name=discord") {
        return jsonResponse({
          name: "discord",
          status: "configured",
          checks: [{ id: "bot_token", label: "Bot token", status: "pass" }],
          identity: { name: "nanobot-test", account: "123" },
          missing_fields: [],
          can_enable: true,
          requires_restart: false,
          message: "Configuration is present.",
        });
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSettingsView({ initialSection: "channels" });

    expect(await screen.findByRole("button", { name: "View Discord settings" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Discord setup" })).toHaveAttribute(
      "href",
      "https://nanobot.wiki/docs/0.2.2/getting-started/chat-apps#discord",
    );
    expect(screen.getByRole("switch", { name: "Discord channel" })).toBeDisabled();
    fireEvent.change(screen.getByPlaceholderText("Discord bot token"), {
      target: { value: "discord-token" },
    });
    fireEvent.click(screen.getByText("Advanced"));
    fireEvent.change(screen.getByLabelText("Allowed channels"), {
      target: { value: "123, 456" },
    });
    fireEvent.click(within(screen.getByRole("radiogroup", { name: "Group behavior" })).getByRole(
      "radio",
      { name: "All messages" },
    ));
    fireEvent.click(screen.getByRole("button", { name: "Check and enable" }));

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([input]) => String(input) === "/api/settings/channels/configure?name=discord&enable=true",
        ),
      ).toBe(true),
    );
    const configureCall = fetchMock.mock.calls.find(
      ([input]) => String(input) === "/api/settings/channels/configure?name=discord&enable=true",
    );
    expect((configureCall?.[1] as RequestInit | undefined)?.method).toBeUndefined();
    const headers = (configureCall?.[1] as RequestInit | undefined)?.headers as Record<string, string>;
    expect(JSON.parse(headers["X-Nanobot-Channel-Values"])).toEqual({
      "channels.discord.token": "discord-token",
      "channels.discord.allowChannels": "123, 456",
      "channels.discord.groupPolicy": "open",
    });
    expect(await screen.findByText("Checked and enabled.")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Discord channel" })).toHaveAttribute(
      "aria-checked",
      "true",
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
      if (url === "/api/settings/nanobot-features/enable?name=discord") {
        return jsonResponse({
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
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

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

    fireEvent.click(screen.getByText("Advanced"));
    expect(screen.getByLabelText("Allowed channels")).toHaveValue("123, 456");
    expect(within(screen.getByRole("radiogroup", { name: "Group behavior" })).getByRole(
      "radio",
      { name: "All messages" },
    )).toHaveAttribute("aria-checked", "true");

    fireEvent.click(screen.getByRole("switch", { name: "Discord channel" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/settings/nanobot-features/enable?name=discord",
        expect.objectContaining({ headers: { Authorization: "Bearer tok" } }),
      ),
    );
  });

  it("links Telegram setup to BotFather without adding a docs link", async () => {
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
              setup: channelSetupContract("telegram"),
            }],
            enabled_count: 0,
          });
        }
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }),
    );

    renderSettingsView({ initialSection: "channels" });

    expect(await screen.findByRole("button", { name: "View Telegram settings" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open BotFather" })).toHaveAttribute(
      "href", "https://t.me/BotFather",
    );
    expect(screen.queryByRole("link", { name: "Open Telegram setup" })).not.toBeInTheDocument();
  });

  it("shows branded setup guide links for supported WebUI channels", async () => {
    const channels = [
      ["websocket", "WebSocket", "Open WebSocket setup"],
      ["telegram", "Telegram", "Open BotFather"],
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
              webui: ["feishu", "weixin"].includes(name) ? "webui/index.tsx" : "webui/index.ts",
              type: "channel",
              enabled: name === "websocket",
              installed: true,
              ready: name === "websocket",
              status: name === "websocket" ? "enabled" : "not_enabled",
              install_supported: true,
              requires_restart: true,
              ...(name === "telegram" ? { setup: channelSetupContract("telegram") } : {}),
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
        fireEvent.click(screen.getByRole("button", { name: "nanobot" }));
      }
      const guide = screen.getByRole("link", { name: guideLabel });
      expect(guide).toHaveAttribute("href", expect.stringMatching(/^https:\/\//));
      expect(guide.querySelector("span[aria-hidden] img, span[aria-hidden] svg")).not.toBeNull();
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
    const consent = screen.getByRole("radiogroup", { name: "Consent granted" });
    expect(within(consent).getByRole("radio", { name: "Not granted" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(within(consent).getByRole("radio", { name: "Granted" })).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("true")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "View Feishu settings" }));
    fireEvent.click(screen.getByRole("button", { name: "nanobot" }));
    fireEvent.click(screen.getByText("Advanced"));
    const region = screen.getByRole("radiogroup", { name: "Region" });
    expect(within(region).getByRole("radio", { name: "Feishu" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(within(region).getByRole("radio", { name: "Lark" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "View Matrix settings" }));
    fireEvent.click(screen.getByText("Advanced"));
    const matrixBehavior = screen.getByRole("radiogroup", { name: "Group behavior" });
    expect(within(matrixBehavior).getByRole("radio", { name: "All messages" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(within(matrixBehavior).getByRole("radio", { name: "Allowlist" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "View QQ settings" }));
    fireEvent.click(screen.getByText("Advanced"));
    const format = screen.getByRole("radiogroup", { name: "Message format" });
    expect(within(format).getByRole("radio", { name: "Plain text" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
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
    expect(fetchMock).not.toHaveBeenCalledWith(
      "/api/settings/nanobot-features/disable?name=websocket",
      expect.anything(),
    );
  });

  it("publishes the latest settings payload to the shell", async () => {
    const payload = settingsPayload();
    const onSettingsChange = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/settings") return jsonResponse(payload);
        if (url === "/api/settings/cli-apps") {
          return jsonResponse({ apps: [], installed_count: 0 });
        }
        if (url === "/api/settings/mcp-presets") {
          return jsonResponse({ presets: [], installed_count: 0 });
        }
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }),
    );

    renderSettingsView({ onSettingsChange });

    await waitFor(() => expect(onSettingsChange).toHaveBeenCalledWith(payload));
  });

  it("does not keep Apps loading while an empty CLI catalog refresh is pending", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/settings") return jsonResponse(settingsPayload());
        if (url === "/api/settings/cli-apps") {
          return jsonResponse({
            apps: [],
            installed_count: 0,
            catalog_updated_at: null,
            catalog_refresh_pending: true,
          });
        }
        if (url === "/api/settings/mcp-presets") {
          return jsonResponse({ presets: [], installed_count: 0 });
        }
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }),
    );

    renderSettingsView();

    expect(await screen.findByText("No tools match this view.")).toBeInTheDocument();
    expect(screen.queryByText("Loading Apps...")).not.toBeInTheDocument();
  });

  it("shows token activity on the overview", async () => {
    const payload: SettingsPayload = {
      ...settingsPayload(),
      usage: {
        days: [
          {
            date: "2026-06-03",
            prompt_tokens: 1200,
            completion_tokens: 300,
            cached_tokens: 500,
            total_tokens: 1500,
            requests: 2,
          },
        ],
        total_tokens: 1500,
        total_tokens_30d: 1500,
        total_tokens_365d: 1500,
        peak_day_tokens: 1500,
        current_streak_days: 1,
        longest_streak_days: 1,
        active_days_30d: 1,
        requests_30d: 2,
        updated_at: "2026-06-03T00:00:00Z",
      },
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/settings") return jsonResponse(payload);
        if (url === "/api/settings/cli-apps") {
          return jsonResponse({ apps: [], installed_count: 0 });
        }
        if (url === "/api/settings/mcp-presets") {
          return jsonResponse({ presets: [], installed_count: 0 });
        }
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }),
    );

    renderSettingsView({ initialSection: "overview" });

    expect(await screen.findByLabelText("Token activity")).toBeInTheDocument();
    expect(screen.getByText("Token Usage")).toBeInTheDocument();
    expect(screen.queryByText("Token activity")).not.toBeInTheDocument();
    expect(screen.queryByText("Total tokens")).not.toBeInTheDocument();
    expect(screen.queryByText("Peak tokens")).not.toBeInTheDocument();
  });

  it("aligns token activity days with the configured timezone", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-02T18:00:00Z"));
    const basePayload = settingsPayload();
    const payload: SettingsPayload = {
      ...basePayload,
      agent: {
        ...basePayload.agent,
        timezone: "Asia/Shanghai",
      },
      usage: {
        days: [
          {
            date: "2026-06-03",
            prompt_tokens: 1200,
            completion_tokens: 300,
            cached_tokens: 500,
            total_tokens: 1500,
            requests: 2,
          },
        ],
        total_tokens: 1500,
        total_tokens_30d: 1500,
        total_tokens_365d: 1500,
        peak_day_tokens: 1500,
        current_streak_days: 1,
        longest_streak_days: 1,
        active_days_30d: 1,
        requests_30d: 2,
        updated_at: "2026-06-03T00:00:00Z",
      },
    };
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));

    renderSettingsView({ initialSection: "overview", initialSettings: payload });

    expect(screen.getByLabelText("2026-06-03: 1.5K tokens, 2 requests")).toBeInTheDocument();
  });

  it("shows context window options in model settings", async () => {
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
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }),
    );

    renderSettingsView({ initialSection: "models" });

    expect(await screen.findByText("Context window")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "64K" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "200K" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "256K" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "500K" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "1M" })).toBeInTheDocument();
  });

  it("signs in to the xAI Grok provider", async () => {
    const base = settingsPayload();
    const xaiProvider = {
      name: "xai_grok",
      label: "xAI Grok",
      configured: false,
      auth_type: "oauth" as const,
      api_key_required: false,
      api_key_hint: null,
      api_base: null,
      default_api_base: "https://cli-chat-proxy.grok.com/v1",
      model_catalog: "builtin",
      oauth_account: null,
      oauth_expires_at: null,
      oauth_login_supported: true,
    };
    const payload: SettingsPayload = { ...base, providers: [xaiProvider] };
    const signedIn: SettingsPayload = {
      ...payload,
      providers: [{ ...xaiProvider, configured: true, oauth_account: "user@example.com" }],
    };
    const authorization = {
      status: "authorization_required",
      provider: "xai_grok",
      flow_id: "flow-123",
      authorization_url: "https://auth.x.ai/oauth2/authorize?state=test",
      expires_in: 600,
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(payload);
      if (url === "/api/settings/provider/oauth-login?provider=xai_grok") {
        return jsonResponse(authorization);
      }
      if (
        url ===
        "/api/settings/provider/oauth-login/complete?provider=xai_grok&flow_id=flow-123"
      ) {
        expect(init?.headers).toMatchObject({
          "X-Nanobot-OAuth-Code": "secret",
        });
        return jsonResponse(signedIn);
      }
      if (url === "/api/settings/cli-apps") {
        return jsonResponse({ apps: [], installed_count: 0 });
      }
      if (url === "/api/settings/mcp-presets") {
        return jsonResponse({ presets: [], installed_count: 0 });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    const popup = {
      opener: window,
      location: { href: "about:blank" },
      close: vi.fn(),
    };
    vi.stubGlobal("open", vi.fn(() => popup));

    renderSettingsView({ initialSection: "models", initialSettings: payload });

    const providerLabel = await screen.findByText("xAI Grok");
    fireEvent.click(providerLabel.closest("button")!);

    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/settings/provider/oauth-login?provider=xai_grok",
        expect.objectContaining({ headers: { Authorization: "Bearer tok" } }),
      ),
    );
    expect(popup.opener).toBeNull();
    expect(popup.location.href).toBe(authorization.authorization_url);

    expect(
      screen.getByText(
        "Complete sign-in in your browser. Nanobot usually finishes automatically; if it does not, paste the authorization code below.",
      ),
    ).toBeInTheDocument();
    const callbackInput = await screen.findByRole("textbox", {
      name: "Authorization code",
    });
    fireEvent.change(callbackInput, {
      target: { value: "secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Finish sign-in" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/settings/provider/oauth-login/complete?provider=xai_grok&flow_id=flow-123",
        expect.objectContaining({
          headers: expect.objectContaining({
            "X-Nanobot-OAuth-Code": "secret",
          }),
        }),
      ),
    );
    expect(await screen.findByText("Signed in as user@example.com")).toBeInTheDocument();
  });

  it("recognizes remote access before starting xAI Grok sign-in", async () => {
    const happyWindow = window as typeof window & {
      happyDOM: { setURL: (url: string) => void };
    };
    const originalUrl = window.location.href;
    happyWindow.happyDOM.setURL("http://203.0.113.10:18887/#/settings?section=models");

    try {
      const base = settingsPayload();
      const xaiProvider = {
        name: "xai_grok",
        label: "xAI Grok",
        configured: false,
        auth_type: "oauth" as const,
        api_key_required: false,
        api_key_hint: null,
        api_base: null,
        default_api_base: "https://cli-chat-proxy.grok.com/v1",
        model_catalog: "builtin",
        oauth_account: null,
        oauth_expires_at: null,
        oauth_login_supported: true,
      };
      const payload: SettingsPayload = { ...base, providers: [xaiProvider] };
      const authorization = {
        status: "authorization_required",
        provider: "xai_grok",
        flow_id: "flow-remote",
        authorization_url: "https://auth.x.ai/oauth2/authorize?state=remote",
        expires_in: 600,
      };
      const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/settings") return jsonResponse(payload);
        if (url === "/api/settings/provider/oauth-login?provider=xai_grok") {
          return jsonResponse(authorization);
        }
        if (
          url ===
          "/api/settings/provider/oauth-login/complete?provider=xai_grok&flow_id=flow-remote"
        ) {
          return jsonResponse({
            status: "pending",
            provider: "xai_grok",
            flow_id: "flow-remote",
          });
        }
        if (url === "/api/settings/cli-apps") {
          return jsonResponse({ apps: [], installed_count: 0 });
        }
        if (url === "/api/settings/mcp-presets") {
          return jsonResponse({ presets: [], installed_count: 0 });
        }
        return jsonResponse({});
      });
      vi.stubGlobal("fetch", fetchMock);
      const popup = {
        opener: window,
        location: { href: "about:blank" },
        close: vi.fn(),
      };
      const openMock = vi.fn(() => popup);
      vi.stubGlobal("open", openMock);

      renderSettingsView({ initialSection: "models", initialSettings: payload });

      fireEvent.click((await screen.findByText("xAI Grok")).closest("button")!);
      expect(
        screen.getByText(
          "Select Sign in to open xAI on your computer, then paste the authorization code shown after login.",
        ),
      ).toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
      const dialog = await screen.findByRole("dialog");

      expect(openMock).not.toHaveBeenCalled();
      expect(
        within(dialog).getByText(
          "Select Sign in to open xAI on your computer. After signing in, paste the authorization code shown by xAI below.",
        ),
      ).toBeInTheDocument();
      expect(
        within(dialog).queryByRole("textbox", { name: "xAI sign-in URL" }),
      ).not.toBeInTheDocument();
      expect(
        within(dialog).queryByRole("button", { name: "Copy" }),
      ).not.toBeInTheDocument();
      expect(
        within(dialog).getByRole("textbox", { name: "Authorization code" }),
      ).toBeInTheDocument();

      fireEvent.click(within(dialog).getByRole("button", { name: "Sign in" }));
      expect(openMock).toHaveBeenCalledWith(
        authorization.authorization_url,
        "_blank",
        "noopener,noreferrer",
      );
      expect(popup.opener).toBeNull();
    } finally {
      happyWindow.happyDOM.setURL(originalUrl);
    }
  });

  it("saves scoped proxies for xAI and OpenAI Codex OAuth providers", async () => {
    const base = settingsPayload();
    const providers: SettingsPayload["providers"] = [
      {
        name: "xai_grok",
        label: "xAI Grok",
        configured: false,
        auth_type: "oauth",
        api_key_required: false,
        api_key_hint: null,
        api_base: null,
        default_api_base: "https://cli-chat-proxy.grok.com/v1",
        model_catalog: "builtin",
        oauth_account: null,
        oauth_expires_at: null,
        oauth_login_supported: true,
        proxy: "http://127.0.0.1:7000",
      },
      {
        name: "openai_codex",
        label: "OpenAI Codex",
        configured: false,
        auth_type: "oauth",
        api_key_required: false,
        api_key_hint: null,
        api_base: null,
        default_api_base: "https://chatgpt.com/backend-api",
        model_catalog: "builtin",
        oauth_account: null,
        oauth_expires_at: null,
        oauth_login_supported: true,
        proxy: null,
      },
    ];
    let payload: SettingsPayload = { ...base, providers };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(payload);
      if (url.startsWith("/api/settings/provider/update?")) {
        const query = new URLSearchParams(url.split("?")[1]);
        const providerName = query.get("provider");
        const proxy = query.get("proxy");
        payload = {
          ...payload,
          providers: payload.providers.map((provider) =>
            provider.name === providerName ? { ...provider, proxy } : provider,
          ),
        };
        return jsonResponse(payload);
      }
      if (url === "/api/settings/cli-apps") {
        return jsonResponse({ apps: [], installed_count: 0 });
      }
      if (url === "/api/settings/mcp-presets") {
        return jsonResponse({ presets: [], installed_count: 0 });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSettingsView({ initialSection: "models", initialSettings: payload });

    fireEvent.click((await screen.findByText("xAI Grok")).closest("button")!);
    const xaiProxy = screen.getByLabelText("Network proxy");
    expect(xaiProxy).toHaveValue("http://127.0.0.1:7000");
    fireEvent.change(xaiProxy, { target: { value: "http://127.0.0.1:7890" } });
    expect(screen.getByRole("button", { name: "Sign in" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Sign in" })).toHaveAttribute(
      "title",
      "Save proxy changes before signing in.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Save proxy" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/settings/provider/update?provider=xai_grok&proxy=http%3A%2F%2F127.0.0.1%3A7890",
        expect.objectContaining({ headers: { Authorization: "Bearer tok" } }),
      ),
    );
    await waitFor(() => expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled());

    fireEvent.click(screen.getByText("OpenAI Codex").closest("button")!);
    const codexProxy = screen.getByLabelText("Network proxy");
    expect(codexProxy).toHaveValue("");
    fireEvent.change(codexProxy, { target: { value: "http://proxy.example:8080" } });
    fireEvent.click(screen.getByRole("button", { name: "Save proxy" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/settings/provider/update?provider=openai_codex&proxy=http%3A%2F%2Fproxy.example%3A8080",
        expect.objectContaining({ headers: { Authorization: "Bearer tok" } }),
      ),
    );
  });

  it("selects image models from provider-specific options", async () => {
    const base = settingsPayload();
    const payload: SettingsPayload = {
      ...base,
      image_generation: {
        ...base.image_generation,
        providers: [
          {
            name: "openrouter",
            label: "OpenRouter",
            configured: true,
            models: ["openai/gpt-5.4-image-2"],
            default_model: "openai/gpt-5.4-image-2",
          },
          {
            name: "gemini",
            label: "Gemini",
            configured: true,
            models: ["gemini-2.5-flash-image", "imagen-4.0-generate-001"],
            default_model: "gemini-2.5-flash-image",
          },
          {
            name: "custom",
            label: "Custom",
            configured: true,
            models: [],
            default_model: null,
          },
        ],
      },
    };

    renderSettingsView({ initialSection: "image", initialSettings: payload });

    expect(screen.queryByDisplayValue("openai/gpt-5.4-image-2")).not.toBeInTheDocument();
    fireEvent.pointerDown(screen.getByRole("button", { name: "OpenRouter" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Gemini" }));

    expect(await screen.findByRole("button", { name: "gemini-2.5-flash-image" })).toBeInTheDocument();
    fireEvent.pointerDown(screen.getByRole("button", { name: "gemini-2.5-flash-image" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "imagen-4.0-generate-001" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "imagen-4.0-generate-001" })).toBeInTheDocument(),
    );

    fireEvent.pointerDown(screen.getByRole("button", { name: "imagen-4.0-generate-001" }));
    const modelInput = await screen.findByRole("textbox", { name: "Search or type model ID" });
    fireEvent.change(modelInput, { target: { value: "imagen-5-preview" } });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Use “imagen-5-preview”" }));
    expect(await screen.findByRole("button", { name: "imagen-5-preview" })).toBeInTheDocument();

    fireEvent.pointerDown(screen.getByRole("button", { name: "Gemini" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Custom" }));
    expect(screen.getByRole("button", { name: "imagen-5-preview" })).toBeInTheDocument();

    fireEvent.pointerDown(screen.getByRole("button", { name: "imagen-5-preview" }));
    const customProviderInput = await screen.findByRole("textbox", {
      name: "Search or type model ID",
    });
    fireEvent.change(customProviderInput, { target: { value: "private/image-v2" } });
    fireEvent.keyDown(customProviderInput, { key: "Enter" });
    expect(await screen.findByRole("button", { name: "private/image-v2" })).toBeInTheDocument();
  });

  it("keeps the default model distinct from the active named configuration", async () => {
    const base = settingsPayload();
    const payload: SettingsPayload = {
      ...base,
      agent: {
        ...base.agent,
        model: "MiniMax-M3",
        provider: "minimax_anthropic",
        resolved_provider: "minimax_anthropic",
        model_preset: "fast",
      },
      model_presets: [
        {
          ...base.model_presets[0],
          active: false,
          model: "openai-codex/gpt-5.5",
          provider: "openai_codex",
        },
        {
          ...base.model_presets[0],
          name: "fast",
          label: "fast",
          active: true,
          is_default: false,
          model: "MiniMax-M3",
          provider: "minimax_anthropic",
        },
      ],
      providers: [
        {
          name: "openai_codex",
          label: "OpenAI Codex",
          configured: true,
          auth_type: "oauth",
          api_key_required: false,
          api_key_hint: null,
          api_base: null,
          default_api_base: null,
          oauth_account: "acct-test",
          oauth_expires_at: null,
          oauth_login_supported: true,
        },
        {
          name: "minimax_anthropic",
          label: "MiniMax (Anthropic)",
          configured: true,
          auth_type: "api_key",
          api_key_required: true,
          api_key_hint: "sk-...",
          api_base: "https://api.minimax.io/anthropic",
          default_api_base: "https://api.minimax.io/anthropic",
        },
      ],
    };
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));

    renderSettingsView({ initialSection: "models", initialSettings: payload });

    const picker = await screen.findByRole("button", { name: "Current configuration" });
    expect(picker).toHaveTextContent("MiniMax-M3");
    expect(picker).toHaveTextContent("fast");
    fireEvent.pointerDown(picker);

    const defaultOption = (await screen.findAllByRole("menuitem")).find((item) =>
      item.textContent?.includes("Default"),
    );
    if (!defaultOption) throw new Error("default configuration was not found");
    expect(defaultOption).toHaveTextContent("openai-codex/gpt-5.5");
    expect(defaultOption).toHaveTextContent("OpenAI Codex · Default");
    expect(defaultOption).not.toHaveTextContent("MiniMax-M3");
  });

  it("uses the resolved provider row for auto dynamic providers without api keys", async () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));

    renderSettingsView({
      initialSection: "models",
      initialSettings: autoDynamicProviderPayload({
        configured: true,
        hasApiKey: false,
        apiBase: "https://proxy.example.test/v1",
        apiKeyHint: null,
      }),
    });

    const configurationButton = await screen.findByRole("button", {
      name: "Current configuration",
    });
    expect(configurationButton).toHaveTextContent("companyProxy/gpt-4o");
    expect(configurationButton).toHaveTextContent("Company Proxy");
    expect(configurationButton).not.toHaveTextContent("Not configured");
  });

  it("does not treat auto dynamic provider api keys as configured without apiBase", async () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));

    renderSettingsView({
      initialSection: "models",
      initialSettings: autoDynamicProviderPayload({
        configured: false,
        hasApiKey: true,
        apiBase: null,
        apiKeyHint: "sk-...",
      }),
    });

    const configurationButton = await screen.findByRole("button", {
      name: "Current configuration",
    });
    expect(configurationButton).toHaveTextContent("Not configured");
    expect(configurationButton).toHaveTextContent("Company Proxy · companyProxy/gpt-4o");
  });

  it("marks the current model as unconfigured when its provider needs setup", async () => {
    const payload: SettingsPayload = {
      ...settingsPayload(),
      agent: {
        ...settingsPayload().agent,
        model: "openai-codex/gpt-5.1-codex",
        provider: "openai_codex",
        resolved_provider: "openai_codex",
        has_api_key: false,
      },
      model_presets: [
        {
          ...settingsPayload().model_presets[0],
          model: "openai-codex/gpt-5.1-codex",
          provider: "openai_codex",
        },
      ],
      providers: [
        {
          name: "openai_codex",
          label: "OpenAI Codex",
          configured: false,
          auth_type: "oauth",
          api_key_required: false,
          api_key_hint: null,
          api_base: null,
          default_api_base: null,
          oauth_account: null,
          oauth_expires_at: null,
          oauth_login_supported: true,
        },
      ],
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/settings") return jsonResponse(payload);
        if (url === "/api/settings/cli-apps") {
          return jsonResponse({ apps: [], installed_count: 0 });
        }
        if (url === "/api/settings/mcp-presets") {
          return jsonResponse({ presets: [], installed_count: 0 });
        }
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }),
    );

    renderSettingsView({ initialSection: "models" });

    const configurationButton = await screen.findByRole("button", {
      name: "Current configuration",
    });
    expect(configurationButton).toHaveTextContent("Not configured");
    expect(configurationButton).toHaveTextContent("OpenAI Codex · openai-codex/gpt-5.1-codex");
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });

  it("keeps unsigned OAuth providers out of the active provider picker", async () => {
    const payload: SettingsPayload = {
      ...settingsPayload(),
      agent: {
        ...settingsPayload().agent,
        model: "deepseek-chat",
        provider: "deepseek",
        resolved_provider: "deepseek",
      },
      model_presets: [
        {
          ...settingsPayload().model_presets[0],
          model: "deepseek-chat",
          provider: "deepseek",
        },
      ],
      providers: [
        {
          name: "deepseek",
          label: "DeepSeek",
          configured: true,
          auth_type: "api_key",
          api_key_required: true,
          api_key_hint: "sk-...",
          api_base: "https://api.deepseek.com",
          default_api_base: "https://api.deepseek.com",
        },
        {
          name: "openai_codex",
          label: "OpenAI Codex",
          configured: false,
          auth_type: "oauth",
          api_key_required: false,
          api_key_hint: null,
          api_base: null,
          default_api_base: null,
          oauth_account: null,
          oauth_expires_at: null,
          oauth_login_supported: true,
        },
        {
          name: "github_copilot",
          label: "GitHub Copilot",
          configured: false,
          auth_type: "oauth",
          api_key_required: false,
          api_key_hint: null,
          api_base: null,
          default_api_base: "https://api.githubcopilot.com",
          oauth_account: null,
          oauth_expires_at: null,
          oauth_login_supported: true,
        },
      ],
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/settings") return jsonResponse(payload);
        if (url === "/api/settings/cli-apps") {
          return jsonResponse({ apps: [], installed_count: 0 });
        }
        if (url === "/api/settings/mcp-presets") {
          return jsonResponse({ presets: [], installed_count: 0 });
        }
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }),
    );

    renderSettingsView({ initialSection: "models" });

    const deepseekButtons = await screen.findAllByRole("button", { name: /DeepSeek/ });
    const providerPicker = deepseekButtons.find(
      (button) => button.getAttribute("aria-haspopup") === "menu",
    );
    if (!providerPicker) throw new Error("provider picker was not found");
    fireEvent.pointerDown(providerPicker);

    expect(await screen.findByRole("menuitem", { name: /DeepSeek/ })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: /OpenAI Codex/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: /GitHub Copilot/ })).not.toBeInTheDocument();
  });

  it("does not fetch model lists for unsigned OAuth providers", async () => {
    const payload: SettingsPayload = {
      ...settingsPayload(),
      agent: {
        ...settingsPayload().agent,
        model: "",
        provider: "openai_codex",
        resolved_provider: "openai_codex",
      },
      model_presets: [
        {
          ...settingsPayload().model_presets[0],
          model: "",
          provider: "openai_codex",
        },
      ],
      providers: [
        {
          name: "openai_codex",
          label: "OpenAI Codex",
          configured: false,
          auth_type: "oauth",
          api_key_required: false,
          api_key_hint: null,
          api_base: null,
          default_api_base: null,
          oauth_account: null,
          oauth_expires_at: null,
          oauth_login_supported: true,
        },
        {
          name: "github_copilot",
          label: "GitHub Copilot",
          configured: false,
          auth_type: "oauth",
          api_key_required: false,
          api_key_hint: null,
          api_base: null,
          default_api_base: "https://api.githubcopilot.com",
          oauth_account: null,
          oauth_expires_at: null,
          oauth_login_supported: true,
        },
      ],
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(payload);
      if (url === "/api/settings/cli-apps") {
        return jsonResponse({ apps: [], installed_count: 0 });
      }
      if (url === "/api/settings/mcp-presets") {
        return jsonResponse({ presets: [], installed_count: 0 });
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSettingsView({ initialSection: "models" });

    fireEvent.pointerDown(await screen.findByRole("button", { name: /Select model/i }));
    expect(
      await screen.findByText("Configure this provider before loading models."),
    ).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).startsWith("/api/settings/provider-models"),
      ),
    ).toBe(false);
  });

  it("prefills manual model ids for configured OAuth providers", async () => {
    const payload: SettingsPayload = {
      ...settingsPayload(),
      agent: {
        ...settingsPayload().agent,
        model: "open-codex/gpt-5.5",
        provider: "openai_codex",
        resolved_provider: "openai_codex",
      },
      model_presets: [
        {
          ...settingsPayload().model_presets[0],
          model: "open-codex/gpt-5.5",
          provider: "openai_codex",
        },
      ],
      providers: [
        {
          name: "openai_codex",
          label: "OpenAI Codex",
          configured: true,
          auth_type: "oauth",
          api_key_required: false,
          api_key_hint: null,
          api_base: null,
          default_api_base: null,
          oauth_account: "acct-test",
          oauth_expires_at: null,
          oauth_login_supported: true,
        },
      ],
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(payload);
      if (url === "/api/settings/cli-apps") {
        return jsonResponse({ apps: [], installed_count: 0 });
      }
      if (url === "/api/settings/mcp-presets") {
        return jsonResponse({ presets: [], installed_count: 0 });
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSettingsView({ initialSection: "models" });

    const modelButtons = await screen.findAllByRole("button", { name: /open-codex\/gpt-5\.5/i });
    fireEvent.pointerDown(modelButtons[modelButtons.length - 1]);
    const input = (await screen.findByPlaceholderText("Search or type model ID")) as HTMLInputElement;
    expect(input.value).toBe("open-codex/gpt-5.5");

    fireEvent.change(input, { target: { value: "openai-codex/gpt-5.5" } });
    expect(await screen.findByText("“openai-codex/gpt-5.5”")).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).startsWith("/api/settings/provider-models"),
      ),
    ).toBe(false);
  });

  it("loads curated models for configured OAuth providers", async () => {
    const base = settingsPayload();
    const payload: SettingsPayload = {
      ...base,
      agent: {
        ...base.agent,
        model: "openai-codex/gpt-5.5",
        provider: "openai_codex",
        resolved_provider: "openai_codex",
      },
      model_presets: [
        {
          ...base.model_presets[0],
          model: "openai-codex/gpt-5.5",
          provider: "openai_codex",
        },
      ],
      providers: [
        {
          name: "openai_codex",
          label: "OpenAI Codex",
          configured: true,
          auth_type: "oauth",
          api_key_required: false,
          api_key_hint: null,
          api_base: null,
          default_api_base: "https://chatgpt.com/backend-api",
          model_catalog: "builtin",
          oauth_account: "acct-test",
          oauth_expires_at: null,
          oauth_login_supported: true,
        },
      ],
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings/provider-models?provider=openai_codex") {
        return jsonResponse({
          provider: "openai_codex",
          label: "OpenAI Codex",
          status: "available",
          catalog_kind: "builtin",
          models: [
            {
              id: "openai-codex/gpt-5.6-sol",
              label: "GPT-5.6-Sol",
              description: "Latest frontier agentic coding model.",
              owned_by: "OpenAI Codex",
              context_window: 372000,
            },
          ],
          model_count: 1,
          fetched_at: 1,
        });
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSettingsView({ initialSection: "models", initialSettings: payload });

    const modelButtons = await screen.findAllByRole("button", {
      name: /openai-codex\/gpt-5\.5/i,
    });
    fireEvent.pointerDown(modelButtons[modelButtons.length - 1]);

    expect(await screen.findByText("GPT-5.6-Sol")).toBeInTheDocument();
    expect(screen.getByText(/Latest frontier agentic coding model\./)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/settings/provider-models?provider=openai_codex",
      expect.objectContaining({ headers: { Authorization: "Bearer tok" } }),
    );
  });

  it("can close the new configuration dialog without trapping the settings page", async () => {
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
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }),
    );

    renderSettingsView({ initialSection: "models" });

    const configurationButton = await screen.findByRole("button", { name: "Current configuration" });
    fireEvent.pointerDown(configurationButton!);
    fireEvent.click(await screen.findByText("Add configuration"));

    expect(await screen.findByRole("heading", { name: "New model configuration" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "New model configuration" })).not.toBeInTheDocument(),
    );
    expect(document.body.style.pointerEvents).not.toBe("none");

    fireEvent.pointerDown(configurationButton!);
    expect(await screen.findByText("Add configuration")).toBeInTheDocument();
  });

  it("loads provider models and lets users choose one without typing the id manually", async () => {
    const payload: SettingsPayload = {
      ...settingsPayload(),
      agent: {
        ...settingsPayload().agent,
        model: "deepseek-chat",
        provider: "deepseek",
        resolved_provider: "deepseek",
      },
      model_presets: [
        {
          ...settingsPayload().model_presets[0],
          model: "deepseek-chat",
          provider: "deepseek",
        },
      ],
      providers: [
        {
          name: "deepseek",
          label: "DeepSeek",
          configured: true,
          auth_type: "api_key",
          api_key_required: true,
          api_key_hint: "sk-...",
          api_base: "https://api.deepseek.com",
          default_api_base: "https://api.deepseek.com",
        },
      ],
    };
    const updatedPayload: SettingsPayload = {
      ...payload,
      agent: {
        ...payload.agent,
        model: "deepseek-reasoner",
      },
      model_presets: [
        {
          ...payload.model_presets[0],
          model: "deepseek-reasoner",
        },
      ],
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(payload);
      if (url === "/api/settings/cli-apps") {
        return jsonResponse({ apps: [], installed_count: 0 });
      }
      if (url === "/api/settings/mcp-presets") {
        return jsonResponse({ presets: [], installed_count: 0 });
      }
      if (url === "/api/settings/provider-models?provider=deepseek") {
        return jsonResponse({
          provider: "deepseek",
          label: "DeepSeek",
          status: "available",
          catalog_kind: "official",
          models: [
            { id: "deepseek-chat", owned_by: "deepseek", context_window: 65536 },
            { id: "deepseek-reasoner", owned_by: "deepseek", context_window: 65536 },
          ],
          model_count: 2,
          fetched_at: 1,
        });
      }
      if (url === "/api/settings/update?model_preset=default&model=deepseek-reasoner") {
        return jsonResponse(updatedPayload);
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSettingsView({ initialSection: "models" });

    const modelButtons = await screen.findAllByRole("button", { name: /deepseek-chat/i });
    fireEvent.pointerDown(modelButtons[modelButtons.length - 1]);
    await screen.findByText("deepseek-reasoner");
    fireEvent.click(screen.getAllByText("deepseek-reasoner")[0]);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/settings/provider-models?provider=deepseek",
        expect.objectContaining({
          headers: { Authorization: "Bearer tok" },
        }),
      ),
    );
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/settings/update?model_preset=default&model=deepseek-reasoner",
        expect.objectContaining({
          headers: { Authorization: "Bearer tok" },
        }),
      ),
    );
  });

  it("saves network safety without exposing technical SSRF copy", async () => {
    const payload = settingsPayload();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(payload);
      if (url === "/api/settings/cli-apps") {
        return jsonResponse({ apps: [], installed_count: 0 });
      }
      if (url === "/api/settings/mcp-presets") {
        return jsonResponse({ presets: [], installed_count: 0 });
      }
      if (url === "/api/settings/network-safety/update?webui_allow_local_service_access=false&webui_default_access_mode=default") {
        return jsonResponse({
          ...payload,
          advanced: { ...payload.advanced, webui_allow_local_service_access: false },
          requires_restart: true,
          restart_required_sections: ["runtime"],
        });
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSettingsView({ initialSection: "advanced" });

    expect(await screen.findByText("Web safety")).toBeInTheDocument();
    expect(screen.queryByText(/SSRF/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Private Service Protection")).not.toBeInTheDocument();
    expect(screen.getByText("Default access")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Restricted" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Default Permission" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Full Access" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("switch", { name: "Local services" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/settings/network-safety/update?webui_allow_local_service_access=false&webui_default_access_mode=default",
        expect.objectContaining({
          headers: { Authorization: "Bearer tok" },
        }),
      ),
    );
  });

  it("saves optional-key web search providers without an API key", async () => {
    const payload = {
      ...settingsPayload(),
      web_search: {
        ...settingsPayload().web_search,
        provider: "duckduckgo",
        providers: [
          { name: "duckduckgo", label: "DuckDuckGo", credential: "none" as const },
          { name: "keenable", label: "Keenable", credential: "optional_api_key" as const },
        ],
      },
    };
    const updatedPayload = {
      ...payload,
      web_search: {
        ...payload.web_search,
        provider: "keenable",
      },
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(payload);
      if (url === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
      if (url === "/api/settings/mcp-presets") return jsonResponse({ presets: [], installed_count: 0 });
      if (
        url ===
        "/api/settings/web-search/update?provider=keenable&max_results=5&timeout=30&use_jina_reader=true"
      ) {
        return jsonResponse(updatedPayload);
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSettingsView({ initialSection: "browser" });

    fireEvent.pointerDown(await screen.findByRole("button", { name: /DuckDuckGo/ }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Keenable" }));
    const saveButton = screen
      .getAllByRole("button", { name: "Save" })
      .find((button) => !(button as HTMLButtonElement).disabled);
    if (!saveButton) throw new Error("enabled Save button was not found");
    fireEvent.click(saveButton);

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/settings/web-search/update?provider=keenable&max_results=5&timeout=30&use_jina_reader=true",
        expect.objectContaining({
          headers: { Authorization: "Bearer tok" },
        }),
      ),
    );
  });

  it("uses native host safety copy on the native surface", async () => {
    const payload = {
      ...settingsPayload(),
      surface: "native" as const,
      runtime_surface: "native" as const,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/settings") return jsonResponse(payload);
        if (url === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
        if (url === "/api/settings/mcp-presets") return jsonResponse({ presets: [], installed_count: 0 });
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }),
    );

    renderSettingsView({ initialSection: "advanced" });

    expect(await screen.findByText("App safety")).toBeInTheDocument();
    expect(screen.queryByText("Web safety")).not.toBeInTheDocument();
    expect(screen.getByText("Allow Full Access shell commands to reach services on this Mac.")).toBeInTheDocument();
  });

  it("refreshes settings with a fresh token after native engine restart", async () => {
    const payload = {
      ...settingsPayload(),
      surface: "native" as const,
      runtime_surface: "native" as const,
      runtime_capabilities: {
        can_restart_engine: true,
        can_pick_folder: true,
        can_open_logs: true,
        can_export_diagnostics: true,
      },
    };
    const restartedPayload = {
      ...payload,
      advanced: { ...payload.advanced, webui_allow_local_service_access: false },
      requires_restart: true,
      restart_required_sections: ["runtime"],
    };
    const refreshedPayload = {
      ...restartedPayload,
      requires_restart: false,
      restart_required_sections: [],
    };
    const restartEngine = vi.fn(async () => "fresh-token");
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const auth = (init?.headers as Record<string, string> | undefined)?.Authorization;
      if (url === "/api/settings" && auth === "Bearer fresh-token") {
        return jsonResponse(refreshedPayload);
      }
      if (url === "/api/settings") return jsonResponse(payload);
      if (url === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
      if (url === "/api/settings/mcp-presets") return jsonResponse({ presets: [], installed_count: 0 });
      if (url === "/api/settings/network-safety/update?webui_allow_local_service_access=false&webui_default_access_mode=default") {
        return jsonResponse(restartedPayload);
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSettingsView({
      initialSection: "advanced",
      onNativeEngineRestart: restartEngine,
    });

    expect(await screen.findByText("App safety")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("switch", { name: "Local services" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(restartEngine).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/settings",
        expect.objectContaining({
          headers: { Authorization: "Bearer fresh-token" },
        }),
      ),
    );
  });
});
