import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { installedMcpPresetsFromPayload } from "@/lib/mcp-preset-events";
import { requestMutationMock, jsonResponse, settingsPayload, renderSettingsView, installSettingsViewTestHooks } from "@/tests/settings-test-utils";


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

const agentPlugin = {
  name: "plugin-computer-use",
  display_name: "Computer Use",
  category: "Plugin",
  description: "Control the desktop with a live preview.",
  requires: "screen-recording, accessibility",
  transport: "stdio",
  install_supported: false,
  installed: true,
  configured: true,
  enabled: false,
  available: false,
  status: "disabled",
  required_fields: [],
  source: "agent-plugin",
};

describe("Settings system domains", () => {
  installSettingsViewTestHooks();

  it("asks before leaving with pending changes and lets the user restart later", () => {
    const leave = vi.fn();
    renderSettingsView({ initialSection: "runtime", initialSettings: {
      ...settingsPayload(), requires_restart: true, restart_required_sections: ["runtime"],
    }, onBackToChat: leave });
    fireEvent.click(screen.getByRole("button", { name: "Back to chat" }));
    const dialog = screen.getByRole("dialog", { name: "Restart before leaving?" });
    expect(leave).not.toHaveBeenCalled();
    expect(within(dialog).getByText("Your changes are saved. Restart to apply them.")).toBeVisible();
    expect(within(dialog).getAllByRole("button").map((button) => button.textContent)).toEqual([
      "Restart later", "Restart",
    ]);
    fireEvent.click(within(dialog).getByRole("button", { name: "Restart later" }));
    expect(leave).toHaveBeenCalledTimes(1);
    expect(requestMutationMock).not.toHaveBeenCalled();
  });

  it("restarts from the exit prompt", () => {
    const restart = vi.fn();
    renderSettingsView({ initialSection: "runtime", initialSettings: {
      ...settingsPayload(), requires_restart: true,
    }, onRestart: restart });
    fireEvent.click(screen.getByRole("button", { name: "Back to chat" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Restart", exact: true }));
    expect(restart).toHaveBeenCalledTimes(1);
  });

  it("leaves directly when no restart is pending", () => {
    const leave = vi.fn();
    renderSettingsView({ initialSection: "runtime", initialSettings: settingsPayload(), onBackToChat: leave });
    fireEvent.click(screen.getByRole("button", { name: "Back to chat" }));
    expect(leave).toHaveBeenCalledTimes(1);
  });

  it("keeps one restart action and pending notice in the sidebar across settings pages", async () => {
    renderSettingsView({
      initialSection: "runtime",
      initialSettings: {
        ...settingsPayload(),
        requires_restart: true,
        restart_required_sections: ["runtime", "image"],
      },
    });
    const sidebar = screen.getByRole("complementary");
    const restart = within(sidebar).getByRole("button", { name: "Restart", exact: true });
    for (const section of ["Capabilities", "Models", "Advanced", "System"]) {
      fireEvent.click(within(sidebar).getByRole("button", { name: section, exact: true }));
      await waitFor(() => {
        expect(screen.getAllByRole("button", { name: "Restart", exact: true })).toEqual([restart]);
        expect(screen.getAllByText("Saved. Restart to apply changes.")).toHaveLength(1);
        expect(within(sidebar).getByText("Saved. Restart to apply changes.")).toBeVisible();
      });
    }
  });

  it("keeps enabled Agent Plugins out of MCP composer attachments", () => {
    const enabled = { ...agentPlugin, enabled: true, available: true, status: "enabled" };
    expect(installedMcpPresetsFromPayload({ presets: [enabled], installed_count: 1 })).toEqual([]);
  });

  it("enables and disables an installed Agent Plugin explicitly", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(settingsPayload());
      if (url === "/api/settings/cli-apps") return jsonResponse({ apps: [], installed_count: 0 });
      if (url === "/api/settings/mcp-presets") {
        return jsonResponse({ presets: [agentPlugin], installed_count: 0 });
      }
      return jsonResponse({});
    }));
    requestMutationMock.mockImplementation(async (action: string) => {
      const enabled = action.endsWith(".enable");
      return {
        presets: [{
          ...agentPlugin,
          enabled,
          available: enabled,
          status: enabled ? "enabled" : "disabled",
        }],
        installed_count: Number(enabled),
      };
    });

    renderSettingsView();

    expect(await screen.findByText("Computer Use")).toBeInTheDocument();
    expect(screen.getByText("Plugins")).toBeInTheDocument();
    expect(screen.getByText(/Control the desktop.*screen-recording, accessibility/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Enable" }));

    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.mcp.enable", { name: "plugin-computer-use" }, 20_000,
    ));
    const enabledButton = await screen.findByRole("button", { name: "Computer Use: Enabled" });
    await waitFor(() => expect(enabledButton).toBeEnabled());
    fireEvent.pointerDown(enabledButton, { button: 0, ctrlKey: false });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Disable" }));

    await waitFor(() => expect(requestMutationMock).toHaveBeenCalledWith(
      "settings.mcp.disable", { name: "plugin-computer-use" }, 20_000,
    ));
    expect(await screen.findByRole("button", { name: "Enable" })).toBeInTheDocument();
  });


  it("opens a chat from the standalone automations empty state", async () => {
    const onBackToChat = vi.fn();
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
      onBackToChat,
    });

    expect(screen.getByRole("heading", { name: "Automations" })).toBeInTheDocument();
    expect(await screen.findByText("No automations yet.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open a chat" }));
    expect(onBackToChat).toHaveBeenCalledTimes(1);
  });

  it("offers a way out of an empty automations filter", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(settingsPayload());
      if (url === "/api/webui/automations") {
        return jsonResponse({
          jobs: [{
            id: "job-1",
            name: "Daily summary",
            enabled: true,
            schedule: { kind: "cron", expr: "0 9 * * *" },
            payload: { message: "Summarize the day" },
            state: {},
          }],
        });
      }
      return jsonResponse({});
    }));

    renderSettingsView({
      initialSection: "automations",
      initialSettings: settingsPayload(),
      showSidebar: false,
    });

    expect(await screen.findByRole("heading", { name: "Daily summary" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Paused 0" }));
    expect(await screen.findByText("No automations match this view.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(await screen.findByRole("heading", { name: "Daily summary" })).toBeInTheDocument();
  });

  it("coalesces focus refreshes while automations are already loading", async () => {
    let resolveAutomations!: (response: Response) => void;
    const pendingAutomations = new Promise<Response>((resolve) => {
      resolveAutomations = resolve;
    });
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(settingsPayload());
      if (url === "/api/webui/automations") return pendingAutomations;
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSettingsView({
      initialSection: "automations",
      initialSettings: settingsPayload(),
      showSidebar: false,
    });

    await waitFor(() => {
      expect(fetchMock.mock.calls.filter(([input]) => (
        String(input) === "/api/webui/automations"
      ))).toHaveLength(1);
    });
    window.dispatchEvent(new Event("focus"));
    window.dispatchEvent(new Event("focus"));

    expect(fetchMock.mock.calls.filter(([input]) => (
      String(input) === "/api/webui/automations"
    ))).toHaveLength(1);
    await act(async () => {
      resolveAutomations(jsonResponse({ jobs: [] }));
      await pendingAutomations;
    });
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
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    requestMutationMock.mockResolvedValueOnce({
      ...stopped,
      installed: true,
      running: true,
      managed: true,
    });

    renderSettingsView({ initialSection: "runtime", initialSettings: base, showSidebar: true });

    const startButton = await screen.findByRole("button", { name: "Start API server" });
    await waitFor(() => expect(startButton).toBeEnabled());
    fireEvent.click(startButton);

    await waitFor(() => {
      expect(requestMutationMock).toHaveBeenCalledWith(
        "settings.api_service.start",
        { host: "127.0.0.1", port: 8900, timeout: 120 },
        150_000,
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
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    requestMutationMock.mockResolvedValueOnce({
      apps: [{ ...installedAnyGen, installed: false, status: "available" }],
      installed_count: 0,
      catalog_updated_at: "2026-04-18",
      last_action: {
        ok: true,
        message: "Uninstalled CLI for AnyGen.",
        still_available: false,
      },
    });

    renderSettingsView();

    expect(await screen.findByText("AnyGen")).toBeInTheDocument();
    const uninstall = screen.getByRole("button", { name: "Uninstall app" });

    fireEvent.click(uninstall);

    await waitFor(() =>
      expect(requestMutationMock).toHaveBeenCalledWith(
        "settings.cli_app.uninstall",
        { name: "anygen" },
        20_000,
      ),
    );
    expect(await screen.findByText("Uninstalled CLI for AnyGen.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));

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

    expect(await screen.findByText("AnyGen")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ready" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Apps" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "MCP" })).toBeInTheDocument();
  });

  it("installs optional channel support before enabling and disabling it", async () => {
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
            configured: true,
            installed: false,
            ready: false,
            status: "missing_dependency",
            install_supported: true,
            requires_restart: true,
          }],
          enabled_count: 0,
        });
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    requestMutationMock.mockImplementation(async (action: string, values: Record<string, unknown>) => {
      if (action === "settings.feature.enable") {
        const enabled = values.install_only !== true;
        return {
          features: [{
            name: "matrix",
            display_name: "Matrix",
            webui: "webui/index.ts",
            type: "channel",
            enabled,
            running: enabled,
            runtime_status: enabled ? "running" : "stopped",
            configured: true,
            installed: true,
            ready: true,
            status: enabled ? "enabled" : "not_enabled",
            install_supported: true,
            requires_restart: true,
          }],
          enabled_count: enabled ? 1 : 0,
          last_action: {
            ok: true,
            message: enabled ? "Enabled channel 'matrix'" : "Installed support for channel 'matrix'",
            enabled,
          },
        };
      }
      if (action === "settings.feature.disable") {
        return {
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
        };
      }
      return settingsPayload();
    });

    renderSettingsView({ initialSection: "channels" });

    const matrixRow = await screen.findByRole("button", { name: "View Matrix settings" });
    expect(matrixRow).toHaveAttribute("aria-haspopup", "dialog");
    fireEvent.click(matrixRow);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("switch", { name: "Matrix channel" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Install Matrix" })).toHaveFocus();
    expect(requestMutationMock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Install Matrix" }));

    await waitFor(() =>
      expect(requestMutationMock).toHaveBeenCalledWith(
        "settings.feature.enable",
        { name: "matrix", install_only: true },
        150_000,
      ),
    );
    const matrixToggle = await screen.findByRole("switch", { name: "Matrix channel" });
    expect(matrixToggle).toHaveAttribute("aria-checked", "false");
    expect(requestMutationMock).toHaveBeenCalledTimes(1);
    fireEvent.click(matrixToggle);

    await waitFor(() =>
      expect(requestMutationMock).toHaveBeenCalledWith(
        "settings.feature.enable",
        { name: "matrix" },
        150_000,
      ),
    );
    await waitFor(() =>
      expect(screen.getByRole("switch", { name: "Matrix channel" })).toHaveAttribute("aria-checked", "true"),
    );
    expect(screen.getAllByText("On").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "View Matrix settings" }));
    expect(screen.getByLabelText("Homeserver")).toBeInTheDocument();
    expect(screen.getByLabelText("User ID")).toBeInTheDocument();
    expect(screen.getByLabelText("Device ID")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Close", exact: true }));
    fireEvent.click(screen.getByRole("switch", { name: "Matrix channel" }));

    await waitFor(() =>
      expect(requestMutationMock).toHaveBeenCalledWith(
        "settings.feature.disable",
        { name: "matrix" },
        20_000,
      ),
    );
    await waitFor(() =>
      expect(screen.getByRole("switch", { name: "Matrix channel" })).toHaveAttribute("aria-checked", "false"),
    );
  });
});
