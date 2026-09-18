import { channelUiContribution } from "@/channel-plugins/registry";
import type { ChannelSetupContract, ChannelSetupContractField, NanobotFeatureInfo } from "@/lib/types";
import {
  fireEvent,
  installSettingsViewTestHooks,
  jsonResponse,
  renderSettingsView,
  requestMutationMock,
  screen,
  settingsPayload,
  waitFor,
} from "@/tests/settings-test-utils";

import { linearManifestUrl } from "../../webui/manifest";

const linearSetup: ChannelSetupContract = {
  fields: [
    field("clientId", "string", true),
    field("clientSecret", "secret", true),
    field("webhookSigningSecret", "secret", true),
    field("publicBaseUrl", "string", true),
    field("host", "string", false, "0.0.0.0"),
    field("port", "int", false, "3979"),
    field("webhookPath", "string", false, "/linear/webhook"),
    field("oauthCallbackPath", "string", false, "/linear/oauth/callback"),
    field("allowFrom", "list"),
  ],
};

const linearFeature: NanobotFeatureInfo = {
  name: "linear",
  display_name: "Linear",
  webui: "webui/index.tsx",
  type: "channel",
  enabled: false,
  configured: false,
  installed: true,
  ready: false,
  status: "not_enabled",
  install_supported: true,
  requires_restart: false,
  setup: linearSetup,
};

