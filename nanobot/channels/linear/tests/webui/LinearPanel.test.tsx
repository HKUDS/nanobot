import { channelUiContribution } from "@/channel-plugins/registry";
import { NanobotClient } from "@/lib/nanobot-client";
import type { ConnectionStatus } from "@/lib/types";
import type { ChannelSetupContract, ChannelSetupContractField, NanobotFeatureInfo } from "@/lib/types";
import {
  act,
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
import { getLinearWorkspaceProfile } from "../../webui/api";

vi.mock("../../webui/api", async (importOriginal) => ({
  ...await importOriginal<typeof import("../../webui/api")>(),
  getLinearWorkspaceProfile: vi.fn(async (_client: unknown, organizationId: string) => ({
    organization_id: organizationId, logo_url: null,
  })),
}));

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
    mockSavedInspection();
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
    expect(actionCalls()).toHaveLength(0);
  });

  it("keeps the channel draft open when saving before MCP setup fails", async () => {
    mockFeature(savedFeature());
    mockSavedInspection();
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
    mockSavedInspection();
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
    await waitFor(() => expect(screen.getByRole("button", { name: "Connect Linear" })).toBeEnabled());
    expect(screen.queryByRole("spinbutton", { name: "Listen port" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Advanced" }));
    fireEvent.change(screen.getByRole("spinbutton", { name: "Listen port" }), {
      target: { value: "3980" },
    });
    expect(screen.getByRole("button", { name: "Connect Linear" })).toBeDisabled();
    await waitFor(() => expect(screen.getByRole("button", { name: "Connect Linear" })).toBeEnabled());
    const params = actionCalls()[0][1] as { values: Record<string, unknown> };
    expect(params.values["channels.linear.port"]).toBe("3980");
    expect(params.values).not.toHaveProperty("channels.linear.clientSecret");
    expect(params.values).not.toHaveProperty("channels.linear.webhookSigningSecret");
  });

  it("keeps an unsaved draft when saving fails without enabling the channel", async () => {
    mockFeature(savedFeature());
    mockSavedInspection();
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
    expect(actionCalls()).toHaveLength(1);
    expect(actionCalls()[0][1]).not.toHaveProperty("enable");
  });

  it("replaces a saved secret only on explicit save and submits just that field", async () => {
    const feature = savedFeature();
    mockFeature(feature);
    mockSavedInspection();
    requestMutationMock.mockResolvedValueOnce({
      saved: true, nanobot_features: { features: [feature], enabled_count: 0 },
    });
    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    await screen.findByText(/No workspaces are authorized/);
    expect(screen.queryByPlaceholderText("Saved secret")).not.toBeInTheDocument();
    expect(screen.getAllByText("Saved", { exact: true })).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Replace OAuth client secret" }));
    const input = screen.getByLabelText("OAuth client secret", { exact: true, selector: "input" });
    expect(input).toHaveFocus();
    fireEvent.change(input, { target: { value: "replacement-secret" } });
    fireEvent.blur(input);
    await new Promise((resolve) => setTimeout(resolve, 750));
    expect(actionCalls()).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Save", exact: true }));
    await waitFor(() => expect(actionCalls()).toHaveLength(1));
    const params = actionCalls()[0][1] as { values: Record<string, unknown> };
    expect(params.values).toEqual({ "channels.linear.clientSecret": "replacement-secret" });
    await waitFor(() => expect(screen.getByRole("button", { name: "Replace OAuth client secret" })).toHaveFocus());
    expect(screen.queryByDisplayValue("replacement-secret")).not.toBeInTheDocument();
    expect(screen.getAllByText("Saved", { exact: true })).toHaveLength(2);
  });

  it("cancels a replacement without submitting or blocking the existing connection", async () => {
    mockFeature(savedFeature());
    mockSavedInspection();
    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Connect Linear" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Replace OAuth client secret" }));
    fireEvent.change(screen.getByLabelText("OAuth client secret", { exact: true, selector: "input" }), {
      target: { value: "discarded-draft" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Cancel", exact: true }));
    expect(screen.getAllByText("Saved", { exact: true })).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Connect Linear" })).toBeEnabled();
    await new Promise(resolve => setTimeout(resolve, 750));
    expect(actionCalls()).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Replace OAuth client secret" }));
    expect(screen.getByLabelText("OAuth client secret", { exact: true, selector: "input" })).toHaveValue("");
  });

  it("keeps the draft after a failed secret save and does not report success", async () => {
    mockFeature(savedFeature());
    mockSavedInspection();
    requestMutationMock.mockResolvedValueOnce({ saved: false });
    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    await screen.findByText(/No workspaces are authorized/);
    fireEvent.click(screen.getByRole("button", { name: "Replace OAuth client secret" }));
    fireEvent.change(screen.getByLabelText("OAuth client secret", { exact: true, selector: "input" }), {
      target: { value: "retry-draft" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save", exact: true }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not confirm the save");
    expect(screen.getByLabelText("OAuth client secret", { exact: true, selector: "input" })).toHaveValue("retry-draft");
    expect(screen.queryByText("Settings saved.")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel", exact: true }));
    expect(screen.getAllByText("Saved", { exact: true })).toHaveLength(2);
  });

  it("confirms a first secret save before enabling authorization", async () => {
    const feature = savedFeature();
    mockFeature({ ...feature, configured_fields: feature.configured_fields?.filter(
      key => key !== "channels.linear.clientSecret",
    ) });
    requestMutationMock.mockResolvedValueOnce({
      saved: true, nanobot_features: { features: [feature], enabled_count: 0 },
    });
    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    const input = screen.getByLabelText("OAuth client secret", { exact: true, selector: "input" });
    fireEvent.change(input, { target: { value: "first-secret" } });
    expect(screen.getByRole("button", { name: "Connect Linear" })).toBeDisabled();
    expect(requestMutationMock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Save", exact: true }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Replace OAuth client secret" })).toHaveFocus());
    expect(screen.getAllByText("Saved", { exact: true })).toHaveLength(2);
    expect(screen.queryByDisplayValue("first-secret")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Connect Linear" })).toBeEnabled();
    expect(actionCalls()[0][1].values).toEqual({ "channels.linear.clientSecret": "first-secret" });
  });

  it("does not submit the other secret's unfinished replacement", async () => {
    const feature = savedFeature();
    mockFeature(feature);
    mockSavedInspection();
    requestMutationMock.mockResolvedValueOnce({
      saved: true, nanobot_features: { features: [feature], enabled_count: 0 },
    });
    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    await screen.findByText(/No workspaces are authorized/);
    fireEvent.click(screen.getByRole("button", { name: "Replace OAuth client secret" }));
    fireEvent.click(screen.getByRole("button", { name: "Replace Webhook signing secret" }));
    const clientGroup = screen.getByRole("group", { name: "OAuth client secret" });
    const webhook = screen.getByLabelText("Webhook signing secret", { exact: true, selector: "input" });
    fireEvent.change(screen.getByLabelText("OAuth client secret", { exact: true, selector: "input" }), {
      target: { value: "client-draft" },
    });
    fireEvent.change(webhook, { target: { value: "unfinished-webhook" } });
    fireEvent.click(within(clientGroup).getByRole("button", { name: "Save", exact: true }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Replace OAuth client secret" })).toBeEnabled());
    expect(actionCalls()).toHaveLength(1);
    expect(actionCalls()[0][1].values).toEqual({ "channels.linear.clientSecret": "client-draft" });
    expect(webhook).toHaveValue("unfinished-webhook");
    fireEvent.click(screen.getByRole("button", { name: "Cancel", exact: true }));
    expect(screen.getAllByText("Saved", { exact: true })).toHaveLength(2);
  });

  it("waits before closing during a secret save and keeps the editor open if it fails", async () => {
    mockFeature(savedFeature());
    mockSavedInspection();
    let failSave!: (reason: Error) => void;
    requestMutationMock.mockImplementationOnce(() => new Promise((_resolve, reject) => { failSave = reject; }));
    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    await screen.findByText(/No workspaces are authorized/);
    fireEvent.click(screen.getByRole("button", { name: "Replace OAuth client secret" }));
    fireEvent.change(screen.getByLabelText("OAuth client secret", { exact: true, selector: "input" }), {
      target: { value: "keep-draft" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save", exact: true }));
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Close", exact: true }));
    expect(dialog).toBeVisible();
    expect(actionCalls()).toHaveLength(1);
    await act(async () => failSave(new Error("Network unavailable")));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not confirm the save");
    expect(dialog).toBeVisible();
    expect(screen.getByLabelText("OAuth client secret", { exact: true, selector: "input" })).toHaveValue("keep-draft");
  });

  it("keeps global reset in Advanced and no longer exposes the ambiguous credential deletion", async () => {
    mockFeature(savedFeature());
    mockSavedInspection();
    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    expect(screen.queryByRole("button", { name: "Remove saved credentials" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reset Linear connection" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Advanced" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Reset Linear connection" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Reset Linear connection" }));
    const confirm = await screen.findByRole("alertdialog", { name: "Reset Linear?" });
    expect(confirm).toHaveTextContent("all workspaces linked through this app");
    expect(actionCalls()).toHaveLength(0);
    fireEvent.click(within(confirm).getByRole("button", { name: "Cancel" }));
    expect(actionCalls()).toHaveLength(0);
  });

  it("flushes the draft on close and waits for one in-flight save", async () => {
    const feature = savedFeature();
    mockFeature(feature);
    mockSavedInspection();
    let finishSave: ((value: unknown) => void) | undefined;
    requestMutationMock.mockImplementationOnce(() => new Promise((resolve) => { finishSave = resolve; }));
    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    fireEvent.change(screen.getByRole("textbox", { name: "OAuth client ID" }), {
      target: { value: "replacement-client" },
    });
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Close", exact: true }));
    expect(actionCalls()).toHaveLength(1);
    expect(dialog).toBeVisible();
    fireEvent.click(within(dialog).getByRole("button", { name: "Close", exact: true }));
    expect(actionCalls()).toHaveLength(1);
    finishSave?.({ saved: true, nanobot_features: { features: [{
      ...feature, config_values: { ...feature.config_values, "channels.linear.clientId": "replacement-client" },
    }], enabled_count: 0 } });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("keeps the dialog and draft after a failed close save and allows retry", async () => {
    const feature = savedFeature();
    mockFeature(feature);
    mockSavedInspection();
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
    expect(actionCalls()).toHaveLength(2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows the OAuth handoff and cancels a pending authorization", async () => {
    mockFeature(savedFeature());
    mockSavedInspection();
    requestMutationMock
      .mockResolvedValueOnce({ session_id: "linear-oauth", status: "pending",
        qr_url: "https://linear.app/oauth/authorize?client_id=test", interval_ms: 5000 })
      .mockResolvedValueOnce({ session_id: "linear-oauth", status: "cancelled" });
    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Connect Linear" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Connect Linear" }));
    expect(await screen.findByRole("link", { name: "Continue in Linear" })).toHaveAttribute(
      "href", "https://linear.app/oauth/authorize?client_id=test",
    );
    expect(screen.getByText("Continue in Linear to choose a workspace and authorize nanobot. Return here when you're done.")).toBeVisible();
    expect(screen.queryByRole("img", { name: /QR/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/scan the QR code/i)).not.toBeInTheDocument();
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
    expect(await screen.findByText(/No workspaces are authorized/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Connect Linear" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Connect another workspace" })).not.toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Close", exact: true }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    fireEvent.click(open);
    expect(within(screen.getByRole("dialog")).getByText("Channel running", { exact: true })).toBeVisible();
    expect(screen.getByRole("button", { name: "Connect Linear" })).toBeEnabled();
    expect(await screen.findByText(/No workspaces are authorized/)).toBeVisible();
    expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.channel.connect.start", { channel: "linear", operation: "inspect" }, 150_000,
    );
  });

  it.each(["stopped", "failed"])("keeps authorized workspaces manageable when the channel is %s", async (runtime_status) => {
    mockFeature({ ...savedFeature(), runtime_status });
    requestMutationMock.mockResolvedValue({
      session_id: "", status: "inspected", installations: [
        { organization_id: "org-1", organization_name: "nanobot", authorization_status: "authorized" },
      ],
    });
    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    expect(await screen.findByRole("article", { name: "nanobot" })).toBeVisible();
    expect(within(screen.getByRole("dialog")).queryByText("Channel running", { exact: true })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Manage nanobot" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Connect Linear" })).toBeEnabled();
    expect(requestMutationMock).toHaveBeenCalledTimes(1);
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

  it("offers an independent add-workspace entry using the existing app with forced consent", async () => {
    mockFeature({ ...savedFeature(), enabled: true, running: true, runtime_status: "running" });
    requestMutationMock
      .mockResolvedValueOnce({ session_id: "", status: "inspected", installations: [
        { organization_id: "org-1", organization_name: "nanobot", authorization_status: "authorized" },
      ] })
      .mockResolvedValueOnce({ session_id: "add", status: "pending",
        qr_url: "https://linear.app/oauth/authorize?client_id=test" });
    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    const add = await screen.findByRole("button", { name: "Connect workspace" });
    expect(screen.getByRole("button", { name: "About connecting workspaces" })).toBeVisible();
    fireEvent.click(add);
    expect(await screen.findByRole("link", { name: "Continue in Linear" })).toBeVisible();
    expect(screen.queryByRole("img", { name: /QR/i })).not.toBeInTheDocument();
    expect(screen.getByRole("article", { name: "nanobot" })).toBeVisible();
    expect(requestMutationMock).toHaveBeenLastCalledWith(
      "settings.channel.connect.start", { channel: "linear", force: true }, 150_000,
    );
  });

  it("reauthorizes from the workspace menu and preserves the connection on cancel", async () => {
    const reveal = vi.spyOn(HTMLElement.prototype, "scrollIntoView");
    mockFeature({ ...savedFeature(), enabled: true, running: true, runtime_status: "running" });
    requestMutationMock
      .mockResolvedValueOnce({ session_id: "", status: "inspected", installations: [
        { organization_id: "org-1", organization_name: "nanobot", authorization_status: "authorized" },
      ] })
      .mockResolvedValueOnce({ session_id: "another-workspace", status: "pending",
        qr_url: "https://linear.app/oauth/authorize?client_id=test" })
      .mockResolvedValueOnce({ session_id: "another-workspace", status: "cancelled" });
    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    const manage = await screen.findByRole("button", { name: "Manage nanobot" });
    expect(screen.queryByRole("button", { name: "Connect another workspace" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reauthorize" })).not.toBeInTheDocument();
    fireEvent.keyDown(manage, { key: "ArrowDown" });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Reauthorize" }));
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.channel.connect.start", { channel: "linear", force: true }, 150_000,
    ));
    expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.channel.connect.start", { channel: "linear", force: true }, 150_000,
    );
    expect(await screen.findByRole("link", { name: "Continue in Linear" })).toBeVisible();
    await waitFor(() => expect(screen.getByRole("link", { name: "Continue in Linear" })).toHaveFocus());
    expect(reveal).toHaveBeenCalledWith({ block: "nearest" });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Manage nanobot" })).toBeEnabled());
    expect(within(screen.getByRole("dialog")).getByText("Channel running", { exact: true })).toBeVisible();
    expect(screen.queryByText("Authorization stopped.")).not.toBeInTheDocument();
    expect(requestMutationMock.mock.calls.some(([, params]) => params.operation === "disconnect")).toBe(false);
  });

  it("updates the running status when an existing installation connects without OAuth", async () => {
    const feature = savedFeature();
    mockFeature(feature);
    mockSavedInspection();
    requestMutationMock.mockResolvedValueOnce({
      session_id: "", status: "succeeded",
      nanobot_features: {
        features: [{ ...feature, enabled: true, running: true, runtime_status: "running" }],
        enabled_count: 1,
      },
    }).mockResolvedValueOnce({ session_id: "", status: "inspected", installations: [] });
    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Connect Linear" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Connect Linear" }));
    expect(await within(screen.getByRole("dialog")).findByText("Channel running", { exact: true })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Connect another workspace" })).not.toBeInTheDocument();
  });

  it("does not show OAuth success when the channel subsequently fails to start", async () => {
    const feature = savedFeature();
    mockFeature(feature);
    mockSavedInspection();
    requestMutationMock.mockResolvedValueOnce({
      session_id: "", status: "succeeded",
      nanobot_features: {
        features: [{ ...feature, enabled: true, runtime_status: "failed",
          runtime_error: "Linear channel failed to start" }], enabled_count: 1,
      },
    }).mockResolvedValueOnce({ session_id: "", status: "inspected", installations: [] });
    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Connect Linear" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Connect Linear" }));
    expect(await screen.findByText("Linear channel failed to start")).toBeVisible();
    expect(screen.queryByText("Linear is connected.")).not.toBeInTheDocument();
  });

  it("does not mark saved credentials or a failed runtime as connected", async () => {
    mockFeature({ ...savedFeature(), enabled: true, configured: true, runtime_status: "failed",
      runtime_error: "Linear channel failed to start" });
    mockSavedInspection();
    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    expect(within(screen.getByRole("dialog")).queryByText("Channel running", { exact: true })).not.toBeInTheDocument();
    expect(screen.getByText("Linear channel failed to start")).toBeVisible();
    await waitFor(() => expect(screen.getByRole("button", { name: "Connect Linear" })).toBeEnabled());
  });

  it("recovers workspace inspection automatically when the WebUI reconnects", async () => {
    mockFeature({ ...savedFeature(), enabled: true, running: true, runtime_status: "running" });
    const client = new NanobotClient({ url: "ws://test.invalid", reconnect: false });
    let onStatus: ((status: ConnectionStatus) => void) | undefined;
    const unsubscribe = vi.fn();
    vi.spyOn(client, "onStatus").mockImplementation((handler) => {
      onStatus = handler;
      handler("reconnecting");
      return unsubscribe;
    });
    vi.spyOn(client, "requestMutation").mockImplementation(requestMutationMock);
    requestMutationMock
      .mockRejectedValueOnce(new Error("WebUI connection is not open"))
      .mockResolvedValue({ installations: [
        { organization_id: "org-1", organization_name: "nanobot", authorization_status: "authorized" },
      ] });
    renderSettingsView({ initialSection: "channels", client });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    expect(await screen.findByText("WebUI connection is not open")).toBeVisible();
    act(() => onStatus?.("open"));
    expect(await screen.findByRole("article", { name: "nanobot" })).toBeVisible();
    expect(screen.queryByText("WebUI connection is not open")).not.toBeInTheDocument();
    expect(requestMutationMock).toHaveBeenCalledTimes(2);
    // A second reconnect must revalidate even while the display cache is fresh.
    act(() => { onStatus?.("reconnecting"); onStatus?.("open"); });
    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledTimes(3));
    fireEvent.click(screen.getByRole("button", { name: "Close", exact: true }));
    expect(unsubscribe).toHaveBeenCalled();
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
    const workspace = screen.getByRole("article", { name: "Example workspace" });
    expect(within(workspace).getByRole("heading", { name: "Example workspace", level: 5 })).toBeVisible();
    expect(within(workspace).getByRole("button", { name: "Member access" })).toBeVisible();
    expect(within(workspace).queryByText("Authorized")).not.toBeInTheDocument();
    expect(screen.getByText(/Example workspace: read, write/)).not.toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Advanced" }));
    expect(screen.getByText(/Example workspace: read, write, app:mentionable, app:assignable/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Advanced" }));
    expect(within(workspace).queryByRole("button", { name: "Remove workspace" })).not.toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("button", { name: "Manage Example workspace" }), { key: "ArrowDown" });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Remove workspace" }));
    const confirm = await screen.findByRole("alertdialog", { name: "Remove Example workspace?" });
    expect(confirm).toHaveTextContent("Linear issues, comments, and nanobot conversation history will be kept.");
    expect(confirm).toHaveTextContent("the Linear channel will also be turned off");
    expect(requestMutationMock).toHaveBeenCalledTimes(1);
    fireEvent.click(within(confirm).getByRole("button", { name: "Remove workspace" }));

    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.channel.connect.start",
      { channel: "linear", operation: "disconnect", organization_id: "org-1" },
      150_000,
    ));
    expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.feature.disable", { name: "linear" }, 20_000,
    );
  });

  it("clears an old cancelled authorization after removing the last workspace", async () => {
    const installation = { organization_id: "org-1", organization_name: "nanobot",
      authorization_status: "authorized" };
    let removed = false;
    mockFeature({ ...savedFeature(), enabled: true, running: true, runtime_status: "running" });
    requestMutationMock.mockImplementation(async (method, params) => {
      if (method === "settings.feature.disable") return {
        features: [{ ...savedFeature(), enabled: false, running: false, runtime_status: "stopped" }],
        enabled_count: 0,
      };
      if (method === "settings.channel.connect.cancel") return {
        session_id: "attempt", status: "cancelled", message: "Linear authorization cancelled.",
      };
      if (params.operation === "disconnect") {
        removed = true;
        return { session_id: "", status: "disconnected", installations: [] };
      }
      if (params.operation === "inspect") return {
        session_id: "", status: "inspected", installations: removed ? [] : [installation],
      };
      return { session_id: "attempt", status: "pending", qr_url: "https://linear.app/oauth/authorize" };
    });
    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    fireEvent.click(await screen.findByRole("button", { name: "Connect workspace" }));
    await screen.findByRole("link", { name: "Continue in Linear" });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Manage nanobot" })).toBeEnabled());
    fireEvent.keyDown(screen.getByRole("button", { name: "Manage nanobot" }), { key: "ArrowDown" });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Remove workspace" }));
    const confirm = await screen.findByRole("alertdialog", { name: "Remove nanobot?" });
    fireEvent.click(within(confirm).getByRole("button", { name: "Remove workspace" }));
    expect(await screen.findByRole("button", { name: "Connect Linear" })).toBeEnabled();
    expect(screen.queryByText("Linear authorization cancelled.")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Continue in Linear" })).not.toBeInTheDocument();
  });

  it("cancels disconnect without a mutation and returns focus to workspace actions", async () => {
    mockFeature({ ...savedFeature(), enabled: true, running: true, runtime_status: "running" });
    requestMutationMock.mockResolvedValue({ session_id: "", status: "inspected", installations: [
      { organization_id: "org-1", organization_name: "nanobot", authorization_status: "authorized" },
    ] });
    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    const manage = await screen.findByRole("button", { name: "Manage nanobot" });
    manage.focus();
    fireEvent.keyDown(manage, { key: "ArrowDown" });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Remove workspace" }));
    const confirm = await screen.findByRole("alertdialog", { name: "Remove nanobot?" });
    await waitFor(() => expect(within(confirm).getByRole("button", { name: "Cancel" })).toHaveFocus());
    fireEvent.click(within(confirm).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    await waitFor(() => expect(manage).toHaveFocus());
    expect(requestMutationMock).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("article", { name: "nanobot" })).toBeVisible();
  });

  it("keeps a failed disconnect retryable and only removes the selected workspace after confirmation", async () => {
    const installations = [
      { organization_id: "org-1", organization_name: "nanobot", authorization_status: "authorized" },
      { organization_id: "org-2", organization_name: "Other workspace", authorization_status: "authorized" },
    ];
    let failDisconnect!: (error: Error) => void;
    mockFeature({ ...savedFeature(), enabled: true, running: true, runtime_status: "running" });
    requestMutationMock
      .mockResolvedValueOnce({ session_id: "", status: "inspected", installations })
      .mockImplementationOnce(() => new Promise((_resolve, reject) => { failDisconnect = reject; }))
      .mockResolvedValueOnce({ session_id: "", status: "disconnected", installations: [installations[1]] });
    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    fireEvent.keyDown(await screen.findByRole("button", { name: "Manage nanobot" }), { key: "ArrowDown" });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Remove workspace" }));
    const confirm = await screen.findByRole("alertdialog", { name: "Remove nanobot?" });
    expect(confirm).not.toHaveTextContent("last connected workspace");
    fireEvent.click(within(confirm).getByRole("button", { name: "Remove workspace" }));
    expect(within(confirm).getByRole("button", { name: "Removing…" })).toBeDisabled();
    expect(within(confirm).getByRole("button", { name: "Cancel" })).toBeDisabled();
    failDisconnect(new Error("Could not revoke authorization"));
    expect(await within(confirm).findByRole("alert")).toHaveTextContent("Could not revoke authorization");
    expect(screen.getByRole("article", { name: "nanobot", hidden: true })).toBeInTheDocument();
    fireEvent.click(within(confirm).getByRole("button", { name: "Remove workspace" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(screen.queryByRole("article", { name: "nanobot" })).not.toBeInTheDocument();
    expect(screen.getByRole("article", { name: "Other workspace" })).toBeVisible();
    expect(requestMutationMock).toHaveBeenLastCalledWith("settings.channel.connect.start", {
      channel: "linear", operation: "disconnect", organization_id: "org-1",
    }, 150_000);
    expect(requestMutationMock.mock.calls.some(([method]) => method === "settings.feature.disable")).toBe(false);
  });

  it("shows a workspace logo and member access without team controls", async () => {
    vi.mocked(getLinearWorkspaceProfile).mockResolvedValueOnce({
      organization_id: "org-1", logo_url: "https://uploads.linear.app/org-1/logo",
    });
    mockFeature({ ...savedFeature(), enabled: true, running: true, runtime_status: "running" });
    requestMutationMock.mockImplementation(async (_method, params) => params.operation === "members"
      ? { session_id: "", status: "members", organization_id: "org-1", legacy_allow_all: false,
        members: [{ id: "u1", name: "Xubin", teams: ["nanobot"], allowed: true }] }
      : { session_id: "", status: "inspected", installations: [
        { organization_id: "org-1", organization_name: "nanobot", authorization_status: "authorized" },
      ] });
    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    const workspace = await screen.findByRole("article", { name: "nanobot" });
    await waitFor(() => expect(workspace.querySelector("img")).toHaveAttribute("src", "https://uploads.linear.app/org-1/logo"));
    expect(within(workspace).queryByRole("button", { name: /team/i })).not.toBeInTheDocument();
    fireEvent.click(within(workspace).getByRole("button", { name: "Member access" }));
    expect(await within(workspace).findByRole("switch", { name: "Allow Xubin to use nanobot" })).toBeVisible();
    expect(within(workspace).getAllByRole("switch")).toHaveLength(1);
    expect(within(workspace).queryByRole("combobox")).not.toBeInTheDocument();
    expect(requestMutationMock.mock.calls.some(([, params]) => params.operation === "member_access")).toBe(false);
  });

  it("keeps member access inside its own workspace card and leaves other cards collapsed", async () => {
    mockFeature({ ...savedFeature(), enabled: true, running: true, runtime_status: "running" });
    requestMutationMock.mockImplementation(async (_method, params) => {
      if (params.operation === "members") return {
        session_id: "", status: "members", organization_id: params.organization_id,
        legacy_allow_all: false,
        members: [{ id: "u1", name: "Xubin", teams: ["nanobot"], allowed: true }],
      };
      return { session_id: "", status: "inspected", installations: [
        { organization_id: "org-1", organization_name: "nanobot", authorization_status: "authorized" },
        { organization_id: "org-2", organization_name: "Design workspace", authorization_status: "authorized" },
      ] };
    });
    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    const workspace = await screen.findByRole("article", { name: "nanobot" });
    const other = screen.getByRole("article", { name: "Design workspace" });
    fireEvent.click(within(workspace).getByRole("button", { name: "Member access" }));
    expect(await within(workspace).findByRole("switch", { name: "Allow Xubin to use nanobot" })).toBeVisible();
    expect(within(other).getByRole("button", { name: "Member access" })).toHaveAttribute("aria-expanded", "false");
    expect(within(other).queryByRole("switch")).not.toBeInTheDocument();
    expect(requestMutationMock).toHaveBeenCalledWith("settings.channel.connect.start", {
      channel: "linear", operation: "members", organization_id: "org-1",
    }, 150_000);
    expect(requestMutationMock.mock.calls.some(([, params]) => params.operation === "member_access")).toBe(false);
  });

  it("keeps missing authorization scopes visible without opening a tooltip", async () => {
    mockFeature({ ...savedFeature(), enabled: true, running: true, runtime_status: "running" });
    requestMutationMock.mockResolvedValue({ session_id: "", status: "inspected", installations: [{
      organization_id: "org-1", organization_name: "nanobot", authorization_status: "missing_scopes",
      scopes: ["read"], missing_scopes: ["write", "app:mentionable"],
    }] });
    renderSettingsView({ initialSection: "channels" });
    fireEvent.click(await screen.findByRole("button", { name: "View Linear settings" }));
    const workspace = await screen.findByRole("article", { name: "nanobot" });
    expect(within(workspace).getByText("Reconnect to grant: write, app:mentionable")).toBeVisible();
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
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
    fireEvent.click(screen.getByRole("button", { name: "Refresh workspaces" }));

    expect(screen.getByRole("button", { name: "Manage Example workspace" })).toBeDisabled();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    finishRefresh?.({ session_id: "", status: "inspected", installations: [installation] });
    await waitFor(() => expect(
      screen.getByRole("button", { name: "Manage Example workspace" }),
    ).toBeEnabled());
  });
});

function mockSavedInspection() {
  requestMutationMock.mockResolvedValueOnce({
    session_id: "", status: "inspected", installations: [],
  });
}

function actionCalls() {
  return requestMutationMock.mock.calls.filter(([, params]) => params?.operation !== "inspect");
}

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
