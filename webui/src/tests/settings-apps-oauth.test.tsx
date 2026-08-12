import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";
import {
  installSettingsViewTestHooks,
  jsonResponse,
  renderSettingsView,
  requestMutationMock,
  settingsPayload,
} from "@/tests/settings-test-utils";

const xmindMcpPreset = {
  name: "xmind",
  display_name: "Xmind",
  category: "productivity",
  description: "Create, read, and edit cloud mind maps through Xmind.",
  docs_url: "https://xmind.com/user-guide/xmind-mcp",
  transport: "streamableHttp",
  auth: "oauth" as const,
  requires: "Xmind account",
  note: "Connects securely in your browser with Xmind OAuth.",
  install_supported: true,
  installed: false,
  configured: false,
  available: false,
  status: "not_installed",
  logo_url: null,
  brand_color: "#F4B41A",
  required_fields: [],
  connection_summary: "",
  enabled_tools: ["*"],
  source: "preset",
};

describe("SettingsView Apps catalog", () => {
  installSettingsViewTestHooks();

  it("connects an OAuth MCP from the Apps catalog without manual callback input", async () => {
    let connected = false;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(settingsPayload());
      if (url === "/api/settings/cli-apps") {
        return jsonResponse({ apps: [], installed_count: 0 });
      }
      if (url === "/api/settings/mcp-presets") {
        return jsonResponse({
          presets: [connected
            ? {
              ...xmindMcpPreset,
              installed: true,
              configured: true,
              available: true,
              status: "configured",
              connection_summary: "https://app.xmind.com/api/mcp",
            }
            : xmindMcpPreset],
          installed_count: connected ? 1 : 0,
        });
      }
      if (url === "/api/settings/mcp-oauth/status?flow_id=flow-123") {
        connected = true;
        return jsonResponse({
          flow_id: "flow-123",
          name: "xmind",
          status: "connected",
          expires_in: 295,
          hot_reload: {
            ok: false,
            requires_restart: false,
            connected: ["xmind"],
            failed: ["notion"],
            message: "MCP config reloaded, but some servers did not connect: notion",
          },
        });
      }
      return { ok: false, status: 404, text: async () => "Not found" } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    requestMutationMock.mockImplementation(async (action: string) => {
      if (action === "settings.mcp.oauth_start") {
        return {
          flow_id: "flow-123",
          name: "xmind",
          status: "authorization_required",
          expires_in: 300,
          authorization_url: "https://accounts.xmind.test/authorize?state=state-123",
        };
      }
      return settingsPayload();
    });
    const replace = vi.fn();
    const popup = {
      opener: window,
      closed: false,
      location: { replace },
      document: { title: "", body: { textContent: "" } },
      focus: vi.fn(),
      close: vi.fn(),
    };
    const open = vi.fn(() => popup);
    vi.stubGlobal("open", open);

    renderSettingsView({ initialSection: "apps" });
    fireEvent.click(await screen.findByRole("button", { name: "MCP" }));
    expect(screen.getByText("MCP tools")).toBeInTheDocument();
    const connectButton = await screen.findByRole("button", { name: "Connect Xmind" });
    expect(connectButton).toHaveTextContent("Connect");
    fireEvent.click(connectButton);

    expect(open).toHaveBeenCalledWith(
      "about:blank",
      "nanobot-mcp-oauth",
      "popup,width=560,height=720,resizable=yes,scrollbars=yes",
    );
    await waitFor(() => expect(replace).toHaveBeenCalledWith(
      "https://accounts.xmind.test/authorize?state=state-123",
    ));
    expect(popup.opener).toBeNull();
    expect(screen.queryByRole("textbox", { name: /authorization/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Finish signing in in the browser window.",
    );
    expect(screen.getByRole("button", { name: "Connecting Xmind" })).toHaveTextContent(
      "Connecting…",
    );
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();

    expect(await screen.findByRole("button", { name: "Manage Xmind" }, { timeout: 2500 }))
      .toHaveTextContent("Manage");
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
    expect(screen.queryByText("Xmind connected.")).not.toBeInTheDocument();
    expect(screen.queryByText(/some servers did not connect: notion/i)).not.toBeInTheDocument();
    expect(popup.close).toHaveBeenCalledTimes(1);
    expect(replace).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/settings/mcp-oauth/status?flow_id=flow-123",
      expect.objectContaining({ headers: { Authorization: "Bearer tok" } }),
    );
  });

  it("shows a real OAuth runtime failure and restarts authorization without a success check", async () => {
    const failedPreset = {
      ...xmindMcpPreset,
      installed: true,
      configured: true,
      available: true,
      status: "configured",
      runtime_status: "failed",
      connection_summary: "https://app.xmind.com/api/mcp",
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(settingsPayload());
      if (url === "/api/settings/cli-apps") {
        return jsonResponse({ apps: [], installed_count: 0 });
      }
      if (url === "/api/settings/mcp-presets") {
        return jsonResponse({ presets: [failedPreset], installed_count: 1 });
      }
      return { ok: false, status: 404, text: async () => "Not found" } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("open", vi.fn(() => null));
    requestMutationMock.mockRejectedValueOnce(new Error("Stopped after request assertion"));

    renderSettingsView({ initialSection: "apps" });
    fireEvent.click(await screen.findByRole("button", { name: "Ready" }));
    expect(await screen.findByText("No tools are ready yet.")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Xmind" })).not.toBeInTheDocument();

    fireEvent.click(await screen.findByRole("button", { name: "MCP" }));

    const heading = await screen.findByRole("heading", { name: "Xmind" });
    const row = heading.closest("article");
    expect(row).not.toBeNull();
    expect(row?.parentElement).toHaveClass("xl:grid-cols-2");
    expect(within(row as HTMLElement).queryByText("MCP")).not.toBeInTheDocument();
    const failed = within(row as HTMLElement).getByText("Connection failed.");
    expect(failed.closest("button")).toBeNull();
    expect(failed.closest("p")?.querySelector(".lucide-triangle-alert")).not.toBeNull();
    expect(row?.querySelector(".lucide-check")).toBeNull();
    expect(within(row as HTMLElement).getByRole("button", { name: "Manage Xmind" })).toHaveTextContent(
      "Fix connection",
    );

    await act(() => i18n.changeLanguage("zh-CN"));
    expect(within(row as HTMLElement).getByText("连接失败。")).toBeInTheDocument();
    const manage = within(row as HTMLElement).getByRole("button", { name: "管理 Xmind" });
    expect(manage).toHaveTextContent("修复连接");
    fireEvent.click(manage);
    const dialog = screen.getByRole("dialog", { name: "Xmind" });
    expect(within(dialog).getByRole("tab", { name: "连接" })).toHaveAttribute("aria-selected", "true");
    expect(within(dialog).getByText("创建、读取和编辑 Xmind 云端思维导图。")).toHaveClass("sr-only");
    expect(within(dialog).getByText("连接失败", { exact: true })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "移除连接" })).toBeInTheDocument();
    const reconnect = within(dialog).getByRole("button", { name: "重新连接" });
    fireEvent.click(reconnect);

    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.mcp.oauth_start",
      { name: "xmind", reset: true },
      30_000,
    ));
    await act(() => i18n.changeLanguage("en"));
  });

  it("refreshes a connecting MCP snapshot until the runtime attempt settles", async () => {
    const connectingPreset = {
      ...xmindMcpPreset,
      installed: true,
      configured: true,
      available: true,
      status: "configured",
      runtime_status: "connecting",
      connection_summary: "https://app.xmind.com/api/mcp",
    };
    let mcpPresetRequests = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(settingsPayload());
      if (url === "/api/settings/cli-apps") {
        return jsonResponse({ apps: [], installed_count: 0 });
      }
      if (url === "/api/settings/mcp-presets") {
        mcpPresetRequests += 1;
        return jsonResponse({
          presets: [{
            ...connectingPreset,
            runtime_status: mcpPresetRequests === 1 ? "connecting" : "connected",
          }],
          installed_count: 1,
        });
      }
      return { ok: false, status: 404, text: async () => "Not found" } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSettingsView({ initialSection: "apps" });
    fireEvent.click(await screen.findByRole("button", { name: "MCP" }));

    expect(await screen.findByRole("button", { name: "Xmind: Connecting…" }))
      .toHaveTextContent("Connecting…");
    expect(await screen.findByRole(
      "button",
      { name: "Manage Xmind" },
      { timeout: 2_500 },
    )).toHaveTextContent("Manage");
    expect(mcpPresetRequests).toBe(2);

    fireEvent.click(screen.getByRole("button", { name: "Ready" }));
    expect(await screen.findByRole("heading", { name: "Xmind" })).toBeInTheDocument();
  });

  it("retries a failed custom MCP and only shows a success check after it connects", async () => {
    const failedCustom = {
      ...xmindMcpPreset,
      name: "team-docs",
      display_name: "team-docs",
      auth: null,
      source: "custom",
      installed: true,
      configured: true,
      available: true,
      status: "configured",
      runtime_status: "failed",
      connection_summary: "https://mcp.example.com/mcp",
    };
    const connectedCustom = { ...failedCustom, runtime_status: "connected" };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(settingsPayload());
      if (url === "/api/settings/cli-apps") {
        return jsonResponse({ apps: [], installed_count: 0 });
      }
      if (url === "/api/settings/mcp-presets") {
        return jsonResponse({ presets: [failedCustom], installed_count: 1 });
      }
      return { ok: false, status: 404, text: async () => "Not found" } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    requestMutationMock.mockResolvedValueOnce({
      presets: [connectedCustom],
      installed_count: 1,
      requires_restart: false,
      hot_reload: {
        ok: true,
        message: "MCP connections refreshed without restarting nanobot.",
        connected: ["team-docs"],
        failed: [],
      },
      last_action: { ok: true, message: "Retried connection for MCP server team-docs." },
    });

    renderSettingsView({ initialSection: "apps" });
    fireEvent.click(await screen.findByRole("button", { name: "MCP" }));
    expect(await screen.findByText("Connection failed.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Manage team-docs" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "team-docs" }))
      .getByRole("button", { name: "Reconnect" }));

    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.mcp.reconnect",
      { name: "team-docs" },
      20_000,
    ));
    const connected = await screen.findByRole("button", { name: "Manage team-docs" });
    expect(connected).toHaveTextContent("Manage");
    expect(connected.querySelector(".lucide-check")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Ready" }));
    const readyHeading = await screen.findByRole("heading", { name: "team-docs" });
    expect(within(readyHeading.closest("article") as HTMLElement).getByText("MCP"))
      .toBeInTheDocument();
  });

  it("configures OAuth for a custom remote MCP without importing JSON", async () => {
    const customPreset = {
      ...xmindMcpPreset,
      name: "team-mcp",
      display_name: "team-mcp",
      source: "custom",
      installed: true,
      status: "authorization_required",
      connection_summary: "https://mcp.example.com/mcp",
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(settingsPayload());
      if (url === "/api/settings/cli-apps") {
        return jsonResponse({ apps: [], installed_count: 0 });
      }
      if (url === "/api/settings/mcp-presets") {
        return jsonResponse({ presets: [], installed_count: 0 });
      }
      return { ok: false, status: 404, text: async () => "Not found" } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    requestMutationMock.mockImplementation(async (action: string) => {
      if (action === "settings.mcp.custom") {
        return {
          presets: [customPreset],
          installed_count: 1,
          hot_reload: {
            ok: false,
            message: "MCP config reloaded, but some servers did not connect: team-mcp",
            failed: ["team-mcp"],
          },
          last_action: { ok: true, message: "Saved custom MCP server team-mcp." },
        };
      }
      return settingsPayload();
    });

    renderSettingsView({ initialSection: "apps" });
    fireEvent.click(await screen.findByRole("button", { name: "MCP" }));
    fireEvent.click(await screen.findByRole("button", { name: "Custom" }));

    expect(screen.queryByText("Authentication")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Server name"), {
      target: { value: "team-mcp" },
    });
    fireEvent.click(screen.getByRole("button", { name: "HTTP" }));
    fireEvent.change(screen.getByLabelText("URL"), {
      target: { value: "https://mcp.example.com/mcp" },
    });

    const authentication = screen.getByRole("group", { name: "Authentication" });
    const oauth = within(authentication).getByRole("button", { name: "OAuth" });
    expect(oauth).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(within(authentication).getByRole("button", { name: "Headers" }));
    fireEvent.change(screen.getByLabelText("Headers JSON"), {
      target: { value: '{"Authorization":"Bearer stale"}' },
    });
    expect(screen.getByText("Add the request headers used by this server.")).toBeInTheDocument();

    fireEvent.click(oauth);
    expect(oauth).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByLabelText("Headers JSON")).not.toBeInTheDocument();
    expect(
      screen.getByText("Save the server, then select Connect to sign in."),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Save MCP" }));

    await waitFor(() => {
      const saveCall = requestMutationMock.mock.calls.find(
        ([action]) => action === "settings.mcp.custom",
      );
      expect(saveCall).toBeDefined();
      const values = saveCall?.[1] as Record<string, string>;
      expect(values).toMatchObject({
        name: "team-mcp",
        transport: "streamableHttp",
        url: "https://mcp.example.com/mcp",
        auth: "oauth",
      });
      expect(values).not.toHaveProperty("headers");
      expect(saveCall?.[2]).toBe(20_000);
    });
    expect(await screen.findByRole("button", { name: "Connect team-mcp" }))
      .toBeInTheDocument();
    expect(
      screen.queryByText("MCP config reloaded, but some servers did not connect: team-mcp"),
    ).not.toBeInTheDocument();
  });

  it("offers a pasted callback flow when the remote WebUI uses HTTP", async () => {
    let completed = false;
    const callbackUrl =
      "http://127.0.0.1:8765/auth/mcp/callback?code=oauth-code&state=manual-state";
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(settingsPayload());
      if (url === "/api/settings/cli-apps") {
        return jsonResponse({ apps: [], installed_count: 0 });
      }
      if (url === "/api/settings/mcp-presets") {
        return jsonResponse({
          presets: [completed
            ? {
              ...xmindMcpPreset,
              installed: true,
              configured: true,
              available: true,
              status: "configured",
              connection_summary: "https://app.xmind.com/api/mcp",
            }
            : xmindMcpPreset],
          installed_count: completed ? 1 : 0,
        });
      }
      if (url === "/api/settings/mcp-oauth/status?flow_id=flow-manual") {
        return jsonResponse({
          flow_id: "flow-manual",
          name: "xmind",
          status: completed ? "connected" : "authorization_required",
          expires_in: 298,
          completion_input: "callback_url",
          authorization_url: completed
            ? undefined
            : "https://accounts.xmind.test/authorize?state=manual-state",
          hot_reload: completed ? { ok: true, requires_restart: false } : undefined,
        });
      }
      return { ok: false, status: 404, text: async () => "Not found" } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    requestMutationMock.mockImplementation(async (action: string) => {
      if (action === "settings.mcp.oauth_start") {
        return {
          flow_id: "flow-manual",
          name: "xmind",
          status: "authorization_required",
          expires_in: 300,
          completion_input: "callback_url",
          authorization_url: "https://accounts.xmind.test/authorize?state=manual-state",
        };
      }
      if (action === "settings.mcp.oauth_complete") {
        completed = true;
        return {
          flow_id: "flow-manual",
          name: "xmind",
          status: "connecting",
          expires_in: 299,
          completion_input: "callback_url",
        };
      }
      return settingsPayload();
    });
    const popup = {
      opener: window,
      closed: false,
      location: { replace: vi.fn() },
      document: { title: "", body: { textContent: "" } },
      focus: vi.fn(),
      close: vi.fn(),
    };
    vi.stubGlobal("open", vi.fn(() => popup));

    renderSettingsView({ initialSection: "apps" });
    fireEvent.click(await screen.findByRole("button", { name: "MCP" }));
    fireEvent.click(await screen.findByRole("button", { name: "Connect Xmind" }));

    const callbackInput = await screen.findByRole("textbox", { name: "Full callback URL" });
    expect(screen.getByText(/localhost page will not load/i)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Finish signing in, then paste the callback URL into nanobot.",
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    fireEvent.change(callbackInput, { target: { value: callbackUrl } });
    fireEvent.click(screen.getByRole("button", { name: "Finish sign-in" }));

    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.mcp.oauth_complete",
      { flow_id: "flow-manual", callback_url: callbackUrl },
      20_000,
    ));
    expect(await screen.findByRole("button", { name: "Manage Xmind" }, { timeout: 2500 }))
      .toHaveTextContent("Manage");
    expect(screen.queryByRole("textbox", { name: "Full callback URL" })).not.toBeInTheDocument();
    expect(popup.close).toHaveBeenCalledTimes(1);
  });

  it("lets the user cancel an active OAuth connection after closing the popup", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(settingsPayload());
      if (url === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
      if (url === "/api/settings/mcp-presets") {
        return jsonResponse({ presets: [xmindMcpPreset], installed_count: 0 });
      }
      if (url === "/api/settings/mcp-oauth/status?flow_id=flow-cancel") {
        return new Promise<Response>(() => {});
      }
      return { ok: false, status: 404, text: async () => "Not found" } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    requestMutationMock.mockImplementation(async (action: string) => {
      if (action === "settings.mcp.oauth_start") {
        return {
          flow_id: "flow-cancel",
          name: "xmind",
          status: "authorization_required",
          expires_in: 300,
          authorization_url: "https://accounts.xmind.test/authorize?state=cancel",
        };
      }
      if (action === "settings.mcp.oauth_cancel") {
        return {
          flow_id: "flow-cancel",
          name: "xmind",
          status: "cancelled",
          expires_in: 299,
        };
      }
      return settingsPayload();
    });
    const popup = {
      opener: window,
      closed: false,
      location: { replace: vi.fn() },
      document: { title: "", body: { textContent: "" } },
      focus: vi.fn(),
      close: vi.fn(),
    };
    vi.stubGlobal("open", vi.fn(() => popup));

    renderSettingsView({ initialSection: "apps" });
    fireEvent.click(await screen.findByRole("button", { name: "MCP" }));
    fireEvent.click(await screen.findByRole("button", { name: "Connect Xmind" }));

    const cancelButton = await screen.findByRole("button", { name: "Cancel" });
    expect(screen.getByRole("button", { name: "Connecting Xmind" })).toBeInTheDocument();
    popup.closed = true;
    fireEvent.click(cancelButton);

    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.mcp.oauth_cancel",
      { flow_id: "flow-cancel" },
      20_000,
    ));
    expect(await screen.findByRole("button", { name: "Connect Xmind" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Connecting Xmind" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
    expect(popup.close).not.toHaveBeenCalled();
  });

  it("silently removes an MCP when the card already shows the result", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(settingsPayload());
      if (url === "/api/settings/cli-apps") {
        return jsonResponse({ apps: [], installed_count: 0 });
      }
      if (url === "/api/settings/mcp-presets") {
        return jsonResponse({
          presets: [{
            ...xmindMcpPreset,
            installed: true,
            configured: true,
            available: true,
            status: "configured",
            connection_summary: "https://app.xmind.com/api/mcp",
          }],
          installed_count: 1,
        });
      }
      return { ok: false, status: 404, text: async () => "Not found" } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    requestMutationMock.mockResolvedValueOnce({
      presets: [xmindMcpPreset],
      installed_count: 0,
      requires_restart: false,
      hot_reload: {
        ok: true,
        message: "MCP config reloaded without restarting nanobot.",
      },
      last_action: {
        ok: true,
        message: "Removed MCP preset for Xmind. MCP config reloaded without restarting nanobot.",
        removed: true,
      },
    });

    renderSettingsView({ initialSection: "apps" });
    fireEvent.click(await screen.findByRole("button", { name: "MCP" }));
    fireEvent.click(await screen.findByRole("button", { name: "Manage Xmind" }));
    const dialog = screen.getByRole("dialog", { name: "Xmind" });
    fireEvent.click(within(dialog).getByRole("tab", { name: "Connection" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove connection" }));

    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.mcp.remove",
      { name: "xmind" },
      20_000,
    ));
    expect(await screen.findByRole("button", { name: "Connect Xmind" })).toBeInTheDocument();
    expect(screen.queryByText(/Removed MCP preset|reloaded without restarting/)).not.toBeInTheDocument();
  });

  it("offers a one-click recovery when the OAuth popup is blocked", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(settingsPayload());
      if (url === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
      if (url === "/api/settings/mcp-presets") {
        return jsonResponse({ presets: [xmindMcpPreset], installed_count: 0 });
      }
      return new Promise<Response>(() => {});
    });
    vi.stubGlobal("fetch", fetchMock);
    requestMutationMock.mockImplementation(async (action: string) => {
      if (action === "settings.mcp.oauth_start") {
        return {
          flow_id: "flow-blocked",
          name: "xmind",
          status: "authorization_required",
          expires_in: 300,
          authorization_url: "https://accounts.xmind.test/authorize?state=blocked",
        };
      }
      return settingsPayload();
    });
    const popup = {
      opener: window,
      closed: false,
      location: { replace: vi.fn() },
      focus: vi.fn(),
      close: vi.fn(),
    };
    const open = vi.fn()
      .mockReturnValueOnce(null)
      .mockReturnValueOnce(popup);
    vi.stubGlobal("open", open);

    renderSettingsView({ initialSection: "apps" });
    fireEvent.click(await screen.findByRole("button", { name: "MCP" }));
    fireEvent.click(await screen.findByRole("button", { name: "Connect Xmind" }));

    const continueButton = await screen.findByRole("button", { name: "Continue sign-in" });
    expect(screen.getByRole("status")).toHaveTextContent("Open the sign-in page to continue.");
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    fireEvent.click(continueButton);
    expect(open).toHaveBeenLastCalledWith(
      "https://accounts.xmind.test/authorize?state=blocked",
      "nanobot-mcp-oauth",
      "popup,width=560,height=720,resizable=yes,scrollbars=yes",
    );
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });

  it("does not mistake a COOP-isolated OAuth tab for a blocked popup", async () => {
    let popupIsolated = false;
    let statusCalls = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(settingsPayload());
      if (url === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
      if (url === "/api/settings/mcp-presets") {
        return jsonResponse({ presets: [xmindMcpPreset], installed_count: 0 });
      }
      if (url === "/api/settings/mcp-oauth/status?flow_id=flow-coop") {
        statusCalls += 1;
        return jsonResponse({
          flow_id: "flow-coop",
          name: "xmind",
          status: statusCalls === 1 ? "authorization_required" : "failed",
          expires_in: 299,
          error: statusCalls === 1 ? undefined : "Cancelled for test cleanup.",
          authorization_url: statusCalls === 1
            ? "https://accounts.xmind.test/authorize?state=coop"
            : undefined,
        });
      }
      return { ok: false, status: 404, text: async () => "Not found" } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    requestMutationMock.mockImplementation(async (action: string) => {
      if (action === "settings.mcp.oauth_start") {
        return {
          flow_id: "flow-coop",
          name: "xmind",
          status: "authorization_required",
          expires_in: 300,
          authorization_url: "https://accounts.xmind.test/authorize?state=coop",
        };
      }
      return settingsPayload();
    });
    const popup = {
      opener: window,
      get closed() {
        return popupIsolated;
      },
      location: {
        replace: vi.fn(() => {
          popupIsolated = true;
        }),
      },
      document: { title: "", body: { textContent: "" } },
      focus: vi.fn(),
      close: vi.fn(),
    };
    vi.stubGlobal("open", vi.fn(() => popup));

    renderSettingsView({ initialSection: "apps" });
    fireEvent.click(await screen.findByRole("button", { name: "MCP" }));
    fireEvent.click(await screen.findByRole("button", { name: "Connect Xmind" }));

    await waitFor(() => expect(statusCalls).toBe(1), { timeout: 2000 });
    expect(screen.getByRole("status")).toHaveTextContent(
      "Finish signing in in the browser window.",
    );
    expect(screen.queryByRole("button", { name: "Continue sign-in" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });

});
