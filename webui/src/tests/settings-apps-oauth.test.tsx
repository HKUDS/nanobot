import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

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

    expect(await screen.findByRole("button", { name: "Xmind: Configured" }, { timeout: 2500 }))
      .toHaveTextContent("Configured");
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
    expect(await screen.findByRole("button", { name: "Xmind: Configured" }, { timeout: 2500 }))
      .toHaveTextContent("Configured");
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
    fireEvent.click(await screen.findByRole("button", { name: "Remove" }));

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
