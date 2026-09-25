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
  within,
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
    field("showReasoning", "bool", false, "true"),
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

  it("creates a private mentionable and assignable Agent app manifest with exact routes", () => {
    const url = new URL(
      linearManifestUrl(
        "https://nanobot.example.com",
        "/linear/webhook",
        "/linear/oauth/callback",
      ),
    );
    const manifest = JSON.parse(url.searchParams.get("manifest") ?? "{}") as {
      distribution?: string;
      display?: { iconUrl?: string; description?: string };
      oauth?: { client_uri?: string; redirect_uris?: string[] };
      webhook?: { url?: string; resourceTypes?: string[] };
    };

    expect(url.origin + url.pathname).toBe(
      "https://linear.app/settings/api/applications/new",
    );
    expect(manifest.distribution).toBe("private");
    expect(manifest.display?.description).toContain("delegate issues");
    expect(manifest.display?.iconUrl).toContain("nanobot_logo.png");
    expect(manifest.oauth?.client_uri).toBe("https://github.com/HKUDS/nanobot");
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

  it("prompts for the missing public URL and focuses its field after dismissal", async () => {
    mockFeature(linearFeature);
    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    const createApp = await screen.findByRole("button", { name: "Create Linear app" });
    expect(createApp).toBeEnabled();
    fireEvent.click(createApp);
    const prompt = await screen.findByRole("alertdialog", { name: "Public HTTPS URL" });
    expect(prompt).toHaveTextContent("Enter a public HTTPS URL to create a Linear app.");
    expect(requestMutationMock).not.toHaveBeenCalled();
    fireEvent.click(within(prompt).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(screen.getByRole("textbox", { name: "Public HTTPS URL" })).toHaveFocus();
    expect(screen.getByRole("dialog")).toBeVisible();
  });

  it("opens the Linear MCP connection settings without starting authorization", async () => {
    mockFeature(savedFeature());
    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    await screen.findByRole("textbox", { name: "OAuth client ID" });
    expect(screen.queryByText(/Use Member access to approve teammates/)).not.toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("button", { name: "Help" }), { key: "ArrowDown" });
    expect(await screen.findByText(/Use Member access to approve teammates/)).toBeVisible();
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    fireEvent.click(await screen.findByRole("button", { name: "Configure Linear MCP" }));
    const dialog = await screen.findByRole("dialog", { name: "Linear" });
    expect(within(dialog).getByRole("button", { name: "Connect" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Configure Linear MCP" })).not.toBeInTheDocument();
    expect(requestMutationMock).not.toHaveBeenCalled();
  });

  it("keeps the channel draft open when saving before MCP setup fails", async () => {
    mockFeature(savedFeature());
    requestMutationMock.mockRejectedValueOnce(new Error("Unable to save settings"));
    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    fireEvent.change(await screen.findByRole("textbox", { name: "OAuth client ID" }), {
      target: { value: "replacement-client" },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Configure Linear MCP" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Unable to save settings");
    expect(screen.getByRole("textbox", { name: "OAuth client ID" })).toHaveValue("replacement-client");
    expect(screen.queryByRole("dialog", { name: "Linear" })).not.toBeInTheDocument();
  });

  it("automatically saves a public URL before OAuth credentials and reveals the app button", async () => {
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
    expect(screen.queryByRole("button", { name: /^Save/ })).not.toBeInTheDocument();

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
      await screen.findByRole("link", { name: "Create Linear app" }),
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
    fireEvent.blur(screen.getByRole("textbox", { name: "OAuth client ID" }));
    expect(await screen.findByText("Unable to save settings")).toBeVisible();
    expect(screen.getByRole("textbox", { name: "OAuth client ID" })).toHaveValue("replacement-client");
    expect(screen.getByRole("button", { name: "Connect Linear" })).toBeDisabled();
    await new Promise((resolve) => setTimeout(resolve, 750));
    expect(requestMutationMock).toHaveBeenCalledTimes(1);
    expect(requestMutationMock.mock.calls[0][1]).not.toHaveProperty("enable");
  });

  it("waits for a secret field to blur before saving its replacement", async () => {
    const feature = savedFeature();
    mockFeature(feature);
    requestMutationMock.mockResolvedValueOnce({
      saved: true, nanobot_features: { features: [feature], enabled_count: 0 },
    });
    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    const input = screen.getByLabelText("OAuth client secret", { exact: true });
    fireEvent.change(input, { target: { value: "replacement-secret" } });
    await new Promise((resolve) => setTimeout(resolve, 750));
    expect(requestMutationMock).not.toHaveBeenCalled();
    fireEvent.blur(input);
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledTimes(1));
    const params = requestMutationMock.mock.calls[0][1] as { values: Record<string, unknown> };
    expect(params.values["channels.linear.clientSecret"]).toBe("replacement-secret");
    expect(params.values).not.toHaveProperty("channels.linear.webhookSigningSecret");
    await waitFor(() => expect(input).toHaveValue(""));
    expect(input).toHaveAttribute("placeholder", "Saved secret");
  });

  it("removes both saved secrets with one action while keeping the public URL and client ID", async () => {
    const feature = savedFeature();
    mockFeature(feature);
    const secretKeys = ["channels.linear.clientSecret", "channels.linear.webhookSigningSecret"];
    requestMutationMock.mockResolvedValueOnce({
      saved: true, nanobot_features: {
        features: [{ ...feature, configured_fields: feature.configured_fields?.filter(
          (key) => !secretKeys.includes(key),
        ) }], enabled_count: 0,
      },
    });
    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    expect(screen.getAllByRole("button", { name: "Remove saved credentials" })).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Remove saved credentials" }));
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledTimes(1));
    const params = requestMutationMock.mock.calls[0][1] as { values: Record<string, unknown> };
    for (const key of secretKeys) expect(params.values[key]).toBeNull();
    expect(params.values["channels.linear.clientId"]).toBe("client-id");
    expect(params.values["channels.linear.publicBaseUrl"]).toBe("https://nanobot.example.com");
    await waitFor(() => expect(screen.queryByRole("button", {
      name: "Remove saved credentials",
    })).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Connect Linear" })).toBeDisabled();
  });

  it("flushes the draft on close and waits for one in-flight save", async () => {
    const feature = savedFeature();
    mockFeature(feature);
    let finishSave: ((value: unknown) => void) | undefined;
    requestMutationMock.mockImplementationOnce(() => new Promise((resolve) => { finishSave = resolve; }));
    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    fireEvent.change(screen.getByRole("textbox", { name: "OAuth client ID" }), {
      target: { value: "replacement-client" },
    });
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Close", exact: true }));
    expect(requestMutationMock).toHaveBeenCalledTimes(1);
    expect(dialog).toBeVisible();
    fireEvent.click(within(dialog).getByRole("button", { name: "Close", exact: true }));
    expect(requestMutationMock).toHaveBeenCalledTimes(1);
    finishSave?.({ saved: true, nanobot_features: { features: [{
      ...feature, config_values: { ...feature.config_values, "channels.linear.clientId": "replacement-client" },
    }], enabled_count: 0 } });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("keeps the dialog and draft after a failed close save and allows retry", async () => {
    const feature = savedFeature();
    mockFeature(feature);
    requestMutationMock.mockRejectedValueOnce(new Error("Connection lost"));
    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    fireEvent.change(screen.getByRole("textbox", { name: "OAuth client ID" }), {
      target: { value: "replacement-client" },
    });
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Close", exact: true }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Connection lost");
    expect(screen.getByRole("dialog")).toBeVisible();
    expect(screen.getByRole("textbox", { name: "OAuth client ID" })).toHaveValue("replacement-client");
    requestMutationMock.mockResolvedValueOnce({ saved: true, nanobot_features: { features: [{
      ...feature, config_values: { ...feature.config_values, "channels.linear.clientId": "replacement-client" },
    }], enabled_count: 0 } });
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Connect Linear" })).toBeEnabled());
    expect(requestMutationMock).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
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
    expect(screen.queryByRole("button", { name: "Remove saved credentials" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(await screen.findByText("Authorization stopped.")).toBeVisible();
    expect(screen.getByRole("textbox", { name: "OAuth client ID" })).toBeEnabled();
    expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.channel.connect.cancel", { channel: "linear", session_id: "linear-oauth" }, 20_000,
    );
  });

  it("restores a running connection on reopen without starting OAuth", async () => {
    mockFeature({ ...savedFeature(), enabled: true, running: true, runtime_status: "running" });
    requestMutationMock.mockResolvedValue({
      session_id: "", status: "inspected", installations: [],
    });
    renderSettingsView({ initialSection: "channels" });
    const open = await screen.findByRole("button", { name: "View Linear settings" });
    fireEvent.click(open);
    expect(within(screen.getByRole("dialog")).getByText("Channel running", { exact: true })).toBeVisible();
    expect(screen.getByRole("button", { name: "Connect another workspace" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Connect Linear" })).not.toBeInTheDocument();
    expect(await screen.findByText(/No workspaces are authorized/)).toBeVisible();
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Close", exact: true }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    fireEvent.click(open);
    expect(within(screen.getByRole("dialog")).getByText("Channel running", { exact: true })).toBeVisible();
    expect(screen.getByRole("button", { name: "Connect another workspace" })).toBeEnabled();
    expect(await screen.findByText(/No workspaces are authorized/)).toBeVisible();
    expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.channel.connect.start", { channel: "linear", operation: "inspect" }, 150_000,
    );
  });

  it("shows workspace inspection failures instead of a contradictory empty state", async () => {
    mockFeature({ ...savedFeature(), enabled: true, running: true, runtime_status: "running" });
    requestMutationMock.mockRejectedValueOnce(new Error("Workspace lookup failed"));

    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Workspace lookup failed");
    expect(screen.queryByText(/No workspaces are authorized/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh workspaces" })).toBeEnabled();
  });

  it("starts another workspace authorization directly and preserves the connection on cancel", async () => {
    mockFeature({ ...savedFeature(), enabled: true, running: true, runtime_status: "running" });
    requestMutationMock
      .mockResolvedValueOnce({ session_id: "", status: "inspected", installations: [] })
      .mockResolvedValueOnce({ session_id: "another-workspace", status: "pending",
        qr_url: "https://linear.app/oauth/authorize?client_id=test" })
      .mockResolvedValueOnce({ session_id: "another-workspace", status: "cancelled" });
    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    fireEvent.click(screen.getByRole("button", { name: "Connect another workspace" }));
    expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.channel.connect.start", { channel: "linear", force: true }, 150_000,
    );
    expect(await screen.findByRole("link", { name: "Continue in Linear" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(await screen.findByRole("button", { name: "Connect another workspace" })).toBeEnabled();
    expect(within(screen.getByRole("dialog")).getByText("Channel running", { exact: true })).toBeVisible();
    expect(screen.queryByText("Authorization stopped.")).not.toBeInTheDocument();
  });

  it("updates the running status when an existing installation connects without OAuth", async () => {
    const feature = savedFeature();
    mockFeature(feature);
    requestMutationMock.mockResolvedValueOnce({
      session_id: "", status: "succeeded",
      nanobot_features: {
        features: [{ ...feature, enabled: true, running: true, runtime_status: "running" }],
        enabled_count: 1,
      },
    }).mockResolvedValueOnce({ session_id: "", status: "inspected", installations: [] });
    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    fireEvent.click(await screen.findByRole("button", { name: "Connect Linear" }));
    expect(await within(screen.getByRole("dialog")).findByText("Channel running", { exact: true })).toBeVisible();
    expect(screen.getByRole("button", { name: "Connect another workspace" })).toBeEnabled();
  });

  it("does not mark saved credentials or a failed runtime as connected", async () => {
    mockFeature({ ...savedFeature(), enabled: true, configured: true, runtime_status: "failed",
      runtime_error: "Linear channel failed to start" });
    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    expect(within(screen.getByRole("dialog")).queryByText("Channel running", { exact: true })).not.toBeInTheDocument();
    expect(screen.getByText("Linear channel failed to start")).toBeVisible();
    expect(screen.getByRole("button", { name: "Connect Linear" })).toBeEnabled();
  });

  it("lists authorized workspaces and confirms disconnecting the last one", async () => {
    const running = {
      ...savedFeature(), enabled: true, running: true, runtime_status: "running" as const,
    };
    const disabled = {
      ...savedFeature(), enabled: false, running: false, runtime_status: "stopped" as const,
    };
    mockFeature(running);
    requestMutationMock
      .mockResolvedValueOnce({
        session_id: "",
        status: "inspected",
        installations: [{
          organization_id: "org-1",
          organization_name: "Example workspace",
          scopes: ["read", "write", "app:mentionable", "app:assignable"],
          authorization_status: "authorized",
        }],
      })
      .mockResolvedValueOnce({
        session_id: "",
        status: "disconnected",
        message: "Disconnected Example workspace.",
        installations: [],
      })
      .mockResolvedValueOnce({ features: [disabled], enabled_count: 0 });

    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    expect(await screen.findByText("Example workspace")).toBeVisible();
    expect(screen.getByText(/app:assignable/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    fireEvent.click(screen.getByRole("button", { name: "Disconnect workspace" }));

    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.channel.connect.start",
      { channel: "linear", operation: "disconnect", organization_id: "org-1" },
      150_000,
    ));
    expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.feature.disable", { name: "linear" }, 20_000,
    );
  });

  it("prevents disconnecting a workspace while its status is refreshing", async () => {
    const running = {
      ...savedFeature(), enabled: true, running: true, runtime_status: "running" as const,
    };
    let finishRefresh: ((value: unknown) => void) | undefined;
    const installation = {
      organization_id: "org-1",
      organization_name: "Example workspace",
      authorization_status: "authorized",
    };
    mockFeature(running);
    requestMutationMock
      .mockResolvedValueOnce({
        session_id: "", status: "inspected", installations: [installation],
      })
      .mockImplementationOnce(() => new Promise((resolve) => { finishRefresh = resolve; }));

    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    expect(await screen.findByText("Example workspace")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    fireEvent.click(screen.getByRole("button", { name: "Refresh workspaces" }));

    expect(screen.getByRole("button", { name: "Disconnect workspace" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    finishRefresh?.({ session_id: "", status: "inspected", installations: [installation] });
    await waitFor(() => expect(
      screen.getByRole("button", { name: "Disconnect workspace" }),
    ).toBeEnabled());
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
    if (url === "/api/settings/mcp-presets") return jsonResponse({
      presets: [{
        name: "linear", display_name: "Linear", category: "productivity",
        description: "Search and update Linear issues.", transport: "streamableHttp",
        auth: "oauth", install_supported: true, installed: false, configured: false,
        available: false, status: "not_installed", required_fields: [],
        enabled_tools: ["*"], source: "preset", connection_summary: "",
      }], installed_count: 0,
    });
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