describe("Linear channel UI", () => {
  installSettingsViewTestHooks();

  it("owns its complete setup panel inside the channel package", () => {
    const contribution = channelUiContribution("linear", "webui/index.tsx");

    expect(contribution?.Panel).toBeDefined();
    expect(contribution?.ConnectFlow).toBeUndefined();
  });

  it("creates a private mention-only Agent app manifest with exact callback routes", () => {
    const url = new URL(
      linearManifestUrl(
        "https://nanobot.example.com",
        "/linear/webhook",
        "/linear/oauth/callback",
      ),
    );
    const manifest = JSON.parse(url.searchParams.get("manifest") ?? "{}") as {
      distribution?: string;
      oauth?: { redirect_uris?: string[] };
      webhook?: { url?: string; resourceTypes?: string[] };
    };

    expect(url.origin + url.pathname).toBe(
      "https://linear.app/settings/api/applications/new",
    );
    expect(manifest.distribution).toBe("private");
    expect(manifest.oauth?.redirect_uris).toEqual([
      "https://nanobot.example.com/linear/oauth/callback",
    ]);
    expect(manifest.webhook?.url).toBe(
      "https://nanobot.example.com/linear/webhook",
    );
    expect(manifest.webhook?.resourceTypes).toEqual([
      "AgentSessionEvent",
      "PermissionChange",
      "OAuthAuthorization",
    ]);
    expect(manifest.webhook?.resourceTypes).not.toContain("Comment");
  });

  it("saves a public URL before OAuth credentials and reveals the app manifest", async () => {
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
          return jsonResponse({ features: [linearFeature], enabled_count: 0 });
        }
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }),
    );
    requestMutationMock.mockResolvedValueOnce({
        name: "linear",
        saved: true,
        saved_keys: ["channels.linear.publicBaseUrl"],
        nanobot_features: {
          features: [{
            ...linearFeature,
            config_values: {
              "channels.linear.publicBaseUrl": "https://nanobot.example.com",
              "channels.linear.host": "0.0.0.0",
              "channels.linear.port": "3979",
              "channels.linear.webhookPath": "/linear/webhook",
              "channels.linear.oauthCallbackPath": "/linear/oauth/callback",
            },
            configured_fields: ["channels.linear.publicBaseUrl"],
          }],
          enabled_count: 0,
          requires_restart: false,
        },
      });

    renderSettingsView({ initialSection: "channels" });

    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    expect(await screen.findByRole("button", { name: "Connect Linear" })).toBeDisabled();
    fireEvent.change(await screen.findByPlaceholderText("https://nanobot.example.com"), {
      target: { value: "https://nanobot.example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Save/ }));

    await waitFor(() =>
      expect(requestMutationMock).toHaveBeenCalledWith(
        "settings.channel.configure",
        expect.objectContaining({
          name: "linear",
          values: expect.objectContaining({
            "channels.linear.publicBaseUrl": "https://nanobot.example.com",
          }),
        }),
        150_000,
      ),
    );
    expect(
      await screen.findByText("Settings saved."),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("link", { name: "Create prefilled Linear app" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Connect Linear" })).toBeDisabled();
  });

  it("preserves saved secrets and gates authorization on saving edited settings", async () => {
    const feature = savedFeature();
    mockFeature(feature);
    requestMutationMock.mockResolvedValueOnce({
      saved: true,
      nanobot_features: {
        features: [{ ...feature, config_values: {
          ...feature.config_values, "channels.linear.port": "3980",
        } }],
        enabled_count: 0,
      },
    });
    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    expect(await screen.findByRole("button", { name: "Connect Linear" })).toBeEnabled();
    expect(screen.queryByRole("spinbutton", { name: "Listen port" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Advanced" }));
    fireEvent.change(screen.getByRole("spinbutton", { name: "Listen port" }), {
      target: { value: "3980" },
    });
    expect(screen.getByRole("button", { name: "Connect Linear" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /^Save/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Connect Linear" })).toBeEnabled());
    const params = requestMutationMock.mock.calls[0][1] as { values: Record<string, unknown> };
    expect(params.values["channels.linear.port"]).toBe("3980");
    expect(params.values).not.toHaveProperty("channels.linear.clientSecret");
    expect(params.values).not.toHaveProperty("channels.linear.webhookSigningSecret");
  });

  it("keeps an unsaved draft when saving fails without enabling the channel", async () => {
    mockFeature(savedFeature());
    requestMutationMock.mockRejectedValueOnce(new Error("Unable to save settings"));
    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    fireEvent.change(await screen.findByRole("textbox", { name: "OAuth client ID" }), {
      target: { value: "replacement-client" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Save/ }));
    expect(await screen.findByText("Unable to save settings")).toBeVisible();
    expect(screen.getByRole("textbox", { name: "OAuth client ID" })).toHaveValue("replacement-client");
    expect(screen.getByRole("button", { name: "Connect Linear" })).toBeDisabled();
    expect(requestMutationMock).toHaveBeenCalledTimes(1);
    expect(requestMutationMock.mock.calls[0][1]).not.toHaveProperty("enable");
  });

  it("shows the OAuth handoff and cancels a pending authorization", async () => {
    mockFeature(savedFeature());
    requestMutationMock
      .mockResolvedValueOnce({ session_id: "linear-oauth", status: "pending",
        qr_url: "https://linear.app/oauth/authorize?client_id=test", interval_ms: 5000 })
      .mockResolvedValueOnce({ session_id: "linear-oauth", status: "cancelled" });
    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    fireEvent.click(await screen.findByRole("button", { name: "Connect Linear" }));
    expect(await screen.findByRole("link", { name: "Continue in Linear" })).toHaveAttribute(
      "href", "https://linear.app/oauth/authorize?client_id=test",
    );
    expect(screen.getByRole("textbox", { name: "OAuth client ID" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^Save/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(await screen.findByText("Authorization stopped.")).toBeVisible();
    expect(screen.getByRole("textbox", { name: "OAuth client ID" })).toBeEnabled();
    expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.channel.connect.cancel", { channel: "linear", session_id: "linear-oauth" }, 20_000,
    );
  });
});

function savedFeature(): NanobotFeatureInfo {
  return {
    ...linearFeature,
    configured_fields: linearSetup.fields.filter((field) => field.required).map((field) => field.key),
    config_values: {
      "channels.linear.publicBaseUrl": "https://nanobot.example.com",
      "channels.linear.clientId": "client-id",
      "channels.linear.host": "0.0.0.0",
      "channels.linear.port": "3979",
      "channels.linear.webhookPath": "/linear/webhook",
      "channels.linear.oauthCallbackPath": "/linear/oauth/callback",
    },
  };
}

function mockFeature(feature: NanobotFeatureInfo) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === "/api/settings") return jsonResponse(settingsPayload());
    if (url === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
    if (url === "/api/settings/mcp-presets") return jsonResponse({ presets: [], installed_count: 0 });
    if (url === "/api/settings/nanobot-features") return jsonResponse({ features: [feature], enabled_count: 0 });
    return { ok: false, status: 404, json: async () => ({}) } as Response;
  }));
}

function field(
  name: string,
  kind: ChannelSetupContractField["kind"],
  required = false,
  defaultValue?: string,
): ChannelSetupContractField {
  return {
    key: `channels.linear.${name}`,
    field: name,
    kind,
    choices: [],
    required,
    ...(defaultValue === undefined ? {} : { default_value: defaultValue }),
  };
}
